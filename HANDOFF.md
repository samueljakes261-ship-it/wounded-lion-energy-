# ArbScanner — Master Project Handoff

> **Purpose:** This document is the source-of-truth handoff for continuing the ArbScanner project in Cursor.
>
> **Important:** Read this document before changing code. The project has already gone through substantial investigation and implementation. Do **not** redo completed reconnaissance, replace working components, or redesign the architecture merely because a different implementation appears cleaner.
>
> **Division of work:** Cursor/Sonnet is being used for implementation directly inside the IDE. ChatGPT ("Chatty") remains the project's critical-analysis and explanation layer: architecture review, reasoning, debugging strategy, prompt review, and helping the developer understand what Cursor is doing.

---

# 1. PROJECT MISSION

ArbScanner is an automated sports-betting arbitrage scanner.

The core objective is to collect bookmaker odds, normalize and match equivalent sporting events across bookmakers, identify arbitrage opportunities, calculate appropriate stakes, and eventually surface those opportunities through the project's frontend.

The project is intended to be practical rather than academic.

The central pipeline is:

```text
Bookmaker feeds
      ↓
Collectors / parsers
      ↓
Normalized MatchOdds
      ↓
Team-name normalization
      ↓
Cross-bookmaker event matching
      ↓
Best available odds
      ↓
Arbitrage detection
      ↓
Stake calculation
      ↓
Opportunities
      ↓
Frontend / API
```

The project began with investigation of multiple bookmakers and data-acquisition approaches before settling on the current implementation path.

---

# 2. ORIGINAL PROJECT DIRECTION

The original idea was to build a low-risk/minimal-risk arbitrage betting system.

Early planning focused on Kenya because the developer had access to Kenyan bookmakers and wanted to prove the concept with a small bankroll.

Kenyan bookmakers investigated included:

- Betika
- SportPesa
- Odibets
- 1xBet

Taxation and bookmaker limitations eventually made a purely Kenyan deployment less attractive.

The project therefore expanded to foreign bookmakers and exchanges.

The long-term system is bookmaker-agnostic: each bookmaker should have a feed/parser adapter producing the same internal `MatchOdds` representation.

---

# 3. IMPORTANT DEVELOPMENT HISTORY

## Phase A — Arbitrage engine and proof of concept

The project first established the core arbitrage logic rather than beginning with a polished frontend.

Important components include:

- match representation
- odds representation
- team-name normalization
- event matching
- best-odds selection
- arbitrage detection
- stake calculation
- opportunity caching/collection

The engine is intended to work independently from the bookmaker-specific acquisition mechanisms.

This separation is important and should be preserved.

---

# 4. BOOKMAKER / DATA-ACQUISITION INVESTIGATIONS

The project investigated several approaches to obtaining bookmaker content.

## 4.1 Direct/public APIs

A recurring problem was that many bookmakers do not provide public APIs suitable for this use case.

The developer contacted bookmakers in some cases, but automation/API access was often rejected once the intended automated use case was disclosed.

Conclusion:

> The project cannot assume bookmaker-provided public APIs will be available.

---

## 4.2 Web scraping / browser automation

Browser-based acquisition became a major part of the project.

Technologies investigated/used:

- Python
- Playwright
- ZenRows
- persistent ZenRows browser sessions
- network request/response interception
- Fetch/XHR reconnaissance
- JSON endpoint capture

ZenRows was particularly important because ordinary direct requests were insufficient for some protected bookmaker sites.

A persistent browser session was eventually created so that a browser could be reused rather than repeatedly creating a fresh browser.

Current helper:

```text
utils/zenrows_persistent.py
```

Current OnWin browser wrapper:

```text
parsers/onwin/browser.py
```

---

# 5. ORBIT EXCHANGE — COMPLETED PROOF

Orbit Exchange was one of the important early bookmaker/feed integrations.

The project successfully captured and parsed Orbit data.

A major milestone was obtaining actual match odds from the bookmaker feed and feeding them into the arbitrage system.

The project reached a point where Orbit odds could be compared against another bookmaker.

This was important because it moved the project from theoretical arbitrage calculations to actual bookmaker data.

---

