#!/usr/bin/env python3
"""Hakee eVakan hoitovuorot (ja valinnaisesti saapuneet viestit/tiedotteet) suoraan eVakan
JSON-rajapinnasta heikolla tunnistautumisella (sähköposti + salasana) ilman selainta.

Tietoturva (julkinen GitHub-repo):
  * Selväkielistä hoitovuorot.json-tiedostoa EI KOSKAAN kirjoiteta tai commitoida julkiseen repoon.
  * Hoitovuorot salataan ennen tallennusta ja git-committia tiedostoon hoitovuorot.enc.json
    samalla AES-256-GCM + PBKDF2-SHA256 (1 000 000 kierrosta) -formaatilla kuin data.enc.json:
      {"v": 1, "alg": "AES-256-GCM", "kdf": "PBKDF2-SHA256", "iter": 1000000, "salt": "...", "iv": "...", "ct": "..."}
  * Salasana luetaan ympäristömuuttujasta FAMILY_PLANNER_PASSWORD (tai secrets.env-tiedostosta).

Toimintatila (oletus):
  1. Synkronoi paikallisen git-repon (origin/main) ja lukee aiemman vertailupohjan
     (.publish-state/hoitovuorot.sent.json tai purkaa hoitovuorot.enc.json).
  2. Hakee eVakasta hoitovuorot 2 kk kalenteri-ikkunalle.
  3. Jos vuoroissa on muutoksia tai uusia vuoroja:
     a) OLETUS (git + webhook): Salaa vuorot tiedostoon hoitovuorot.enc.json, commitoi ja pushaa
        sen GitHub-repoon (origin/main), ja kutsuu sen jälkeen Grok Botin julkaisu-webhookia.
     b) VARATILA (--webhook-only / --no-git-commit): Ei tee git-committia, vaan lähettää
        muuttuneet vuorot suoraan webhookin JSON-payloadissa Grok Botille (sekä lähettää
        saman JSON-payloadin aina myös oletustilassa webhook-kutsun mukana varalta).

Purkaminen (Grok Bot / tarkistus):
  * python3 fetch-evaka.py --decrypt
      Purkaa hoitovuorot.enc.json -> tulostaa JSON-listan stdoutiin.
  * python3 fetch-evaka.py --decrypt-to shared/hoitovuorot.json
      Purkaa hoitovuorot.enc.json atomisesti annettuun tiedostoon.

Kirjoittaa:
  * hoitovuorot.enc.json                 (AES-256-GCM-salattu [{lapsi, pvm, alku, loppu}], commitoitava)
  * .publish-state/hoitovuorot.sent.json (viimeksi synkattu tila, gitignorettu)
  * shared/hoitovuorot.json              (päivitetään vain, jos paikallinen shared/-kansio on olemassa; gitignorettu)
  * raw/evaka_messages.json              (viimeisimmät viestit, jos --with-messages annetaan; gitignorettu)

Tunnukset ja webhook-asetukset luetaan ympäristömuuttujista tai tiedostosta secrets.env:
  * EVAKA_USERNAME           (pakollinen haettaessa eVakasta)
  * EVAKA_PASSWORD           (pakollinen haettaessa eVakasta)
  * FAMILY_PLANNER_PASSWORD  (pakollinen salaukseen ja purkuun; sama salasana kuin data.enc.json)
  * GROK_WEBHOOK_URL         (tai EVAKA_WEBHOOK_URL / WEBHOOK_URL)
  * GROK_WEBHOOK_KEY         (tai EVAKA_WEBHOOK_KEY / WEBHOOK_KEY)
  * GITHUB_TOKEN             (valinnainen; käytetään git push -tunnistautumiseen, jos asetettu)
"""
import argparse, base64, ctypes, ctypes.util, datetime as dt, hashlib, http.cookiejar, json, os, subprocess, sys, urllib.error, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True

ROOT = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("Europe/Helsinki")
BASE_URL = "https://varhaiskasvatus.kouvola.fi"
UA = "perhekalenteri-evaka/1.0"
PBKDF2_ITER = 1000000


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


