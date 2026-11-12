#!/usr/bin/env python3
"""Hakee Kouvolan Aromi14 eMenus -rajapinnasta molempien päiväkotien ruokalistat:
  1. Lehvätien päiväkoti (Lehvatienpk, rooli="arki" — arkipäivät)
  2. Jaakonpuiston päiväkoti (Jaakonpuistonpk, rooli="vuoro" — viikonloput, juhlapyhät, ilta-/yöhoito)

Vertaa tulevien päivien (pvm >= tänään) aterioita aiempaan tilaan (.publish-state/ruokalistat.sent.json
tai ruokalistat.enc.json). Vain jos tulevien viikkojen ruokalistoissa on uusia tai muuttuneita
päiviä/aterioita:
  * Salaa ruokalistat tiedostoon ruokalistat.enc.json (AES-256-GCM + PBKDF2-SHA256, 1 000 000 kierrosta,
    FAMILY_PLANNER_PASSWORD — sama muoto kuin data.enc.json, hoitovuorot.enc.json ja muistilista.enc.json).
  * Commitoi ja pushaa ruokalistat.enc.json GitHub-repoon (origin/main).
  * Kutsuu Grok Botin julkaisu-webhookia (jos GROK_WEBHOOK_URL on asetettu).

Purkaminen (Grok Bot / publish.sh / collect.py):
  * python3 fetch-menus.py --decrypt
  * python3 fetch-menus.py --out-menus publish/ruokalistat.enc.json --decrypt-to shared/ruokalistat.json
"""
import argparse, base64, ctypes, ctypes.util, datetime as dt, hashlib, json, os, subprocess, sys, urllib.error, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True

ROOT = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("Europe/Helsinki")
UA = "perhekalenteri-menus/1.0"
PBKDF2_ITER = 1000000

AROMI = "https://aromimenu.cgisaas.fi/KouvolaAromieMenus/FI/Default/Kouvola"
# rooli: "arki" = arkipäivän lista, "vuoro" = viikonloppu, juhlapyhä ja yön yli
MENUS = [
    (["toivo", "hermanni"], "Lehvatienpk", "ad8a057f-2aee-4403-b178-205c8e7b20e2", "Lehvätien päiväkoti", "arki"),
    (["toivo", "hermanni"], "Jaakonpuistonpk", "fd6b518d-6673-4361-a576-ece9efb81b62", "Jaakonpuiston päiväkoti", "vuoro"),
]


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


# ---------- AES-256-GCM + PBKDF2-SHA256 ----------
_LIBCRYPTO = None
EVP_CTRL_GCM_SET_IVLEN = 0x9
EVP_CTRL_GCM_GET_TAG = 0x10
EVP_CTRL_GCM_SET_TAG = 0x11


def _get_libcrypto():
    global _LIBCRYPTO
    if _LIBCRYPTO is not None:
        return _LIBCRYPTO
    for name in (ctypes.util.find_library("crypto"), "libcrypto.so.3", "libcrypto.so.1.1", "libcrypto.so"):
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError:
            continue
    else:
        raise RuntimeError("OpenSSL libcrypto-kirjastoa ei löytynyt järjestelmästä")

    lib.EVP_CIPHER_CTX_new.restype = ctypes.c_void_p
    lib.EVP_CIPHER_CTX_free.argtypes = [ctypes.c_void_p]
    lib.EVP_aes_256_gcm.restype = ctypes.c_void_p
    lib.EVP_CipherInit_ex.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    lib.EVP_CipherUpdate.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    lib.EVP_CipherFinal_ex.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.EVP_CIPHER_CTX_ctrl.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
    ]
    _LIBCRYPTO = lib
    return lib