# 6. BETKANYON — COMPLETED PROOF / MATCHING

BetKanyon was investigated and used as another bookmaker source.

The project successfully reached the point where bookmaker data could be compared against Orbit.

One of the most important proof-of-concept milestones was:

> Orbit Exchange and BetKanyon data were successfully matched and the arbitrage engine identified an actual arbitrage opportunity.

This is a critical completed milestone.

Do not replace the arbitrage engine simply because OnWin acquisition is still being optimized.

The purpose of continuing bookmaker integrations is to feed the already-proven engine with faster and more complete odds.

---

# 7. TURKISH BOOKMAKER / CLIENT PROJECT CONTEXT

The developer also began a client-specific Turkish arbitrage scanner project.

The client is based in Turkey.

The developer is the sole developer on the project.

The client pays approximately €100 per week / €400 per month and covers project/API expenses.

The project focused on bookmakers including:

- kolay90.com
- Betfair Exchange

Other bookmaker URLs investigated during V1 reconnaissance included:

- Orbit Exchange
- kolay90.com
- novel34.com/mobile/main.html
- betkanyon1617.com
- onwin4329.com
- Betfair Exchange

The client specifically insisted on including Kolay90.

Kolay90 required login to view odds and proved more difficult to interrogate through browser DevTools/network inspection than the easier endpoints.

This investigation is part of the broader history and should not be forgotten when planning the final bookmaker architecture.

---

# 8. FRONTEND HISTORY

A frontend was generated using Lovable.

GitHub repository:

```text
green-edge-scanner
```

The Lovable-generated frontend was cloned into the ArbScanner project.

The frontend was built with Vite.

At one stage:

```text
VITE v8.1.4
Local: http://localhost:8080/
```

The project name was later changed from:

```text
Green Edge Scanner
```

to:

```text
Wounded Lion Energy
```

Use **Wounded Lion Energy** going forward where the application/product name is required.

The developer explicitly did **not** want to rebuild the frontend from scratch.

Frontend work should primarily be:

1. connect the existing frontend to the backend/API,
2. ensure opportunities are coming from real/stub dynamic data rather than hardcoded UI values,
3. stress-test the end-to-end flow.

The major development focus is the backend/data pipeline.

---

# 9. CURRENT CORE ARCHITECTURE

The repository has evolved around the following structure:

```text
ArbScanner/
│
├── engine/
│   ├── match_finder.py
│   ├── matcher.py
│   ├── normalizer.py
│   ├── stake_calculator.py
│   └── ...
│
├── models/
│   ├── match.py
│   ├── arbitrage_opportunity.py
│   └── ...
│
├── parsers/
│   ├── orbit/
│   ├── betkanyon/
│   └── onwin/
│
├── experiments/
│   ├── decrypt/
│   └── betkanyon/
│       └── network/
│
├── output/
│
├── tests/
│
├── utils/
│
├── collector.py
├── cached_opportunities.json
└── ...
```

The exact current tree should be inspected by Cursor rather than assumed from this document.

---

# 10. CORE INTERNAL DATA MODEL

Bookmaker-specific parsers should not leak bookmaker-specific JSON structures into the arbitrage engine.

They should produce the project's internal `MatchOdds` representation.

Current OnWin parser imports:

```python
from models.match import MatchOdds
```

The intended normalized representation includes:

- bookmaker
- competition
- sport
- market
- home team
- away team
- home odds
- draw odds
- away odds
- start time
- collection timestamp

The arbitrage engine should operate on this normalized representation.

---

# 11. MATCH NORMALIZATION

The project has already implemented a team-name normalization layer.

Current component:

```text
engine/normalizer.py
```

This exists because different bookmakers may use:

- different spelling
- accents
- abbreviations
- punctuation
- alternate team names
- different language representations

Do not remove or bypass this layer.

The matching engine depends on normalization.

---

# 12. MATCH FINDING / MATCHING

Current components:

```text
engine/match_finder.py
engine/matcher.py
```

These are responsible for identifying that two bookmaker listings represent the same underlying sporting event.

They have already been modified/tested during the project.

Do not rewrite them without first running the existing tests and understanding their current behavior.

---

# 13. BEST ODDS AND ARBITRAGE ENGINE

