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
