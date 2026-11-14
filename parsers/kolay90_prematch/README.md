# Kolay90 prematch (authenticated Chrome)

Kolay90 prematch uses one Chrome window that a person has logged into.
It does not use ZenRows, cookie replay, or standalone HTTP clients.

On the VPS that window lives on a RealVNC virtual desktop. The operator
connects with RealVNC Viewer, completes Cloudflare, accepts the agreement,
and logs in. The worker only attaches to that same Chrome.

## RealVNC session

1. Install RealVNC Server and set its password in RealVNC's own config.
   Do not put that password in this repo or on a command line.
2. From the repo root:

```
python -m parsers.kolay90_prematch.vnc_session start
```

This starts `vncserver-virtual` (or `vncserver`) on display `:1` when that
desktop is down, then opens Chrome there with remote debugging bound to
`127.0.0.1:9222`. If Chrome is already listening, it is left alone.

3. Connect with RealVNC Viewer to `host:1` (TCP 5901).
4. In that Chrome window: complete Cloudflare, accept the agreement, log in.
5. Leave the window open.
6. Start the engine. The Kolay90 worker reuses that tab and polls
   `GET /service/getMaclar` with in-page `fetch`.
7. If the session expires, the worker reports `KOLAY90_AUTHENTICATION_REQUIRED`
   and keeps the last-good snapshot. Repeat steps 3–5 in the same desktop.
   Do not open a second Chrome.

`python -m parsers.kolay90_prematch.vnc_session status` reports whether the
desktop, the VNC port, and the Chrome debugging port are up. It does not
print passwords or cookies.

Optional environment, all on the VPS process:

- `KOLAY90_VNC_DISPLAY` (default `:1`)
- `KOLAY90_VNC_SERVER` (default: `vncserver-virtual`, then `vncserver`)
- `KOLAY90_CHROME_BIN`
- `KOLAY90_CHROME_PROFILE`
- `KOLAY90_CDP_URL` (default `http://127.0.0.1:9222`)

## Local Chrome, without RealVNC

1. Start the dedicated Chrome profile with remote debugging and keep it open:

```
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$PWD\experiments\kolay90_direct\chrome_profile" `
  https://kolay90.com/
```

2. In that window: open Kolay90 if needed.
3. Manually complete Cloudflare if it appears.
4. Accept the Kolay90 user agreement.
5. Log in.
6. Confirm the normal authenticated Kolay90 application is visible.
7. Start the engine (`ENGINE_MODE=prematch` or the usual live+prematch start).
8. The Kolay90 worker attaches to `127.0.0.1:9222` and reuses that tab.
9. It polls `GET /service/getMaclar` with in-page `fetch` from that page.
10. If the session expires, the worker reports `KOLAY90_AUTHENTICATION_REQUIRED`,
    keeps the last-good snapshot, and waits. Repeat steps 3–6 in the same Chrome.
    Do not close the browser.

Do not copy cookies. Do not paste tokens. Do not start a second Chrome profile
for the worker.