The project contains the following conceptual stages:

```text
all bookmaker odds
        ↓
same-event matching
        ↓
best available outcome odds
        ↓
arbitrage calculation
        ↓
stake allocation
```

An arbitrage exists when the implied probabilities of the best available mutually exclusive outcomes sum to less than 1.

The project has already demonstrated this with real bookmaker data.

This is not a theoretical component that needs to be rebuilt.

---

# 14. COLLECTOR

Current central collector:

```text
collector.py
```

The collector coordinates bookmaker feeds and the engine.

There has been experimentation around importing bookmaker feeds only when the scanner runs so that server-side/frontend processes do not unnecessarily import Playwright/browser dependencies.

This is intentional architecture and should not be "cleaned up" without understanding the deployment implications.

---

# 15. ONWIN — CURRENT MAJOR WORKSTREAM

OnWin became the current focus because its live odds feed is available through internal ErisGaming endpoints.

This is the most important current acquisition task.

The key distinction is:

## INITIAL FEED

The initial feed is:

```text
get_main_line.erisgaming
```

This is the known working main-line feed.

It provides a large initial snapshot of betting data.

Previously the response was around 5 MB.

This feed was successfully parsed and used in the project's bookmaker/arbitrage pipeline.

It is **not** the update feed.

---

# 16. ONWIN INITIAL FEED — PROVEN

The project has already successfully intercepted:

```text
get_main_line.erisgaming
```

The feed produced the bookmaker's event/market/odds structure.

The project previously ran the resulting data against BetKanyon and found:

> **1 arbitrage opportunity**

This is one of the strongest proof-of-concept milestones in the entire project.

Therefore:

### DO NOT

- go searching again for the initial OnWin endpoint,
- replace the initial feed unnecessarily,
- assume OnWin acquisition is completely unsolved,
- rebuild the matching/arbitrage engine.

The initial feed works.

The problem is performance and live updating.

---

# 17. WHY THE UPDATE FEED WAS INVESTIGATED

The initial `get_main_line.erisgaming` response is very large.

Approximately:

```text
~5 MB
```

If the application repeatedly downloads the entire main-line snapshot simply to discover a small odds change, this is inefficient.

Therefore the project investigated whether OnWin exposes a separate update/delta mechanism.

The goal is:

```text
Initial snapshot
      ↓
Build local state
      ↓
Receive small/frequent updates
      ↓
Modify only affected event/market/outcome
      ↓
Recalculate affected opportunities
```

This should dramatically reduce unnecessary processing.

---

# 18. ONWIN UPDATE ENDPOINT — FOUND AND PROVEN

The project eventually identified and intercepted:

```text
find_event_snapshots.erisgaming
```

This endpoint is extremely important.

It is returning repeated JSON responses containing event snapshots/changes.

The test program:

```text
test_onwin_event_snapshots.py
```

was created specifically to observe this behavior.

---

# 19. ONWIN UPDATE TEST — IMPORTANT RESULT

The latest successful test proved that the endpoint is changing over time.

Example:

```text
VERSION: [117229]
EVENTS IN RESPONSE: 6
BASELINE RESPONSE CAPTURED.
```

Then:

```text
VERSION: [117414]
EVENTS IN RESPONSE: 6

CHANGES DETECTED:
New events: 0
Removed events: 0
Changed events: 1
Changed outcomes: 5
```

Then further versions:

```text
[117571]
[117726]
[117894]
[118041]
```

were observed.

The same event repeatedly changed odds.

Example event:

```text
019fafc4-c307-7b6a-888f-f230e8d42ea0
```

Observed changes included:

```text
throw_in_1x2
p1: 2.07 → 2.08
p2: 1.85 → 1.84
```

and:

```text
throw_in_ou
over: 1.70 → 1.85
under: 2.03 → 1.85
```

and:

```text
throw_in_dc
p1_draw: 1.85 → 1.86
```

The next update reversed some of those changes.

Therefore:

> **The project has experimentally proven that `find_event_snapshots.erisgaming` is delivering changing bookmaker state over time.**

We are no longer merely investigating whether an update feed exists.

The engineering task is now to integrate it.

---