def aes_gcm_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    lib = _get_libcrypto()
    ctx = lib.EVP_CIPHER_CTX_new()
    if not ctx:
        raise RuntimeError("EVP_CIPHER_CTX_new epäonnistui")
    try:
        if lib.EVP_CipherInit_ex(ctx, lib.EVP_aes_256_gcm(), None, None, None, 1) != 1:
            raise RuntimeError("EVP_CipherInit_ex (encrypt) epäonnistui")
        if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, len(iv), None) != 1:
            raise RuntimeError("EVP_CTRL_GCM_SET_IVLEN epäonnistui")
        if lib.EVP_CipherInit_ex(ctx, None, None, key, iv, 1) != 1:
            raise RuntimeError("EVP_CipherInit_ex (key/iv) epäonnistui")
        outbuf = ctypes.create_string_buffer(len(plaintext) + 16)
        outlen = ctypes.c_int(0)
        if lib.EVP_CipherUpdate(ctx, outbuf, ctypes.byref(outlen), plaintext, len(plaintext)) != 1:
            raise RuntimeError("EVP_CipherUpdate epäonnistui")
        finbuf = ctypes.create_string_buffer(16)
        finlen = ctypes.c_int(0)
        if lib.EVP_CipherFinal_ex(ctx, finbuf, ctypes.byref(finlen)) != 1:
            raise RuntimeError("EVP_CipherFinal_ex epäonnistui")
        tag = ctypes.create_string_buffer(16)
        if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, 16, tag) != 1:
            raise RuntimeError("EVP_CTRL_GCM_GET_TAG epäonnistui")
        return outbuf.raw[:outlen.value] + finbuf.raw[:finlen.value] + tag.raw
    finally:
        lib.EVP_CIPHER_CTX_free(ctx)


def aes_gcm_decrypt(key: bytes, iv: bytes, ct_and_tag: bytes) -> bytes:
    if len(ct_and_tag) < 16:
        raise ValueError("Salattu data on liian lyhyt")
    ct, tag = ct_and_tag[:-16], ct_and_tag[-16:]
    lib = _get_libcrypto()
    ctx = lib.EVP_CIPHER_CTX_new()
    if not ctx:
        raise RuntimeError("EVP_CIPHER_CTX_new epäonnistui")
    try:
        if lib.EVP_CipherInit_ex(ctx, lib.EVP_aes_256_gcm(), None, None, None, 0) != 1:
            raise RuntimeError("EVP_CipherInit_ex (decrypt) epäonnistui")
        if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, len(iv), None) != 1:
            raise RuntimeError("EVP_CTRL_GCM_SET_IVLEN epäonnistui")
        if lib.EVP_CipherInit_ex(ctx, None, None, key, iv, 0) != 1:
            raise RuntimeError("EVP_CipherInit_ex (key/iv) epäonnistui")
        outbuf = ctypes.create_string_buffer(len(ct) + 16)
        outlen = ctypes.c_int(0)
        if lib.EVP_CipherUpdate(ctx, outbuf, ctypes.byref(outlen), ct, len(ct)) != 1:
            raise RuntimeError("EVP_CipherUpdate epäonnistui")
        tagbuf = ctypes.create_string_buffer(tag, 16)
        if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, 16, tagbuf) != 1:
            raise RuntimeError("EVP_CTRL_GCM_SET_TAG epäonnistui")
        finbuf = ctypes.create_string_buffer(16)
        finlen = ctypes.c_int(0)
        if lib.EVP_CipherFinal_ex(ctx, finbuf, ctypes.byref(finlen)) != 1:
            raise ValueError("GCM-tagin tarkistus epäonnistui (väärä FAMILY_PLANNER_PASSWORD tai vioittunut data)")
        return outbuf.raw[:outlen.value] + finbuf.raw[:finlen.value]
    finally:
        lib.EVP_CIPHER_CTX_free(ctx)


