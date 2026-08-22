# Isolated kolay90 direct-access experiment

**Experiment only.** This directory does not replace or modify BetKanyon,
Orbit, OnWin, live/prematch feeds, `collector.py`, `run_engine.py`, the
matcher, the arb engine, or the frontend.

## Question

Can a legitimate kolay90 browser session be established once and then
reused for direct HTTP `GET /service/getMaclar` without ZenRows, and can
football prematch 1X2 be parsed accurately from that JSON?

## Run

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

## Session security

Cookie **names** such as `bet_cms` and `cf_clearance` may be discussed.
Cookie **values** are never hard-coded, committed, printed, or stored in
tracked files.

## Tests

```
.\.venv\Scripts\python.exe -m pytest experiments\kolay90_direct\test_parser.py -q
```
