# Onwin VPS Chrome

Isolated collector for a dedicated Google Chrome on the VPS. It does not
use the Kolay90 profile or port 9222, and it does not launch a browser.
The CDP client is the same one the Windows collector already uses.
Production ingest stays off until `ONWIN_VPS_PUBLISH=1`.

The existing TigerVNC display (`:1`) must already be running. These
scripts do not start a desktop.

From the repo root on the VPS:

```bash
cp experiments/onwin_vps/config.env.example experiments/onwin_vps/config.env
chmod +x experiments/onwin_vps/chrome.sh experiments/onwin_vps/collector.sh
experiments/onwin_vps/chrome.sh start
experiments/onwin_vps/chrome.sh status
experiments/onwin_vps/collector.sh start
experiments/onwin_vps/collector.sh status
```

Open the VNC desktop, finish any Onwin check in the new Chrome window,
and leave both tabs open.

```bash
experiments/onwin_vps/collector.sh stop
experiments/onwin_vps/collector.sh restart
experiments/onwin_vps/chrome.sh stop
experiments/onwin_vps/chrome.sh restart
```

`collector.sh restart` does not restart Chrome. `chrome.sh restart` does
not restart Kolay90. Status of a running collector is
`experiments/onwin_vps/output/status.json`.

Optional systemd units are `onwin-vps-chrome.service` and
`onwin-vps-collector.service` in this directory. Install them only after
the manual checks succeed. `ONWIN_VPS_PUBLISH` stays `0` until the
Windows collector is stopped.
