#!/usr/bin/env python3
"""Hakee (ja valinnaisesti muokkaa) Google Keep -muistiinpanon "Muistilista" kohteet,
salaa ne tiedostoon muistilista.enc.json (AES-256-GCM + PBKDF2-SHA256, 1 000 000 kierrosta),
commitoi ja pushaa muutokset GitHub-repoon (origin/main) ja kutsuu Grok Botin julkaisu-webhookia.

Tietoturva (julkinen GitHub-repo):
  * Selväkielistä muistilista.json-tiedostoa EI KOSKAAN kirjoiteta tai commitoida julkiseen repoon.
  * Muistilista salataan ennen tallennusta ja git-committia tiedostoon muistilista.enc.json
    samalla AES-256-GCM + PBKDF2-SHA256 (1 000 000 kierrosta) -formaatilla kuin data.enc.json ja hoitovuorot.enc.json:
      {"v": 1, "alg": "AES-256-GCM", "kdf": "PBKDF2-SHA256", "iter": 1000000, "salt": "...", "iv": "...", "ct": "..."}
  * Salasana luetaan ympäristömuuttujasta FAMILY_PLANNER_PASSWORD (tai secrets.env-tiedostosta).

Purkaminen (Grok Bot / publish.sh / tarkistus — ei vaadi gkeepapi-kirjastoa):
  * python3 fetch-keep.py --decrypt
      Purkaa muistilista.enc.json -> tulostaa JSON-listan ([{teksti, tehty}]) stdoutiin.
  * python3 fetch-keep.py --out-todo publish/muistilista.enc.json --decrypt-to shared/muistilista.json
      Purkaa muistilista.enc.json atomisesti annettuun tiedostoon.

Kertaluonteinen Google Keep Master Tokenin luonti (Raspberry Pi):
  * python3 fetch-keep.py --exchange-oauth-token "oauth2_4/..." [--save-token]
      Vaihtaa EmbeddedSetup-sivulta kopioidun oauth_token-evästeen pysyväksi KEEP_MASTER_TOKENiksi
      (ja tallentaa sen secrets.env-tiedostoon, jos --save-token annetaan).

Muokkauskomennot (tulevaa tabletti-käyttöliittymää ja komentoriviä varten):
  * python3 fetch-keep.py --add "Osta maitoa"
  * python3 fetch-keep.py --check "Osta maitoa"
  * python3 fetch-keep.py --uncheck "Osta maitoa"
  * python3 fetch-keep.py --remove "Osta maitoa"

Tunnukset ja asetukset luetaan ympäristömuuttujista tai tiedostosta secrets.env:
  * KEEP_EMAIL               (Google-tilin sähköposti; oletuksena EVAKA_USERNAME jos asetettu)
  * KEEP_MASTER_TOKEN        (Google Keepin aas_et/... master token, pakollinen Keep-hakuun)
  * KEEP_NOTE_TITLE          (oletus: "Muistilista")
  * KEEP_NOTE_ID             (valinnainen; jos asetettu, hakee suoraan tällä Keep-tunnisteella)
  * FAMILY_PLANNER_PASSWORD  (pakollinen salaukseen ja purkuun; sama salasana kuin data.enc.json)
  * GROK_WEBHOOK_URL         (tai EVAKA_WEBHOOK_URL / WEBHOOK_URL)
  * GROK_WEBHOOK_KEY         (tai EVAKA_WEBHOOK_KEY / WEBHOOK_KEY)
  * GITHUB_TOKEN             (valinnainen; käytetään git push -tunnistautumiseen, jos asetettu)
"""
import argparse, base64, ctypes, ctypes.util, datetime as dt, hashlib, json, os, subprocess, sys, urllib.error, urllib.request
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True

ROOT = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("Europe/Helsinki")
UA = "perhekalenteri-keep/1.0"
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


def save_secret_var(path, key, value):
    """Päivittää tai lisää avain=arvo-rivin secrets.env-tiedostoon."""
    lines = []
    replaced = False
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith(f"{key}=") or s.startswith(f"export {key}="):
                    lines.append(f'{key}="{value}"\n')
                    replaced = True
                else:
                    lines.append(line if line.endswith("\n") else line + "\n")
    if not replaced:
        lines.append(f'{key}="{value}"\n')
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(lines)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