def get_or_create_salt(salt_file=None, existing_enc_path=None):
    if salt_file and os.path.exists(salt_file):
        try:
            raw = base64.b64decode(open(salt_file, encoding="utf-8").read().strip())
            if len(raw) == 16:
                return raw
        except Exception:
            pass
    for p in (
        existing_enc_path,
        os.path.join(ROOT, "hoitovuorot.enc.json"),
        os.path.join(ROOT, "muistilista.enc.json"),
        os.path.join(ROOT, "data.enc.json"),
    ):
        if p and os.path.exists(p):
            try:
                doc = json.load(open(p, encoding="utf-8"))
                raw = base64.b64decode(doc.get("salt", ""))
                if len(raw) == 16:
                    if salt_file:
                        os.makedirs(os.path.dirname(os.path.abspath(salt_file)), exist_ok=True)
                        with open(salt_file, "w", encoding="utf-8") as f:
                            f.write(base64.b64encode(raw).decode("ascii"))
                    return raw
            except Exception:
                pass
    salt = os.urandom(16)
    if salt_file:
        os.makedirs(os.path.dirname(os.path.abspath(salt_file)), exist_ok=True)
        with open(salt_file, "w", encoding="utf-8") as f:
            f.write(base64.b64encode(salt).decode("ascii"))
    return salt


def encrypt_json_envelope(obj, password, salt_file=None, existing_enc_path=None):
    if not password:
        raise ValueError("FAMILY_PLANNER_PASSWORD puuttuu")
    salt = get_or_create_salt(salt_file=salt_file, existing_enc_path=existing_enc_path)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITER, dklen=32)
    iv = os.urandom(12)
    plain_bytes = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct_bytes = aes_gcm_encrypt(key, iv, plain_bytes)
    return {
        "v": 1,
        "alg": "AES-256-GCM",
        "kdf": "PBKDF2-SHA256",
        "iter": PBKDF2_ITER,
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ct": base64.b64encode(ct_bytes).decode("ascii"),
    }


def decrypt_json_envelope(doc, password):
    if not password:
        raise ValueError("FAMILY_PLANNER_PASSWORD puuttuu")
    if not isinstance(doc, dict) or doc.get("alg") != "AES-256-GCM" or doc.get("kdf") != "PBKDF2-SHA256":
        raise ValueError("Tuntematon salausmuoto")
    iters = int(doc.get("iter") or PBKDF2_ITER)
    salt = base64.b64decode(doc["salt"])
    iv = base64.b64decode(doc["iv"])
    ct = base64.b64decode(doc["ct"])
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters, dklen=32)
    plain_bytes = aes_gcm_decrypt(key, iv, ct)
    return json.loads(plain_bytes.decode("utf-8"))


def load_encrypted_json_list(path, password):
    if not path or not password or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        data = decrypt_json_envelope(doc, password)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def atomic_write_json(path, obj, compact=False):
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
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


# ---------- Kouvolan Aromi14 eMenus ----------
def http_json(url, data=None, timeout=25):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def menu_window(today):
    """Kuluvan kuukauden alusta seuraavan kuukauden loppuun (ruokalistat)."""
    start = today.replace(day=1)
    if start.month == 11:
        end = dt.date(start.year + 1, 1, 1) - dt.timedelta(days=1)
    elif start.month == 12:
        end = dt.date(start.year + 1, 2, 1) - dt.timedelta(days=1)
    else:
        end = dt.date(start.year, start.month + 2, 1) - dt.timedelta(days=1)
    return start, end


def aromi_restaurants():
    bootstrap = MENUS[0][1]
    info = http_json(
        f"{AROMI}/{bootstrap}/api/Common/Page/GetPageInfo?"
        + urllib.parse.urlencode({"currentpage": "Restaurant"})
    )
    out = {}
    for r in (info or {}).get("Restaurants") or []:
        code = r.get("UniqueCode")
        if code:
            out[code] = r
    return out


