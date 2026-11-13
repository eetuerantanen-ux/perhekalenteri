#!/usr/bin/env python3
"""Vesiportaali (Elkome) water consumption collector for the Raspberry Pi.

One writer, one local history, two thin consumers:

  * cozify-logger dashboard  ->  /var/www/html/water.json
  * perhekalenteri           ->  water.db (daily/hourly history)

The portal (https://vesiportaali.elkome.com) is an ASP.NET Core Identity app.
This script logs in with the *local* account (email + password) created under
My Account, reuses the session cookie in .publish-state/vesi-cookies.json, and
only re-authenticates when the session expires. No browser is involved and no
credential is ever printed.

The authenticated page's own API is used (same calls AngularJS makes):

  GET  /ConsumptionData/GetConsumptionDataModel
  GET  /ConsumptionData/GetConsumptionPoints
  POST /ConsumptionData/GetConsumptionData   {mode, period, beginDate, ...}

  period=DAY    -> hourly readings (litres per interval)
  period=MONTH  -> daily readings  (litres per day)
  period=YEAR   -> monthly totals  (litres per month)

Readings are upserted into water.db, so the portal's two-year retention is not
the history limit: once a reading is stored here it stays.

Exit codes: 0 ok, 2 configuration, 3 authentication, 4 fetch/parse.
"""

from __future__ import annotations

import argparse
import gzip
import html
import http.cookiejar
import json
import os
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# Paths and constants
# --------------------------------------------------------------------------

ROOT = Path(os.environ.get("VESI_ROOT", "/home/pi/perhekalenteri"))
SECRETS_PATH = ROOT / "secrets.env"
STATE_DIR = ROOT / ".publish-state"
COOKIE_JAR = STATE_DIR / "vesi-cookies.json"
DB_PATH = ROOT / "water.db"

BASE_URL = "https://vesiportaali.elkome.com"
DEFAULT_PROVIDER = "vesiportaali.kouvolanvesi.fi"

MODEL_PATH = "/ConsumptionData/GetConsumptionDataModel"
POINTS_PATH = "/ConsumptionData/GetConsumptionPoints"
DATA_PATH = "/ConsumptionData/GetConsumptionData"

LOGIN_PATH = "/Identity/Account/Login"
LOGIN_POST_PATH = "/Identity/Account/Login?handler=Login"

DATE_FORMAT = "%d.%m.%Y"
DATETIME_FORMAT = "%d.%m.%Y %H:%M"
DATETIME_SECONDS_FORMAT = "%d.%m.%Y %H:%M:%S"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 perhekalenteri-water/1.0"
)

_TZ = None


class PortalError(RuntimeError):
    """Base class for expected, logged failures."""

    exit_code = 4


class ConfigError(PortalError):
    exit_code = 2


class AuthError(PortalError):
    exit_code = 3


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def local_tz():
    """Europe/Helsinki, with a fixed-offset fallback for non-Linux test runs."""
    global _TZ
    if _TZ is None:
        try:
            from zoneinfo import ZoneInfo

            _TZ = ZoneInfo("Europe/Helsinki")
        except Exception:
            _TZ = timezone(timedelta(hours=2))
    return _TZ