# ---------- AES-256-GCM + PBKDF2-SHA256 (yhteensopiva tools/encrypt.js, fetch-evaka.py & app.js kanssa) ----------
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
    for p in (existing_enc_path, os.path.join(ROOT, "hoitovuorot.enc.json"), os.path.join(ROOT, "data.enc.json")):
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


# ---------- Google Keep & .venv-lataus ----------
def ensure_keep_deps():
    """Tuo gkeepapi (ja gpsoauth). Jos nykyisessä Pythonissa ei ole gkeepapi-pakettia,
    mutta ROOT/.venv/bin/python3 on olemassa, käynnistää skriptin automaattisesti .venv-ympäristössä.
    """
    try:
        import gkeepapi  # noqa: F401
        import gkeepapi.node

        def _safe_weblink_load(self, raw):
            super(gkeepapi.node.WebLink, self)._load(raw)
            wl = raw.get("webLink") or {}
            self._title = wl.get("title")
            self._url = wl.get("url", "")
            self._image_url = wl.get("imageUrl")
            self._provenance_url = wl.get("provenanceUrl", "")
            self._description = wl.get("description")

        if hasattr(gkeepapi.node, "WebLink"):
            gkeepapi.node.WebLink._load = _safe_weblink_load
        return
    except ImportError:
        venv_py = os.path.join(ROOT, ".venv", "bin", "python3")
        if os.path.exists(venv_py) and os.path.realpath(sys.executable) != os.path.realpath(venv_py):
            os.execv(venv_py, [venv_py] + sys.argv)
        print(
            "fetch-keep.py: gkeepapi-kirjastoa ei löytynyt.\n"
            "Asenna se Raspberry Pi:llä komennolla:\n"
            f"  python3 -m venv {os.path.join(ROOT, '.venv')} && "
            f"{os.path.join(ROOT, '.venv', 'bin', 'pip')} install gkeepapi gpsoauth",
            file=sys.stderr,
        )
        sys.exit(2)


def exchange_oauth_for_master_token(email, oauth_token, android_id="0123456789abcdef"):
    ensure_keep_deps()
    import gpsoauth
    res = gpsoauth.exchange_token(email, oauth_token, android_id)
    if not isinstance(res, dict) or "Token" not in res:
        raise RuntimeError(f"Master tokenin vaihto epäonnistui: {res}")
    return res["Token"]


def find_keep_note(keep, note_title="Muistilista", note_id=None):
    if note_id:
        n = keep.get(note_id)
        if n is not None:
            return n
    title_norm = (note_title or "Muistilista").strip().lower()
    candidates = []
    for n in keep.all():
        if getattr(n, "trashed", False) or getattr(n, "deleted", False):
            continue
        t = (getattr(n, "title", "") or "").strip().lower()
        if t == title_norm:
            candidates.append(n)
    if not candidates:
        raise RuntimeError(f'Google Keepistä ei löytynyt muistiinpanoa otsikolla "{note_title}"')
    # Suositaan kiinnitettyä (pinned) tai arkistoimatonta muistiinpanoa
    candidates.sort(key=lambda n: (not bool(getattr(n, "pinned", False)), bool(getattr(n, "archived", False))))
    return candidates[0]


def extract_todo_items(note):
    """Muuntaa Google Keep -muistiinpanon (List tai Note) muotoon [{teksti, tehty}]."""
    items = []
    if hasattr(note, "items"):
        # gkeepapi.node.List: note.unchecked + note.checked (tai note.items lajiteltuna)
        unchecked = getattr(note, "unchecked", None)
        checked = getattr(note, "checked", None)
        if unchecked is not None and checked is not None:
            ordered = list(unchecked) + list(checked)
        else:
            ordered = list(note.items)
        for it in ordered:
            txt = (getattr(it, "text", "") or "").strip()
            if not txt:
                continue
            items.append({
                "teksti": txt,
                "tehty": bool(getattr(it, "checked", False)),
            })
    else:
        raw_text = getattr(note, "text", "") or ""
        for line in raw_text.splitlines():
            s = line.strip()
            if not s:
                continue
            done = False
            if s.startswith(("[x]", "[X]", "✓", "✔")):
                done = True
                s = s.lstrip("[xX]✓✔ ").strip()
            elif s.startswith(("[ ]", "-", "*", "•")):
                s = s.lstrip("[ ]-*• ").strip()
            if s:
                items.append({"teksti": s, "tehty": done})
    return items


