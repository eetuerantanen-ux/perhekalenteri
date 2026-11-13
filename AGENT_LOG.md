# Perhekalenteri — Agent Collaboration & Change Log (`AGENT_LOG.md`)

This file is the shared coordination log between **Antigravity**, **Grok Bot**, and **DeepSeek Harness** for developing and maintaining `perhekalenteri`.

## Collaboration Rules for All Agents

1. **Read First**: Before planning or making any code, style, or automation changes, always read this file (`AGENT_LOG.md`) first to see recent changes made by the other agents, and [`ARCHITECTURE.md`](ARCHITECTURE.md) for the technical map of the system.
2. **Preserve Changes (Important for Grok Bot's Publish Script)**:
   - Antigravity and DeepSeek Harness may commit updates directly to `index.html`, `app.js`, `style.css`, and `AGENT_LOG.md` in this GitHub repository.
   - If Grok Bot publishes from a local working directory or template directory, Grok Bot **must** sync/pull changes from `origin/main` before publishing so it does not overwrite edits made by Antigravity (such as `index.html` template files, `app.js`, `style.css`, or `AGENT_LOG.md`).
3. **Publishing via Webhook**:
   - After Antigravity commits and pushes code changes and updates `AGENT_LOG.md`, Antigravity triggers Grok Bot's publish webhook (credentials stored privately in `~/.gemini/perhekalenteri-webhook.env`, never in git) and marks the entry as `Published via webhook: YES`.
   - When Grok Bot sees an entry already published via the webhook, it can skip redundant work on its next hourly cycle if no new changes occurred.
4. **Log Every Code/Feature Change**:
   - Do **not** log routine hourly data-only updates (`data.enc.json`, `prices.json`, `forecast.json`).
   - **Do** log every UI, logic, CSS, data-schema, or automation change.
   - Add new entries at the **top** of the `## Change Log` section (newest first).
   - Every entry must clearly identify the author in the heading: **`[Antigravity]`**, **`[Grok Bot]`**, or **`[DeepSeek Harness]`**.
5. **Commit Directly, But Sync First**: DeepSeek Harness commits directly to `main` from a local clone. Like Grok Bot, it must `git fetch` and rebase onto `origin/main` before pushing, so it never overwrites Antigravity's or Grok Bot's commits.

---

## Current Data & Automation Schedule (Europe/Helsinki)

| Routine | Run by | Schedule | Exact steps / commands |
|---|---|---|---|
| Perhekalenterin päivitys | Tekninen automaatiobotti (Grok Bot) | every 30 min, 06:00–22:00 (and on webhook trigger) | sync `publish/` from `origin/main` → decrypt `publish/hoitovuorot.enc.json` (`fetch-evaka.py --decrypt-to shared/hoitovuorot.json`), `publish/muistilista.enc.json` (`fetch-keep.py --decrypt-to shared/muistilista.json`), and `publish/ruokalistat.enc.json` (`fetch-menus.py --decrypt-to shared/ruokalistat.json`) → fetch 4 Google calendars → `python3 collect.py` → `bash publish.sh` |
| Pörssisähkön hinnat | Tekninen automaatiobotti (Grok Bot) | daily 16:00 | `python3 fetch-prices.py` (internally runs `python3 fetch-forecast.py --out publish/forecast.json`) |
| **Ruokalistat (Aromi14)** | **Raspberry Pi (`fetch-menus.py`)** | **Tuesdays at 14:00 (`0 14 * * 2`) on Pi** | Fetches both **Lehvätien päiväkoti** (`Lehvatienpk`, `rooli="arki"`) and **Jaakonpuiston päiväkoti** (`Jaakonpuistonpk`, `rooli="vuoro"`) from Kouvolan Aromi14 eMenus for the current + next month, compares upcoming days (`pvm >= today`) against `.publish-state/ruokalistat.sent.json` / `ruokalistat.enc.json`, and **only when new or updated menu items appear in the coming weeks**: encrypts with `AES-256-GCM` (`PBKDF2-SHA256`, 1,000,000 iterations, `FAMILY_PLANNER_PASSWORD`) to **`ruokalistat.enc.json`**, commits & pushes `ruokalistat.enc.json` to `origin/main`, and calls Grok Bot's publish webhook. `publish.sh` decrypts `publish/ruokalistat.enc.json` into `shared/ruokalistat.json`, and `collect.py` reads `shared/ruokalistat.json` instead of polling Aromi14 every 30 minutes |
| **Muistilista (Google Keep)** | **Raspberry Pi (`fetch-keep.py`) + Arjen apuri fallback** | **Hourly 07:00–21:00 (`0 7-21 * * *`) on Pi** | Connects to Google Keep (`gkeepapi` with `KEEP_EMAIL` + `KEEP_MASTER_TOKEN`), reads note `"Muistilista"` (`[{teksti, tehty}]`), compares against `.publish-state/muistilista.sent.json` / `muistilista.enc.json`, and if changed: encrypts with `AES-256-GCM` (`PBKDF2-SHA256`, 1,000,000 iterations, `FAMILY_PLANNER_PASSWORD`) to **`muistilista.enc.json`**, commits & pushes `muistilista.enc.json` to `origin/main`, and calls Grok Bot's publish webhook (`muistilista_enc` + `muistilista` + `diff` in POST JSON body). `publish.sh` decrypts `muistilista.enc.json` into `shared/muistilista.json` (`python3 publish/fetch-keep.py --out-todo publish/muistilista.enc.json --decrypt-to shared/muistilista.json`, newer source wins vs. Arjen apuri fallback). Also supports `--add`, `--remove`, `--check`, `--uncheck` for two-way editing |
| Muistutukset (eVaka) | Arjen apuri (Grok Bot) | hourly on weekdays 07:00–19:00 | writes `shared/muistutukset.json` (eVaka, read-only; fields `otsikko`, `pvm`, `lapsi`, `lahde`) |
| Muistutukset (email) | Arjen apuri (Grok Bot) | hourly 08:00–21:00 | appends to `shared/muistutukset.json` from `eetu.org` email (`lahde="sähköposti"`) |
| **Hoitovuorot (eVaka)** | **Raspberry Pi (`fetch-evaka.py`) + Arjen apuri fallback** | **Daily at 07:00, 14:00, and 19:00 (`0 7,14,19 * * *`) on Pi** | Logs into `varhaiskasvatus.kouvola.fi` citizen API (`EVAKA_USERNAME` + `EVAKA_PASSWORD`), fetches 2-month care shifts (`[{lapsi, pvm, alku, loppu}]`), compares against `.publish-state/hoitovuorot.sent.json` / `hoitovuorot.enc.json`, and if changed: encrypts with `AES-256-GCM` (`PBKDF2-SHA256`, 1,000,000 iterations, `FAMILY_PLANNER_PASSWORD`) to **`hoitovuorot.enc.json`**, commits & pushes `hoitovuorot.enc.json` to `origin/main`, and calls Grok Bot's publish webhook (`hoitovuorot_enc` + `hoitovuorot` + `diff` in POST JSON body). `publish.sh` decrypts `hoitovuorot.enc.json` into `shared/hoitovuorot.json` (newer source wins vs. Arjen apuri fallback) |
| Antigravity / Pi julkaisu (webhook) | Koodaribotti (Grok Bot) | on demand | webhook triggers `publish.sh` (decrypts `hoitovuorot.enc.json`, `muistilista.enc.json`, & `ruokalistat.enc.json` → `shared/` → `collect.py` → `data.enc.json`) |
| Tablet version check | tablet browser | data every 5 min; full reload every 6 h | `app.js checkVersion()` fetches `version.json` and reloads when the version changes |

---

## Entry Template

```markdown
### YYYY-MM-DD HH:MM (Europe/Helsinki) — [Antigravity | Grok Bot | DeepSeek Harness] — Short Title
- **Agent**: Antigravity (or Grok Bot / DeepSeek Harness)
- **Changes**:
  - Detailed list of changes made (or planned).
- **Reasoning**:
  - Why this change was made and the design/technical rationale behind it.
- **Affected Files & Components**:
  - Files (`index.html`, `app.js`, `style.css`, `version.json`, etc.) and UI/data components affected.
- **Grok Bot Automation Impact**:
  - **Required / None**: Explicitly state whether Grok Bot needs to update its data fetchers, schema (`data.enc.json`, `prices.json`, `forecast.json`), or publish scripts.
- **Publish Status**:
  - Whether the publish webhook was triggered by Antigravity.
```

---

## Change Log

### 2026-11-14 00:08 (Europe/Helsinki) — [DeepSeek Harness] — SSH access to the Raspberry Pi established; first health check and two documentation corrections

- **Agent**: DeepSeek Harness
- **Changes**:
  - **SSH access**: generated a dedicated ed25519 keypair on this machine (`~/.ssh/id_ed25519`, comment `dsh-deepseek-harness`) and installed the public key in `pi@192.168.1.243:~/.ssh/authorized_keys`. Verified key-only login (`ssh -o BatchMode=yes`), i.e. no password is required or stored anywhere. The Pi's password was intentionally **not** collected or saved.
  - **First health check (read-only)** — all green:
    - host `raspberrypi`, `pi@192.168.1.243`, `Linux 5.10.103-v7l+ armv7l`, uptime 45 days.
    - system Python 3.9.2 and `/home/pi/perhekalenteri/.venv` Python 3.9.2 both present.
    - `cron` service active; the repo clone is at `6a98fa4` with a **clean** working tree.
    - `cron.log` shows the 19:00 evaka/keep runs and the 20:00/21:00 keep runs with `exit=0`, "no changes" — i.e. the collectors are healthy and correctly idle.
    - Root filesystem 21 GB of 30 GB used (74 %) — worth watching but not urgent.
  - **Documentation corrections in [`ARCHITECTURE.md`](ARCHITECTURE.md) §7**:
    1. **§7.5**: noted that the live crontab also contains an unrelated `cozify-logger` job (every 10 min) that is not part of this project.
    2. **§7.6**: recorded the *observed* contents of the Pi's `secrets.env` and the consequence that `GROK_WEBHOOK_*` and `SMTP_*` are **not** set there. SMTP works from `run_evaka_cron.py` defaults plus `/home/pi/smtp_pw`; the webhook does not fire at all, so Pi-originated changes still push to git but publish only on the next scheduled 30-minute run (06:00–22:00). Data correctness is unaffected — only publish latency — and adding the two `GROK_WEBHOOK_*` variables to the Pi would restore immediate publishing.
  - **Operating notes for future agents** (Windows-specific): pass remote scripts by piping them into `ssh … bash -s` rather than as an inline argument, because PowerShell strips the inner quotes; and add `-o UpdateHostKeys=no` so ssh does not try (and fail) to rewrite `known_hosts` inside the sandbox.
  - **No changes** to any code file, generated data file, or the Pi itself.
- **Reasoning**:
  - Calendar symptoms often originate upstream of the page (stale or missing data), so being able to read the Pi's cron log and failure counters turns "the card is wrong" into a diagnosable question. Doing it with a key instead of the Pi password avoids spreading a credential that also unlocks `GITHUB_TOKEN`, eVaka and Google Keep. The two doc corrections exist because the numbers in a document that disagrees with the machine are worse than no document.
- **Affected Files & Components**:
  - `ARCHITECTURE.md` (§7.5, §7.6); `AGENT_LOG.md`. Remote access setup on this workstation (`~/.ssh/id_ed25519`), `authorized_keys` on the Pi.
- **Grok Bot Automation Impact**:
  - **Recommended, optional**: add `GROK_WEBHOOK_URL` / `GROK_WEBHOOK_KEY` to `/home/pi/perhekalenteri/secrets.env` to restore immediate webhook publishing from the Pi. No schema or fetcher change needed.
- **Publish Status**:
  - **Published via webhook**: NO (documentation-only change; no stamped code file changed).

### 2026-11-13 23:55 (Europe/Helsinki) — [Antigravity] — Document Raspberry Pi environment, virtualenv build, failure alerting wrapper, and configuration in ARCHITECTURE.md

- **Agent**: Antigravity
- **Changes**:
  - Expanded **[`ARCHITECTURE.md`](ARCHITECTURE.md) §7** ("Automation & Raspberry Pi Environment") to document the Raspberry Pi (`pi@192.168.1.243`, Debian 11 Bullseye, 32-bit ARMv7) setup, configuration, and runtime architecture:
    1. **Host environment & Git configuration (§7.1, §7.2)**: Documented system specs, repository location (`/home/pi/perhekalenteri`), `.git/info/exclude` rules, and automated HTTPS git push authentication using `GITHUB_TOKEN` from `secrets.env` via HTTP extra headers.
    2. **Python environments & virtualenv build (§7.3)**: Documented the dual-runtime setup — system Python 3.9 for `fetch-evaka.py` and `fetch-menus.py` (zero pip dependencies, ctypes OpenSSL libcrypto), and dedicated virtualenv `/home/pi/perhekalenteri/.venv` for `fetch-keep.py` with prebuilt ARMv7 wheels (`--only-binary=pycryptodomex` from piwheels), runtime `gkeepapi 0.14.2` patches, and one-time OAuth token exchange to permanent `KEEP_MASTER_TOKEN`.
    3. **Cron wrapper & failure alerting (§7.5)**: Documented `/home/pi/perhekalenteri/run_evaka_cron.py`, per-job state tracking in `.publish-state/`, and automatic email alerts sent via Gandi authenticated SMTP (`mail.gandi.net:465`, SSL, `From: eetu@eetu.org`, `To: eetu.e.rantanen@gmail.com`) when any job fails 3 consecutive times.
    4. **Crontab & secrets inventory (§7.5, §7.6)**: Documented the active crontab schedules and full environment variable specification in `secrets.env`.
  - Updated Section 1 (table), Section 4 (data flow diagram with `run_evaka_cron.py`), and Section 5 (crypto/dependency constraints) in `ARCHITECTURE.md`.
- **Reasoning**:
  - Keeps `ARCHITECTURE.md` as an accurate and complete technical map of the entire system for all collaborating agents (Antigravity, Grok Bot, DeepSeek Harness).
- **Affected Files & Components**:
  - `ARCHITECTURE.md` (§1, §4, §5, §7)
  - `AGENT_LOG.md`
- **Grok Bot Automation Impact**:
  - **None**: Documentation update only.
- **Publish Status**:
  - **Published via webhook**: NO (docs-only change; no stamped code file modified).

### 2026-11-13 23:44 (Europe/Helsinki) — [DeepSeek Harness] — Planner password consolidated into `secrets.env`; docs and ignore rules follow

- **Agent**: DeepSeek Harness
- **Changes**:
  - Eetu moved the planner password from the standalone `calendarpw.txt` into `secrets.env` as **`FAMILY_PLANNER_PASSWORD`** and deleted `calendarpw.txt`. That is the variable the Raspberry Pi scripts already read, so there is now a single gitignored secret file for both the publish webhook and the encryption key.
  - **Verified** the new location end-to-end: reading `FAMILY_PLANNER_PASSWORD` from `secrets.env` and decrypting `data.enc.json` through the browser's WebCrypto path (PBKDF2-SHA256 @ 1 000 000 iterations → AES-256-GCM) succeeds — 5 members, 134 events, 30 daycare shifts, `paivitetty` 2026-11-13 23:29. The check printed no password and no personal values.
  - **[`ARCHITECTURE.md`](ARCHITECTURE.md) §9** now states the password lives in gitignored `secrets.env` as `FAMILY_PLANNER_PASSWORD`, and repeats the rule: never commit it, never echo it, never pass it on a command line; read it from the environment.
  - **`.gitignore`**: kept the `calendarpw.txt` entry as a defensive guard against the file being recreated (now with a comment saying the password has moved to `secrets.env`).
  - Temporary verification script deleted; no plaintext data file written into the repository.
  - **No changes** to `index.html`, `app.js`, `style.css`, `version.json`, or any generated data file.
- **Reasoning**:
  - Two secret files in a public repository's working tree is one more way to leak one of them. Consolidating on `secrets.env` matches what the Pi scripts and the webhook already expect, and the ignore entry for the old filename costs nothing while preventing a regression.
- **Affected Files & Components**:
  - `ARCHITECTURE.md` (§9); `.gitignore`; `AGENT_LOG.md`. `secrets.env` is local-only and untracked.
- **Grok Bot Automation Impact**:
  - **None for the schema or fetchers.** For the publisher: its `.gitignore` heredoc should carry both `secrets.env` and `calendarpw.txt` so neither can be committed by a publish run.
- **Publish Status**:
  - **Published via webhook**: NO (documentation/ignore change only; no stamped code file changed, so the version hash is unaffected).

### 2026-11-13 23:41 (Europe/Helsinki) — [DeepSeek Harness] — Gitignore the local planner password file; verify it decrypts and correct the documented data schema

- **Agent**: DeepSeek Harness
- **Changes**:
  - **`.gitignore`**: added `calendarpw.txt`. The local planner-password file was sitting **untracked but not ignored** at the repository root, so any `git add -A` in this clone (which is how the publish routine stages its working copy) would have committed a plaintext password to this public repository. `git check-ignore` now confirms it is excluded.
  - **Verified the password** with the same WebCrypto path the browser uses — PBKDF2-SHA256 (1 000 000 iterations) over the envelope salt → AES-256-GCM decrypt of `data.enc.json`. Result: decryption succeeds; envelope confirmed as 16-byte salt, 12-byte IV, ~211 KB ciphertext. The check printed **only** field names and counts, never the password or any personal values.
  - **Corrected [`ARCHITECTURE.md`](ARCHITECTURE.md) §5** against the decrypted payload: added the previously undocumented top-level keys `aikavyohyke`, `kalenterit[{kalenteri, ok, tapahtumia}]` and `viikkonumerot{ "YYYY-MM-DD": "Viikko 44 / 2026" }`; documented the real `ruokalistat[]` fields (`henkilot`, `lahde`, `koodi`, `ryhma`, `ok`, and `ruoat[].merkinnat`); completed `saa` (`paikka`, `nyt.sade`, `tunnit[].sade_tn`); noted that only shift events carry `puokkari` / `puokkari_kuka`; and recorded the verified snapshot (134 events / 30 shifts / 5 members / 2 menu lists of 38+57 days / 16 forecast days / 0 errors).
  - **`ARCHITECTURE.md` §9** now says where the password lives locally (`calendarpw.txt`, gitignored) and repeats the rule: never commit it, never echo it, never pass it as a command-line argument.
  - Temporary verification scripts were deleted; no plaintext data file was written to the repository.
  - **No changes** to `index.html`, `app.js`, `style.css`, `version.json`, or any generated data file.
- **Reasoning**:
  - A plaintext password inside a public repository's working tree is a leak waiting for one careless `git add -A`, so it belongs in `.gitignore` next to `secrets.env`. Having the password also made it possible to replace the schema I had inferred by reading `app.js` with the schema the payload actually has, which is what future coding work will rely on.
- **Affected Files & Components**:
  - `.gitignore` (`calendarpw.txt`); `ARCHITECTURE.md` (§5 and §9); `AGENT_LOG.md`.
- **Grok Bot Automation Impact**:
  - **None**: no fetched data, schema, or publish-script change. Note for the publisher: its `.gitignore` heredoc should also carry `calendarpw.txt` so the exclusion survives a publish run, in the same spirit as `secrets.env`.
- **Publish Status**:
  - **Published via webhook**: NO (gitignore + documentation only; no stamped code file changed, so the version hash is unaffected and there is nothing to publish).

### 2026-11-13 23:38 (Europe/Helsinki) — [DeepSeek Harness] — Add `ARCHITECTURE.md` (system map) and link it from the read-first rule

- **Agent**: DeepSeek Harness
- **Changes**:
  - Added **[`ARCHITECTURE.md`](ARCHITECTURE.md)** to the repository root: a technical map verified against the current code, covering the repository layout, deployment (GitHub Pages, legacy branch build from `main`, no build step), the version-stamping/cache-busting contract, the frontend structure (`index.html` / `app.js` / `style.css` division, render model, hash-routed views, idle timeout, runtime card scrolling), the data flow Pi → publisher → browser, the `AES-256-GCM` + `PBKDF2-SHA256` envelope and the decrypted `data.enc.json` schema, `prices.json` / `forecast.json` / `version.json` shapes, the care-shift domain rules (meal windows, `arki`/`vuoro` selection, 16:00 menu rollover), the three Raspberry Pi scripts and their schedules, contributor rules, local testing options (`?nyt`, `?tila`, localhost `data.json` fallback), and known constraints.
  - Updated collaboration **rule 1** to point at `ARCHITECTURE.md` alongside `AGENT_LOG.md`.
  - Documentation contains **no secrets** and **no personal data**: webhook credential names only (`GROK_WEBHOOK_URL` / `GROK_WEBHOOK_KEY`, `FAMILY_PLANNER_PASSWORD`), no family member names, and daycares referred to by role (`arki` / `vuoro`) rather than name.
  - **No changes** to `index.html`, `app.js`, `style.css`, `version.json`, or any generated data file.
- **Reasoning**:
  - The repository had no README or architecture documentation at all; the only durable knowledge was the change history in this log. A standing document lowers the cost of onboarding a fourth agent (or a human) and records the invariants that break the pipeline when ignored — generated files, version-stamp hooks, no-plaintext rule, sync-before-push.
- **Affected Files & Components**:
  - `ARCHITECTURE.md` (new); `AGENT_LOG.md` (rule 1 + this entry).
- **Grok Bot Automation Impact**:
  - **None**: `ARCHITECTURE.md` is not one of the stamped code files and new files are preserved untouched by the publish routine. No schema, fetcher, or publish-script change; no version-hash impact.
- **Publish Status**:
  - **Published via webhook**: NO (documentation-only change; nothing to publish and the version hash is unaffected, so the webhook was deliberately not called).

### 2026-11-13 23:28 (Europe/Helsinki) — [DeepSeek Harness] — Record publish-webhook access in local `secrets.env`; connectivity test commit

- **Agent**: DeepSeek Harness
- **Changes**:
  - **Publish webhook access**: Eetu provided the Grok Bot publish webhook, now stored **locally only** in `secrets.env` (gitignored via `.gitignore:7`) as `GROK_WEBHOOK_URL` and `GROK_WEBHOOK_KEY`. Confirmed with `git check-ignore -v secrets.env` that the file can never be committed, and that `git status` does not list it. Values are not recorded here (names only).
  - **HTTPS path**: requests are sent with the DSH-bundled Node runtime (environment variables, `Authorization: Bearer <key>` header), because this sandbox's Windows TLS backend (schannel) cannot complete a handshake — `curl.exe` and .NET fail with `SEC_E_NO_CREDENTIALS`, while Node's own OpenSSL stack works (verified with a `200` POST to a public echo endpoint).
  - **This entry is the connectivity test commit**: it exercises the full chain — commit → push to `origin/main` → `POST` to the publish webhook → `publish.sh` → regenerated `data.enc.json` + version hash.
  - **No changes** to `index.html`, `app.js`, `style.css`, `version.json`, or generated data files. `secrets.env` remains untracked.
- **Reasoning**:
  - DeepSeek Harness now shares publish duty with Antigravity, so the webhook credential must live somewhere gitignored and documented by name, and the publish chain needs one verified end-to-end run before real code work begins.
- **Affected Files & Components**:
  - `AGENT_LOG.md` (tracked); `secrets.env` (local, gitignored, never committed).
- **Grok Bot Automation Impact**:
  - **None**: no schema, fetcher, or publish-script change. DeepSeek Harness can now trigger the existing publish webhook after pushing code changes; Grok Bot's routines stay exactly as they are.
- **Publish Status**:
  - **Published via webhook**: YES (connectivity test trigger sent immediately after pushing this commit; result reported in chat rather than requiring a second commit).

### 2026-11-13 23:22 (Europe/Helsinki) — [DeepSeek Harness] — Join as a third collaborating agent; document the sandboxed Git setup used for direct commits

- **Agent**: DeepSeek Harness
- **Changes**:
  - **Joined the repo as a third collaborating agent** alongside Antigravity and Grok Bot. Updated the header, renamed the rules section to "Collaboration Rules for All Agents", added rule 5 (commit directly, but `git fetch` + rebase onto `origin/main` first), and extended the author tags and entry template with **`[DeepSeek Harness]`**.
  - **Fresh clone prepared locally** at `C:\Users\eetu\OneDrive\Ohjelmointi\perhekalenteri` (branch `main`, tracking `origin/main`, clean tree, 13.3 MB). Commit identity is `eetuerantanen-ux <239039043+eetuerantanen-ux@users.noreply.github.com>`, matching the existing history so commits attribute to Eetu's GitHub account.
  - **Environment notes for the other agents** (these are quirks of the DeepSeek Harness sandbox, not of the repo):
    1. `http.sslBackend=openssl` is set in the local clone's `.git/config` (untracked). The default `schannel` backend fails in the sandbox with `SEC_E_NO_CREDENTIALS`, so TLS must go through Git's bundled OpenSSL + CA bundle.
    2. **Credential helpers cannot be used here**: git executes helpers through `sh.exe`, and msys processes abort in the sandbox (`couldn't create signal pipe, Win32 error 5`). Pushes therefore use the OAuth credential already in Windows Credential Manager (written by `git-credential-manager github login`) and pass it per-command as an `http.extraheader` Basic-auth header. No token is written to any file in the repo.
    3. Verified end-to-end with `git push --dry-run origin main` (exit 0, authenticated; anonymous pushes to this repo are rejected).
  - **No changes** to `index.html`, `app.js`, `style.css`, `version.json`, or any generated data file (`data.enc.json`, `prices.json`, `forecast.json`).
- **Reasoning**:
  - All three agents now commit to the same `main` branch, so the log must name the newcomer and state how it syncs, to keep the "preserve the other agents' changes" guarantee intact and to stop anyone from mistaking the odd TLS/credential workaround for a repo bug.
- **Affected Files & Components**:
  - `AGENT_LOG.md` only.
- **Grok Bot Automation Impact**:
  - **None**: `AGENT_LOG.md` is already preserved by `publish.sh`; no schema, fetcher, or publish-script change is needed. Because no code file changed, there is no version-hash impact (`version.json` untouched).
- **Publish Status**:
  - **Published via webhook**: NO (documentation-only change; no frontend, data, or automation change to publish).

### 2026-11-12 23:38 (Europe/Helsinki) — [Grok Bot] — Stop 30-min Aromi14 polling; decrypt weekly `ruokalistat.enc.json` and hourly `muistilista.enc.json` in `publish.sh`

- **Agent**: Grok Bot
- **Changes**:
  - **`publish.sh`**: Before `collect.py`, decrypts freshly fetched `origin/main:ruokalistat.enc.json` (`fetch-menus.py --out-menus … --decrypt-to shared/ruokalistat.json`) and `origin/main:muistilista.enc.json` (`fetch-keep.py --out-todo … --decrypt-to shared/muistilista.json`), mirroring the existing `hoitovuorot.enc.json` handling. The newer source wins (enc git-commit time vs. shared-file mtime). The previous shared file is backed up to `.publish-state/` before overwrite. Decrypt, missing-file, or missing-script failures keep the fallback and never fail the publish (if the decrypt script is not yet in `publish/`, it is taken from `origin/main`). Hardened the published-repo `.gitignore` heredoc with `ruokalistat.json`, `muistilista.json`, `muistutukset.json`, `.venv/`, `__pycache__/`, and `*.pyc`.
  - **`collect.py`**: `menus()` now reads `shared/ruokalistat.json` (same schema/roles: Lehvätien päiväkoti `arki`, Jaakonpuiston päiväkoti `vuoro`). Live Aromi14 fetching runs only if that file is missing or unreadable. Meal rules unchanged.
  - **Docs**: `fetch-notes.md` and `README.md` no longer say menus are fetched every 30 minutes; they describe the Raspberry Pi weekly/hourly encrypted files and the `publish.sh` decrypt step.
  - **Verified** on a normal `publish.sh` run: exit 0, commit `e45340e`, live `data.enc.json` updated. Version remains `aa5d0ab364` (no frontend code change). Decrypted `data.enc.json` contains both daycare menus (Lehvatienpk 38 days, Jaakonpuistonpk 57 days) and `muistilista` (`tila=ok`, 2 items). The run made **no Aromi14 requests**. Plaintext JSONs live only in `shared/` (outside `publish/`); `git add` in `publish/` ignores them via `.gitignore` (confirmed with decoy files).
- **Reasoning**:
  - Daycare menus now arrive weekly from the Raspberry Pi as encrypted `ruokalistat.enc.json`, and the todo list hourly as `muistilista.enc.json`. The 30-minute refresh should decrypt those files for `collect.py` and stop polling Aromi14 on every run.
- **Affected Files & Components**:
  - `publish.sh`, `collect.py`, `fetch-notes.md`, `README.md`, `data.enc.json`
  - `site/index.html`, `site/app.js`, `site/style.css`, `version.json` unchanged (`aa5d0ab364`)
- **Grok Bot Automation Impact**:
  - **Implemented** the `publish.sh` decrypt-and-prefer-newer steps and the `collect.py` shared-file read. **No new automation created.** The existing 30-min routine still runs `publish.sh`, which now performs the decrypts; Aromi14 polling is removed from that cycle.
- **Publish Status**:
  - **Published via webhook**: NO (manual `publish.sh` run after this AGENT_LOG request; data published at commit `e45340e`). Live version: `aa5d0ab364`.

### 2026-11-12 23:14 (Europe/Helsinki) — [Antigravity] — Move daycare food menu fetching (`Lehvätien päiväkoti` & `Jaakonpuiston päiväkoti`) to weekly Tuesday 14:00 Raspberry Pi job (`fetch-menus.py` -> `ruokalistat.enc.json`) & activate `fetch-keep.py`
- **Agent**: Antigravity
- **Changes**:
  - **Added `fetch-menus.py` & weekly Tuesday 14:00 cron (`0 14 * * 2`) on Raspberry Pi**:
    1. Fetches both **Lehvätien päiväkoti** (`Lehvatienpk`, id `ad8a057f-2aee-4403-b178-205c8e7b20e2`, `rooli: "arki"` for regular weekdays) and **Jaakonpuiston päiväkoti** (`Jaakonpuistonpk`, id `fd6b518d-6673-4361-a576-ece9efb81b62`, `rooli: "vuoro"` for weekends, public holidays, and evening/overnight shifts) from Kouvolan Aromi14 eMenus for the current + next month (`menu_window(today)`), using the exact schema expected by `collect.py` and `app.js`.
    2. Compares upcoming days (`pvm >= today`) against `.publish-state/ruokalistat.sent.json` / `ruokalistat.enc.json`. **Only when new or updated menu items appear in the coming weeks** does it encrypt the list into **`ruokalistat.enc.json`** (`AES-256-GCM`, `PBKDF2-SHA256`, 1,000,000 iterations, `FAMILY_PLANNER_PASSWORD`), commit & push `ruokalistat.enc.json` to `origin/main`, and trigger the publish webhook.
    3. Includes `--decrypt` and `--decrypt-to shared/ruokalistat.json` flags using Python stdlib + OpenSSL `libcrypto`.
    4. Ran initial live fetch & push on the Raspberry Pi (`Lehvatienpk: 30 tulevaa pv; Jaakonpuistonpk: 46 tulevaa pv` -> `ruokalistat.enc.json` committed and pushed to `origin/main`).
  - **Activated `fetch-keep.py` on Raspberry Pi (`0 7-21 * * *`)**:
    1. Added `gkeepapi 0.14.2` (Python 3.9) compatibility (`keep.resume(...)` fallback + safe `WebLink._load` handling).
    2. Configured `KEEP_MASTER_TOKEN` in `/home/pi/perhekalenteri/secrets.env` and pushed initial encrypted `muistilista.enc.json` to `origin/main`.
  - **Failure Alerting (`run_evaka_cron.py`)**:
    - Wrapped all three Raspberry Pi cron jobs (`evaka` at `0 7,14,19 * * *`, `keep` at `0 7-21 * * *`, and `menus` at `0 14 * * 2`) with per-job failure tracking and Gandi SMTP email alerts (`mail.gandi.net:465`, `From: eetu@eetu.org`, `To: eetu.e.rantanen@gmail.com`) if any job fails 3 times in a row.
- **Reasoning**:
  - Daycare food menus only change when new weekly/monthly menus are published, so polling Aromi14 every 30 minutes is unnecessary. Checking once a week on Tuesdays at 14:00 on the Raspberry Pi and updating `ruokalistat.enc.json` only when upcoming weeks have new items eliminates redundant requests while keeping both `Lehvätien päiväkoti` (`arki`) and `Jaakonpuiston päiväkoti` (`vuoro`) menus up to date.
- **Affected Files & Components**:
  - `fetch-menus.py` (new weekly Aromi14 menu fetcher)
  - `ruokalistat.enc.json` (initial encrypted menu data in repo root)
  - `fetch-keep.py` (`gkeepapi 0.14.2` compatibility)
  - `muistilista.enc.json` (initial encrypted todo list in repo root)
  - `.gitignore` (`ruokalistat.json` added), `AGENT_LOG.md`
- **Grok Bot Automation Impact**:
  - **Required (`publish.sh` & `collect.py` — Stop polling Aromi14 in `collect.py`)**:
    1. In `publish.sh` (before running `collect.py`), decrypt `publish/ruokalistat.enc.json` into `shared/ruokalistat.json` (alongside `hoitovuorot.enc.json` and `muistilista.enc.json`):
       ```bash
       if [ -f "$PUB/ruokalistat.enc.json" ]; then
         python3 "$PUB/fetch-menus.py" --out-menus "$PUB/ruokalistat.enc.json" --decrypt-to "$ROOT/shared/ruokalistat.json"
       fi
       ```
    2. In `collect.py`, update `menus(today)` to read `shared/ruokalistat.json` (decrypted from the Raspberry Pi's `ruokalistat.enc.json`) instead of fetching live from Aromi14 on every 30-minute run (keeping live Aromi14 fetching only as a fallback if `shared/ruokalistat.json` is missing).
    3. Add `ruokalistat.json` to `publish.sh`'s `.gitignore` heredoc.
- **Publish Status**:
  - **Published via webhook**: NO (Raspberry Pi automation scripts, `muistilista.enc.json`, `ruokalistat.enc.json`, and `AGENT_LOG.md` pushed to `origin/main`).

### 2026-11-12 22:11 (Europe/Helsinki) — [Antigravity] — Add `fetch-keep.py` for Google Keep `Muistilista` automation (`muistilista.enc.json` + webhook + two-way edit support)
- **Agent**: Antigravity
- **Changes**:
  - Added `fetch-keep.py` to the repository root to automate fetching (and future tablet editing) of the Google Keep `"Muistilista"` note on the Raspberry Pi using the exact same encrypted architecture as `fetch-evaka.py` (`hoitovuorot.enc.json`):
    1. **Google Keep Sync (`gkeepapi`)**: Authenticates with `KEEP_EMAIL` (falls back to `EVAKA_USERNAME`) and `KEEP_MASTER_TOKEN` from `secrets.env`, caches sync state in `.publish-state/keep_state.json`, finds the `"Muistilista"` note, and extracts `[{teksti, tehty}]` items. Automatically re-execs into `ROOT/.venv/bin/python3` if `gkeepapi` is installed in a local virtualenv on the Raspberry Pi.
    2. **One-Time Token Setup Helper**: Includes `--exchange-oauth-token "oauth2_4/..." --save-token` (`gpsoauth.exchange_token`) to exchange a one-time Google `oauth_token` cookie into a permanent `KEEP_MASTER_TOKEN` in `secrets.env`.
    3. **Diff & `AES-256-GCM` Encryption (`muistilista.enc.json`)**: Compares items against `.publish-state/muistilista.sent.json` (or decrypted `muistilista.enc.json`). Only when items are added, removed, reordered, or checked/unchecked does it encrypt the list into **`muistilista.enc.json`** (`AES-256-GCM`, `PBKDF2-SHA256`, `iter: 1000000`, `FAMILY_PLANNER_PASSWORD`), commit & push `muistilista.enc.json` to `origin/main` (`Muistilista (salattu) YYYY-MM-DD HH:MM`), and call Grok Bot's publish webhook with `event: "muistilista_updated"`, `muistilista_enc`, `muistilista`, and `diff`.
    4. **Stdlib-Only Decryption for `publish.sh`**: `--decrypt` and `--decrypt-to shared/muistilista.json` use only Python stdlib + OpenSSL `libcrypto` (no `gkeepapi` required on Grok Bot's side).
    5. **Two-Way Mutation Flags (Ready for Tablet UI)**: Supports `--add "Teksti"`, `--remove "Teksti"`, `--check "Teksti"`, and `--uncheck "Teksti"` to modify the Google Keep note directly, sync back to Google Keep, and push the updated `muistilista.enc.json`.
  - Updated `.gitignore` to ignore `muistilista.json`, `muistutukset.json`, `.venv/`, `__pycache__/`, and `*.pyc`.
- **Reasoning**:
  - Transfers periodic `Muistilista` fetching to the Raspberry Pi without browser scraping or AI token usage, keeps todo items encrypted at rest (`muistilista.enc.json`) in the public repo, and provides built-in add/remove/check support for upcoming tablet UI editing.
- **Affected Files & Components**:
  - `fetch-keep.py` (new script in repository root)
  - `.gitignore`
  - `AGENT_LOG.md`
- **Grok Bot Automation Impact**:
  - **Required (`publish.sh`)**:
    1. Mirror the `hoitovuorot.enc.json` decrypt step in `publish.sh` for `muistilista.enc.json` before `collect.py` runs (preferring whichever of `publish/muistilista.enc.json` vs. Arjen apuri's `shared/muistilista.json` is newer):
       ```bash
       if [ -f "$PUB/muistilista.enc.json" ]; then
         python3 "$PUB/fetch-keep.py" --out-todo "$PUB/muistilista.enc.json" --decrypt-to "$ROOT/shared/muistilista.json"
       fi
       ```
    2. Add `muistilista.json`, `muistutukset.json`, `.venv/`, `__pycache__/`, and `*.pyc` to `publish.sh`'s `.gitignore` heredoc so they are preserved on publish runs.
- **Publish Status**:
  - **Published via webhook**: NO (script + documentation update only; no frontend UI changes).

### 2026-11-12 21:53 (Europe/Helsinki) — [Antigravity] — Change `Ruokalista` card rollover time from 13.00 to 16.00
- **Agent**: Antigravity
- **Changes**:
  - Updated `renderMenu(n)` in `app.js` so the front-page `Ruokalista` card displays today's meal menu until `16.00` (`p.hh < 16`) instead of `13.00` (`p.hh < 13`), switching to the next care day (`nextCareDay(todayKey, false) || todayKey`) at `16.00`.
- **Reasoning**:
  - Requested by the user so today's meals remain visible on the display through the afternoon (e.g. välipala) and switch to the next care day at 16.00.
- **Affected Files & Components**:
  - `app.js` (`renderMenu`)
  - `AGENT_LOG.md`
- **Grok Bot Automation Impact**:
  - **None**: Frontend-only change in `app.js`; Grok Bot's publish script will automatically adopt `app.js` from `origin/main` and update the version hash.
- **Publish Status**:
  - **Published via webhook**: YES.

### 2026-11-12 15:05 (Europe/Helsinki) — [Antigravity] — Document end-to-end encrypted daycare shift update flow (`hoitovuorot.enc.json`) in `AGENT_LOG.md` & prevent `.pyc` commits
- **Agent**: Antigravity
- **Changes**:
  - Added the **Current Data & Automation Schedule** reference section at the top of `AGENT_LOG.md` and updated the historical schedule table below so both agents have the exact, verified end-to-end flow for how daycare shifts (`Hoitovuorot`) are now updated:
    1. **Raspberry Pi (`fetch-evaka.py`)**: Fetches care shifts directly from eVaka's citizen API (`varhaiskasvatus.kouvola.fi`) for the 2-month calendar window (`[{lapsi, pvm, alku, loppu}]`).
    2. **Diff & Encryption**: Compares shifts in the active window against `.publish-state/hoitovuorot.sent.json` (or decrypted `hoitovuorot.enc.json`). When changes occur, encrypts the shifts into **`hoitovuorot.enc.json`** using `AES-256-GCM` + `PBKDF2-SHA256` (`iter: 1000000`, `FAMILY_PLANNER_PASSWORD`) — identical to `data.enc.json` — so plaintext shifts are never exposed in the public repository.
    3. **Git Push + Webhook Trigger**: Commits and pushes `hoitovuorot.enc.json` to `origin/main` (verified live in commit `7c7e29c`) and immediately POSTs to Grok Bot's publish webhook with both `hoitovuorot_enc` and `hoitovuorot` / `diff` in the JSON payload.
    4. **Grok Bot Consumption (`publish.sh` / `collect.py`)**: On webhook trigger or 30-min cycle, Grok Bot pulls `origin/main`, decrypts `publish/hoitovuorot.enc.json` into `shared/hoitovuorot.json` (`python3 publish/fetch-evaka.py --out-shifts publish/hoitovuorot.enc.json --decrypt-to shared/hoitovuorot.json`, preferring whichever of `hoitovuorot.enc.json` vs. Arjen apuri's `shared/hoitovuorot.json` is newer), and runs `collect.py` + `encrypt.js` to publish the updated `data.enc.json`.
  - Added `sys.dont_write_bytecode = True` to `fetch-evaka.py`, removed `__pycache__/fetch-evaka.cpython-313.pyc` from git tracking (`git rm -r --cached __pycache__`), and added `__pycache__/` and `*.pyc` to `.gitignore`.
- **Reasoning**:
  - Ensures `AGENT_LOG.md` clearly documents the new daycare shift update architecture (replacing the old "cadence not documented" note) and prevents Python bytecode files from being committed when `publish.sh` runs `fetch-evaka.py --decrypt-to` followed by `git add -A`.
- **Affected Files & Components**:
  - `AGENT_LOG.md`
  - `fetch-evaka.py` (`sys.dont_write_bytecode = True`)
  - `.gitignore` (`__pycache__/`, `*.pyc`)
  - Removed tracked `__pycache__/fetch-evaka.cpython-313.pyc`
- **Grok Bot Automation Impact**:
  - **Optional minor `.gitignore` tweak in `publish.sh`**: Add `__pycache__/` and `*.pyc` to `publish.sh`'s `.gitignore` heredoc (though `sys.dont_write_bytecode = True` in `fetch-evaka.py` already prevents `.pyc` generation).
- **Publish Status**:
  - **Published via webhook**: NO (documentation + repo hygiene update only).

### 2026-11-12 15:03 (Europe/Helsinki) — [Grok Bot] — Published iltapala meal rule + invisible dynamic scrolling; publish.sh now decrypts `hoitovuorot.enc.json`
- **Agent**: Grok Bot
- **Changes**:
  - **Published to GitHub Pages** (version `d063d2fe58`) the following frontend changes (developed in `site-dev/`, copied to `site/`; `site/`==`origin` before copy, so no upstream code lost):
    1. **Iltapala meal rule** (`app.js` `mealKids`): a meal is shown for a child only if the care shift actually covers that meal's serving time (start AND end). A short evening shift (e.g. 19:30-20:30, parent handover) now correctly shows **only Iltapala**, not Paivallinen. Verified live on the real eVaka data for 2026-11-01 and 2026-11-21 (day-popup meals = `["Iltapala"]` only).
    2. **Invisible, dynamic scrolling + fade hint** (`app.js`, `style.css`): day-view cards (Saa, Tanaan, Ruokalista, Tulevat paivat, Muistutukset, Muistilista), popup bodies, and week/month day cells scroll when content overflows, with **no visible scrollbar** (scrollbar-width:none + ::-webkit-scrollbar display:none), touch/drag + mouse-wheel support, and the page itself does not bounce (body overscroll-behavior:none). A soft bottom fade (`.has-more::after`) appears only while more content is below (toggled via scroll + ResizeObserver). A scroll drag no longer opens a card's popup (pointer move >10px suppresses the tap). Muistilista text no longer ellipsis-truncates (wraps + scrolls).
  - **Pipeline (`publish.sh`)** - handles Antigravity's encrypted `hoitovuorot.enc.json`:
    1. Before `collect.py`, if `origin/main:hoitovuorot.enc.json` exists it is decrypted with `fetch-evaka.py --decrypt-to shared/hoitovuorot.json` using `FAMILY_PLANNER_PASSWORD` (same key/envelope as `data.enc.json`).
    2. **Arjen apuri's `shared/hoitovuorot.json` is kept as fallback**; the **newer source wins** (enc git-commit time vs `shared/hoitovuorot.json` mtime). The previous file is backed up to `.publish-state/` before overwrite. Decrypt/missing-file failures keep the fallback and never fail the publish.
    3. Hardened the published-repo `.gitignore` heredoc with `hoitovuorot.json` and `secrets.env`.
- **Reasoning**:
  - eVaka shifts are now encrypted at rest in the public repo, so the publish pipeline must decrypt them locally to feed `collect.py`, while preserving the Arjen apuri fallback and preferring whichever source is newer.
- **Security note (plaintext check)**:
  - Verified: **no plaintext `hoitovuorot.json` has ever been committed** to `origin/main` in the current tree or anywhere in git history (scanned all commit trees across all refs). Nothing to remediate.
- **Affected Files & Components**:
  - `site/index.html` (unchanged), `site/app.js`, `site/style.css`, `version.json` (`d063d2fe58`), `data.enc.json`
  - `publish.sh` (decrypt step + `.gitignore` hardening). `collect.py` unchanged (still reads `shared/hoitovuorot.json`).
- **Grok Bot Automation Impact**:
  - **Implemented** the `publish.sh` decrypt-and-prefer-newer step. **No new automation created.**
- **Publish Status**:
  - **Published via webhook**: YES (webhook-triggered routine published the code at commit `283c20d`; manual `publish.sh` re-run confirmed no further delta). Live version: `d063d2fe58`.

### 2026-11-12 14:38 (Europe/Helsinki) — [Antigravity] — Encrypt daycare shifts as `hoitovuorot.enc.json` (`AES-256-GCM`) in `fetch-evaka.py` and gitignore plaintext `hoitovuorot.json`
- **Agent**: Antigravity
- **Changes**:
  - Updated `fetch-evaka.py` so that **plaintext `hoitovuorot.json` is never written to or committed in the public repository**:
    1. Encrypts the fetched daycare shifts (`[{lapsi, pvm, alku, loppu}]`) into **`hoitovuorot.enc.json`** using the exact same `AES-256-GCM` + `PBKDF2-SHA256` (`iter: 1000000`, 16-byte `salt`, fresh 12-byte random `iv`) envelope format and `FAMILY_PLANNER_PASSWORD` as `data.enc.json` (implemented via Python's built-in `hashlib.pbkdf2_hmac` + OpenSSL `libcrypto` via `ctypes`, so no third-party `pip` packages are needed on Raspberry Pi).
    2. Reads baseline comparison state from `.publish-state/hoitovuorot.sent.json` (gitignored) or by decrypting `hoitovuorot.enc.json` in place.
    3. Commits and pushes **only** `hoitovuorot.enc.json` (`git commit -m "Hoitovuorot (salattu) YYYY-MM-DD HH:MM"`), with an explicit safety guard that refuses to `git add`/`commit` any file not ending in `.enc.json`, and automatically deletes any leftover plaintext `hoitovuorot.json` in the repo root.
    4. Added `--decrypt` (prints decrypted JSON to stdout) and `--decrypt-to PATH` (atomically writes decrypted JSON to `PATH`, e.g., `shared/hoitovuorot.json`) CLI flags using `FAMILY_PLANNER_PASSWORD`.
  - Updated `.gitignore` to explicitly ignore `hoitovuorot.json` and `secrets.env`.
- **Usage & CLI Flags (Raspberry Pi & Grok Bot)**:
  - Required in Raspberry Pi's `secrets.env` (alongside `EVAKA_USERNAME`, `EVAKA_PASSWORD`, `GROK_WEBHOOK_URL`, `GROK_WEBHOOK_KEY`, and optional `GITHUB_TOKEN`):
    ```dotenv
    FAMILY_PLANNER_PASSWORD=<same password used for data.enc.json>
    ```
  - Default cron run on Raspberry Pi (fetches shifts; if changed, encrypts `hoitovuorot.enc.json`, commits & pushes to `origin/main`, and triggers webhook):
    ```bash
    python3 fetch-evaka.py
    ```
  - Decrypt `hoitovuorot.enc.json` into `shared/hoitovuorot.json` (for Grok Bot's `publish.sh` / `collect.py` or local inspection):
    ```bash
    python3 fetch-evaka.py --out-shifts publish/hoitovuorot.enc.json --decrypt-to shared/hoitovuorot.json
    ```
- **Reasoning**:
  - Because `eetuerantanen-ux/perhekalenteri` is a public repository, committing plaintext `hoitovuorot.json` would expose children's names and daycare shift hours in the repository and git history (and trigger `check_plaintext.py`). Encrypting `hoitovuorot.enc.json` with `AES-256-GCM` + `PBKDF2-SHA256` (1,000,000 iterations) provides the same cryptographic protection as `data.enc.json`.
- **Affected Files & Components**:
  - `fetch-evaka.py`
  - `.gitignore`
  - `AGENT_LOG.md`
- **Grok Bot Automation Impact**:
  - **Required (`publish.sh` / `collect.py`)**:
    1. In `publish.sh` (after `git fetch` + `rebase origin/main` and before running `collect.py`), if `publish/hoitovuorot.enc.json` exists, decrypt it into `shared/hoitovuorot.json`:
       ```bash
       if [ -f "$PUB/hoitovuorot.enc.json" ]; then
         python3 "$PUB/fetch-evaka.py" --out-shifts "$PUB/hoitovuorot.enc.json" --decrypt-to "$ROOT/shared/hoitovuorot.json"
       fi
       ```
    2. In `publish.sh`'s `.gitignore` heredoc, add `hoitovuorot.json` and `secrets.env` alongside `data.json` so they remain gitignored on future publishes.
- **Publish Status**:
  - **Published via webhook**: NO (script + `.gitignore` + documentation update only; no frontend UI/code change).

### 2026-11-12 14:02 (Europe/Helsinki) — [Antigravity] — Default `fetch-evaka.py` to git commit `hoitovuorot.json` + call publish webhook (with webhook-payload backup)
- **Agent**: Antigravity
- **Changes**:
  - Updated `fetch-evaka.py` per Grok Bot's suggestion so the **default mode** when care shifts change (or new shifts appear) is:
    1. Sync local repo with `origin/main` (`git fetch` + `git rebase --autostash origin/main`).
    2. Write updated shifts to `hoitovuorot.json` in the repository root (and `shared/hoitovuorot.json` if `shared/` exists locally).
    3. Compare active-window shifts (`pvm >= start_date`) against the previous baseline (`.publish-state/hoitovuorot.sent.json` / `hoitovuorot.json`).
    4. **Default primary action**: `git add hoitovuorot.json` -> `git commit -m "Hoitovuorot YYYY-MM-DD HH:MM"` -> `git push origin HEAD:main` (with automatic rebase retry and optional `GITHUB_TOKEN` auth fallback from `secrets.env`).
    5. **Trigger publish webhook**: Calls the existing Grok Bot publish webhook (`GROK_WEBHOOK_URL` / `WEBHOOK_URL` with `Authorization: Bearer <key>`) so Grok Bot immediately pulls `hoitovuorot.json` from `origin/main` and updates the encrypted calendar (`data.enc.json`).
    6. **Backup mode preserved**: The webhook `POST` body always includes the full JSON payload (`{"event": "hoitovuorot_updated", "mode": "git_and_webhook", "committed_to_git": true, "hoitovuorot": [...], "diff": {"added": [...], "removed": [...]}}`), and running with `--webhook-only` (`--no-git-commit`) skips git commit/push and sends only the webhook payload.
  - Stores the last-synced state in `.publish-state/hoitovuorot.sent.json` (which is already ignored by `.gitignore`) so no temporary state file is ever committed to the repo.
- **Usage & CLI Flags (Raspberry Pi / Cron)**:
  - Default cron run (fetches shifts; if changed, commits & pushes `hoitovuorot.json` to `origin/main` and calls the webhook):
    ```bash
    python3 fetch-evaka.py
    ```
  - Backup webhook-only mode (no git commit/push; sends shifts in webhook JSON payload):
    ```bash
    python3 fetch-evaka.py --webhook-only
    ```
  - Initialize baseline state on first install without triggering git push or webhook:
    ```bash
    python3 fetch-evaka.py --init-state
    ```
  - Force a webhook call even if shifts have not changed:
    ```bash
    python3 fetch-evaka.py --force-webhook
    ```
- **Reasoning**:
  - Committing `hoitovuorot.json` to `origin/main` and calling the existing publish webhook lets the Raspberry Pi trigger calendar updates using the exact webhook already in place, while keeping the direct webhook payload as an automatic fallback.
- **Affected Files & Components**:
  - `fetch-evaka.py` (in repository root; no changes to `index.html`, `app.js`, or `style.css`).
  - `AGENT_LOG.md`
- **Grok Bot Automation Impact**:
  - **Action for Grok Bot's `publish.sh` / `collect.py`**: When `publish.sh` syncs `publish/` from `origin/main` (or when the webhook runs), copy `publish/hoitovuorot.json` into `shared/hoitovuorot.json` before `collect.py` runs (or read `publish/hoitovuorot.json` directly in `collect.py`). Note: `check_plaintext.py` treats non-`GENERATED_RE` files in `publish/` as `$OTH` (logged to `notices.log` only), or `check_plaintext.py` can ignore `hoitovuorot.json` in `publish/` if desired.
- **Publish Status**:
  - **Published via webhook**: NO (script + documentation update only).

### 2026-11-12 12:56 (Europe/Helsinki) — [Antigravity] — Verify handover package locally and remove `perhekalenteri-handover.tar.gz.gpg` from public repo
- **Agent**: Antigravity
- **Changes**:
  - Downloaded, decrypted, and verified `perhekalenteri-handover.tar.gz.gpg` into Antigravity's persistent private storage (`~/.gemini/perhekalenteri-handover/`).
  - Removed `perhekalenteri-handover.tar.gz.gpg` from the public GitHub repository (`git rm perhekalenteri-handover.tar.gz.gpg`) as instructed in the handover entry and `HANDOVER.md`.
- **Reasoning**:
  - The handover package is now safely stored and verified in Antigravity's private persistent storage, so the encrypted archive no longer needs to remain in the public repository.
- **Affected Files & Components**:
  - `perhekalenteri-handover.tar.gz.gpg` (removed from repository root)
  - `AGENT_LOG.md`
- **Grok Bot Automation Impact**:
  - **None**: Do not re-add `perhekalenteri-handover.tar.gz.gpg` unless a new handover snapshot is explicitly requested.
- **Publish Status**:
  - **Published via webhook**: NO (no site code/UI changes).

### 2026-11-12 12:47 (Europe/Helsinki) — [Grok Bot] — Encrypted handover package + automation schedule
- **Agent**: Grok Bot
- **Changes**:
  - Added `perhekalenteri-handover.tar.gz.gpg` to the repository root: an encrypted archive of all scripts, docs, site/site-dev code, formats and the real secrets Antigravity needs to take over the family planner if Eetu's Grok Bot usage ends. Includes `HANDOVER.md` (architecture, APIs, flow) and `secrets.env` (secret values).
  - **Encryption**: GPG symmetric (OpenPGP), cipher **AES-256**, S2K mode 3 (iterated+salted), S2K digest **SHA-512**, S2K count **65011712**. Passphrase provided by Eetu out-of-band (not in this repo or any log).
  - **Decrypt**: `gpg --decrypt perhekalenteri-handover.tar.gz.gpg | tar xz` (run in an empty dir).
  - **After extracting**: delete the package from the repo — `git rm perhekalenteri-handover.tar.gz.gpg && git commit && git push` — and keep `secrets.env` out of the repo. The repo is public.
  - `secrets.env` contains (names only): `FAMILY_PLANNER_PASSWORD`, `GITHUB_TOKEN` (Eetu's own gh OAuth token, scopes gist/read:org/repo/workflow — consider rotating after migration), `GITHUB_USER`, `GIT_REMOTE`.
- **Reasoning**:
  - Business-continuity handover requested by Eetu, so another agent can download, decrypt and then delete the package.
- **Affected Files & Components**:
  - New: `perhekalenteri-handover.tar.gz.gpg` (repo root). No change to page behaviour. `publish.sh`/`fetch-prices.py` leave the `.gpg` untouched (binary, not stamped, not plaintext-checked, not in .gitignore).

#### Automation schedule (all Europe/Helsinki)
| Routine | Run by | Schedule | Exact steps / commands |
|---|---|---|---|
| Perhekalenterin päivitys | Tekninen automaatiobotti | every 30 min, 06:00–22:00 | fetch 4 Google calendars with the Calendar connector per `fetch-notes.md` (read-only) → `python3 collect.py` → `bash publish.sh` |
| Pörssisähkön hinnat | Tekninen automaatiobotti | daily 16:00 | `python3 fetch-prices.py` (internally runs `python3 fetch-forecast.py --out publish/forecast.json`) |
| Muistilista (Google Keep) | Arjen apuri | hourly 07:00–21:00 | writes `shared/muistilista.json` (`[{teksti, tehty}]`) from Keep note "Muistilista" (box browser) |
| Muistutukset (eVaka) | Arjen apuri | hourly on weekdays 07:00–19:00 | writes `shared/muistutukset.json` (eVaka, read-only; fields otsikko, pvm, lapsi, lahde) |
| Muistutukset (email) | Arjen apuri | hourly 08:00–21:00 | appends to `shared/muistutukset.json` from eetu.org email (lahde="sähköposti") |
| Hoitovuorot | Raspberry Pi (`fetch-evaka.py`) + Grok Bot (`publish.sh`) | Scheduled cron on Pi + webhook trigger | Pi fetches eVaka shifts → encrypts `hoitovuorot.enc.json` (`AES-256-GCM`) → commits & pushes to `origin/main` → calls Grok Bot webhook → `publish.sh` decrypts to `shared/hoitovuorot.json` (`[{lapsi, pvm, alku, loppu}]`) |
| Antigravity-julkaisu (webhook) | Koodaribotti | on demand | webhook triggers a publish; URL/key live only in the Grok Bot app (not exportable) |
| Tablet version check | tablet browser | data every 5 min; full reload every 6 h | `app.js checkVersion()` fetches `version.json` and reloads when the version changes |

- **Verification**: Tekninen automaatiobotti's two routines and the webhook owner are verified against repo notes (`fetch-notes.md`, `README.md`) and Grok Bot's own records. Arjen apuri's Keep/eVaka/email cadences come from Grok Bot's records (not independently verifiable from repo files). **Hoitovuorot** is now updated by the Raspberry Pi running `fetch-evaka.py` (commits encrypted `hoitovuorot.enc.json` and calls the publish webhook).
- **Grok Bot Automation Impact**:
  - **None** to data schema or fetchers. Publish scripts already preserve non-generated repo files. No secrets are stored in this log.

### 2026-11-12 12:23 (Europe/Helsinki) — [Antigravity] — Make `Tänään` tile clickable to open hovering window with today's events
- **Agent**: Antigravity
- **Changes**:
  - Added `role="button" tabindex="0" aria-label="Näytä päivän kaikki tapahtumat"` to `#today` in `index.html`.
  - Registered `today: "tanaan"` in `INFO_CARDS`, added `CARD_LINK("kaikki")` to `renderToday()`, wired `#today` into the click/keyboard listeners, and implemented `renderTodayPop(n)` in `app.js` to display all calendar events for the current day (both all-day/multi-day banners and timed events without truncation, including full time ranges, participants, location, tentative status, past/ongoing highlighting, and the `nyt HH.MM` indicator line) inside `#infoPop`.
  - Updated `style.css` to include `#today[role="button"]` interactive/focus styles, aligned `.today .card-title` so the electricity average badge and `kaikki ›` link sit cleanly on the right, and styled `.dp-ev.past`, `.dp-ev.now`, and `.dp-list .nowline::before`.
- **Reasoning**:
  - The front-page `Tänään` card truncates timed events (`MAX`) and clamps long titles to fit the dashboard layout. Making `Tänään` clickable like `Ruokalista`, `Muistutukset`, and `Muistilista` lets users tap the card to view all of today's calendar events and full details in a consistent hovering modal (`#infoPop`) with 30s auto-close.
- **Affected Files & Components**:
  - `index.html` (`#today` attributes)
  - `app.js` (`INFO_CARDS`, `renderTodayPop`, `renderInfoPop`, `renderToday`, click handler)
  - `style.css` (`.today .card-title`, `#today[role="button"]`, `.dp-ev.past`, `.dp-ev.now`, `.dp-list .nowline::before`)
- **Grok Bot Automation Impact**:
  - **None**: No changes to data schema or automation scripts required.
- **Publish Status**:
  - **Published via webhook**: YES (`2026-11-12 12:36 Europe/Helsinki` — triggered by Antigravity after pushing commit `c8cd0e4`).

### 2026-11-12 11:57 (Europe/Helsinki) — [Grok Bot] — Publish sync: pull/rebase before publishing, adopt upstream code, preserve AGENT_LOG.md
- **Agent**: Grok Bot
- **Changes**:
  - `publish.sh` (Grok Bot's 30-min data publish, runs 6–22) now runs `git fetch` + `git rebase origin/main` in its publish clone **before** building, and never force-pushes. Push is retried (max 3): on rejection it fetches; if only data/`AGENT_LOG.md` changed upstream it rebases and pushes again, if code changed meanwhile it drops its own commit and adopts the change on the next run.
  - Upstream code adoption: Grok Bot keeps an **un-stamped** copy of the last published `index.html`, `app.js`, `style.css` as the common base. If origin's file differs from the base and Grok Bot's local copy has not changed, the upstream (Antigravity) version is adopted into Grok Bot's local site and dev sources and then republished, so Antigravity's commits are not overwritten. If **both** sides changed the same file, the code is **not** published (data still is) and Grok Bot reports a conflict for manual merge.
  - Code is checked for plaintext personal data separately; if it fails, the code is not published (encrypted data publishing continues) and Grok Bot reports it.
  - `fetch-prices.py` (daily 16:00 price/forecast update) also rebases onto `origin/main` before committing, commits only `prices.json`/`forecast.json`, and retries push with pull --rebase on rejection.
  - `AGENT_LOG.md` is never modified or deleted by the automations; Grok Bot only adds its own entries (like this one).
- **Reasoning**:
  - Required by the first entry of this log: Antigravity commits directly to `main`, so Grok Bot's automated publishes must sync and must not clobber those commits.
- **Affected Files & Components**:
  - Grok Bot side only: `publish.sh`, `fetch-prices.py` (not in this repo). No change to page behaviour.
  - Generated on every run: `index.html` version stamp, `version.json`, `data.enc.json`, `prices.json`, `forecast.json`.
- **Notes for Antigravity**:
  - **Version stamp**: Grok Bot writes `?v=<hash>` on the `style.css` and `app.js` links and `<meta name="app-version" content="<hash>">` in `index.html`, plus `version.json` (`{"v":"<hash>"}`). The hash is the first 10 hex characters of sha256 over the un-stamped `index.html` + `style.css` + `app.js`. Open tablets reload when `version.json` changes. You may leave existing stamps as they are (they are stripped before comparison), and you don't need to bump `version.json`; Grok Bot re-stamps after adopting your change. Keep the `<meta name="app-version" ...>` tag and the plain `href="style.css"` and `src="app.js"` references so stamping keeps working.
  - **Do not edit data files** (`data.enc.json`, `prices.json`, `forecast.json`, `version.json`); they are regenerated and overwritten by the automations. `data.enc.json` is AES-GCM encrypted; its decrypted schema is unchanged.
  - **No plaintext personal data** in code (family member names, daycare names, etc.); names must come from the encrypted data. A failing code check blocks code publishing.
  - New files you add to the repo (other than the three code files) are left untouched by Grok Bot's publish.
- **Grok Bot Automation Impact**:
  - **Done**: publish/sync updated as described (resolves the action required by the 2026-11-12 11:39 entry). Data schema impact: none.

### 2026-11-12 11:39 (Europe/Helsinki) — [Antigravity] — Initialize shared `AGENT_LOG.md` collaboration log
- **Agent**: Antigravity
- **Changes**:
  - Created `AGENT_LOG.md` in the repository root to track all code, UI, and automation changes between Antigravity and Grok Bot.
  - Defined the standard entry template covering changes, reasoning, affected files/components, and Grok Bot automation impact.
- **Reasoning**:
  - Both Antigravity and Grok Bot are used to develop and maintain `perhekalenteri`. A single source of truth in the repository ensures both agents stay aware of each other's modifications, prevents accidental overwrites during automated publishing, and clearly flags when backend/automation updates are needed.
- **Affected Files & Components**:
  - `AGENT_LOG.md` (new file in repository root)
  - No functional changes to `index.html`, `app.js`, or `style.css` yet.
- **Grok Bot Automation Impact**:
  - **Action Required (Publish Workflow)**: Ensure Grok Bot's publish/sync automation preserves `AGENT_LOG.md` in the repo root and pulls/merges repo changes (`index.html`, `app.js`, `style.css`, `AGENT_LOG.md`) before pushing hourly updates so Antigravity's commits are not overwritten.
  - **Data Schema Impact**: None.
