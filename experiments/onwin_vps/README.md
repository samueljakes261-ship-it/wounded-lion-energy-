# Onwin VPS Chrome

Onwin live and prematch run only on this VPS. The Windows PC runs the
Kolay91 collector and does not open Onwin.

Google Chrome stays up on port 9223, with its own profile, on a private
Xvfb screen (`:98`). That screen is not VNC and it is not Kolay90's
display. The collector attaches over the debugging port and writes live
and prematch odds into the snapshot files the engine already reads. No
ingest token. A dropped debugger reconnects without closing the tabs.
Chrome is restarted when port 9223 is down, or when that port answers but the collector still cannot attach. Background-tab
throttling is disabled so the sportsbook keeps sending odds. A quiet
tab is left open. Reloading it sent both feeds through Cloudflare and
both collectors dropped. Response bodies are read on the collector
loop, not inside a debugger event, so a burst of odds cannot stall the
connection. If the live page then goes quiet, the collector asks that
same open page for the last feed again. It does not navigate. The last
good odds stay in the snapshot files through a debugger reconnect: live
for three minutes, prematch for fifteen. A Cloudflare check is left
alone. Chrome comes back on the last session instead of opening the
sportsbook again.

```bash
cd ~/apps/ArbScanner
git fetch origin cursor/prematch-arbitrage
git checkout cursor/prematch-arbitrage
git pull origin cursor/prematch-arbitrage
chmod +x experiments/onwin_vps/chrome.sh experiments/onwin_vps/collector.sh
experiments/onwin_vps/chrome.sh install
experiments/onwin_vps/chrome.sh start
experiments/onwin_vps/collector.sh start
experiments/onwin_vps/collector.sh status
```

Restart the engine so it is running this checkout:

```bash
sudo systemctl restart arbscanner-engine
```

Inspect, restart, and stop:

```bash
experiments/onwin_vps/chrome.sh status
experiments/onwin_vps/collector.sh status
experiments/onwin_vps/collector.sh restart
experiments/onwin_vps/chrome.sh restart
experiments/onwin_vps/collector.sh stop
experiments/onwin_vps/chrome.sh stop
```

`collector.sh restart` does not restart Chrome. `chrome.sh restart` does
not restart Kolay90. Restart Chrome once after pulling these flags so
the sportsbook tabs are not throttled. After that, leave both services
running. Status is `experiments/onwin_vps/output/status.json`. Logs are
`experiments/onwin_vps/output/chrome.log` and `collector.log`.
