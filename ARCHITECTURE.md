# Architecture — `perhekalenteri`

A short technical map of how this project is put together, for any agent or human about to change it.
Read this together with [`AGENT_LOG.md`](AGENT_LOG.md), which holds the collaboration rules and the
newest-first change history.

**In one sentence:** a dependency-free static dashboard for a kitchen tablet, showing a Finnish family's
calendar, daycare shifts, daycare menus, a Keep todo list, eVaka reminders, weather and spot electricity
prices — all from a single encrypted JSON file, deployed straight from `main` by GitHub Pages with no
build step.

---

## 1. Repository layout

This repository is **the deployed site plus the Raspberry Pi automation scripts**. It contains no
framework, no `package.json`, no bundler and no CI.

| Path | Lines | Role |
|---|---|---|
| `index.html` | 137 | Static skeleton: header, day/week/month views, four overlays, lock screen |
| `app.js` | ~1170 | All frontend logic (single IIFE, vanilla JS) |
| `style.css` | ~585 | All styling (17 commented sections, no media queries) |
| `fonts/Fraunces.ttf`, `fonts/Nunito.ttf` | — | The only binary assets; referenced by `@font-face` |
| `data.enc.json` | — | **Generated.** Encrypted whole-app state |
| `prices.json`, `forecast.json` | — | **Generated.** Public electricity spot prices / forecast |
| `version.json` | — | **Generated.** `{"v":"<hash>"}` used for cache busting |
| `hoitovuorot.enc.json` | — | Daycare shifts, written by the Pi (`fetch-evaka.py`) |
| `muistilista.enc.json` | — | Keep todo list, written by the Pi (`fetch-keep.py`) |
| `ruokalistat.enc.json` | — | Daycare menus, written by the Pi (`fetch-menus.py`) |
| `fetch-evaka.py`, `fetch-keep.py`, `fetch-menus.py` | 721 / 832 / 684 | Pi-side fetchers (Python 3; evaka & menus stdlib+ctypes, keep uses gkeepapi in .venv) |
| `AGENT_LOG.md` | — | Collaboration rules + change log |
| `.nojekyll`, `robots.txt` | — | Serve files verbatim; keep the page out of search engines |

