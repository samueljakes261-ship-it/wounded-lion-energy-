# Credential Management — Plain-Language Guide

This explains the credential system in `credentials/` that manages ZenRows
API keys for ArbScanner: what it does, what each piece is, and how to
operate it day-to-day on Windows and on a VPS. No prior security background
assumed.

---

## 1. The problem this solves

Before this system, the whole app used exactly **one** ZenRows key, read
straight from `.env`. If that key ran out of quota, got rate-limited, or was
revoked, every scraper using it (OnWin, BetKanyon) broke until someone
manually fixed `.env` and restarted everything.

Now you can register **multiple** ZenRows accounts/keys you're legitimately
authorized to use. The app automatically:

- picks a healthy one to use,
- notices when one stops working and figures out *why*,
- switches to another authorized one if that's the right response,
- and waits out (cools down) problems that switching wouldn't fix, like
  rate limits.

It does **not** try to dodge ZenRows' rate limits or terms — it only
rotates between accounts you've configured yourself, and only for the
reasons where that's actually appropriate (see §5).

---

## 2. The pieces, in plain terms

| Piece | What it is | Analogy |
|---|---|---|
| `MASTER_CREDENTIAL_KEY` | One secret value in your `.env` file | The key to a safe |
| `credentials.json` | A file holding your ZenRows keys, each locked (encrypted) | The safe itself |
| `runtime/credentials_state.json` | A small file recording "which key is healthy right now" | A sticky note, not a secret |
| `CredentialManager` (`credentials/manager.py`) | The code that decides which key to use next | The person who opens the safe and hands you a key |
| `python -m credentials.cli` | A command-line tool to manage keys | The safe's keypad |

**Nothing in `credentials.json` is readable without `MASTER_CREDENTIAL_KEY`.**
Even if someone got a copy of `credentials.json`, it's useless to them
without that key. And `MASTER_CREDENTIAL_KEY` itself never goes into
`credentials.json`, Git, or any log line.

### Why two files instead of one?

`credentials.json` holds the actual (locked) secrets — treat it like a
password vault. `runtime/credentials_state.json` holds no secrets at all,
just bookkeeping like "credential zenrows-01 failed 2 times, cooling down
until 10:42am". It's safe to delete at any time — the app just rebuilds it
from scratch and re-learns which credentials are healthy.

---

## 3. What happens when a credential fails

Every failure is put into one of these buckets, and each bucket is handled
differently — the system deliberately does **not** treat every error the
same way:

| What happened | What the system does |
|---|---|
| Key is invalid/revoked (`INVALID_CREDENTIAL`) | Disables that key immediately; switches to another authorized one |
| Repeated login/auth failures (`AUTHENTICATION_FAILURE`) | Cools down, then disables after 3 in a row; switches over |
| You've used up that account's quota (`QUOTA_EXHAUSTED`) | Cools that key down for a long time; switches to another authorized one |
| ZenRows says "slow down" (`RATE_LIMITED`) | **Never switches keys** — waits out ZenRows' own cooldown on the *same* key, exactly as they ask |
| A one-off network/server hiccup | Retries the *same* key a couple of times with increasing delays, then tries another key only if it keeps failing |
| Something unrecognized | Logs it and fails safely — never guesses aggressively |

Switching keys is called "failover." It's the right move for a broken key.
It's the *wrong* move for a rate limit, because that would look like trying
to dodge ZenRows' limits — this system never does that.

If **every** configured key is currently unavailable, the app gets a clear
error ("all authorized credentials unavailable") instead of hanging or
looping forever.

---

## 4. What happens after a restart

- **`credentials.json` (your actual keys) is never touched by a restart.**
  You never have to re-add your keys.
- **`runtime/credentials_state.json` (the health bookkeeping) gets cleared**
  by the reset scripts (see §7). Every credential starts "fresh" again —
  a credential that was cooling down before the restart gets a clean
  slate, since whatever caused the original problem may well be gone by
  the time you're restarting anyway.

---

## 5. Setting it up (first time, Windows)

1. Copy the templates:

   ```powershell
   Copy-Item .env.example .env
   ```

   (If you already have a working `.env`, skip this — just add the new
   `MASTER_CREDENTIAL_KEY` line described next.)

2. Generate a master key and create the empty store:

   ```powershell
   .venv\Scripts\python.exe -m credentials.cli init
   ```

   This prints a line like `MASTER_CREDENTIAL_KEY=<random value>`. Copy
   that into your `.env` file. **Never share this value or commit it.**

3. Add your ZenRows credential(s). The "secret" is the same
   `wss://browser.zenrows.com?apikey=...` connection string you'd otherwise
   put in `ZENROWS_BROWSER_WS`:

   ```powershell
   .venv\Scripts\python.exe -m credentials.cli add --provider zenrows --secret "wss://browser.zenrows.com?apikey=YOUR_KEY" --label "primary"
   ```

   Add a second (or third) authorized account the same way, with a
   different `--label`, to get automatic failover:

   ```powershell
   .venv\Scripts\python.exe -m credentials.cli add --provider zenrows --secret "wss://browser.zenrows.com?apikey=YOUR_BACKUP_KEY" --label "backup"
   ```

4. Confirm it's working:

   ```powershell
   .venv\Scripts\python.exe -m credentials.cli list
   .venv\Scripts\python.exe -m credentials.cli health --provider zenrows
   ```

