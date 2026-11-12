#!/usr/bin/env python3
"""Hakee eVakan hoitovuorot (ja saapuneet viestit/tiedotteet) suoraan eVakan JSON-rajapinnasta
heikolla tunnistautumisella (sähköposti + salasana) ilman selainta.

Jos hoitovuoroissa on muutoksia tai uusia vuoroja (tai annetaan --force-webhook),
lähettää päivitetyt vuorot ja muutoserittelyn (diff) webhookilla Grok Botille.

Kirjoittaa:
  * shared/hoitovuorot.json       ([{lapsi, pvm, alku, loppu}])
  * shared/.hoitovuorot.json.sent.json (viimeksi webhookilla onnistuneesti lähetetty tila)
  * raw/evaka_messages.json       (viimeisimmät viestit ja tiedotteet, ellei --no-messages)

Tunnukset ja webhook-asetukset luetaan ympäristömuuttujista tai tiedostosta secrets.env:
  * EVAKA_USERNAME      (pakollinen)
  * EVAKA_PASSWORD      (pakollinen)
  * EVAKA_WEBHOOK_URL   (valinnainen, tai GROK_WEBHOOK_URL)
  * EVAKA_WEBHOOK_KEY   (valinnainen, tai GROK_WEBHOOK_KEY)
"""
import argparse, datetime as dt, http.cookiejar, json, os, sys, urllib.error, urllib.parse, urllib.request
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
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def load_json_list(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def shift_key(s):
    return (
        str(s.get("pvm") or ""),
        str(s.get("lapsi") or ""),
        str(s.get("alku") or ""),
        str(s.get("loppu") or ""),
    )


def sort_shifts(shifts):
    return sorted(shifts, key=shift_key)


def diff_shifts(old_shifts, new_shifts, start_date_iso):
    """Vertaa uusia hoitovuoroja aiempiin haetun aikaikkunan (pvm >= start_date_iso) sisällä.
    Palauttaa (added, removed), joissa kumpikin on järjestetty lista vuoro-objekteja.
    """
    if old_shifts is None:
        return sort_shifts(new_shifts), []
    old_in_window = [s for s in old_shifts if str(s.get("pvm") or "") >= start_date_iso]
    new_in_window = [s for s in new_shifts if str(s.get("pvm") or "") >= start_date_iso]
    old_map = {shift_key(s): s for s in old_in_window}
    new_map = {shift_key(s): s for s in new_in_window}
    added = [new_map[k] for k in sorted(new_map.keys() - old_map.keys())]
    removed = [old_map[k] for k in sorted(old_map.keys() - new_map.keys())]
    return added, removed


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
    return sort_shifts(shifts)


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


def send_webhook(url, key, payload, timeout=25):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if key:
        auth_val = key if key.lower().startswith("bearer ") else f"Bearer {key}"
        headers["Authorization"] = auth_val
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.status
        resp_body = resp.read().decode("utf-8", errors="replace").strip()
        return status, resp_body


def default_state_path(out_shifts_path):
    d = os.path.dirname(os.path.abspath(out_shifts_path))
    b = os.path.basename(out_shifts_path)
    return os.path.join(d, f".{b}.sent.json")


def main():
    ap = argparse.ArgumentParser(description="Hae eVakan hoitovuorot ja lähetä muutokset webhookilla.")
    ap.add_argument("--from-date", help="Alkupäivä YYYY-MM-DD (oletus: kuluvan kuun ruudukon alku)")
    ap.add_argument("--to-date", help="Loppupäivä YYYY-MM-DD (oletus: seuraavan kuun ruudukon loppu)")
    ap.add_argument("--out-shifts", default=os.path.join(ROOT, "shared", "hoitovuorot.json"))
    ap.add_argument("--state-file", help="Tiedosto johon tallennetaan viimeksi webhookilla lähetetyt vuorot")
    ap.add_argument("--out-messages", default=os.path.join(ROOT, "raw", "evaka_messages.json"))
    ap.add_argument("--no-messages", action="store_true", help="Älä hae viestejä")
    ap.add_argument("--webhook-url", help="Webhook-osoite (oletus: EVAKA_WEBHOOK_URL tai GROK_WEBHOOK_URL)")
    ap.add_argument("--webhook-key", help="Webhook-avain (oletus: EVAKA_WEBHOOK_KEY tai GROK_WEBHOOK_KEY)")
    ap.add_argument("--no-webhook", action="store_true", help="Älä lähetä webhookia vaikka muutoksia löytyisi")
    ap.add_argument("--force-webhook", action="store_true", help="Lähetä webhook vaikka muutoksia ei olisi")
    ap.add_argument("--init-state", action="store_true", help="Tallenna nykytila vertailupohjaksi lähettämättä webhookia")
    args = ap.parse_args()

    load_secrets(os.path.join(ROOT, "secrets.env"))
    user = os.environ.get("EVAKA_USERNAME")
    pw = os.environ.get("EVAKA_PASSWORD")
    if not user or not pw:
        print("fetch-evaka.py: EVAKA_USERNAME tai EVAKA_PASSWORD puuttuu (secrets.env)", file=sys.stderr)
        sys.exit(2)

    webhook_url = args.webhook_url or os.environ.get("EVAKA_WEBHOOK_URL") or os.environ.get("GROK_WEBHOOK_URL")
    webhook_key = args.webhook_key or os.environ.get("EVAKA_WEBHOOK_KEY") or os.environ.get("GROK_WEBHOOK_KEY")
    state_path = args.state_file or default_state_path(args.out_shifts)

    today = dt.datetime.now(TZ).date()
    default_start, default_end = calendar_window(today)
    start_date = dt.date.fromisoformat(args.from_date) if args.from_date else default_start
    end_date = dt.date.fromisoformat(args.to_date) if args.to_date else default_end

    # Luetaan aiempi vertailutila (ensisijaisesti viimeksi webhookilla kuitattu tila, muuten nykyinen hoitovuorot.json)
    baseline_shifts = load_json_list(state_path)
    if baseline_shifts is None:
        baseline_shifts = load_json_list(args.out_shifts)

    client = EvakaClient()
    client.login(user, pw)

    shifts = fetch_care_shifts(client, start_date, end_date)
    added, removed = diff_shifts(baseline_shifts, shifts, start_date.isoformat())
    has_changes = bool(added or removed)

    atomic_write_json(args.out_shifts, shifts)
    print(
        f"hoitovuorot.json päivitetty ({start_date}..{end_date}): {len(shifts)} vuoroa "
        f"(uusia: {len(added)}, poistuneita/muuttuneita: {len(removed)})"
    )

    if args.init_state:
        atomic_write_json(state_path, shifts)
        print(f"Vertailutila alustettu ({state_path}), webhookia ei lähetetty.")
    elif not args.no_webhook and webhook_url and (has_changes or args.force_webhook):
        payload = {
            "source": "perhekalenteri-pi-evaka",
            "event": "hoitovuorot_updated",
            "timestamp": dt.datetime.now(TZ).isoformat(timespec="seconds"),
            "forced": bool(args.force_webhook and not has_changes),
            "window": {
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
            },
            "summary": {
                "total": len(shifts),
                "added_count": len(added),
                "removed_count": len(removed),
            },
            "diff": {
                "added": added,
                "removed": removed,
            },
            "hoitovuorot": shifts,
        }
        try:
            status, resp_body = send_webhook(webhook_url, webhook_key, payload)
            atomic_write_json(state_path, shifts)
            print(f"Webhook lähetetty (HTTP {status}): {resp_body[:160]}")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace").strip()
            print(f"fetch-evaka.py: Webhook epäonnistui (HTTP {e.code}): {err_body[:200]}", file=sys.stderr)
            sys.exit(3)
        except Exception as e:
            print(f"fetch-evaka.py: Webhook-virhe: {e}", file=sys.stderr)
            sys.exit(3)
    elif not has_changes:
        # Jos muutoksia ei ollut ja state_path puuttui vielä (mutta out_shifts oli jo ajan tasalla), tallennetaan state_path
        if not os.path.exists(state_path):
            atomic_write_json(state_path, shifts)
        print("Ei muutoksia hoitovuoroissa — webhookia ei lähetetä.")
    elif not webhook_url and not args.no_webhook:
        print("Huom: Hoitovuoroissa on muutoksia, mutta EVAKA_WEBHOOK_URL/GROK_WEBHOOK_URL ei ole asetettu.")

    if not args.no_messages:
        msgs = fetch_messages(client)
        atomic_write_json(args.out_messages, msgs)
        print(f"evaka_messages.json päivitetty: {len(msgs['ketjut'])} viestiketjua")


if __name__ == "__main__":
    main()
