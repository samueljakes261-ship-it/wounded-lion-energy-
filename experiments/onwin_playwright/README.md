# Onwin Playwright experiment

This does not start ZenRows and does not publish odds. It uses the
Chrome window the Kolay91 collector already opened.

Leave the Kolay91 collector running, then from the repo root:

```
python -m experiments.onwin_playwright.run
```

A new tab opens in that same window on the live soccer page. Finish any
Cloudflare or Onwin check in that tab and leave it open. The Kolay91
tab is not closed. Ctrl+C closes only the Onwin tab.

The terminal prints request paths and a status line.
`experiments/onwin_playwright/output/` holds the captured response and
`status.json`. It is gitignored. Tokens and cookies are not written there.

If Onwin has moved host, set `ONWIN_EXPERIMENT_URL` to the new sportsbook
URL before starting. To compare with a main-line file you already have,
pass `--production-snapshot path\to\file.json`. That only reads the file.