def apply_keep_mutations(note, add_items=None, remove_items=None, check_items=None, uncheck_items=None):
    """Suorittaa lisäykset/poistot/kuittaukset Google Keep -muistiinpanoon."""
    changed = False
    add_items = [x.strip() for x in (add_items or []) if x and x.strip()]
    remove_set = {x.strip().lower() for x in (remove_items or []) if x and x.strip()}
    check_set = {x.strip().lower() for x in (check_items or []) if x and x.strip()}
    uncheck_set = {x.strip().lower() for x in (uncheck_items or []) if x and x.strip()}

    if hasattr(note, "items"):
        for it in list(note.items):
            txt_norm = (getattr(it, "text", "") or "").strip().lower()
            if txt_norm in remove_set:
                it.delete()
                changed = True
            elif txt_norm in check_set and not it.checked:
                it.checked = True
                changed = True
            elif txt_norm in uncheck_set and it.checked:
                it.checked = False
                changed = True
        for txt in add_items:
            import gkeepapi
            placement = getattr(gkeepapi.node.NewListItemPlacementValue, "Bottom", None)
            if placement is not None:
                note.add(txt, False, placement)
            else:
                note.add(txt, False)
            changed = True
    else:
        lines = [ln for ln in (note.text or "").splitlines() if ln.strip()]
        if remove_set:
            new_lines = [ln for ln in lines if ln.strip().lower() not in remove_set]
            if new_lines != lines:
                lines = new_lines
                changed = True
        for txt in add_items:
            lines.append(txt)
            changed = True
        if changed:
            note.text = "\n".join(lines)
    return changed


def fetch_and_mutate_keep_todo(
    email,
    master_token,
    note_title="Muistilista",
    note_id=None,
    cache_file=None,
    add_items=None,
    remove_items=None,
    check_items=None,
    uncheck_items=None,
):
    ensure_keep_deps()
    import gkeepapi

    keep = gkeepapi.Keep()
    cached_state = None
    if cache_file and os.path.exists(cache_file):
        try:
            cached_state = json.load(open(cache_file, encoding="utf-8"))
        except Exception:
            cached_state = None

    if hasattr(keep, "authenticate"):
        keep.authenticate(email, master_token, state=cached_state)
    else:
        keep.resume(email, master_token, state=cached_state)
    note = find_keep_note(keep, note_title=note_title, note_id=note_id)

    mutated = apply_keep_mutations(
        note,
        add_items=add_items,
        remove_items=remove_items,
        check_items=check_items,
        uncheck_items=uncheck_items,
    )
    if mutated:
        keep.sync()

    if cache_file:
        try:
            atomic_write_json(cache_file, keep.dump(), compact=True)
        except Exception:
            pass

    return extract_todo_items(note)


def diff_todo(old_items, new_items):
    """Vertaa aiempaa ja uutta muistilistaa ([{teksti, tehty}]).
    Palauttaa (has_changes, added, removed, toggled).
    """
    if old_items is None:
        return True, list(new_items), [], []
    has_changes = (old_items != new_items)
    old_map = {str(x.get("teksti") or ""): bool(x.get("tehty")) for x in old_items if isinstance(x, dict)}
    new_map = {str(x.get("teksti") or ""): bool(x.get("tehty")) for x in new_items if isinstance(x, dict)}
    added = [{"teksti": k, "tehty": new_map[k]} for k in new_map if k not in old_map]
    removed = [{"teksti": k, "tehty": old_map[k]} for k in old_map if k not in new_map]
    toggled = [
        {"teksti": k, "tehty": new_map[k]}
        for k in new_map
        if k in old_map and old_map[k] != new_map[k]
    ]
    return has_changes, added, removed, toggled


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