# 20. ONWIN UPDATE FEED CURRENT BEHAVIOR

The current test observes responses approximately every several seconds.

The responses were approximately:

```text
480–482 KB
```

in the observed test.

This is substantially smaller than the original ~5 MB main-line snapshot.

The test currently compares successive responses and reports:

- new events
- removed events
- changed events
- changed outcomes
- old odds
- new odds

This is already enough to establish the delta concept.

---

# 21. IMPORTANT ONWIN DATA INSIGHT

The update feed is not necessarily a tiny one-record WebSocket message.

It may still return a multi-event snapshot containing a limited set of events.

Therefore Cursor should **not assume** the endpoint is a classic WebSocket/delta API.

Instead, the implementation should treat it as:

```text
repeated event snapshot/update payloads
```

and efficiently reconcile them against local state.

---

# 22. CURRENT ONWIN PARSER

Current file:

```text
parsers/onwin/parser.py
```

The parser currently targets live football 1X2 markets.

Important constant:

```python
FOOTBALL_SPORT_ID = "d6934640-cf1d-11e9-864b-0242ac13000a"
```

The parser:

1. reads the JSON payload,
2. locates football by sport ID,
3. walks categories,
4. walks tournaments,
5. walks events,
6. filters to:

```text
status == "in_progress"
```

7. extracts participants,
8. enters:

```text
normal_time--0
```

9. selects:

```text
score_1x2--nil
```

10. extracts:

```text
outcome::p1
outcome::draw
outcome::p2
```

11. creates `MatchOdds`.

This parser is specifically a **main-line football 1X2 parser**.

It should not automatically be assumed to be the final update-state reconciler.

---

# 23. CURRENT ONWIN BROWSER

Current file:

```text
parsers/onwin/browser.py
```

Current architecture:

```python
from utils.zenrows_persistent import ZenRowsSession

class OnwinBrowser:
    def __init__(self):
        self.session = ZenRowsSession()

    def page(self):
        return self.session.get_page()
```

This means OnWin uses the persistent ZenRows browser infrastructure.

---

# 24. CURRENT ONWIN FEED

Current file:

```text
parsers/onwin/feed.py
```

The feed currently captures:

```text
get_main_line.erisgaming
```

and can run the raw response through:

```text
OnWinParser
```

The feed also contains diagnostic network logging for fragments such as:

```text
api-onwin
erisgaming
update
updates
diff
stream
subscribe
subscription
/rpc/
```

This diagnostic investigation helped locate the update behavior.

The feed has methods conceptually equivalent to:

```text
fetch()
collect_once()
get_match_odds()
close()
```

---

# 25. ONWIN INTERCEPTOR / SESSION

The OnWin parser package currently contains additional infrastructure including:

```text
parsers/onwin/interceptor.py
parsers/onwin/session.py
```

Cursor must inspect these before creating replacements.

Do not assume they are redundant simply because some test files are experimental.

---

# 26. CURRENT TEST / EXPERIMENT FILES

The repository currently contains multiple OnWin tests and experiments, including:

```text
test_onwin.py
test_onwin_api.py
test_onwin_event_snapshots.py
test_onwin_parser.py
test_onwin_snapshot.py
test_onwin_updates.py
tests/test_onwin_matching.py
```

There are also historical/experimental tests such as:

```text
tests/test_onwinnnn_parser.py
```

These should be reviewed before deletion.

Some are experiments rather than production tests.

Do not delete them blindly.

---

# 27. ONWIN NETWORK RECONNAISSANCE FILES

Important investigation files include:

```text
experiments/betkanyon/network/onwin_catalog1.txt
experiments/betkanyon/network/onwin_live_updates.txt
experiments/betkanyon/network/onwin_translations.txt
```

These contain network/reconnaissance information and should be treated as historical evidence.

Do not discard them simply because they are not imported by Python.

---

# 28. DECRYPTION EXPERIMENTS

The project also contains:

```text
experiments/decrypt/
```

including:

```text
decrypted_output.json
encrypted_payload.txt
```

These experiments were part of trying to understand bookmaker/network payloads.

They are historical investigation material.

Do not automatically delete them.

---

