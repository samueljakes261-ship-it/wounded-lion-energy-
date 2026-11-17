# Kolay90 prematch (authenticated Chrome)

Kolay90 prematch uses one Chrome window that a person has logged into.
It does not use ZenRows, cookie replay, or standalone HTTP clients.

On the VPS that window lives on a TigerVNC virtual desktop running XFCE.
The operator connects with TigerVNC Viewer through an SSH tunnel,
completes Cloudflare, accepts the agreement, and logs in. The worker
only attaches to that same Chrome.

## TigerVNC session

TigerVNC listens on `127.0.0.1:5901` only. The password file is
`~/.vnc/passwd` and is never read or printed by this repo. XFCE is
started by `~/.vnc/xstartup`. Leave that file and the password file
as they are.

1. On the VPS, from the repo root, start the desktop only if display
   `:1` is down:

```
python -m parsers.kolay90_prematch.vnc_session start
```

If `tigervncserver -list` already shows display `:1`, this does not
start a second server. It opens one visible Chrome window after XFCE
is up, using `experiments/kolay90_direct/chrome_profile` (mode 0700).
Remote debugging stays on `127.0.0.1:9222`. A second Chrome is not
started for the same profile.

2. From Windows, keep this tunnel open. It forwards local port 15901
   to the VPS localhost port 5901:

```
ssh -4 -vvv -o IPQoS=none -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=10 -N -L 127.0.0.1:15901:127.0.0.1:5901 woundedlion@135.125.151.59
```

In another PowerShell window:

```
Test-NetConnection 127.0.0.1 -Port 15901
```

`TcpTestSucceeded : True` means the tunnel is up. Then open TigerVNC
Viewer to `127.0.0.1:15901` and enter the TigerVNC password. Do not
open port 5901 on the public address.

3. In that Chrome window: complete Cloudflare, accept the agreement, log in.
4. Leave the window open.
5. Start the engine. The Kolay90 worker attaches to that same Chrome and
   polls `GET /service/getMaclar` with in-page `fetch`. The phase becomes
   `AUTHENTICATED` only after that request returns parsable odds.
6. If the session expires, the phase becomes `SESSION_EXPIRED`, new odds
   are not published, and the last-good snapshot keeps its original
   timestamps. Log in again in the same window.

```
python -m parsers.kolay90_prematch.vnc_session status
python -m parsers.kolay90_prematch.vnc_session restart
```

`status` reports whether display `:1` is running, whether XFCE is up,
the Chrome process, the profile path, the auth phase, and the last
authenticated request. It does not print passwords, cookies, or profile
contents. `restart` stops only the Chrome process using this profile
and opens it again on the same desktop. The TigerVNC session stays up.

Optional environment, all on the VPS process:

- `KOLAY90_VNC_DISPLAY` (default `:1`)
- `KOLAY90_VNC_LOCALHOST` (default `yes`)
- `KOLAY90_VNC_GEOMETRY` (default `1600x900`)
- `KOLAY90_VNC_DEPTH` (default `24`)
- `KOLAY90_VNC_SERVER` (default `tigervncserver`)
- `KOLAY90_CHROME_BIN`
- `KOLAY90_CHROME_PROFILE`
- `KOLAY90_CDP_URL` (default `http://127.0.0.1:9222`)
- `KOLAY90_VNC_AUTOSTART` (`1`/`true`/`yes` lets the worker open the desktop once)

## Local Chrome, without TigerVNC

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
