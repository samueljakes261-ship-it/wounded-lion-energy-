# Kolay90 prematch (authenticated Chrome)

Kolay90 prematch uses a **manually authenticated local Chrome** session.
It does not use ZenRows, cookie replay, or standalone HTTP clients.

## Startup

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