**You don't have to do any of this right away.** If `credentials.json`
doesn't exist yet (or has no ZenRows entries), the app automatically falls
back to whatever is in `ZENROWS_BROWSER_WS` in your `.env` — exactly like
before. Nothing breaks if you don't migrate immediately.

---

## 6. Day-to-day credential commands

```powershell
# See all configured credentials and their current status
.venv\Scripts\python.exe -m credentials.cli list

# Temporarily take a credential out of rotation
.venv\Scripts\python.exe -m credentials.cli disable zenrows-01

# Bring it back
.venv\Scripts\python.exe -m credentials.cli enable zenrows-01

# Permanently remove a credential (e.g. a cancelled account)
.venv\Scripts\python.exe -m credentials.cli remove zenrows-01

# Rotate a key: add the new one, then remove/disable the old one
.venv\Scripts\python.exe -m credentials.cli add --provider zenrows --secret "wss://browser.zenrows.com?apikey=NEW_KEY" --label "primary (rotated)"
.venv\Scripts\python.exe -m credentials.cli disable zenrows-01

# Check health (never spends a real ZenRows session unless --probe is added,
# and even --probe only opens a plain TCP connection, no billed request)
.venv\Scripts\python.exe -m credentials.cli health --provider zenrows
.venv\Scripts\python.exe -m credentials.cli health --provider zenrows --probe

# Clear the health bookkeeping (e.g. after fixing an account) without
# touching the actual keys
.venv\Scripts\python.exe -m credentials.cli reset-state --provider zenrows
```

None of these commands ever print a decrypted secret.

---

## 7. Restarting the app

### Windows (development)

```powershell
# See exactly what would happen, without changing anything
.\scripts\reset-dev.ps1 -DryRun

# Actually stop, clean up, and restart the API + frontend + engine
.\scripts\reset-dev.ps1

# Stop and clean up only, without restarting
.\scripts\reset-dev.ps1 -SkipRestart

# Also delete *.log files (kept by default)
.\scripts\reset-dev.ps1 -ClearLogs
```

This script only ever stops processes it can prove belong to this project
(it checks each running `python.exe`/`node.exe`'s command line for this
project's own folder path *and* a recognizable entrypoint like
`uvicorn`/`run_engine.py`/`vite`) — it will never touch some unrelated
Python or Node process you happen to have open. It never deletes source
code, `.venv`, `node_modules`, `.env`, or `credentials.json`.

### Linux / VPS (production)

```bash
./scripts/reset-prod.sh --dry-run
./scripts/reset-prod.sh
./scripts/reset-prod.sh --skip-restart
./scripts/reset-prod.sh --clear-logs
```

This script first checks whether you're already using `systemd`, `pm2`,
Docker Compose, or Supervisor for this project, and if so, uses that
instead of inventing its own process manager. Only if none of those are
detected does it fall back to the same "start it directly" approach as the
Windows script.

---

## 8. Deploying to a VPS

1. Copy the project to the VPS as usual (Git clone/pull), **excluding**
   `.env` and `credentials.json` (they're already gitignored, so a normal
   `git clone` won't bring them along).
2. Create `.env` on the VPS directly (never via Git):
   ```bash
   cp .env.example .env
   nano .env   # fill in MASTER_CREDENTIAL_KEY and anything else needed
   ```
   `MASTER_CREDENTIAL_KEY` can also come from your hosting provider's
   secret manager / environment-variable injection instead of a literal
   `.env` file, if you prefer that — the code just reads it from the
   environment either way.
3. Copy `credentials.json` to the VPS out-of-band (`scp`, your deployment
   pipeline's secret file transfer, etc.) — **not** through Git:
   ```bash
   scp credentials.json user@your-vps:/path/to/ArbScanner/credentials.json
   ```
4. Restrict its permissions so only the app's own user can read it:
   ```bash
   chmod 600 credentials.json
   ```
5. Start the app with `./scripts/reset-prod.sh` (or your existing
   systemd/pm2/Docker/Supervisor setup, which the script will detect and
   defer to automatically).

---

## 9. Backing up the encrypted store safely

`credentials.json` is safe to back up as a normal file (it's already
encrypted), but treat it with the same care as a password vault:

- Store backups somewhere access-controlled, not a public share.
- Keep `MASTER_CREDENTIAL_KEY` in a **separate** backup location from
  `credentials.json` — if both end up in the same place, the encryption
  provides no real protection.
- `runtime/credentials_state.json` does **not** need backing up — it's
  regenerated automatically and contains no secrets.

---

## 10. What must never be committed to Git

Already handled by `.gitignore`, but good to know explicitly:

- `.env` (contains `MASTER_CREDENTIAL_KEY` and other real secrets)
- `credentials.json` (your encrypted ZenRows keys)
- `runtime/` (non-secret, but it's disposable local state)

Safe to commit (and already tracked):

- `.env.example` (placeholders only)
- `credentials.example.json` (placeholders only)
- `scripts/reset-dev.ps1`, `scripts/reset-prod.sh`
- everything under `credentials/` (the code itself contains no secrets)

---

## 11. Where this fits in the existing project

`utils/zenrows_persistent.py` (used by OnWin) and
`browser/sessions/zenrows.py` (used by BetKanyon and legacy code) are the
two places that actually open a ZenRows browser session. Both were changed
to ask `credentials/zenrows_provider.py` for a working connection instead
of reading `ZENROWS_BROWSER_WS` directly — everything else in the project
(the feeds, workers, collector, arbitrage engine, frontend) is unchanged
and unaware this exists.
