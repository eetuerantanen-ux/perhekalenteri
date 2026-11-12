#!/usr/bin/env python3
"""Hakee eVakan hoitovuorot (ja saapuneet viestit/tiedotteet) suoraan eVakan JSON-rajapinnasta
heikolla tunnistautumisella (sähköposti + salasana) ilman selainta.

Kirjoittaa:
  * shared/hoitovuorot.json  ([{lapsi, pvm, alku, loppu}])
  * raw/evaka_messages.json  (viimeisimmät viestit ja tiedotteet muistutusten poimintaa varten)

Tunnukset luetaan ympäristömuuttujista EVAKA_USERNAME ja EVAKA_PASSWORD
tai tiedostosta secrets.env (samassa hakemistossa).
"""
import argparse, datetime as dt, http.cookiejar, json, os, sys, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("Europe/Helsinki")
BASE_URL = "https://varhaiskasvatus.kouvola.fi"
UA = "perhekalenteri-evaka/1.0"


def load_secrets(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            if s.startswith("export "):
                s = s[len("export "):].strip()
            k, v = s.split("=", 1)
            k = k.strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            os.environ.setdefault(k, v)


def calendar_window(today):
    """Kuluvan kuun 1. päivän ISO-viikon maanantaista seuraavan kuun viimeisen päivän ISO-viikon sunnuntaihin."""
    first_this = today.replace(day=1)
    start = first_this - dt.timedelta(days=first_this.weekday())
    if first_this.month == 11:
        last_next = dt.date(first_this.year + 1, 1, 1) - dt.timedelta(days=1)
    elif first_this.month == 12:
        last_next = dt.date(first_this.year + 1, 2, 1) - dt.timedelta(days=1)
    else:
        last_next = dt.date(first_this.year, first_this.month + 2, 1) - dt.timedelta(days=1)
    end = last_next + dt.timedelta(days=(6 - last_next.weekday()))
    return start, end


class EvakaClient:
    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def request(self, path, data=None, timeout=25):
        headers = {
            "User-Agent": UA,
            "Accept": "application/json",
            "X-Evaka-Csrf": "1",
        }
        for c in self.cj:
            if "csrf" in c.name.lower():
                headers["X-Csrf"] = c.value
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method="POST" if body is not None else "GET",
        )
        with self.opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8").strip()
            if not raw or not raw.startswith(("{", "[")):
                return raw
            return json.loads(raw)

    def login(self, username, password):
        self.request("/api/citizen/auth/status")
        self.request("/api/citizen/auth/weak-login", {"username": username, "password": password})
        st = self.request("/api/citizen/auth/status") or {}
        if not st.get("loggedIn"):
            raise RuntimeError("eVaka-kirjautuminen epäonnistui (loggedIn=False)")
        return st


def atomic_write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def fetch_care_shifts(client, start_date, end_date):
    q = urllib.parse.urlencode({"from": start_date.isoformat(), "to": end_date.isoformat()})
    res = client.request(f"/api/citizen/reservations?{q}") or {}
    child_names = {}
    for c in res.get("children") or []:
        cid = c.get("id")
        first = (c.get("preferredName") or c.get("firstName") or "").strip().split()[0]
        if cid and first:
            child_names[cid] = first

    shifts = []
    for day in res.get("days") or []:
        pvm = day.get("date")
        if not pvm:
            continue
        for ch in day.get("children") or []:
            # Jos lapselle on merkitty poissaolo (esim. PLANNED_ABSENCE), hoitovuoroa ei ole.
            if ch.get("absence") is not None:
                continue
            lapsi = child_names.get(ch.get("childId"))
            if not lapsi:
                continue
            for rv in ch.get("reservations") or []:
                if rv.get("type") == "TIMES" and isinstance(rv.get("range"), dict):
                    alku = (rv["range"].get("start") or "")[:5]
                    loppu = (rv["range"].get("end") or "")[:5]
                    if len(alku) == 5 and len(loppu) == 5:
                        shifts.append({
                            "lapsi": lapsi,
                            "pvm": pvm,
                            "alku": alku,
                            "loppu": loppu,
                        })
    return shifts


def fetch_messages(client, page_size=20):
    q = urllib.parse.urlencode({"page": 1, "pageSize": page_size})
    res = client.request(f"/api/citizen/messages/received?{q}") or {}
    threads = []
    for t in res.get("data") or []:
        msgs = t.get("messages") or []
        latest = msgs[-1] if msgs else {}
        sender = (latest.get("sender") or {}).get("name")
        threads.append({
            "id": t.get("id"),
            "otsikko": t.get("title"),
            "tyyppi": t.get("messageType"),
            "kiireellinen": bool(t.get("urgent")),
            "lahetetty": latest.get("sentAt"),
            "lahettaja": sender,
            "sisalto": latest.get("content"),
        })
    return {"haettu": dt.datetime.now(TZ).isoformat(timespec="seconds"), "ketjut": threads}


def main():
    ap = argparse.ArgumentParser(description="Hae eVakan hoitovuorot ja viestit.")
    ap.add_argument("--from-date", help="Alkupäivä YYYY-MM-DD (oletus: kuluvan kuun ruudukon alku)")
    ap.add_argument("--to-date", help="Loppupäivä YYYY-MM-DD (oletus: seuraavan kuun ruudukon loppu)")
    ap.add_argument("--out-shifts", default=os.path.join(ROOT, "shared", "hoitovuorot.json"))
    ap.add_argument("--out-messages", default=os.path.join(ROOT, "raw", "evaka_messages.json"))
    ap.add_argument("--no-messages", action="store_true", help="Älä hae viestejä")
    args = ap.parse_args()

    load_secrets(os.path.join(ROOT, "secrets.env"))
    user = os.environ.get("EVAKA_USERNAME")
    pw = os.environ.get("EVAKA_PASSWORD")
    if not user or not pw:
        print("fetch-evaka.py: EVAKA_USERNAME tai EVAKA_PASSWORD puuttuu (secrets.env)", file=sys.stderr)
        sys.exit(2)

    today = dt.datetime.now(TZ).date()
    default_start, default_end = calendar_window(today)
    start_date = dt.date.fromisoformat(args.from_date) if args.from_date else default_start
    end_date = dt.date.fromisoformat(args.to_date) if args.to_date else default_end

    client = EvakaClient()
    client.login(user, pw)

    shifts = fetch_care_shifts(client, start_date, end_date)
    atomic_write_json(args.out_shifts, shifts)
    print(f"hoitovuorot.json päivitetty ({start_date}..{end_date}): {len(shifts)} vuoroa")

    if not args.no_messages:
        msgs = fetch_messages(client)
        atomic_write_json(args.out_messages, msgs)
        print(f"evaka_messages.json päivitetty: {len(msgs['ketjut'])} viestiketjua")


if __name__ == "__main__":
    main()
