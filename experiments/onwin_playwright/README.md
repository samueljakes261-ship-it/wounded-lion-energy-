# Onwin Playwright experiment

This does not start ZenRows and does not publish odds.

From the repo root, with the normal virtualenv active:

```
python -m playwright install chromium
python -m experiments.onwin_playwright.run
```

Chromium opens the same live soccer page the production feed uses.
Finish any Cloudflare or Onwin check in that window and leave it open.
The terminal prints request paths and a status line. Ctrl+C closes the
browser.

`experiments/onwin_playwright/output/` holds the captured response and
`status.json`. It is gitignored. Tokens and cookies are not written there.

If Onwin has moved host, set `ONWIN_EXPERIMENT_URL` to the new sportsbook
URL before starting. To compare with a main-line file you already have,
pass `--production-snapshot path\to\file.json`. That only reads the file.
