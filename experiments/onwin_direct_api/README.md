# Isolated OnWin direct API experiment

**This directory is an experiment.** It does not replace, import, or
modify the production OnWin persistent feed (`parsers/onwin/`).

## Question

After a **normal installed Google Chrome** session loads OnWin (matching the
captured request *shape*: origin `onwin4511.com`, `get_main_line` URL,
`content-type: application/json`, plus dynamically minted `x-token` /
`x-message-metadata`), can that API response be obtained **without**
ZenRows CDP/API?

The supplied browser cURL is treated as **shape evidence only**.

Captured `x-token` / `x-message-metadata` **values are never** copied into
source, env files, logs, or git.

A negative result is a valid result.

## What this does not do

- Does not change `parsers/onwin/`, `collector.py`, `run_engine.py`
- Does not replace ZenRows in production
- Does not hard-code captured `x-token` / `x-message-metadata` values
- Does not bypass Cloudflare, CAPTCHA, or access controls
- Does not use a proxy
- Does not touch BetKanyon, Orbit, prematch, the arb engine, or the UI

## Run

From the repo root, with the existing venv (Playwright is already
installed for other browser sessions; this experiment does **not** add
a production `requirements.txt` dependency). Local Chromium is required
once for this experiment only:

```
.\.venv\Scripts\python.exe -m playwright install chromium
```

Then:

```
.\.venv\Scripts\python.exe experiments\onwin_direct_api\experiment.py
```

Optional environment:

| Variable | Default | Meaning |
|---|---|---|
| `ONWIN_EXPERIMENT_PAGE` | `https://onwin4511.com/sportsbook/live/main-line/soccer` | First navigation target |
| `ONWIN_EXPERIMENT_HEADLESS` | `0` (headed, a normal window) | Set `1` for headless |
| `ONWIN_EXPERIMENT_TIMEOUT` | `180` | Seconds to wait for `get_main_line` |

The experiment prefers the system's Google Chrome (`channel="chrome"`) so
the session matches the capture (Chrome 151). It falls back to Playwright
Chromium if Chrome is unavailable. It does **not** replay captured tokens.

Output is written under `experiments/onwin_direct_api/output/` (gitignored).
Logs redact `x-token`, `x-message-metadata`, cookies, and similar values.

## Classification labels

- `DIRECT_ACCESS_WORKS` — browser session + in-page fetch + standalone HTTP all succeed
- `DIRECT_ACCESS_WORKS_ONLY_INSIDE_BROWSER` — in-page fetch works, standalone HTTP does not
- `DIRECT_ACCESS_REQUIRES_SESSION_METADATA` — request needs dynamically captured `x-token` / `x-message-metadata`
- `DIRECT_ACCESS_REQUIRES_ZENROWS` — a normal local browser could not establish the session the API needs
- `INCONCLUSIVE` — the run did not produce enough evidence
