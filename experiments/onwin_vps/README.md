# Onwin VPS Chrome

Google Chrome on port 9223, with its own profile, on a private Xvfb
screen (`:98`). That screen is not VNC and it is not Kolay90's display.
The collector attaches over the debugging port and writes live and
prematch odds into the snapshot files the engine already reads. No ingest
token.

Stop the Windows Onwin collector before starting this one. Both write the
same snapshot files.

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
not restart Kolay90. Status is `experiments/onwin_vps/output/status.json`.
Logs are `experiments/onwin_vps/output/chrome.log` and `collector.log`.