# 29. GENERATED OUTPUT FILES

Current OnWin investigation output includes:

```text
output/onwin_main_line.json
output/onwin_event_snapshots.json
output/onwin_update_analysis.json
```

These are generated evidence/output files.

They may be large and should generally not be treated as normal source code.

Check `.gitignore` policy before deciding whether generated output should be committed.

The important information is the behavior they demonstrate, not necessarily keeping every generated payload in Git.

---

# 30. ZENROWS PERSISTENT SESSION

Current file:

```text
utils/zenrows_persistent.py
```

This is important infrastructure.

Its purpose is to maintain a persistent browser/session instead of repeatedly paying the initialization overhead of creating a new browser session.

Performance work should build on this rather than bypassing it.

---

# 31. CURRENT PROJECT STATUS

## ✅ COMPLETED / PROVEN

The following are considered established milestones:

- Python project environment works.
- Virtual environment setup works.
- Playwright/browser automation is working.
- ZenRows browser access works.
- Persistent ZenRows browser infrastructure exists.
- Network request/response interception works.
- Orbit data acquisition was proven.
- BetKanyon data acquisition was proven.
- Cross-bookmaker matching was proven.
- Arbitrage detection was proven with real bookmaker data.
- Stake-calculation architecture exists.
- Team normalization exists.
- Match matching exists.
- Best-odds selection exists.
- OnWin main-line endpoint was found.
- `get_main_line.erisgaming` was successfully captured.
- OnWin main-line data can be parsed.
- OnWin odds were successfully compared against another bookmaker.
- An actual arbitrage opportunity was found from real data.
- OnWin update endpoint investigation was successful.
- `find_event_snapshots.erisgaming` was identified.
- Repeated update responses were captured.
- Version changes were observed.
- Event-level changes were detected.
- Outcome-level odds changes were detected.

---

# 32. 🟡 PARTIALLY IMPLEMENTED

These areas exist but are not necessarily production-complete:

- OnWin update-state reconciliation.
- Efficient local odds state.
- Triggering arbitrage recalculation only for affected matches.
- Production-grade continuous collector loop.
- Final performance optimization.
- Frontend/backend integration.
- Dynamic live opportunity feed to the frontend.
- Robust handling of bookmaker event lifecycle changes.
- Production error recovery/reconnection.
- Final deployment architecture.

---

# 33. 🔴 NOT YET DONE

The immediate engineering goal is:

```text
get_main_line.erisgaming
        ↓
initial local state
        ↓
find_event_snapshots.erisgaming
        ↓
continuous updates
        ↓
update local state
        ↓
convert affected state to MatchOdds
        ↓
rerun matching/best-odds/arbitrage logic
        ↓
update opportunities
```

This should happen without downloading/reprocessing the full 5 MB initial feed for every odds change.

---

# 34. PERFORMANCE GOAL

The scanner should eventually behave like:

```text
START
  ↓
Fetch initial snapshot once
  ↓
Parse/cache state
  ↓
Keep browser/session alive
  ↓
Observe update feed
  ↓
Detect affected events/outcomes
  ↓
Patch local state
  ↓
Recalculate only affected opportunities
  ↓
Repeat
```

Not:

```text
wait
 ↓
download 5 MB
 ↓
parse everything
 ↓
match everything
 ↓
calculate everything
 ↓
wait
 ↓
repeat
```

The second architecture wastes bandwidth, CPU, memory and latency.

---

# 35. EVENT ID WARNING

During investigation it appeared that OnWin can update/change event IDs.

Therefore the update architecture must not blindly assume:

```text
event_id = permanent identity
```

Event identity needs to be treated carefully.

The system should distinguish between:

- bookmaker event identifier
- participant identity
- competition
- start time
- market identity
- outcome identity

If an event ID changes while the underlying sporting event remains the same, the system needs a reconciliation strategy.

Do not invent such a strategy without first inspecting actual update payloads and existing data.

---

# 36. MARKET SCOPE

The current OnWin parser focuses on:

```text
normal_time--0
```

and:

```text
score_1x2--nil
```

for football 1X2.

However, the update feed has demonstrated other markets such as throw-ins.

That does **not** automatically mean the first production version must support every market.