def aromi_menu(code, rid, start, end):
    base = f"{AROMI}/{code}/api"
    groups = http_json(
        f"{base}/GetRestaurantPublicDinerGroups?"
        + urllib.parse.urlencode({
            "id": rid,
            "startDate": start.strftime("%Y-%m-%dT00:00:00.000Z"),
            "endDate": end.strftime("%Y-%m-%dT00:00:00.000Z"),
        })
    )
    if not groups:
        raise RuntimeError(f"Ei julkisia ruokailijaryhmiä ({code})")
    g = dict(groups[0])
    g["SuitabilityDietIds"] = g.get("SuitabilityDietIds") or []
    meals = http_json(
        f"{base}/Common/Restaurant/RestaurantMeals?"
        + urllib.parse.urlencode({
            "Id": rid,
            "StartDate": start.strftime("%Y-%m-%dT00:00:00.000Z"),
            "EndDate": end.strftime("%Y-%m-%dT00:00:00.000Z"),
        }),
        data=g,
    )
    out = []
    for day in meals or []:
        pvm = (day.get("Date") or "")[:10]
        if not pvm:
            continue
        items = []
        for m in day.get("Meals") or []:
            name = (m.get("MealName") or "").strip()
            dishes = [
                {
                    "nimi": (x.get("DishName") or "").strip(),
                    "merkinnat": (x.get("DietDetails") or "").strip(),
                }
                for x in (m.get("Dishes") or [])
                if (x.get("DishName") or "").strip()
            ]
            if dishes:
                items.append({"ateria": name, "ruoat": dishes})
        if items:
            out.append({"pvm": pvm, "ateriat": items})
    out.sort(key=lambda d: d["pvm"])
    return {"ryhma": groups[0].get("Name"), "paivat": out}


def fetch_all_menus(start_date, end_date):
    found = aromi_restaurants()
    res = []
    for kids, code, rid_fallback, label, rooli in MENUS:
        r = found.get(code) or {}
        rid = r.get("Id") or rid_fallback
        title = r.get("Name") or label
        item = {
            "henkilot": kids,
            "otsikko": title,
            "lahde": f"{AROMI}/{code}/Page/Restaurant",
            "rooli": rooli,
            "koodi": code,
        }
        if not r:
            item["huom"] = "ravintolaa ei löytynyt listasta, käytetään varalla olevaa id:tä"
        menu_data = aromi_menu(code, rid, start_date, end_date)
        item.update(menu_data)
        item["ok"] = True
        res.append(item)
    return res


def diff_menus(old_menus, new_menus, from_date_iso):
    """Vertaa tulevien päivien (pvm >= from_date_iso) ruokalistoja aiempaan tilaan.
    Palauttaa (has_changes, summary_by_code).
    """
    def extract_upcoming(menus_list):
        if not isinstance(menus_list, list):
            return {}
        by_code = {}
        for m in menus_list:
            if not isinstance(m, dict):
                continue
            code = m.get("koodi") or m.get("rooli") or ""
            days = {
                d.get("pvm"): d.get("ateriat") or []
                for d in (m.get("paivat") or [])
                if isinstance(d, dict) and str(d.get("pvm") or "") >= from_date_iso and (d.get("ateriat") or [])
            }
            by_code[code] = days
        return by_code

    old_map = extract_upcoming(old_menus)
    new_map = extract_upcoming(new_menus)
    if not old_menus:
        has_changes = True
    else:
        has_changes = (old_map != new_map)

    summary = {}
    for code, new_days in new_map.items():
        old_days = old_map.get(code) or {}
        added_dates = sorted(set(new_days.keys()) - set(old_days.keys()))
        updated_dates = sorted(k for k in (set(new_days.keys()) & set(old_days.keys())) if new_days[k] != old_days[k])
        summary[code] = {
            "upcoming_days": len(new_days),
            "added_dates": added_dates,
            "updated_dates": updated_dates,
        }
    return has_changes, summary


# ---------- Git & Webhook ----------
def run_git(repo_dir, args, github_token=None, check=True):
    cmd = ["git", "-C", repo_dir]
    if github_token:
        basic = base64.b64encode(f"x-access-token:{github_token}".encode("utf-8")).decode("ascii")
        cmd += ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"]
    cmd += args
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def is_git_repo(repo_dir):
    try:
        r = run_git(repo_dir, ["rev-parse", "--is-inside-work-tree"], check=False)
        return r.returncode == 0 and r.stdout.strip() == "true"
    except Exception:
        return False


