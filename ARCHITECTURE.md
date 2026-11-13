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
| `fetch-evaka.py`, `fetch-keep.py`, `fetch-menus.py` | 721 / 832 / 684 | Pi-side fetchers (Python 3, stdlib only) |
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
 │ fetch-evaka.py           │            │ publish.sh                │     │ app.js           │
 │  eVaka API → shifts      │──push──▶   │  decrypt .enc.json files  │     │  fetch           │
 │ fetch-keep.py            │            │  collect.py               │     │  data.enc.json   │
 │  Google Keep → todo      │──push──▶   │  encrypt.js               │────▶│  PBKDF2 + AES-GCM│
 │ fetch-menus.py           │            │  data.enc.json            │     │  renderAll()     │
 │  Aromi14 → menus         │            │  version stamping         │     │                  │
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
- Browser decryption uses WebCrypto. On the Pi it uses OpenSSL `libcrypto` through `ctypes`, so **no pip
  packages are required** — a deliberate constraint for the Raspberry Pi.
- The derived key is cached in `localStorage` under `perhekalenteri.avain.v1` as `{salt, iter, k}`.
  The password is therefore typed once per device; the lock screen reappears if the salt/iteration change
  (i.e. the password was rotated) or after "unohda salasana".
- A salt is shared per file via `.publish-state/`, so re-encrypting keeps the same key derivation.

### `data.enc.json` — decrypted payload

The decrypted object is the single source of truth for the whole UI:

| Key | Shape |
|---|---|
| `jasenet` | `{ key: { nimi, tunnus, vari } }` — member id, display name, avatar initials, colour. `pyha` is the holiday pseudo-member |
| `tapahtumat` | `[{ alku, loppu, otsikko, henkilot: [key], kalenteri, kokopaiva, paikka, alustava, hoitovuoro, puokkari, puokkari_kuka }]` |
| `ruokalistat` | `[{ otsikko, rooli: "arki" \| "vuoro", paivat: [{ pvm, ateriat: [{ ateria, ruoat: [{ nimi }] }] }] }]` |
| `muistutukset` | `{ tila: "ok", kohteet: [{ otsikko, pvm, lapsi, lahde }] }` |
| `muistilista` | `{ tila: "ok", kohteet: [{ teksti, tehty }] }` |
| `saa` | `{ lahde, nyt: {koodi, lampo, tuntuu, tuuli, paiva}, tunnit: [{aika, koodi, lampo, paiva}], paivat: [{pvm, koodi, max, min, sade_tn, sade_mm, aurinko_nousee, aurinko_laskee}] }` |
| `paivitetty` | ISO timestamp; drives the "Päivitetty" status and the staleness warning (`STALE_MIN` = 180) |
| `virheet` | `[{ lahde }]` — sources that failed during collection, listed in the footer |

Field notes:

- `hoitovuoro: true` marks a daycare shift; `puokkari`/`puokkari_kuka` mark the "puokkari" (shift-swap) tag.
- `kokopaiva: true` means an all-day/multi-day event; the UI computes `long` from that or a ≥24 h duration.
- `alustava: true` renders the "alustava" (tentative) styling.
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

## 7. Automation (Raspberry Pi)

All three scripts are Python 3, stdlib-only, run from the repository root, and read `secrets.env` next to
them. They share the same skeleton: load secrets → fetch → diff against `.publish-state/` → encrypt →
`git add` **only** the `.enc.json` → commit → push (max 3 attempts with rebase) → POST webhook.

| Script | Source | Output | Flag surface |
|---|---|---|---|
| `fetch-evaka.py` | `varhaiskasvatus.kouvola.fi` citizen API (username/password) | `hoitovuorot.enc.json` | `--from-date`, `--to-date`, `--out-shifts`, `--decrypt`, `--decrypt-to`, `--no-git-commit`, `--no-webhook`, `--force-webhook`, `--init-state`, `--with-messages` |
| `fetch-keep.py` | Google Keep note "Muistilista" via `gkeepapi` + master token | `muistilista.enc.json` | `--decrypt`, `--decrypt-to`, `--add`, `--remove`, `--check`, `--uncheck`, `--exchange-oauth-token` |
| `fetch-menus.py` | Kouvola Aromi14 eMenus for two daycares (`arki` and `vuoro` role) | `ruokalistat.enc.json` | `--decrypt`, `--decrypt-to`, `--out-menus` |

Safety properties worth preserving:

- `git_commit_and_push_*()` refuses to `git add` any path not ending in `.enc.json`.
- Underlying plaintext is only ever written outside the repository (or to `shared/`, which is gitignored).
- The webhook payload also carries the plaintext diff as a fallback if the git push did not happen
  (`--webhook-only` mode).
- Git identity defaults to the repository owner's noreply address; a `GITHUB_TOKEN` in `secrets.env`
  enables token-authenticated pushes instead of an interactive credential helper.

### Schedules (Europe/Helsinki)

| Job | Cadence |
|---|---|
| App data publish (`publish.sh` via publisher) | every 30 min, 06:00–22:00, and on webhook trigger |
| `fetch-evaka.py` (shifts) | daily 07:00, 14:00, 19:00 |
| `fetch-keep.py` (todo) | hourly 07:00–21:00 |
| `fetch-menus.py` (menus) | Tuesdays 14:00 |
| Electricity prices (`fetch-prices.py`) | daily 16:00 |

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