def log(message):
    stamp = datetime.now(local_tz()).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def load_secrets(path):
    """Load KEY=VALUE lines into os.environ without overriding real env vars."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            os.environ.setdefault(key, value)


def first(*names, default=None):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def parse_portal_datetime(text, fmt=DATETIME_FORMAT):
    return datetime.strptime(text, fmt).replace(tzinfo=local_tz())


def month_start(day):
    return day.replace(day=1)


def month_end(day):
    if day.month == 12:
        return day.replace(month=12, day=31)
    return day.replace(month=day.month + 1, day=1) - timedelta(days=1)


def next_month(day):
    return month_end(day) + timedelta(days=1)


def month_starts(start, end):
    cursor = month_start(start)
    while cursor <= end:
        yield cursor
        cursor = next_month(cursor)


class Response:
    __slots__ = ("url", "status", "headers", "raw")

    def __init__(self, url, status, headers, raw):
        self.url = url
        self.status = status
        self.headers = headers
        self.raw = raw

    @property
    def text(self):
        return self.raw.decode("utf-8", "replace")

    @property
    def content_type(self):
        return self.headers.get("Content-Type", "") if self.headers else ""


def extract_antiforgery(raw):
    for match in re.finditer(rb"<input[^>]*>", raw):
        tag = match.group(0)
        if b"__RequestVerificationToken" in tag:
            value = re.search(rb'value="([^"]*)"', tag)
            if value:
                return html.unescape(value.group(1).decode("utf-8", "replace"))
    return None


def extract_validation(raw):
    """Return the error text (or translation key) from a failed login page.

    ASP.NET renders the summary server-side, but this app localises the text in
    Angular with a `translate="..."` key, so the visible message is often only
    the key. Fall back to that key instead of reporting an empty error.
    """
    match = re.search(
        rb'<div[^>]*class="[^"]*validation-summary-errors[^"]*"[^>]*>(.*?)</div>',
        raw,
        re.S,
    )
    if not match:
        return None
    block = match.group(1)
    text = re.sub(rb"<[^>]+>", b" ", block)
    text = " ".join(html.unescape(text.decode("utf-8", "replace")).split())
    if text:
        return text
    keys = re.findall(rb'translate="([^"]+)"', block)
    return ", ".join(key.decode("utf-8", "replace") for key in keys) or None


# --------------------------------------------------------------------------
# Portal session
# --------------------------------------------------------------------------

class PortalClient:
    def __init__(self, email, password, provider, cookie_path=COOKIE_JAR):
        self.email = email
        self.password = password
        self.provider = provider
        self.cookie_path = Path(cookie_path)
        self.jar = http.cookiejar.MozillaCookieJar(str(self.cookie_path))
        if self.cookie_path.exists():
            try:
                self.jar.load(ignore_discard=True, ignore_expires=True)
            except Exception as exc:  # corrupt jar is not fatal, just re-login
                log(f"could not load saved cookies ({exc}); starting with a fresh session")
                self.jar = http.cookiejar.MozillaCookieJar(str(self.cookie_path))
        context = ssl.create_default_context()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=context),
        )
        self.opener.addheaders = [
            ("User-Agent", USER_AGENT),
            ("Accept-Language", "fi-FI,fi;q=0.9,en;q=0.5"),
        ]

    # -- HTTP ---------------------------------------------------------
    def _open(self, path, data=None, json_body=None):
        url = path if path.startswith("http") else BASE_URL + path
        body = None
        content_type = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        elif data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")
            content_type = "application/x-www-form-urlencoded"
        request = urllib.request.Request(
            url, data=body, method="POST" if body is not None else "GET"
        )
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with self.opener.open(request, timeout=60) as response:
                raw = response.read()
                if "gzip" in (response.headers.get("Content-Encoding") or ""):
                    raw = gzip.decompress(raw)
                return Response(response.geturl(), response.status, response.headers, raw)
        except urllib.error.HTTPError as error:
            return Response(error.geturl(), error.code, error.headers, error.read())

    def get(self, path):
        return self._open(path)

    def post(self, path, data):
        return self._open(path, data)

    def post_json(self, path, payload):
        return self._open(path, json_body=payload)

    # -- auth ---------------------------------------------------------
    def _on_login_page(self, response):
        return LOGIN_PATH.lower() in (response.url or "").lower()

    def is_authenticated(self):
        # A tiny JSON endpoint is enough and avoids pulling the 160 kB page.
        response = self.get(MODEL_PATH)
        return response.status == 200 and "json" in response.content_type

    def login(self):
        # Select the utility first: the provider cookie scopes the whole tenant.
        self.get(
            "/ProviderSelection/SelectProvider?provider="
            + urllib.parse.quote(self.provider, safe="")
        )
        page = self.get(LOGIN_PATH)
        token = extract_antiforgery(page.raw)
        if not token:
            raise ConfigError(
                "login page did not contain an antiforgery token "
                f"(HTTP {page.status}, url {page.url})"
            )
        response = self.post(
            LOGIN_POST_PATH,
            {
                "Input.Email": self.email,
                "Input.Password": self.password,
                "Input.RememberMe": "true",
                "__RequestVerificationToken": token,
            },
        )
        if self._on_login_page(response):
            message = extract_validation(response.raw) or "login rejected"
            message = {
                "InvalidLoginAttempt": "invalid email or password",
            }.get(message, message)
            raise AuthError(f"login failed: {message}")
        self.save_cookies()

    def save_cookies(self):
        self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
        self.jar.save(ignore_discard=True, ignore_expires=True)
        try:
            self.cookie_path.chmod(0o600)
        except OSError:
            pass

    def authenticate(self, force=False):
        if not force and len(self.jar) and self.is_authenticated():
            log("reused the saved portal session")
            return
        log("logging in to Vesiportaali")
        self.login()
        if not self.is_authenticated():
            raise AuthError("login appeared to succeed but the data API is still gated")
        log("login ok")


def build_client():
    email = first("VESI_EMAIL")
    password = first("VESI_PASSWORD")
    provider = first("VESI_PROVIDER", default=DEFAULT_PROVIDER)
    if not email or not password:
        raise ConfigError(
            "VESI_EMAIL / VESI_PASSWORD are missing; "
            "run tools/provision-vesi.ps1 or add them to secrets.env"
        )
    return PortalClient(email, password, provider)


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

def connect_db(path=DB_PATH):
    connection = sqlite3.connect(str(path), timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily (
            day        TEXT PRIMARY KEY,
            liters     REAL NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hourly (
            ts         INTEGER PRIMARY KEY,
            day        TEXT NOT NULL,
            local      TEXT NOT NULL,
            liters     REAL NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hourly_day ON hourly(day);
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    connection.commit()
    return connection


def meta_get(connection, key, default=None):
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def meta_set(connection, key, value):
    connection.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    connection.commit()


def upsert_daily(connection, payload):
    rows = payload.get("data") or []
    now = int(time.time())
    items = []
    for row in rows:
        day = parse_portal_datetime(row["timestamp"]).date().isoformat()
        items.append((day, round(float(row["value"]), 1), now))
    connection.executemany(
        "INSERT INTO daily(day, liters, updated_at) VALUES(?, ?, ?) "
        "ON CONFLICT(day) DO UPDATE SET liters = excluded.liters, "
        "updated_at = excluded.updated_at",
        items,
    )
    connection.commit()
    return len(items)


def replace_hourly_day(connection, day, payload):
    """Replace one local day's hourly rows.

    The meter's timestamps drift a little between reports (05:58 vs 06:00), so
    deleting the day first keeps repeated fetches idempotent instead of
    double-counting the same interval under a slightly different timestamp.
    """
    rows = payload.get("data") or []
    now = int(time.time())
    items = []
    for row in rows:
        moment = parse_portal_datetime(row["timestamp"])
        items.append(
            (
                int(moment.timestamp()),
                day.isoformat(),
                row["timestamp"],
                round(float(row["value"]), 1),
                now,
            )
        )
    with connection:
        connection.execute("DELETE FROM hourly WHERE day = ?", (day.isoformat(),))
        connection.executemany(
            "INSERT INTO hourly(ts, day, local, liters, updated_at) VALUES(?, ?, ?, ?, ?)",
            items,
        )
    return len(items)


# --------------------------------------------------------------------------
# Portal API
# --------------------------------------------------------------------------

def api_json(client, path, payload=None, attempts=3):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            response = (
                client.post_json(path, payload) if payload is not None else client.get(path)
            )
        except (urllib.error.URLError, OSError) as error:
            last_error = str(error)
        else:
            if LOGIN_PATH.lower() in (response.url or "").lower():
                raise AuthError("portal session expired")
            if response.status == 200 and "json" in response.content_type:
                try:
                    return json.loads(response.text)
                except ValueError as error:
                    last_error = f"invalid JSON ({error})"
            else:
                last_error = f"HTTP {response.status} ({response.content_type or 'no content type'})"
        if attempt < attempts:
            time.sleep(2 * attempt)
    raise PortalError(f"{path} failed after {attempts} attempts: {last_error}")


def select_point(points):
    if not points:
        raise PortalError("the account has no consumption points")
    wanted = first("VESI_CONSUMPTION_ID")
    if wanted:
        for point in points:
            if str(point.get("consumptionId")) == str(wanted):
                return point
        raise ConfigError(f"VESI_CONSUMPTION_ID={wanted} was not found on the account")
    if len(points) > 1:
        log(f"warning: {len(points)} consumption points on the account; using the first")
    return points[0]


def build_payload(model, point, mode, period, begin, end):
    payload = dict(model)
    payload.update(
        {
            "mode": mode,
            "period": period,
            "beginDate": begin.strftime(DATE_FORMAT),
            "endDate": end.strftime(DATE_FORMAT),
            "consumptionId": point["consumptionId"],
            "meterId": point["meterId"],
            "data": [],
        }
    )
    return payload


def fetch_month(client, model, point, start):
    return api_json(
        client,
        DATA_PATH,
        build_payload(model, point, "CONSUMPTION", "MONTH", start, month_end(start)),
    )


def fetch_day(client, model, point, day):
    return api_json(
        client,
        DATA_PATH,
        build_payload(model, point, "CONSUMPTION", "DAY", day, day),
    )


# --------------------------------------------------------------------------
# Sync and export
# --------------------------------------------------------------------------

def sum_daily(connection, start, end):
    row = connection.execute(
        "SELECT COALESCE(SUM(liters), 0) FROM daily WHERE day >= ? AND day <= ?",
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    return round(float(row[0]), 1)


def day_liters(connection, day):
    row = connection.execute(
        "SELECT liters FROM daily WHERE day = ?", (day.isoformat(),)
    ).fetchone()
    return round(float(row[0]), 1) if row else None


def build_export(connection, point, info, days=30):
    now = datetime.now(local_tz())
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    month_begin = today.replace(day=1)
    year_begin = today.replace(month=1, day=1)

    daily_rows = connection.execute(
        "SELECT day, liters FROM daily ORDER BY day DESC LIMIT ?", (days,)
    ).fetchall()
    daily_rows.reverse()

    hourly_rows = connection.execute(
        "SELECT ts, local, liters FROM hourly ORDER BY ts DESC LIMIT 24"
    ).fetchall()
    hourly_rows.reverse()

    volume = info.get("volume") if info else None
    reading_at = info.get("timestampStringFin") if info else None
    if info and info.get("timestampString"):
        try:
            reading_utc = datetime.strptime(
                info["timestampString"], DATETIME_SECONDS_FORMAT
            ).replace(tzinfo=timezone.utc)
            reading_utc = int(reading_utc.timestamp())
        except ValueError:
            reading_utc = None
    else:
        reading_utc = None

    return {
        "updated_at": int(now.timestamp()),
        "updated_str": now.strftime("%d.%m.%Y klo %H:%M:%S"),
        "source": "Vesiportaali / Kouvolan Vesi",
        "meter": {
            "consumption_id": str(point.get("consumptionId", "")),
            "meter_id": str(point.get("meterId", "")),
            "volume_m3": volume,
            "reading_at": reading_at,
            "reading_utc": reading_utc,
        },
        "alerts": [
            {"name": item.get("name", ""), "active": bool(item.get("isActive"))}
            for item in ((info or {}).get("infoCodesList") or [])
        ],
        "today": {"date": today.isoformat(), "liters": day_liters(connection, today)},
        "yesterday": {
            "date": (today - timedelta(days=1)).isoformat(),
            "liters": day_liters(connection, today - timedelta(days=1)),
        },
        "week": {"start": week_start.isoformat(), "liters": sum_daily(connection, week_start, today)},
        "month": {
            "start": month_begin.isoformat(),
            "liters": sum_daily(connection, month_begin, today),
        },
        "year": {"start": year_begin.isoformat(), "liters": sum_daily(connection, year_begin, today)},
        "daily": [{"date": day, "liters": round(float(liters), 1)} for day, liters in daily_rows],
        "hourly": [
            {"ts": ts, "local": local, "liters": round(float(liters), 1)}
            for ts, local, liters in hourly_rows
        ],
    }


def write_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    os.replace(temporary, target)
    try:
        target.chmod(0o644)
    except OSError:
        pass
    log(f"wrote {target} ({len(payload['daily'])} days, {len(payload['hourly'])} hourly)")


def catch_up(client, model, point, connection, today, last_run_day):
    """Fill daily months that became available since the last successful run.

    Hourly detail is deliberately **not** backfilled: it is collected from the
    day the collector starts (yesterday + today on every run), because the
    family calendar only needs consumption from now on. Daily history is cheap
    and drives the dashboard's long-range chart, so gaps there heal on the
    first run of a day.
    """
    if last_run_day is None or last_run_day >= today:
        return

    # Daily rows: whole months older than the previous month, which the normal
    # run already refreshes.
    previous_month = month_start(month_start(today) - timedelta(days=1))
    earliest_month = month_start(today - timedelta(days=730))
    from_month = max(month_start(last_run_day), earliest_month)
    if from_month < previous_month:
        months = list(month_starts(from_month, previous_month - timedelta(days=1)))
        log(f"catch-up: {len(months)} month(s) of daily data")
        for begin in months:
            payload = fetch_month(client, model, point, begin)
            count = upsert_daily(connection, payload)
            log(f"  {begin:%Y-%m}: {count} days")
            time.sleep(0.3)


def sync(client, connection, args):
    model = api_json(client, MODEL_PATH)
    points = api_json(client, POINTS_PATH)
    point = select_point(points)

    meta_set(connection, "consumption_id", point.get("consumptionId", ""))
    meta_set(connection, "meter_id", point.get("meterId", ""))

    today = datetime.now(local_tz()).date()
    current_month = month_start(today)
    last_run_text = meta_get(connection, "last_run_day")
    last_run_day = (
        datetime.strptime(last_run_text, "%Y-%m-%d").date() if last_run_text else None
    )
    first_run_today = last_run_day != today

    # The model endpoint returns an empty minDate; the data response carries it.
    current_payload = fetch_month(client, model, point, current_month)
    current_count = upsert_daily(connection, current_payload)
    log(f"{current_month:%Y-%m}: {current_count} days")

    min_date = None
    if current_payload.get("minDate"):
        try:
            min_date = datetime.strptime(current_payload["minDate"], DATE_FORMAT).date()
        except ValueError:
            pass

    # The portal keeps about two years online; that is the useful default floor.
    start = today - timedelta(days=730)
    if min_date and min_date > start:
        start = min_date
    history_start = first("VESI_HISTORY_START")
    if history_start:
        try:
            start = datetime.strptime(history_start, "%Y-%m-%d").date()
        except ValueError as error:
            raise ConfigError(f"VESI_HISTORY_START must be YYYY-MM-DD: {error}")

    backfill_done = meta_get(connection, "backfill_done") == "1"
    if args.backfill or not backfill_done:
        starts = [m for m in month_starts(start, current_month) if m < current_month]
        if starts:
            log(f"backfill: {len(starts)} months ({starts[0]:%Y-%m} .. {starts[-1]:%Y-%m})")
            for index, begin in enumerate(starts, start=1):
                payload = fetch_month(client, model, point, begin)
                count = upsert_daily(connection, payload)
                if index % 6 == 0 or index == len(starts):
                    log(f"  {begin:%Y-%m}: {count} days")
                time.sleep(0.3)
        meta_set(connection, "backfill_done", "1")
    else:
        previous_month = month_start(current_month - timedelta(days=1))
        if previous_month != current_month:
            payload = fetch_month(client, model, point, previous_month)
            count = upsert_daily(connection, payload)
            log(f"{previous_month:%Y-%m}: {count} days")

    info = None
    for day in (today - timedelta(days=1), today):
        payload = fetch_day(client, model, point, day)
        count = replace_hourly_day(connection, day, payload)
        if payload.get("infoCodes"):
            info = payload["infoCodes"]
        log(f"{day}: {count} hourly readings")

    if not meta_get(connection, "hourly_since"):
        meta_set(connection, "hourly_since", (today - timedelta(days=1)).isoformat())
        log(f"hourly collection starts at {today - timedelta(days=1)}")

    if first_run_today:
        log("first run today: refreshing the previous night and filling any gaps")
        catch_up(client, model, point, connection, today, last_run_day)

    if info and info.get("timestampStringFin"):
        meta_set(connection, "last_volume", info.get("volume", ""))
        meta_set(connection, "last_volume_at", info.get("timestampStringFin", ""))
        log(
            f"latest reading {info.get('volume')} m3 @ "
            f"{info.get('timestampStringFin')}"
        )

    meta_set(connection, "last_sync", int(time.time()))

    if args.json:
        write_json(
            args.json,
            build_export(connection, point, info, days=args.days),
        )

    meta_set(connection, "last_run_day", today.isoformat())


# --------------------------------------------------------------------------
# Reconnaissance: what does the authenticated page actually request?
# --------------------------------------------------------------------------

CANDIDATE_PATTERNS = [
    r"""\$http\s*\.\s*(?:get|post)\s*\(\s*['"]([^'"]+)""",
    r"""\burl\s*:\s*['"]([^'"]+)['"]""",
    r"""\baction\s*=\s*["']([^"']+)["']""",
    r"""\bhref\s*=\s*["'](/Consumption[^"']*)["']""",
    r"""['"](/api/[^'"]+)['"]""",
    r"""['"](/(?:ConsumptionData|ConsumptionPoints|Shared|Report|Export)[^'"]*)['"]""",
]


def scan_candidates(text):
    found = []
    for pattern in CANDIDATE_PATTERNS:
        for match in re.finditer(pattern, text):
            value = html.unescape(match.group(1)).strip()
            if value and value not in found:
                found.append(value)
    return found


def probe(client, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = []

    for path, filename in (
        ("/ConsumptionData", "consumption.html"),
        ("/ConsumptionPoints", "points.html"),
    ):
        response = client.get(path)
        target = out_dir / filename
        target.write_bytes(response.raw)
        lines.append(
            f"{path} -> HTTP {response.status} {response.content_type} "
            f"{len(response.raw)} bytes, final url {response.url}, saved {target}"
        )

    page = (out_dir / "consumption.html").read_text(encoding="utf-8", errors="replace")

    scripts = []
    for match in re.finditer(r"""<script[^>]+src=["']([^"']+)["']""", page, re.I):
        if match.group(1) not in scripts:
            scripts.append(match.group(1))
    lines.append("script src:")
    lines.extend(f"  {src}" for src in scripts)

    inline = []
    for index, match in enumerate(
        re.finditer(r"<script([^>]*)>(.*?)</script>", page, re.S | re.I)
    ):
        attrs, body = match.group(1), match.group(2)
        if "src=" in attrs.lower() or len(body.strip()) < 40:
            continue
        if not any(key in body for key in ("$http", "ajax", "Consumption", "/api/")):
            continue
        name = f"inline-{index}.js"
        (out_dir / name).write_text(body, encoding="utf-8")
        inline.append(f"  {name} ({len(body)} chars)")
    lines.append("inline scripts of interest:")
    lines.extend(inline or ["  (none)"])

    candidates = scan_candidates(page)
    lines.append("candidate endpoints:")
    lines.extend(f"  {candidate}" for candidate in candidates)
    if not candidates:
        lines.append("  (none found)")

    for match in re.finditer(r'ng-init="([^"]{0,400})"', page):
        lines.append(f"ng-init: {html.unescape(match.group(1))}")

    report = "\n".join(lines)
    (out_dir / "report.txt").write_text(report + "\n", encoding="utf-8")
    print(report)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def print_stats(connection):
    daily = connection.execute(
        "SELECT COUNT(*), MIN(day), MAX(day) FROM daily"
    ).fetchone()
    hourly = connection.execute(
        "SELECT COUNT(*), MIN(day), MAX(day) FROM hourly"
    ).fetchone()
    print(f"daily:  {daily[0]} rows, {daily[1]} .. {daily[2]}")
    print(f"hourly: {hourly[0]} rows, {hourly[1]} .. {hourly[2]}")
    for key in (
        "consumption_id",
        "meter_id",
        "last_volume",
        "last_volume_at",
        "last_run_day",
        "hourly_since",
        "last_sync",
        "backfill_done",
    ):
        print(f"{key}: {meta_get(connection, key)}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--login-test", action="store_true", help="authenticate and exit")
    parser.add_argument("--probe", action="store_true", help="dump authenticated pages and scan for endpoints")
    parser.add_argument("--probe-dir", default="/tmp/vesi-probe")
    parser.add_argument("--force-login", action="store_true", help="ignore the saved session cookie")
    parser.add_argument("--backfill", action="store_true", help="refetch the whole history")
    parser.add_argument("--days", type=int, default=30, help="days in the JSON export (default 30)")
    parser.add_argument("--json", default=None, help="write the dashboard JSON here")
    parser.add_argument("--verify", action="store_true", help="print database statistics and exit")
    parser.add_argument("--show-config", action="store_true", help="print resolved paths and exit")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    load_secrets(SECRETS_PATH)

    if args.show_config:
        print(f"root:        {ROOT}")
        print(f"secrets:     {SECRETS_PATH} ({'present' if SECRETS_PATH.exists() else 'missing'})")
        print(f"database:    {DB_PATH}")
        print(f"cookie jar:  {COOKIE_JAR}")
        print(f"email:       {'set' if os.environ.get('VESI_EMAIL') else 'missing'}")
        print(f"password:    {'set' if os.environ.get('VESI_PASSWORD') else 'missing'}")
        print(f"provider:    {os.environ.get('VESI_PROVIDER', DEFAULT_PROVIDER)}")
        print(f"history:     {os.environ.get('VESI_HISTORY_START', '2 years back (default)')}")
        return 0

    if args.verify:
        connection = connect_db()
        try:
            print_stats(connection)
        finally:
            connection.close()
        return 0

    client = build_client()

    if args.login_test:
        client.authenticate(force=args.force_login)
        log("login test passed")
        return 0

    if args.probe:
        client.authenticate(force=args.force_login)
        probe(client, args.probe_dir)
        return 0

    client.authenticate(force=args.force_login)
    connection = connect_db()
    try:
        sync(client, connection, args)
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PortalError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(error.exit_code)