def git_sync_before_read(repo_dir, github_token=None):
    if not is_git_repo(repo_dir):
        return
    run_git(repo_dir, ["fetch", "-q", "origin", "main"], github_token=github_token, check=False)
    run_git(repo_dir, ["rebase", "-q", "--autostash", "origin/main"], github_token=github_token, check=False)


def git_commit_and_push_enc(repo_dir, enc_file, label="Ruokalistat", github_token=None):
    if not enc_file.endswith(".enc.json"):
        raise RuntimeError(f"Turvaesto: selväkielistä tiedostoa ({enc_file}) ei koskaan commitoida gitiin")
    if not is_git_repo(repo_dir):
        raise RuntimeError(f"Hakemisto {repo_dir} ei ole git-repo")

    rel_path = os.path.relpath(os.path.abspath(enc_file), repo_dir)
    git_name = os.environ.get("GIT_NAME", "eetuerantanen-ux")
    git_email = os.environ.get("GIT_EMAIL", "239039043+eetuerantanen-ux@users.noreply.github.com")

    run_git(repo_dir, ["add", "--", rel_path])
    diff_chk = run_git(repo_dir, ["diff", "--cached", "--quiet", "--", rel_path], check=False)
    if diff_chk.returncode == 0:
        return False

    stamp = dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    run_git(
        repo_dir,
        ["-c", f"user.name={git_name}", "-c", f"user.email={git_email}", "commit", "-q", "-m", f"{label} (salattu) {stamp}"],
    )

    for _ in range(1, 4):
        push_res = run_git(repo_dir, ["push", "-q", "origin", "HEAD:main"], github_token=github_token, check=False)
        if push_res.returncode == 0:
            return True
        if not github_token and os.environ.get("GITHUB_TOKEN"):
            github_token = os.environ.get("GITHUB_TOKEN")
            push_res = run_git(repo_dir, ["push", "-q", "origin", "HEAD:main"], github_token=github_token, check=False)
            if push_res.returncode == 0:
                return True
        run_git(repo_dir, ["fetch", "-q", "origin", "main"], github_token=github_token, check=False)
        rb = run_git(repo_dir, ["rebase", "-q", "origin/main"], github_token=github_token, check=False)
        if rb.returncode != 0:
            run_git(repo_dir, ["rebase", "--abort"], check=False)
            raise RuntimeError(f"git rebase origin/main epäonnistui: {rb.stderr.strip()}")
    raise RuntimeError(f"git push origin HEAD:main epäonnistui 3 yrityksellä: {push_res.stderr.strip()}")


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


def default_enc_menus_path():
    return os.path.join(ROOT, "ruokalistat.enc.json")


def default_state_path():
    return os.path.join(ROOT, ".publish-state", "ruokalistat.sent.json")


def default_salt_path():
    return os.path.join(ROOT, ".publish-state", "salt")