The current arbitrage MVP should remain focused.

First get:

```text
football
1X2
live odds
```

working reliably and quickly.

Broader market support can come later.

---

# 37. IMPORTANT DO-NOT-REWORK RULES

Cursor must not:

### ❌ Rebuild the arbitrage detector

unless tests demonstrate a real bug.

### ❌ Replace the normalizer

without understanding current matching behavior.

### ❌ Replace the matcher

without proving current matching is incorrect.

### ❌ Search again for `get_main_line.erisgaming`

It has already been found and successfully captured.

### ❌ Assume `find_event_snapshots.erisgaming` is undiscovered

It has already been found and experimentally proven.

### ❌ Rebuild the frontend

The frontend already exists.

### ❌ Delete experiments simply because they are messy

Some experiments contain the reasoning/evidence behind the current architecture.

### ❌ Optimize before measuring

Record baseline latency, CPU, memory and update-processing time first.

### ❌ Convert everything to async just for style

The browser/Playwright architecture has real constraints. Change execution models only when there is a measured benefit.

---

# 38. CURSOR OPERATING RULES

Before modifying code:

1. Inspect the repository.
2. Read this document.
3. Identify existing implementations.
4. Run existing relevant tests.
5. Explain what is already working.
6. Identify the smallest change required.
7. Make the change.
8. Run targeted tests.
9. Run broader tests if appropriate.
10. Report exactly what changed.

Cursor should prefer:

```text
small verified changes
```

over:

```text
large architectural rewrites
```

---

# 39. CURSOR MUST VERIFY BEFORE DELETING

Before deleting any file, Cursor must determine whether it is:

- production code,
- a regression test,
- a reconnaissance experiment,
- captured evidence,
- generated output,
- obsolete duplicate,
- accidental file.

If uncertain, leave it in place and report it.

---

# 40. CURRENT FIRST ENGINEERING TASK

The first real implementation task after handoff should be:

## Build the OnWin initial-state + update-state pipeline.

The desired design is approximately:

```text
OnWinBrowser / persistent session
              │
              ├── initial feed
              │     get_main_line.erisgaming
              │
              └── update feed
                    find_event_snapshots.erisgaming
                           │
                           ↓
                    local event state
                           │
                           ↓
                    changed event detection
                           │
                           ↓
                    normalized MatchOdds
                           │
                           ↓
                    arbitrage engine
```

The update processor should not necessarily reparse every event every time.

Where safe, use the information in the update payload to identify affected state.

---

# 41. FIRST CURSOR PROMPT

Use this as the first implementation prompt in Cursor:

> Read `HANDOFF.md` completely before changing anything.
>
> We are continuing an existing arbitrage scanner project. Do not rebuild or redesign completed components.
>
> First inspect the repository and report:
>
> 1. the current directory structure,
> 2. the current bookmaker/feed implementations,
> 3. the current arbitrage engine,
> 4. the current OnWin implementation,
> 5. the existing tests,
> 6. the current relationship between `get_main_line.erisgaming` and `find_event_snapshots.erisgaming`,
> 7. which parts of the handoff are already implemented in code,
> 8. which parts remain unfinished.
>
> Do not modify any files yet.
>
> Then explain a minimal implementation plan for integrating the OnWin initial snapshot with the continuous update feed.
>
> Important:
> - `get_main_line.erisgaming` is the known working initial feed.
> - `find_event_snapshots.erisgaming` has already been experimentally proven to provide changing event/outcome data.
> - The goal is to maintain local state and patch it from updates rather than repeatedly downloading and fully processing the ~5 MB initial feed.
> - Do not replace the existing normalizer, matcher, arbitrage detector, or frontend.
> - Do not delete experiments or tests without first explaining why they are obsolete.
>
> Stop after the analysis and plan. Do not implement yet.

---

# 42. SECOND CURSOR PHASE

Only after reviewing Cursor's analysis should implementation begin.

The implementation should likely be divided into small stages:

### Stage 1

Create/verify an OnWin state representation.

### Stage 2

Capture the initial main-line feed into that state.

### Stage 3

Capture the update feed continuously.

### Stage 4

Determine exactly how updates map onto local state.