def git_commit_and_push_enc(repo_dir, enc_file, label="Muistilista", github_token=None):
    """Commitoi ja pushaa VAIN salatun .enc.json-tiedoston origin/mainiin (max 3 yritystä rebasella)."""
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


def default_enc_todo_path():
    return os.path.join(ROOT, "muistilista.enc.json")


def default_state_path():
    return os.path.join(ROOT, ".publish-state", "muistilista.sent.json")


def default_keep_cache_path():
    return os.path.join(ROOT, ".publish-state", "keep_state.json")


def default_salt_path():
    return os.path.join(ROOT, ".publish-state", "salt")


def main():
    ap = argparse.ArgumentParser(description="Hae Google Keepin Muistilista, salaa muistilista.enc.json, commitoi gitiin ja kutsu webhookia.")
    ap.add_argument("--note-title", help="Google Keep -muistiinpanon otsikko (oletus: KEEP_NOTE_TITLE tai 'Muistilista')")
    ap.add_argument("--note-id", help="Valinnainen Google Keep -muistiinpanon ID (oletus: KEEP_NOTE_ID)")
    ap.add_argument("--out-todo", "--out-enc", dest="out_todo", default=default_enc_todo_path(),
                    help="Polku salattuun muistilista.enc.json-tiedostoon (oletus: ./muistilista.enc.json)")
    ap.add_argument("--out-plain", help="Valinnainen polku selväkieliselle muistilista.json-tiedostolle (ei koskaan commitoida gitiin)")
    ap.add_argument("--state-file", default=default_state_path(), help="Tiedosto johon tallennetaan viimeksi synkattu tila")
    ap.add_argument("--keep-cache", default=default_keep_cache_path(), help="Välimuistitiedosto gkeepapi-synkronoinnille")
    ap.add_argument("--no-git-commit", "--webhook-only", dest="no_git_commit", action="store_true",
                    help="Varatila: älä commitoi/pushaa muistilista.enc.json-tiedostoa gitiin, lähetä vain webhook-payload")
    ap.add_argument("--webhook-url", help="Webhook-osoite (oletus: GROK_WEBHOOK_URL / EVAKA_WEBHOOK_URL / WEBHOOK_URL)")
    ap.add_argument("--webhook-key", help="Webhook-avain (oletus: GROK_WEBHOOK_KEY / EVAKA_WEBHOOK_KEY / WEBHOOK_KEY)")
    ap.add_argument("--no-webhook", action="store_true", help="Älä kutsu webhookia vaikka muutoksia löytyisi")
    ap.add_argument("--force-webhook", action="store_true", help="Kutsu webhookia vaikka muutoksia ei olisi")
    ap.add_argument("--init-state", action="store_true", help="Tallenna nykytila vertailupohjaksi ilman git-pushia tai webhookia")
    ap.add_argument("--decrypt", action="store_true", help="Purkaa muistilista.enc.json -> tulostaa selväkielisen JSON-listan stdoutiin")
    ap.add_argument("--decrypt-to", metavar="PATH", help="Purkaa muistilista.enc.json atomisesti annettuun tiedostoon (esim. shared/muistilista.json)")
    ap.add_argument("--exchange-oauth-token", metavar="OAUTH_TOKEN",
                    help="Vaihtaa Google EmbeddedSetup oauth_token-evästeen pysyväksi KEEP_MASTER_TOKENiksi")
    ap.add_argument("--save-token", action="store_true", help="Tallentaa --exchange-oauth-token-komennolla luodun tokenin suoraan secrets.env-tiedostoon")
    ap.add_argument("--add", action="append", default=[], metavar="TEKSTI", help="Lisää uusi rivi Google Keep -muistilistaan")
    ap.add_argument("--remove", action="append", default=[], metavar="TEKSTI", help="Poista rivi Google Keep -muistilistasta")
    ap.add_argument("--check", action="append", default=[], metavar="TEKSTI", help="Merkitse rivi tehdyksi Google Keep -muistilistassa")
    ap.add_argument("--uncheck", action="append", default=[], metavar="TEKSTI", help="Merkitse rivi tekemättömäksi Google Keep -muistilistassa")
    args = ap.parse_args()

    secrets_path = os.path.join(ROOT, "secrets.env")
    load_secrets(secrets_path)
    enc_password = os.environ.get("FAMILY_PLANNER_PASSWORD") or os.environ.get("EVAKA_ENCRYPT_PASSWORD")

    # 1) Purkutila (Grok Botin publish.sh / collect.py tai paikallinen tarkistus — toimii puhtaalla stdlibillä)
    if args.decrypt or args.decrypt_to:
        if not enc_password:
            print("fetch-keep.py: FAMILY_PLANNER_PASSWORD puuttuu purkua varten", file=sys.stderr)
            sys.exit(2)
        if not os.path.exists(args.out_todo):
            print(f"fetch-keep.py: Salattua tiedostoa ei löydy: {args.out_todo}", file=sys.stderr)
            sys.exit(1)
        with open(args.out_todo, encoding="utf-8") as f:
            doc = json.load(f)
        items = decrypt_json_envelope(doc, enc_password)
        if args.decrypt_to:
            atomic_write_json(args.decrypt_to, items)
            print(f"Purettu {len(items)} muistilistan kohdetta -> {args.decrypt_to}")
        if args.decrypt:
            json.dump(items, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        return

    email = os.environ.get("KEEP_EMAIL") or os.environ.get("EVAKA_USERNAME")

    # 2) Kertaluonteinen OAuth-tokenin vaihto Master Tokeniksi
    if args.exchange_oauth_token:
        if not email:
            print("fetch-keep.py: KEEP_EMAIL (tai EVAKA_USERNAME) puuttuu secrets.env-tiedostosta", file=sys.stderr)
            sys.exit(2)
        master_token = exchange_oauth_for_master_token(email, args.exchange_oauth_token.strip())
        if args.save_token:
            save_secret_var(secrets_path, "KEEP_EMAIL", email)
            save_secret_var(secrets_path, "KEEP_MASTER_TOKEN", master_token)
            print(f"KEEP_MASTER_TOKEN tallennettu tiedostoon {secrets_path}")
        else:
            print(f'KEEP_MASTER_TOKEN="{master_token}"')
        return

    master_token = os.environ.get("KEEP_MASTER_TOKEN")
    if not email or not master_token:
        print(
            "fetch-keep.py: KEEP_EMAIL tai KEEP_MASTER_TOKEN puuttuu (secrets.env).\n"
            "Voit luoda KEEP_MASTER_TOKENin komennolla:\n"
            '  python3 fetch-keep.py --exchange-oauth-token "oauth2_4/..." --save-token',
            file=sys.stderr,
        )
        sys.exit(2)
    if not enc_password:
        print("fetch-keep.py: FAMILY_PLANNER_PASSWORD puuttuu (vaaditaan muistilistan salaamiseen)", file=sys.stderr)
        sys.exit(2)

    note_title = args.note_title or os.environ.get("KEEP_NOTE_TITLE") or "Muistilista"
    note_id = args.note_id or os.environ.get("KEEP_NOTE_ID")
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

    repo_dir = os.path.dirname(os.path.abspath(args.out_todo)) or ROOT
    if not args.no_git_commit and not args.init_state:
        git_sync_before_read(repo_dir, github_token=None)

    shared_todo_path = os.path.join(ROOT, "shared", "muistilista.json")
    baseline_items = (
        load_json_list(state_path)
        or load_encrypted_json_list(args.out_todo, enc_password)
        or load_json_list(shared_todo_path)
    )

    items = fetch_and_mutate_keep_todo(
        email=email,
        master_token=master_token,
        note_title=note_title,
        note_id=note_id,
        cache_file=args.keep_cache,
        add_items=args.add,
        remove_items=args.remove,
        check_items=args.check,
        uncheck_items=args.uncheck,
    )

    has_changes, added, removed, toggled = diff_todo(baseline_items, items)
    if not os.path.exists(args.out_todo):
        has_changes = True

    if os.path.isdir(os.path.join(ROOT, "shared")):
        atomic_write_json(shared_todo_path, items)
    if args.out_plain:
        atomic_write_json(args.out_plain, items)

    # Poistetaan mahdollinen selväkielinen muistilista.json repon juuresta
    legacy_plain = os.path.join(ROOT, "muistilista.json")
    if os.path.exists(legacy_plain) and (not args.out_plain or os.path.abspath(args.out_plain) != os.path.abspath(legacy_plain)):
        try:
            os.remove(legacy_plain)
        except OSError:
            pass

    enc_doc = None
    if has_changes or not os.path.exists(args.out_todo):
        enc_doc = encrypt_json_envelope(
            items,
            enc_password,
            salt_file=default_salt_path(),
            existing_enc_path=args.out_todo,
        )
        atomic_write_json(args.out_todo, enc_doc, compact=True)

    print(
        f"muistilista.enc.json tarkistettu: {len(items)} kohdetta "
        f"(uusia: {len(added)}, poistettuja: {len(removed)}, tila muuttunut: {len(toggled)})"
    )

    if args.init_state:
        atomic_write_json(state_path, items)
        print(f"Vertailutila alustettu ({state_path}), ei git-pushia eikä webhookia.")
        return

    committed_to_git = False
    if has_changes and not args.no_git_commit:
        if is_git_repo(repo_dir):
            try:
                committed_to_git = git_commit_and_push_enc(repo_dir, args.out_todo, label="Muistilista", github_token=None)
                if committed_to_git:
                    print("muistilista.enc.json (AES-256-GCM) commitoitu ja pushattu origin/main-haaraan.")
                else:
                    print("muistilista.enc.json oli jo ajan tasalla gitissä.")
            except Exception as e:
                print(f"fetch-keep.py: git commit/push epäonnistui ({e}) — jatketaan webhook-varatilalla", file=sys.stderr)
        else:
            print(f"Huom: {repo_dir} ei ole git-repo, ohitetaan git commit/push ja käytetään webhook-varatilaa.")

    if not args.no_webhook and webhook_url and (has_changes or args.force_webhook):
        if enc_doc is None and os.path.exists(args.out_todo):
            try:
                enc_doc = json.load(open(args.out_todo, encoding="utf-8"))
            except Exception:
                enc_doc = encrypt_json_envelope(items, enc_password, salt_file=default_salt_path())
        payload = {
            "source": "perhekalenteri-pi-keep",
            "event": "muistilista_updated",
            "mode": "webhook_only" if args.no_git_commit else "git_and_webhook",
            "committed_to_git": committed_to_git,
            "encrypted_file": os.path.basename(args.out_todo),
            "timestamp": dt.datetime.now(TZ).isoformat(timespec="seconds"),
            "forced": bool(args.force_webhook and not has_changes),
            "summary": {
                "total": len(items),
                "added_count": len(added),
                "removed_count": len(removed),
                "toggled_count": len(toggled),
            },
            "diff": {
                "added": added,
                "removed": removed,
                "toggled": toggled,
            },
            "muistilista_enc": enc_doc,
            "muistilista": items,
        }
        try:
            status, resp_body = send_webhook(webhook_url, webhook_key, payload)
            atomic_write_json(state_path, items)
            print(f"Webhook lähetetty (HTTP {status}): {resp_body[:160]}")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace").strip()
            print(f"fetch-keep.py: Webhook epäonnistui (HTTP {e.code}): {err_body[:200]}", file=sys.stderr)
            sys.exit(3)
        except Exception as e:
            print(f"fetch-keep.py: Webhook-virhe: {e}", file=sys.stderr)
            sys.exit(3)
    elif has_changes and committed_to_git and (args.no_webhook or not webhook_url):
        atomic_write_json(state_path, items)
        if not args.no_webhook and not webhook_url:
            print("Huom: muistilista.enc.json pushattiin gitiin, mutta GROK_WEBHOOK_URL puuttuu secrets.env-tiedostosta.")
    elif not has_changes:
        if not os.path.exists(state_path):
            atomic_write_json(state_path, items)
        print("Ei muutoksia muistilistassa — ei git-committia eikä webhook-kutsua.")


if __name__ == "__main__":
    main()