def main():
    ap = argparse.ArgumentParser(description="Hae Lehvätien ja Jaakonpuiston päiväkotien ruokalistat, salaa ruokalistat.enc.json ja päivitä vain kun uusia ruokalistoja ilmestyy.")
    ap.add_argument("--from-date", help="Alkupäivä YYYY-MM-DD (oletus: kuluvan kuun 1. päivä)")
    ap.add_argument("--to-date", help="Loppupäivä YYYY-MM-DD (oletus: seuraavan kuun viimeinen päivä)")
    ap.add_argument("--out-menus", "--out-enc", dest="out_menus", default=default_enc_menus_path(),
                    help="Polku salattuun ruokalistat.enc.json-tiedostoon (oletus: ./ruokalistat.enc.json)")
    ap.add_argument("--out-plain", help="Valinnainen polku selväkieliselle ruokalistat.json-tiedostolle (ei koskaan commitoida gitiin)")
    ap.add_argument("--state-file", default=default_state_path(), help="Tiedosto johon tallennetaan viimeksi synkattu tila")
    ap.add_argument("--no-git-commit", "--webhook-only", dest="no_git_commit", action="store_true",
                    help="Varatila: älä commitoi/pushaa ruokalistat.enc.json-tiedostoa gitiin")
    ap.add_argument("--webhook-url", help="Webhook-osoite (oletus: GROK_WEBHOOK_URL / EVAKA_WEBHOOK_URL / WEBHOOK_URL)")
    ap.add_argument("--webhook-key", help="Webhook-avain (oletus: GROK_WEBHOOK_KEY / EVAKA_WEBHOOK_KEY / WEBHOOK_KEY)")
    ap.add_argument("--no-webhook", action="store_true", help="Älä kutsu webhookia vaikka muutoksia löytyisi")
    ap.add_argument("--force-webhook", action="store_true", help="Kutsu webhookia vaikka muutoksia ei olisi")
    ap.add_argument("--init-state", action="store_true", help="Tallenna nykytila vertailupohjaksi ilman git-pushia tai webhookia")
    ap.add_argument("--decrypt", action="store_true", help="Purkaa ruokalistat.enc.json -> tulostaa selväkielisen JSON-listan stdoutiin")
    ap.add_argument("--decrypt-to", metavar="PATH", help="Purkaa ruokalistat.enc.json atomisesti annettuun tiedostoon (esim. shared/ruokalistat.json)")
    args = ap.parse_args()

    load_secrets(os.path.join(ROOT, "secrets.env"))
    enc_password = os.environ.get("FAMILY_PLANNER_PASSWORD") or os.environ.get("EVAKA_ENCRYPT_PASSWORD")

    if args.decrypt or args.decrypt_to:
        if not enc_password:
            print("fetch-menus.py: FAMILY_PLANNER_PASSWORD puuttuu purkua varten", file=sys.stderr)
            sys.exit(2)
        if not os.path.exists(args.out_menus):
            print(f"fetch-menus.py: Salattua tiedostoa ei löydy: {args.out_menus}", file=sys.stderr)
            sys.exit(1)
        with open(args.out_menus, encoding="utf-8") as f:
            doc = json.load(f)
        menus = decrypt_json_envelope(doc, enc_password)
        if args.decrypt_to:
            atomic_write_json(args.decrypt_to, menus)
            print(f"Purettu {len(menus)} päiväkodin ruokalistat -> {args.decrypt_to}")
        if args.decrypt:
            json.dump(menus, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        return

    if not enc_password:
        print("fetch-menus.py: FAMILY_PLANNER_PASSWORD puuttuu (vaaditaan ruokalistojen salaamiseen)", file=sys.stderr)
        sys.exit(2)

    webhook_url = (
        args.webhook_url
        or os.environ.get("GROK_WEBHOOK_URL")
        or os.environ.get("EVAKA_WEBHOOK_URL")
        or os.environ.get("WEBHOOK_URL")
    )
    webhook_key = (
        args.webhook_key
        or os.environ.get("GROK_WEBHOOK_KEY")
        or os.environ.get("EVAKA_WEBHOOK_KEY")
        or os.environ.get("WEBHOOK_KEY")
    )
    state_path = args.state_file

    today = dt.datetime.now(TZ).date()
    default_start, default_end = menu_window(today)
    start_date = dt.date.fromisoformat(args.from_date) if args.from_date else default_start
    end_date = dt.date.fromisoformat(args.to_date) if args.to_date else default_end

    repo_dir = os.path.dirname(os.path.abspath(args.out_menus)) or ROOT
    if not args.no_git_commit and not args.init_state:
        git_sync_before_read(repo_dir, github_token=None)

    shared_menus_path = os.path.join(ROOT, "shared", "ruokalistat.json")
    baseline_menus = (
        load_json_list(state_path)
        or load_encrypted_json_list(args.out_menus, enc_password)
        or load_json_list(shared_menus_path)
    )

    menus = fetch_all_menus(start_date, end_date)
    has_changes, diff_summary = diff_menus(baseline_menus, menus, today.isoformat())
    if not os.path.exists(args.out_menus):
        has_changes = True

    if os.path.isdir(os.path.join(ROOT, "shared")):
        atomic_write_json(shared_menus_path, menus)
    if args.out_plain:
        atomic_write_json(args.out_plain, menus)

    legacy_plain = os.path.join(ROOT, "ruokalistat.json")
    if os.path.exists(legacy_plain) and (not args.out_plain or os.path.abspath(args.out_plain) != os.path.abspath(legacy_plain)):
        try:
            os.remove(legacy_plain)
        except OSError:
            pass

    enc_doc = None
    if has_changes or not os.path.exists(args.out_menus):
        enc_doc = encrypt_json_envelope(
            menus,
            enc_password,
            salt_file=default_salt_path(),
            existing_enc_path=args.out_menus,
        )
        atomic_write_json(args.out_menus, enc_doc, compact=True)

    parts = []
    for code, info in diff_summary.items():
        parts.append(
            f"{code}: {info['upcoming_days']} tulevaa pv "
            f"(uusia: {len(info['added_dates'])}, muuttuneita: {len(info['updated_dates'])})"
        )
    print(f"ruokalistat.enc.json tarkistettu ({start_date}..{end_date}): " + "; ".join(parts))

    if args.init_state:
        atomic_write_json(state_path, menus)
        print(f"Vertailutila alustettu ({state_path}), ei git-pushia eikä webhookia.")
        return

    committed_to_git = False
    if has_changes and not args.no_git_commit:
        if is_git_repo(repo_dir):
            try:
                committed_to_git = git_commit_and_push_enc(repo_dir, args.out_menus, label="Ruokalistat", github_token=None)
                if committed_to_git:
                    print("ruokalistat.enc.json (AES-256-GCM) commitoitu ja pushattu origin/main-haaraan.")
                else:
                    print("ruokalistat.enc.json oli jo ajan tasalla gitissä.")
            except Exception as e:
                print(f"fetch-menus.py: git commit/push epäonnistui ({e}) — jatketaan webhook-varatilalla", file=sys.stderr)
        else:
            print(f"Huom: {repo_dir} ei ole git-repo, ohitetaan git commit/push ja käytetään webhook-varatilaa.")

    if not args.no_webhook and webhook_url and (has_changes or args.force_webhook):
        if enc_doc is None and os.path.exists(args.out_menus):
            try:
                enc_doc = json.load(open(args.out_menus, encoding="utf-8"))
            except Exception:
                enc_doc = encrypt_json_envelope(menus, enc_password, salt_file=default_salt_path())
        payload = {
            "source": "perhekalenteri-pi-menus",
            "event": "ruokalistat_updated",
            "mode": "webhook_only" if args.no_git_commit else "git_and_webhook",
            "committed_to_git": committed_to_git,
            "encrypted_file": os.path.basename(args.out_menus),
            "timestamp": dt.datetime.now(TZ).isoformat(timespec="seconds"),
            "forced": bool(args.force_webhook and not has_changes),
            "window": {
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
            },
            "diff": diff_summary,
            "ruokalistat_enc": enc_doc,
            "ruokalistat": menus,
        }
        try:
            status, resp_body = send_webhook(webhook_url, webhook_key, payload)
            atomic_write_json(state_path, menus)
            print(f"Webhook lähetetty (HTTP {status}): {resp_body[:160]}")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace").strip()
            print(f"fetch-menus.py: Webhook epäonnistui (HTTP {e.code}): {err_body[:200]}", file=sys.stderr)
            sys.exit(3)
        except Exception as e:
            print(f"fetch-menus.py: Webhook-virhe: {e}", file=sys.stderr)
            sys.exit(3)
    elif has_changes and committed_to_git and (args.no_webhook or not webhook_url):
        atomic_write_json(state_path, menus)
        if not args.no_webhook and not webhook_url:
            print("Huom: ruokalistat.enc.json pushattiin gitiin, mutta GROK_WEBHOOK_URL puuttuu secrets.env-tiedostosta.")
    elif not has_changes:
        if not os.path.exists(state_path):
            atomic_write_json(state_path, menus)
        print("Ei uusia tai muuttuneita ruokalistoja tuleville viikoille — ei git-committia eikä webhook-kutsua.")


if __name__ == "__main__":
    main()