### Stage 5

Patch state efficiently.

### Stage 6

Convert affected events into `MatchOdds`.

### Stage 7

Run matching/arbitrage calculations only where necessary.

### Stage 8

Measure performance.

### Stage 9

Stress test.

### Stage 10

Connect the live result to the existing frontend/backend architecture.

Do not combine all ten stages into one giant rewrite.

---

# 43. TESTING PHILOSOPHY

The project is not finished merely because the program runs.

A production-ready scanner must demonstrate:

- feed reliability,
- correct event matching,
- correct odds updates,
- no stale odds,
- correct arbitrage calculations,
- correct stake calculations,
- acceptable update latency,
- reconnection behavior,
- browser/session stability,
- memory stability,
- frontend consistency.

Tests should therefore include both:

```text
unit tests
```

and:

```text
real-feed integration tests
```

where appropriate.

---

# 44. PERFORMANCE MEASUREMENTS TO ADD

Eventually measure:

```text
initial feed download time
initial parsing time
update arrival interval
update processing time
state patch time
MatchOdds conversion time
match-finder time
arbitrage calculation time
total update-to-opportunity latency
memory usage
CPU usage
```

The most important live metric is:

```text
odds change received
        ↓
opportunity updated
```

The elapsed time between those two events.

---

# 45. FRONTEND END STATE

The frontend should eventually display real live opportunities.

It should not contain hardcoded arbitrage opportunities as the source of truth.

A likely final flow is:

```text
Bookmakers
    ↓
Collector
    ↓
Arbitrage engine
    ↓
Backend/API
    ↓
Wounded Lion Energy frontend
```

Stub data may be used for UI development/testing, but the architecture should make it possible to replace the stub source with the live collector.

---

# 46. SECURITY / CREDENTIALS

Never commit:

- API keys
- ZenRows credentials
- bookmaker credentials
- session cookies
- authentication tokens
- private client credentials

Use environment variables or appropriate local configuration.

Generated network captures should also be reviewed before committing if they may contain credentials or private session information.

---

# 47. GIT WORKFLOW

A Git checkpoint has just been created before this handoff.

Going forward:

```text
small change
   ↓
test
   ↓
git diff
   ↓
commit
```

Avoid allowing large unrelated changes to accumulate.

Before major refactors:

```text
git status
git diff
```

and create a checkpoint.

---

# 48. DEVELOPER EXPERIENCE

The developer is still learning Python/programming and needs explanations rather than opaque changes.

Cursor should therefore explain:

- what it is changing,
- why it is changing it,
- what file it is changing,
- what the code does,
- how the change affects the pipeline,
- how it was tested.

Do not respond with unexplained large code dumps.

---

# 49. CHATGPT / CURSOR WORKFLOW

The intended workflow is:

```text
Developer
    ↓
asks ChatGPT/Chatty for analysis
    ↓
ChatGPT explains / designs / reviews prompt
    ↓
Developer gives focused prompt to Cursor
    ↓
Cursor edits code
    ↓
Developer runs/tests
    ↓
Developer brings result back to ChatGPT
    ↓
ChatGPT critically analyzes result
    ↓
repeat
```

Cursor is the implementation environment.

ChatGPT is the second set of eyes.

This is deliberate.

---

# 50. CURRENT PROJECT POSITION — ONE SENTENCE

The project has already proven the fundamental arbitrage concept with real bookmaker data; the current engineering priority is to turn OnWin's proven initial feed plus its proven `find_event_snapshots.erisgaming` update feed into a fast, persistent, reliable live state pipeline without rebuilding the working arbitrage engine.

---

# 51. FINAL INSTRUCTION TO CURSOR

**Do not confuse unfinished with unproven.**

Many things in this project are unfinished because they require production integration, not because the underlying concept failed.

The following are already proven:

```text
bookmaker acquisition
        +
normalization
        +
event matching
        +
best odds
        +
arbitrage detection
        +
stake calculation
        +
OnWin initial feed
        +
OnWin update feed discovery
```

The remaining work is primarily:

```text
integration
+
state management
+
performance
+
reliability
+
productionization
+
frontend connection
```

Build forward from what exists.
Do not start over.