# ---------- AES-256-GCM + PBKDF2-SHA256 (yhteensopiva tools/encrypt.js & app.js kanssa) ----------
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
    """Palauttaa ciphertext || 16-tavuinen GCM-autentikointitagi (sama muoto kuin WebCrypto AES-GCM)."""
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
    """Tarkistaa 16-tavuisen GCM-tagin ja palauttaa selväkieliset tavut."""
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
    """Lukee suolan .publish-state/salt-tiedostosta, olemassa olevasta .enc.json-tiedostosta tai luo uuden 16-tavuisen suolan."""
    if salt_file and os.path.exists(salt_file):
        try:
            raw = base64.b64decode(open(salt_file, encoding="utf-8").read().strip())
            if len(raw) == 16:
                return raw
        except Exception:
            pass
    for p in (existing_enc_path, os.path.join(ROOT, "data.enc.json")):
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
    """Salaa JSON-objektin AES-256-GCM + PBKDF2-SHA256 (1 000 000 kierrosta) -rakenteeseen."""
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
    """Purkaa AES-256-GCM + PBKDF2-SHA256 -salatun JSON-envelope-objektin."""
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
    """Päivittää paikallisen repon origin/mainista ennen vertailua, jotta vertailupohja on tuore."""
    if not is_git_repo(repo_dir):
        return
    run_git(repo_dir, ["fetch", "-q", "origin", "main"], github_token=github_token, check=False)
    run_git(repo_dir, ["rebase", "-q", "--autostash", "origin/main"], github_token=github_token, check=False)


def git_commit_and_push_shifts(repo_dir, enc_shifts_file, github_token=None):
    """Commitoi ja pushaa VAIN salatun .enc.json-tiedoston origin/mainiin (max 3 yritystä rebasella)."""
    if not enc_shifts_file.endswith(".enc.json"):
        raise RuntimeError(f"Turvaesto: selväkielistä tiedostoa ({enc_shifts_file}) ei koskaan commitoida gitiin")
    if not is_git_repo(repo_dir):
        raise RuntimeError(f"Hakemisto {repo_dir} ei ole git-repo")

    rel_path = os.path.relpath(os.path.abspath(enc_shifts_file), repo_dir)
    git_name = os.environ.get("GIT_NAME", "eetuerantanen-ux")
    git_email = os.environ.get("GIT_EMAIL", "239039043+eetuerantanen-ux@users.noreply.github.com")

    run_git(repo_dir, ["add", "--", rel_path])
    diff_chk = run_git(repo_dir, ["diff", "--cached", "--quiet", "--", rel_path], check=False)
    if diff_chk.returncode == 0:
        return False  # Ei uutta commitoitavaa gitissä

    stamp = dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    run_git(
        repo_dir,
        ["-c", f"user.name={git_name}", "-c", f"user.email={git_email}", "commit", "-q", "-m", f"Hoitovuorot (salattu) {stamp}"],
    )

    for attempt in range(1, 4):
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


def default_enc_shifts_path():
    # Oletuksena repon juuren salattu hoitovuorot.enc.json
    return os.path.join(ROOT, "hoitovuorot.enc.json")


def default_state_path():
    # .publish-state/ on .gitignoressa, joten tilatiedosto ei koskaan päädy git-committiin
    return os.path.join(ROOT, ".publish-state", "hoitovuorot.sent.json")


def default_salt_path():
    return os.path.join(ROOT, ".publish-state", "salt")


