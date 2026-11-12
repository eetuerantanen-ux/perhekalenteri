# Perhekalenteri — Agent Collaboration & Change Log (`AGENT_LOG.md`)

This file is the shared coordination log between **Antigravity** and **Grok Bot** for developing and maintaining `perhekalenteri`.

## Collaboration Rules for Both Agents

1. **Read First**: Before planning or making any code, style, or automation changes, always read this file (`AGENT_LOG.md`) first to see recent changes made by the other agent.
2. **Preserve Changes (Important for Grok Bot's Publish Script)**:
   - Antigravity may commit updates directly to `index.html`, `app.js`, `style.css`, and `AGENT_LOG.md` in this GitHub repository.
   - If Grok Bot publishes from a local working directory or template directory, Grok Bot **must** sync/pull changes from `origin/main` before publishing so it does not overwrite edits made by Antigravity (such as `index.html` template files, `app.js`, `style.css`, or `AGENT_LOG.md`).
3. **Publishing via Webhook**:
   - After Antigravity commits and pushes code changes and updates `AGENT_LOG.md`, Antigravity triggers Grok Bot's publish webhook (credentials stored privately in `~/.gemini/perhekalenteri-webhook.env`, never in git) and marks the entry as `Published via webhook: YES`.
   - When Grok Bot sees an entry already published via the webhook, it can skip redundant work on its next hourly cycle if no new changes occurred.
4. **Log Every Code/Feature Change**:
   - Do **not** log routine hourly data-only updates (`data.enc.json`, `prices.json`, `forecast.json`).
   - **Do** log every UI, logic, CSS, data-schema, or automation change.
   - Add new entries at the **top** of the `## Change Log` section (newest first).
   - Every entry must clearly identify the author in the heading: **`[Antigravity]`** or **`[Grok Bot]`**.

---

## Entry Template

```markdown
### YYYY-MM-DD HH:MM (Europe/Helsinki) — [Antigravity | Grok Bot] — Short Title
- **Agent**: Antigravity (or Grok Bot)
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

### 2026-11-12 13:36 (Europe/Helsinki) — [Antigravity] — Share lightweight `fetch-evaka.py` (direct JSON API, no browser needed)
- **Agent**: Antigravity
- **Changes**:
  - Added `fetch-evaka.py` to the repository root so Grok Bot can adopt it into its local `perhekalenteri/` workspace and replace browser-based eVaka scraping.
  - Uses pure Python 3 standard library (`urllib.request` + `http.cookiejar`, zero external dependencies) to authenticate directly against Kouvola eVaka's Citizen JSON API (`POST /api/citizen/auth/weak-login` with `X-Evaka-Csrf: 1`).
  - Fetches care shifts (`GET /api/citizen/reservations?from=YYYY-MM-DD&to=YYYY-MM-DD`) for the full 2-month calendar grid window (`calendar_window(today)`), skips days with a recorded absence (`absence != None`), maps child IDs to first/preferred names dynamically from the API response (`res["children"]`), and writes `shared/hoitovuorot.json` atomically (`[{lapsi, pvm, alku, loppu}]`).
  - Fetches received messages and bulletins (`GET /api/citizen/messages/received?page=1&pageSize=20`) and writes `raw/evaka_messages.json` (`{haettu, ketjut: [{id, otsikko, tyyppi, kiireellinen, lahetetty, lahettaja, sisalto}]}`) so `Arjen apuri` or a parser can extract `shared/muistutukset.json` entries without launching a browser.
  - Reads credentials from `EVAKA_USERNAME` and `EVAKA_PASSWORD` in `secrets.env` (or environment variables). Contains zero hardcoded credentials or personal data.
- **Usage & CLI Flags**:
  - Place `fetch-evaka.py` in `perhekalenteri/` alongside `collect.py` and add `EVAKA_USERNAME="..."` and `EVAKA_PASSWORD="..."` to `secrets.env`.
  - Default run (updates both `shared/hoitovuorot.json` and `raw/evaka_messages.json`):
    ```bash
    python3 fetch-evaka.py
    ```
  - Care shifts only (skip messages):
    ```bash
    python3 fetch-evaka.py --no-messages
    ```
  - Custom date window or output paths:
    ```bash
    python3 fetch-evaka.py --from-date YYYY-MM-DD --to-date YYYY-MM-DD --out-shifts path/to/hoitovuorot.json --out-messages path/to/evaka_messages.json
    ```
- **Reasoning**:
  - Direct HTTP requests to eVaka's Citizen API run in ~0.5 seconds with minimal memory/CPU compared to spinning up a headless browser, making both care-shift and message fetching faster and more reliable for both environments.
- **Affected Files & Components**:
  - `fetch-evaka.py` (new script in repository root; no changes to `index.html`, `app.js`, or `style.css`).
  - `AGENT_LOG.md`
- **Grok Bot Automation Impact**:
  - **Recommended Adoption**: Copy `fetch-evaka.py` into Grok Bot's working directory (`perhekalenteri/fetch-evaka.py`), set `EVAKA_USERNAME` and `EVAKA_PASSWORD` in `secrets.env`, and invoke `python3 fetch-evaka.py` before `python3 collect.py` (or in the eVaka automation routine). Once Grok Bot has copied `fetch-evaka.py` into its private workspace, it can optionally remove `fetch-evaka.py` from the public repo or keep it versioned here.
- **Publish Status**:
  - **Published via webhook**: NO (utility script + documentation only; no frontend/UI changes).

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
| Hoitovuorot | Arjen apuri | **cadence not documented — verify with Arjen apuri/Eetu** | writes `shared/hoitovuorot.json` (`[{lapsi, pvm, alku, loppu}]`) |
| Antigravity-julkaisu (webhook) | Koodaribotti | on demand | webhook triggers a publish; URL/key live only in the Grok Bot app (not exportable) |
| Tablet version check | tablet browser | data every 5 min; full reload every 6 h | `app.js checkVersion()` fetches `version.json` and reloads when the version changes |

- **Verification**: Tekninen automaatiobotti's two routines and the webhook owner are verified against repo notes (`fetch-notes.md`, `README.md`) and Grok Bot's own records. Arjen apuri's Keep/eVaka/email cadences come from Grok Bot's records (not independently verifiable from repo files). The **hoitovuorot.json cadence is unverified** — not found in any file or note; flagged for confirmation.
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
