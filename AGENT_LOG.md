# Perhekalenteri — Agent Collaboration & Change Log (`AGENT_LOG.md`)

This file is the shared coordination log between **Antigravity** and **Grok Bot** for developing and maintaining `perhekalenteri`.

## Collaboration Rules for Both Agents

1. **Read First**: Before planning or making any code, style, or automation changes, always read this file (`AGENT_LOG.md`) first to see recent changes made by the other agent.
2. **Preserve Changes (Important for Grok Bot's Publish Script)**:
   - Antigravity may commit updates directly to `index.html`, `app.js`, `style.css`, `version.json`, and `AGENT_LOG.md` in this GitHub repository.
   - If Grok Bot publishes from a local working directory or template directory, Grok Bot **must** sync/pull changes from `origin/main` before publishing so it does not overwrite edits made by Antigravity (such as `index.html` template files, `app.js`, `style.css`, or `AGENT_LOG.md`).
3. **Log Every Code/Feature Change**:
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
```

---

## Change Log

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