def main():
    ap = argparse.ArgumentParser(description="Hae eVakan hoitovuorot, salaa hoitovuorot.enc.json, commitoi gitiin ja kutsu webhookia.")
    ap.add_argument("--from-date", help="Alkupäivä YYYY-MM-DD (oletus: kuluvan kuun ruudukon alku)")
    ap.add_argument("--to-date", help="Loppupäivä YYYY-MM-DD (oletus: seuraavan kuun ruudukon loppu)")
    ap.add_argument("--out-shifts", "--out-enc", dest="out_shifts", default=default_enc_shifts_path(),
                    help="Polku salattuun hoitovuorot.enc.json-tiedostoon (oletus: ./hoitovuorot.enc.json)")
    ap.add_argument("--out-plain", help="Valinnainen polku selväkieliselle hoitovuorot.json-tiedostolle (ei koskaan commitoida gitiin)")
    ap.add_argument("--state-file", default=default_state_path(), help="Tiedosto johon tallennetaan viimeksi synkattu tila")
    ap.add_argument("--out-messages", default=os.path.join(ROOT, "raw", "evaka_messages.json"))
    ap.add_argument("--with-messages", action="store_true", help="Hae myös eVakan saapuneet viestit raw/evaka_messages.json-tiedostoon")
    ap.add_argument("--no-messages", action="store_true", help="Älä hae viestejä (oletus)")
    ap.add_argument("--no-git-commit", "--webhook-only", dest="no_git_commit", action="store_true",
                    help="Varatila: älä commitoi/pushaa hoitovuorot.enc.json-tiedostoa gitiin, lähetä vain webhook-payload")
    ap.add_argument("--webhook-url", help="Webhook-osoite (oletus: GROK_WEBHOOK_URL / EVAKA_WEBHOOK_URL / WEBHOOK_URL)")
    ap.add_argument("--webhook-key", help="Webhook-avain (oletus: GROK_WEBHOOK_KEY / EVAKA_WEBHOOK_KEY / WEBHOOK_KEY)")
    ap.add_argument("--no-webhook", action="store_true", help="Älä kutsu webhookia vaikka muutoksia löytyisi")
    ap.add_argument("--force-webhook", action="store_true", help="Kutsu webhookia vaikka muutoksia ei olisi")
    ap.add_argument("--init-state", action="store_true", help="Tallenna nykytila vertailupohjaksi ilman git-pushia tai webhookia")
    ap.add_argument("--decrypt", action="store_true", help="Purkaa hoitovuorot.enc.json -> tulostaa selväkielisen JSON-listan stdoutiin")
    ap.add_argument("--decrypt-to", metavar="PATH", help="Purkaa hoitovuorot.enc.json atomisesti annettuun tiedostoon (esim. shared/hoitovuorot.json)")
    args = ap.parse_args()

    load_secrets(os.path.join(ROOT, "secrets.env"))
    enc_password = os.environ.get("FAMILY_PLANNER_PASSWORD") or os.environ.get("EVAKA_ENCRYPT_PASSWORD")

    # Purkutila (esim. Grok Botin publish.sh / collect.py tai paikallinen tarkistus)
    if args.decrypt or args.decrypt_to:
        if not enc_password:
            print("fetch-evaka.py: FAMILY_PLANNER_PASSWORD puuttuu purkua varten", file=sys.stderr)
            sys.exit(2)
        if not os.path.exists(args.out_shifts):
            print(f"fetch-evaka.py: Salattua tiedostoa ei löydy: {args.out_shifts}", file=sys.stderr)
            sys.exit(1)
        with open(args.out_shifts, encoding="utf-8") as f:
            doc = json.load(f)
        shifts = decrypt_json_envelope(doc, enc_password)
        if args.decrypt_to:
            atomic_write_json(args.decrypt_to, shifts)
            print(f"Purettu {len(shifts)} hoitovuoroa -> {args.decrypt_to}")
        if args.decrypt:
            json.dump(shifts, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        return

    user = os.environ.get("EVAKA_USERNAME")
    pw = os.environ.get("EVAKA_PASSWORD")
    if not user or not pw:
        print("fetch-evaka.py: EVAKA_USERNAME tai EVAKA_PASSWORD puuttuu (secrets.env)", file=sys.stderr)
        sys.exit(2)
    if not enc_password:
        print("fetch-evaka.py: FAMILY_PLANNER_PASSWORD puuttuu (vaaditaan hoitovuorojen salaamiseen)", file=sys.stderr)
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
    default_start, default_end = calendar_window(today)
    start_date = dt.date.fromisoformat(args.from_date) if args.from_date else default_start
    end_date = dt.date.fromisoformat(args.to_date) if args.to_date else default_end

    repo_dir = os.path.dirname(os.path.abspath(args.out_shifts)) or ROOT
    if not args.no_git_commit and not args.init_state:
        git_sync_before_read(repo_dir, github_token=None)

    # Luetaan aiempi vertailutila (1. viimeksi synkattu tila, 2. salattu hoitovuorot.enc.json, 3. shared/hoitovuorot.json)
    shared_shifts_path = os.path.join(ROOT, "shared", "hoitovuorot.json")
    baseline_shifts = (
        load_json_list(state_path)
        or load_encrypted_json_list(args.out_shifts, enc_password)
        or load_json_list(shared_shifts_path)
    )

    client = EvakaClient()
    client.login(user, pw)

    shifts = fetch_care_shifts(client, start_date, end_date)
    added, removed = diff_shifts(baseline_shifts, shifts, start_date.isoformat())
    has_changes = bool(added or removed) or not os.path.exists(args.out_shifts)

    # Jos paikallinen shared/-kansio on olemassa (gitignorettu), pidetään se ajan tasalla
    if os.path.isdir(os.path.join(ROOT, "shared")):
        atomic_write_json(shared_shifts_path, shifts)
    if args.out_plain:
        atomic_write_json(args.out_plain, shifts)

    # Jos repon juureen on aiemmin jäänyt selväkielinen hoitovuorot.json, poistetaan se turvallisuussyistä
    legacy_plain = os.path.join(ROOT, "hoitovuorot.json")
    if os.path.exists(legacy_plain) and (not args.out_plain or os.path.abspath(args.out_plain) != os.path.abspath(legacy_plain)):
        try:
            os.remove(legacy_plain)
        except OSError:
            pass

    # Päivitetään salattu hoitovuorot.enc.json vain, jos vuorot muuttuivat tai tiedosto puuttuu
    enc_doc = None
    if has_changes or not os.path.exists(args.out_shifts):
        enc_doc = encrypt_json_envelope(
            shifts,
            enc_password,
            salt_file=default_salt_path(),
            existing_enc_path=args.out_shifts,
        )
        atomic_write_json(args.out_shifts, enc_doc, compact=True)

    print(
        f"hoitovuorot.enc.json tarkistettu ({start_date}..{end_date}): {len(shifts)} vuoroa "
        f"(uusia: {len(added)}, poistuneita/muuttuneita: {len(removed)})"
    )

    if args.init_state:
        atomic_write_json(state_path, shifts)
        print(f"Vertailutila alustettu ({state_path}), ei git-pushia eikä webhookia.")
        return

    committed_to_git = False
    if has_changes and not args.no_git_commit:
        if is_git_repo(repo_dir):
            try:
                committed_to_git = git_commit_and_push_shifts(repo_dir, args.out_shifts, github_token=None)
                if committed_to_git:
                    print("hoitovuorot.enc.json (AES-256-GCM) commitoitu ja pushattu origin/main-haaraan.")
                else:
                    print("hoitovuorot.enc.json oli jo ajan tasalla gitissä.")
            except Exception as e:
                print(f"fetch-evaka.py: git commit/push epäonnistui ({e}) — jatketaan webhook-varatilalla", file=sys.stderr)
        else:
            print(f"Huom: {repo_dir} ei ole git-repo, ohitetaan git commit/push ja käytetään webhook-varatilaa.")

    if not args.no_webhook and webhook_url and (has_changes or args.force_webhook):
        if enc_doc is None and os.path.exists(args.out_shifts):
            try:
                enc_doc = json.load(open(args.out_shifts, encoding="utf-8"))
            except Exception:
                enc_doc = encrypt_json_envelope(shifts, enc_password, salt_file=default_salt_path())
        payload = {
            "source": "perhekalenteri-pi-evaka",
            "event": "hoitovuorot_updated",
            "mode": "webhook_only" if args.no_git_commit else "git_and_webhook",
            "committed_to_git": committed_to_git,
            "encrypted_file": os.path.basename(args.out_shifts),
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
            "hoitovuorot_enc": enc_doc,
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
    elif has_changes and committed_to_git and (args.no_webhook or not webhook_url):
        atomic_write_json(state_path, shifts)
        if not args.no_webhook and not webhook_url:
            print("Huom: hoitovuorot.enc.json pushattiin gitiin, mutta GROK_WEBHOOK_URL puuttuu secrets.env-tiedostosta.")
    elif not has_changes:
        if not os.path.exists(state_path):
            atomic_write_json(state_path, shifts)
        print("Ei muutoksia hoitovuoroissa — ei git-committia eikä webhook-kutsua.")

    if args.with_messages and not args.no_messages:
        msgs = fetch_messages(client)
        atomic_write_json(args.out_messages, msgs)
        print(f"evaka_messages.json päivitetty: {len(msgs['ketjut'])} viestiketjua")


if __name__ == "__main__":
    main()
