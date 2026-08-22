# Isolated kolay90 direct-access experiment

**Experiment only.** This directory does not replace or modify BetKanyon,
Orbit, OnWin, live/prematch feeds, `collector.py`, `run_engine.py`, the
matcher, the arb engine, or the frontend.

## Question

Can a legitimate kolay90 browser session be established once and then
reused for direct HTTP `GET /service/getMaclar` without ZenRows, and can
football prematch 1X2 be parsed accurately from that JSON?

## Attach to your authenticated Chrome

Chrome must already be running with remote debugging. Use a **separate**
profile so your normal Chrome is not disturbed:

```
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$PWD\experiments\kolay90_direct\chrome_profile"
```

In that window: open kolay90.com, complete Cloudflare, log in, confirm
`https://kolay90.com/service/getMaclar` returns JSON. Then:

```
.\.venv\Scripts\python.exe experiments\kolay90_direct\attach_cdp.py
```

This attaches with CDP. It does not launch another Chrome, inject cookies,
or use ZenRows.

## Older persistent-browser runner

From the repo root:

```
.\.venv\Scripts\python.exe experiments\kolay90_direct\run.py
```

A visible Chrome window opens using
`experiments/kolay90_direct/browser_profile/` (gitignored).

1. Complete any Cloudflare challenge yourself in that window.
2. Log in if the site asks you to.
3. When the normal authenticated site is visible, press ENTER in the terminal.

Do not bypass Cloudflare. This experiment does not use ZenRows.

A captured browser request used `GET /service/getMaclar` with
`Accept`, `User-Agent`, and `X-Requested-With: XMLHttpRequest`.
Cookie **values** from any live session are never stored in this repo.
The runner reads cookies only from the persistent browser at runtime.

## Session security

Cookie **names** such as `bet_cms` and `cf_clearance` may be discussed.
Cookie **values** are never hard-coded, committed, printed, or stored in
tracked files.

## Tests

```
.\.venv\Scripts\python.exe -m pytest experiments\kolay90_direct\test_parser.py -q
```