**Not in this repository** (they live on the publisher's side): `publish.sh`, `collect.py`, `encrypt.js`,
`fetch-prices.py`, `README.md`, `fetch-notes.md`, and the publish webhook credentials.

---

## 2. Deployment — there is no build

| Property | Value |
|---|---|
| Live URL | <https://eetuerantanen-ux.github.io/perhekalenteri/> |
| Hosting | GitHub Pages |
| Build type | `legacy` (branch build, no Actions workflow) |
| Source | branch `main`, path `/` |
| Build step | **none** — a push to `main` is deployed within about a minute |

Because there is no build, **the repository root is exactly what the tablet downloads**. `.nojekyll`
stops Jekyll from touching the files. `robots.txt` disallows everything and `index.html` carries
`<meta name="robots" content="noindex, nofollow">`, since the repository is public and the data is
private.

### Version stamping and cache busting

The publisher (`publish.sh`) rewrites three things on every code publish:

1. `href="style.css?v=<hash>"` and `src="app.js?v=<hash>"` in `index.html`,
2. `<meta name="app-version" content="<hash>">` in `index.html`,
3. `version.json` → `{"v":"<hash>"}`.

`<hash>` is the first 10 hex characters of `sha256` over the **un-stamped** `index.html` + `style.css` +
`app.js` (stamps are stripped before hashing). Open tablets poll `version.json` every 5 minutes and
`location.replace("?v=<hash>")` when it differs, which forces a fresh copy of the two assets.

**Consequences for contributors:**

- Keep the `<meta name="app-version">` tag and the plain `href="style.css"` / `src="app.js"` references.
- Do not edit `version.json` by hand; it is regenerated.
- The hash moves **only** when one of those three files changes. A data-only or docs-only change will not
  reload any tablet.

---

## 3. Frontend

### Files

**`index.html`** — static markup only, no templating, no inline logic. It provides:

- `.top` — brand, view nav (`päivä` / `viikko` / `kuukausi`), member chips, status line
- `#dayView` — three columns: clock + weather | today + menu | upcoming + reminders + todo
- `#weekView`, `#monthView` — hidden until selected
- `#dayPop`, `#pricePop`, `#infoPop` — the three overlay windows
- `#lock` — password form, shown until the data key is available

**`app.js`** — one IIFE, `"use strict"`, zero dependencies. Rough division:

| Lines (approx.) | Area |
|---|---|
| 1–50 | Constants, time helpers (`hk`, `midnight`, `addDays`, `isoWeek`, `mondayOfIsoWeek`) |
| 51–90 | Inline SVG weather icons, member/colour helpers |
| 91–213 | Event queries per day, meal/care-shift logic, `nextCareDay` |
| 214–600 | Header, electricity price card + price chart overlay, the four info overlays |
| 600–800 | Day-view cards: weather, today, upcoming, menu, reminders, todo, footer |
| 739–830 | Week and month grids |
| 831–990 | Day popup, view switching, `renderAll` |
| 991–1030 | WebCrypto decryption + password cache (`localStorage`) |
| 1030–1174 | Boot: version check, `load()`, event listeners, scroll enhancement, timers |

**`style.css`** — palette and layout driven by custom properties on `:root`, with a full dark palette on
`body.night`. Section map is in `/* ---------- ... ---------- */` comments: top bar, grid, clock, weather,
today, menu, upcoming, reminders/todo, view switch, week/month views, month grid, day popup, price link
and chart, tappable cards, hidden scrolling.

### Layout model

- Fixed kiosk geometry: `html, body { overflow: hidden }`, `#app { width:100vw; height:100vh }`,
  day grid `grid-template-columns: 318px 1fr 1.08fr`.
- **There are no media queries.** The design targets one landscape tablet; portrait is not handled.
- Cards are fixed-size; overflow is handled at runtime by `enhanceScrollAll()`, which wraps everything
  after the `.card-title` into a `.card-scroll` element, hides the scrollbar
  (`.scroll-hide`) and toggles a `.has-more` fade while more content remains below.
  Anything rendered into a card ends up inside that wrapper.
- Drag-vs-tap: `pointerdown` records the position, `pointermove` beyond 10 px sets `_ptrDragged`, and the
  click handler ignores taps that were really scroll drags.

### Rendering model

- No virtual DOM: every render rebuilds `innerHTML` of its container. All interpolated text goes through
  `esc()`; event/member colours are inlined as `background`/`border-color` from `data.jasenet`.
- `renderAll()` re-renders every card, is called after each data load, and once a minute.
- Views are hash-routed (`#viikko`, `#kuukausi`); 30 s of inactivity returns to the day view
  (`VIEW_IDLE_MS`), and any open overlay is closed on the way back.
- Overlays: `#dayPop` (one day's detail from week/month grids), `#pricePop` (spot + forecast chart),
  `#infoPop` (full content of the Tänään / Muistutukset / Muistilista / Ruokalista cards).
  Open/close state lives in `openDayKey`, `pricePopOpen`, `infoPopMode`.

### Timers and refresh

| Interval | Action |
|---|---|
| 1 s | `renderHeader` — clock, date, night-mode class |
| 60 s | `renderAll` — relative times, "nyt" markers |
| 5 min | `load()` — refetch `data.enc.json`, `prices.json`, `forecast.json`; `checkVersion()` |
| 6 h | full `location.reload()` |

The screen is kept awake with the Wake Lock API where the browser supports it (Android Chrome).

### Test hooks in the URL

- `?nyt=2026-11-13T18:00:00` — freeze "now" (all rendering and comparisons use `now()`).
- `?tila=paiva` / `?tila=yo` — force day/night palette regardless of the clock.
- `?hinnat=<path>` — local development only; override the price feed.

---

## 4. Data flow

```
      Raspberry Pi (cron)                    publisher (Grok Bot)                 browser
 ┌──────────────────────────┐            ┌───────────────────────────┐     ┌──────────────────┐
 │ run_evaka_cron.py        │            │ publish.sh                │     │ app.js           │
 │  ├── fetch-evaka.py      │──push──▶   │  decrypt .enc.json files  │     │  fetch           │
 │  │   eVaka API → shifts  │            │  collect.py               │     │  data.enc.json   │
 │  ├── fetch-keep.py       │──push──▶   │  encrypt.js               │────▶│  PBKDF2 + AES-GCM│
 │  │   Google Keep → todo  │            │  data.enc.json            │     │  renderAll()     │
 │  └── fetch-menus.py      │──push──▶   │  version stamping         │     │                  │
 │      Aromi14 → menus     │            │                           │     │                  │
 └────────────┬─────────────┘            └───────────▲───────────────┘     └──────────────────┘
              │  POST webhook (Bearer key)            │
              └───────────────────────────────────────┘
```

1. Pi jobs fetch from their sources, diff against their last known state, and only on change: encrypt,
   commit **only** the `.enc.json` file, push to `origin/main`, and POST the publish webhook.
2. The webhook makes the publisher pull, decrypt the `.enc.json` files into plaintext on its own machine,
   run `collect.py` to assemble the app state, re-encrypt it as `data.enc.json`, re-stamp the version, and push.
3. The tablet refreshes `data.enc.json` every 5 minutes and decrypts it locally.

Plaintext personal data never enters git: only `.enc.json` files (and the generated `data.enc.json`) are
committed. `.gitignore` covers `data.json`, `hoitovuorot.json`, `muistilista.json`, `muistutukset.json`,
`ruokalistat.json`, `secrets.env`, `shared/`, `raw/`, `.publish-state/` and friends.

---

## 5. Data formats

### Encryption envelope

Every `.enc.json` file in the repository uses the same envelope:

```json
{ "v": 1, "alg": "AES-256-GCM", "kdf": "PBKDF2-SHA256", "iter": 1000000,
  "salt": "<base64>", "iv": "<base64>", "ct": "<base64, includes GCM tag>" }
```

- Key = PBKDF2-SHA256(password `FAMILY_PLANNER_PASSWORD`, salt, 1 000 000 iterations) → 256-bit AES-GCM key.
- Browser decryption uses WebCrypto. On the Pi and publisher side, decryption and encryption for `fetch-evaka.py`
  and `fetch-menus.py` use OpenSSL `libcrypto` through `ctypes`, so **no pip packages are required for crypto or
  for those two fetchers**. `fetch-keep.py` additionally requires `gkeepapi` in a local virtualenv (`.venv`) for
  Google Keep's private protocol, while its `--decrypt` flag uses only stdlib + `ctypes`.
- The derived key is cached in `localStorage` under `perhekalenteri.avain.v1` as `{salt, iter, k}`.
  The password is therefore typed once per device; the lock screen reappears if the salt/iteration change
  (i.e. the password was rotated) or after "unohda salasana".
- A salt is shared per file via `.publish-state/`, so re-encrypting keeps the same key derivation.

### `data.enc.json` — decrypted payload

The decrypted object is the single source of truth for the whole UI. The shapes below were verified
against a real decrypted payload (`paivitetty` 2026-11-13 23:29) — at that moment: 134 events
(30 of them daycare shifts), 5 members, 2 menu lists (38 + 57 days), 16 forecast days, 0 collection errors.

| Key | Shape |
|---|---|
| `paivitetty` | ISO timestamp; drives the "Päivitetty" status and the staleness warning (`STALE_MIN` = 180) |
| `aikavyohyke` | `"Europe/Helsinki"` — informational; the UI hard-codes the same zone |
| `jasenet` | `{ key: { nimi, tunnus, vari } }` — member id, display name, avatar initials, colour. `pyha` is the holiday pseudo-member |
| `kalenterit` | `[{ kalenteri, ok, tapahtumia }]` — per-source fetch status, mirrors the footer's error report |
| `viikkonumerot` | `{ "YYYY-MM-DD": "Viikko 44 / 2026" }` — pre-formatted week labels, ~10 entries |
| `tapahtumat` | `[{ alku, loppu, otsikko, kokopaiva, kalenteri, henkilot: [key], paikka, alustava, hoitovuoro?, puokkari?, puokkari_kuka? }]` |
| `saa` | `{ paikka, lahde, nyt: {aika, koodi, lampo, tuntuu, tuuli, paiva, sade}, tunnit: [{aika, lampo, koodi, sade_tn, paiva}], paivat: [{pvm, koodi, max, min, sade_mm, sade_tn, aurinko_nousee, aurinko_laskee}] }` |
| `ruokalistat` | `[{ henkilot, otsikko, lahde, rooli: "arki" \| "vuoro", koodi, ryhma, ok: true, paivat: [{ pvm, ateriat: [{ ateria, ruoat: [{ nimi, merkinnat }] }] }] }]` |
| `muistutukset` | `{ tila: "ok", kohteet: [{ otsikko, pvm, lapsi, lahde }] }` |
| `muistilista` | `{ tila: "ok", kohteet: [{ teksti, tehty }] }` |
| `virheet` | `[{ lahde }]` — sources that failed during collection, listed in the footer |

Field notes:

- `hoitovuoro: true` marks a daycare shift; only shift events carry `puokkari` / `puokkari_kuka`
  (29 of 30 shifts in the verified payload) — plain events omit those keys entirely.
- `kokopaiva: true` means an all-day/multi-day event; the UI computes `long` from that or a ≥24 h duration.
- `alustava: true` renders the "alustava" (tentative) styling; `paikka` is optional.
- `ruokalistat[].ateriat[].ruoat[].merkinnat` carries the daycare's own annotations (allergens/diet notes)
  and is not currently rendered by the UI.
- `muistutukset.tila` / `muistilista.tila` are `"ok"` when the source was reachable; anything else shows a
  "not available right now" placeholder instead of failing.


### `prices.json`

`{ maa, yksikko, alv, jakso_min, lahde, hinnat: [{ alku, c }] }` — spot price `c` in c/kWh including VAT
(`alv` 25.5 %), `jakso_min` is the slot length (15). Colours: `<5` green, `5–15` yellow, `15–30` orange,
`>30` red.

### `forecast.json`

`{ lahde, lahde_url, haettu, alv, yksikko, jakso_min, paivat: [{ pvm, ka }], tunnit: [{ alku, c }] }` —
hourly forecast slots plus a per-day average (`ka`) used for the badge on upcoming days.

### `version.json`

`{ "v": "<10 hex chars>" }` — compared against `<meta name="app-version">`; mismatch triggers a reload.

---

## 6. Domain logic

Time is always `Europe/Helsinki`. All conversions go through `Intl.DateTimeFormat.formatToParts` (`hk()`);
never construct local dates with `new Date(y, m, d)` — DST correctness depends on `midnight()` and
`offsetMin()`.

### Care shifts drive most of the UI

`careShiftsOn(key)` returns the `hoitovuoro` events intersecting a day. From that:

- **`mealKids(key, meal)`** — a meal is shown for a child only if the shift covers that meal's serving
  window: aamupala if care starts ≤ 08:00, lounas 11:00–11:30, välipala 14:00–14:30, päivällinen
  17:00–17:30, iltapala 19:30–20:00 (or a shift running past midnight). This is why a short evening
  handover shift shows only iltapala. Meal order: `Aamupala, Lounas, Välipala, Päivällinen, Iltapala`.
- **Menu list choice** — `menuListForMeal()` picks the `vuoro` list on weekends, holidays and overnight
  boundaries (päivällinen/iltapala when a shift runs past midnight, aamupala when one began the previous
  evening), otherwise the `arki` list.
- **`isCareDay` / `nextCareDay`** — whether the day has any care at all, and the next day that does.
- **Holidays** — `isHolidayEv()` checks `henkilot` containing `pyha` or `kalenteri === "pyha"`.

### Rollover and selection rules

- Front-page **Ruokalista** shows today until **16:00**, then switches to the next care day
  (`renderMenu`, `p.hh < 16`). Afternoon välipala therefore stays visible.
- **Tänään** shows all all-day banners plus up to `max(2, 7 − longs)` timed events, then "+N muuta".
- Week/month grids cap pills per cell (`MAXP = 3`; week rows cap at 6 items, or 4 when meals are shown).
- Overnight shifts are drawn as a single shift pill spanning into the next day (`evRange` uses `→`).

---

## 7. Automation & Raspberry Pi Environment

The background data collection runs on an always-on Raspberry Pi on the local home network (`pi@192.168.1.243`). It gathers daycare shifts from eVaka, todo items from Google Keep, and weekly food menus from Kouvolan Aromi14, commits the encrypted payloads to `origin/main`, and triggers the publisher via webhook.

### 7.1 Host environment & hardware

| Property | Value |
|---|---|
| Device | Raspberry Pi (`pi@192.168.1.243`, local LAN) |
| Operating System | Debian GNU/Linux 11 (Bullseye), 32-bit (`armv7l`), Linux kernel 5.10 |
| Base Python | Python 3.9.2 (`/usr/bin/python3`) |
| Working directory | `/home/pi/perhekalenteri` (clone of `eetuerantanen-ux/perhekalenteri.git`) |
| Log destination | `/home/pi/perhekalenteri/cron.log` |
| Local state directory | `/home/pi/perhekalenteri/.publish-state/` (gitignored; holds salts, sent baselines, failure states) |

### 7.2 Git configuration & authentication on the Pi

The Pi repository clone pushes directly to GitHub Pages (`origin/main`) using HTTPS:

- **Token authentication**: GitHub requires personal access tokens (PAT) for HTTPS operations. The Pi stores a fine-grained GitHub PAT in `/home/pi/perhekalenteri/secrets.env` as `GITHUB_TOKEN`. The Python fetcher git runner (`run_git`) automatically injects this token per command using `-c http.https://github.com/.extraheader="AUTHORIZATION: basic <base64>"` so interactive credential helpers or global config modifications are never needed.
- **Git identity**: Commits are made under `eetuerantanen-ux <239039043+eetuerantanen-ux@users.noreply.github.com>`.
- **Exclusions**: In addition to the repo `.gitignore`, `/home/pi/perhekalenteri/.git/info/exclude` ensures local configuration, log files, python bytecode, and runtime wrappers never get committed:
  ```
  secrets.env
  *.log
  .publish-state/
  hoitovuorot.json
  muistilista.json
  muistutukset.json
  ruokalistat.json
  run_evaka_cron.py
  .venv/
  __pycache__/
  *.pyc
  ```

### 7.3 Python environments & build dependencies

Two Python runtimes operate on the Pi:

1. **System Python (`/usr/bin/python3`, Python 3.9.2)**:
   - Used by `fetch-evaka.py` and `fetch-menus.py`.
   - Requires zero external pip packages. HTTP calls use `urllib.request`; encryption uses standard library `hashlib.pbkdf2_hmac` plus OpenSSL `libcrypto.so` loaded dynamically via `ctypes`.
2. **Dedicated Virtualenv (`/home/pi/perhekalenteri/.venv`)**:
   - Used by `fetch-keep.py` due to Google Keep requiring an unofficial API library (`gkeepapi`).
   - **Build note for Bullseye ARMv7**: Compiling C-extensions (such as `pycryptodomex`) directly fails on Bullseye due to missing build headers in minimal installations. Therefore, prebuilt binary wheels from `piwheels.org` are installed using `--only-binary=pycryptodomex`:
     ```bash
     python3 -m venv /home/pi/perhekalenteri/.venv
     /home/pi/perhekalenteri/.venv/bin/pip install --only-binary=pycryptodomex gkeepapi==0.14.2 gpsoauth==2.0.0 urllib3==1.26.20
     ```
   - `fetch-keep.py` includes runtime compatibility patches for `gkeepapi 0.14.2` on Python 3.9 (`keep.resume` fallback and safe `WebLink._load` handling).
   - If invoked from system Python, `fetch-keep.py` automatically detects and re-execs itself inside `.venv/bin/python3`.
   - **Google Keep master token**: Keep does not support standard OAuth2 user consent flows. A one-time login token (`oauth2_4/...`) generated via Google browser login is exchanged once for a permanent master token (`aas_et/...`) via `python3 fetch-keep.py --exchange-oauth-token "oauth2_4/..." --save-token`, which writes `KEEP_MASTER_TOKEN` into `secrets.env`.

### 7.4 Script inventory & APIs

All three scripts share the same execution lifecycle: load `secrets.env` → fetch remote API → diff against `.publish-state/*.sent.json` → encrypt (`AES-256-GCM`, `iter: 1000000`, `FAMILY_PLANNER_PASSWORD`) → `git add` **only** `.enc.json` → commit → push (with automatic rebase retry) → POST publish webhook.

| Script | Source API & Protocol | Output | Flag surface |
|---|---|---|---|
| `fetch-evaka.py` | `varhaiskasvatus.kouvola.fi` citizen API (HTTPS session login with `EVAKA_USERNAME` & `EVAKA_PASSWORD`) | `hoitovuorot.enc.json` | `--from-date`, `--to-date`, `--out-shifts`, `--decrypt`, `--decrypt-to`, `--no-git-commit`, `--no-webhook`, `--force-webhook`, `--init-state`, `--with-messages` |
| `fetch-keep.py` | Google Keep note "Muistilista" via `gkeepapi` + `KEEP_MASTER_TOKEN` (`.venv`) | `muistilista.enc.json` | `--decrypt`, `--decrypt-to`, `--add`, `--remove`, `--check`, `--uncheck`, `--exchange-oauth-token` |
| `fetch-menus.py` | Kouvolan Aromi14 eMenus API for Lehvätien (`arki`) and Jaakonpuiston (`vuoro`) daycares | `ruokalistat.enc.json` | `--decrypt`, `--decrypt-to`, `--out-menus` |

Safety properties:
- `git_commit_and_push_*()` explicitly checks file extensions and refuses to `git add` any path not ending in `.enc.json`.
- Plaintext is never written inside the tracked repository tree (only to gitignored `shared/` or temporary buffers).
- The webhook payload includes the plaintext diff as a fallback if the git push fails (`--webhook-only` mode).

### 7.5 Cron scheduling & failure alerting (`run_evaka_cron.py`)

Cron on the Pi does not execute `fetch-*.py` directly. Instead, all three tasks run through a unified monitoring wrapper: `/home/pi/perhekalenteri/run_evaka_cron.py`.

#### Wrapper responsibilities
1. **Runtime routing**: Invokes `fetch-evaka.py` and `fetch-menus.py` using system Python, and `fetch-keep.py` using the `.venv` Python runtime.
2. **Logging**: Captures stdout, stderr, and exit codes with Europe/Helsinki timestamps to `/home/pi/perhekalenteri/cron.log`.
3. **Failure tracking**: Tracks consecutive failures per job in `.publish-state/<job>_fail_state.json`. Any successful run resets the consecutive failure counter and clears any alert state.
4. **Email alerting via Gandi SMTP**: If any job fails **3 consecutive times** (`MAX_FAILURES = 3`), the wrapper immediately formats and sends an alert email to `eetu.e.rantanen@gmail.com` via Gandi's authenticated SMTP relay (`mail.gandi.net:465`, SSL/TLS, sender `eetu@eetu.org`, password from `/home/pi/smtp_pw` or `secrets.env`). The alert subject identifies the failing job (e.g. *"Hoitovuorojen päivitysautomaatio epäonnistui"*) and the body includes exact timestamps, exit codes, and full stderr/tracebacks of the 3 failed attempts.

#### Active crontab (`crontab -l` on `pi@192.168.1.243`)

```cron
# eVaka daycare shifts (daily at 07:00, 14:00, and 19:00)
0 7,14,19 * * * /usr/bin/python3 /home/pi/perhekalenteri/run_evaka_cron.py

# Google Keep todo list (hourly between 07:00 and 21:00)
0 7-21 * * * /usr/bin/python3 /home/pi/perhekalenteri/run_evaka_cron.py --job keep

# Aromi14 daycare menus (once a week on Tuesdays at 14:00)
0 14 * * 2 /usr/bin/python3 /home/pi/perhekalenteri/run_evaka_cron.py --job menus
```

### 7.6 Secrets & environment variables (`secrets.env`)

Secrets are stored on the Pi in `/home/pi/perhekalenteri/secrets.env` with restricted permissions (`chmod 600`), never tracked in git:

| Variable | Description |
|---|---|
| `FAMILY_PLANNER_PASSWORD` | Shared symmetric encryption passphrase used for PBKDF2-SHA256 (1M iterations) + AES-256-GCM. Identical key used for `data.enc.json`, `hoitovuorot.enc.json`, `muistilista.enc.json`, and `ruokalistat.enc.json`. |
| `GITHUB_TOKEN` | GitHub Personal Access Token for Git push authentication to `origin/main`. |
| `GITHUB_USER` | `eetuerantanen-ux` |
| `GIT_REMOTE` | `https://github.com/eetuerantanen-ux/perhekalenteri.git` |
| `EVAKA_USERNAME` | Login email for Kouvolan eVaka citizen portal (`varhaiskasvatus.kouvola.fi`). |
| `EVAKA_PASSWORD` | eVaka login password (read from `/home/pi/evaka_pw`). |
| `KEEP_EMAIL` | Google account email for Keep synchronization (`eetu.e.rantanen@gmail.com`). |
| `KEEP_MASTER_TOKEN` | Permanent Google Keep master token (`aas_et/...`). |
| `GROK_WEBHOOK_URL` | Publisher webhook endpoint (`publish.sh` trigger). |
| `GROK_WEBHOOK_KEY` | Bearer authorization key for publisher webhook. |
| `SMTP_HOST` | Gandi SMTP relay server (`mail.gandi.net`). |
| `SMTP_PORT` | `465` (SSL). |
| `SMTP_USER` | `eetu@eetu.org` |
| `SMTP_FROM` | `eetu@eetu.org` |
| `SMTP_PASSWORD` | Gandi mailbox password (read from `/home/pi/smtp_pw` or `secrets.env`). |
| `ALERT_EMAIL` | Recipient address for failure alerts (`eetu.e.rantanen@gmail.com`). |

---

## 8. Rules for anyone changing this repository

1. **Never edit generated files** — `data.enc.json`, `prices.json`, `forecast.json`, `version.json`.
   They are produced by the publisher and any manual edit will be overwritten.
2. **Keep the stamp hooks** — `<meta name="app-version">`, plain `href="style.css"`, `src="app.js"`.
   Adding new JS/CSS files is not supported by the stamping step.
3. **No plaintext personal data in code** — no family member names, no daycare names, no addresses.
   Names come from `data.jasenet` at runtime; a failing check blocks code publishing.
4. **No dependencies** — no npm, no bundler, no CDN. The tablet loads four static files plus two fonts.
5. **Sync before pushing** — `git fetch` + rebase onto `origin/main`; never force-push.
6. **Log every UI/logic/CSS/schema/automation change** in `AGENT_LOG.md`, newest first, tagged with the
   author, and state the publish status. Routine data-only publishes are not logged.
7. **Dark mode and night colours** come from `body.night`; new components must define colours in both
   palettes, using the `--*` custom properties rather than hard-coded values.

---

## 9. Local development and testing

There is no test suite and no linter. Anything added must be verified by hand.

The app expects `data.enc.json` and asks for the planner password on first load, so a plain static server
is not enough to see real data:

- The planner password is kept **outside git** in `secrets.env` (gitignored) as
  `FAMILY_PLANNER_PASSWORD` — the same variable the Raspberry Pi scripts read. Never commit it, never
  echo it, and never pass it as a command-line argument: read it from the environment instead.
- Serve the directory with any static server and open it in the tablet or a browser to check layout with
  empty/placeholder state.
- To exercise real content, either enter the planner password once (it is then cached in `localStorage`),
  or temporarily move `data.enc.json` aside on `localhost` so `app.js` falls back to a plaintext
  `data.json` (gitignored) — the fallback path only runs for `127.0.0.1` / `localhost`.
- Use `?nyt=…` to pin the clock to specific days, and `?tila=yo` to inspect night mode without waiting
  until 21:00.
- Because the layout has no media queries, verify at the tablet's own landscape resolution rather than
  resizing a desktop window.

---

## 10. Known constraints and future work

- **Single-purpose layout.** Fixed three-column grid tuned to one tablet; portrait and small screens are
  not considered. Adding responsive behaviour is a design decision, not a refactor.
- **Duplicated render paths.** Day cards, week grid and month grid each format events and meals their own
  way; a feature added in one usually needs the other two checked.
- **Duplicated automation helpers.** The three Python scripts each carry an identical
  crypto/git/webhook block (~150 lines). Extracting a shared module would help maintainability but each
  script must stay standalone on the Pi and callable by path from the publisher.
- **No safety net.** No tests, no lint, no CI; correctness rests on manual verification and the
  `AGENT_LOG.md` discipline.
- **Data staleness is visible but silent.** The footer warns after 3 hours; there is no alerting inside
  the page beyond that.
