"""
One-shot PREMATCH forensic cycle.

Does not change pagination, matching, endpoints, or production polling.
Run: python -m kenyan.diagnostics.prematch_cycle
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from kenyan.api_router import serialize_opportunities
from kenyan.diagnostics.export import (
    canonical_fixture_key,
    classify_betika_event,
    classify_sportpesa_game,
    classify_vzip_event,
    matchodds_record,
    sanitize_url,
)
from kenyan.engine import (
    KenyanArbitrageEngine,
    _is_stale,
    _is_three_way,
    _is_two_way,
)
from kenyan.http_utils import fetch_json as original_fetch_json
from kenyan.http_utils import looks_like_bot_challenge
from kenyan.match_snapshot import merge_match_records, match_identity, visible_matches
from kenyan.markets import kenyan_market_key, sport_key
from kenyan.matcher import (
    KenyanEventMatcher,
    KenyanMatchFinder,
    dedupe_same_book_listings,
)
from kenyan.opportunity_store import KenyanOpportunityStore
from kenyan.workers import bet22, betika, onexbet, sportpesa
from kenyan.workers.vzip_pages import CHAMP_EVENT_CAP, build_champ_events_url, with_query

OUTPUT_ROOT = Path(__file__).resolve().parent / "runs"


def _git_rev() -> dict:
    def run(args):
        try:
            result = subprocess.run(
                args,
                cwd=str(Path(__file__).resolve().parents[2]),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            return None, str(exc)
        return (result.stdout or "").strip(), (result.stderr or "").strip()

    head, err = run(["git", "rev-parse", "HEAD"])
    branch, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    dirty, _ = run(["git", "status", "--porcelain"])
    return {
        "head": head or None,
        "branch": branch or None,
        "dirty": bool(dirty),
        "error": err or None,
    }


class FetchRecorder:
    def __init__(self):
        self.records = []

    def wrap(self, original):
        recorder = self

        def wrapped(url, *args, **kwargs):
            result = original(url, *args, **kwargs)
            compact = _compact_body(url, result)
            recorder.records.append(
                {
                    "url": sanitize_url(url),
                    "ok": result.ok,
                    "status_code": result.status_code,
                    "content_type": result.content_type,
                    "response_size_bytes": result.response_size_bytes,
                    "elapsed_seconds": result.elapsed_seconds,
                    "error": result.error,
                    "looks_like_json": result.looks_like_json,
                    "bot_challenge": looks_like_bot_challenge(result),
                    "compact": compact,
                }
            )
            return result

        return wrapped


def _compact_body(url, result):
    body = result.json_body
    path = urlsplit(url).path
    if not result.looks_like_json:
        preview = (result.text_body or "")[:180]
        return {
            "kind": "non_json",
            "preview": preview,
        }
    if "GetChampsZip" in path and isinstance(body, dict):
        rows = body.get("Value") or []
        champs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            champs.append(
                {
                    "LI": row.get("LI"),
                    "GC": row.get("GC"),
                    "T": row.get("T"),
                    "L": row.get("L") or row.get("LN"),
                    "SI": row.get("SI"),
                }
            )
        return {"kind": "champs", "count": len(champs), "champs": champs}
    if "Get1x2_VZip" in path:
        events = []
        if isinstance(body, dict):
            events = body.get("Value") or []
        elif isinstance(body, list):
            events = body
        compact_events = []
        for event in events if isinstance(events, list) else []:
            if not isinstance(event, dict):
                continue
            if "eventGroups" in event:
                selections = 0
                for group in event.get("eventGroups") or []:
                    if isinstance(group, dict):
                        selections += len(group.get("events") or [])
                compact_events.append(
                    {
                        "I": event.get("id"),
                        "SI": (event.get("sport") or {}).get("id"),
                        "O1": (event.get("opponent1") or {}).get("fullName"),
                        "O2": (event.get("opponent2") or {}).get("fullName"),
                        "L": (event.get("liga") or {}).get("name"),
                        "S": event.get("startTs"),
                        "markets": len(event.get("eventGroups") or []),
                        "selections": selections,
                    }
                )
            else:
                flat = event.get("E") or []
                compact_events.append(
                    {
                        "I": event.get("I"),
                        "SI": event.get("SI"),
                        "O1": event.get("O1"),
                        "O2": event.get("O2"),
                        "L": event.get("L"),
                        "S": event.get("S"),
                        "markets": len({row.get("G") for row in flat if isinstance(row, dict)}),
                        "selections": len(flat) if isinstance(flat, list) else 0,
                    }
                )
        return {"kind": "vzip_events", "count": len(compact_events), "events": compact_events}
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        rows = []
        for row in body["data"]:
            if not isinstance(row, dict):
                continue
            odds = row.get("odds") if isinstance(row.get("odds"), list) else []
            selections = 0
            for market in odds:
                if isinstance(market, dict) and isinstance(market.get("odds"), list):
                    selections += len(market["odds"])
            rows.append(
                {
                    "match_id": row.get("match_id") or row.get("game_id"),
                    "sport_id": row.get("sport_id"),
                    "sport_name": row.get("sport_name"),
                    "home_team": row.get("home_team"),
                    "away_team": row.get("away_team"),
                    "start_time": row.get("start_time"),
                    "markets": len(odds),
                    "selections": selections,
                }
            )
        meta = body.get("meta") or {}
        return {
            "kind": "betika",
            "count": len(rows),
            "meta_total": meta.get("total"),
            "events": rows,
        }
    if isinstance(body, list):
        games = []
        for game in body:
            if not isinstance(game, dict):
                continue
            markets = game.get("markets") if isinstance(game.get("markets"), list) else []
            selections = 0
            for market in markets:
                if isinstance(market, dict) and isinstance(market.get("selections"), list):
                    selections += len(market["selections"])
            games.append(
                {
                    "id": game.get("id") or game.get("externalId"),
                    "SI": (game.get("sport") or {}).get("id") if isinstance(game.get("sport"), dict) else None,
                    "competitors": [
                        (c.get("name") if isinstance(c, dict) else None)
                        for c in (game.get("competitors") or [])
                    ],
                    "dateTimestamp": game.get("dateTimestamp"),
                    "markets": len(markets),
                    "selections": selections,
                }
            )
        return {"kind": "sportpesa_games", "count": len(games), "events": games}
    return {"kind": "other_json"}


def _patch_fetch(recorder):
    wrapped = recorder.wrap(original_fetch_json)
    targets = (
        "kenyan.http_utils",
        "kenyan.workers.vzip_pages",
        "kenyan.workers.betika",
        "kenyan.workers.sportpesa",
        "kenyan.workers.onexbet",
        "kenyan.workers.bet22",
    )
    restored = []
    for name in targets:
        module = sys.modules.get(name) or __import__(name, fromlist=["fetch_json"])
        if hasattr(module, "fetch_json"):
            restored.append((module, module.fetch_json))
            module.fetch_json = wrapped
    return restored, wrapped


def _unpatch_fetch(restored):
    for module, original in restored:
        module.fetch_json = original


def _diagnostics_dict(diagnostics) -> dict:
    if diagnostics is None:
        return {}
    return {
        "endpoint_status": diagnostics.endpoint_status,
        "http_status_code": diagnostics.http_status_code,
        "content_type": diagnostics.content_type,
        "response_size_bytes": diagnostics.response_size_bytes,
        "events_discovered": diagnostics.events_discovered,
        "football_events": diagnostics.football_events,
        "one_x_two_events": diagnostics.one_x_two_events,
        "valid_normalized_events": diagnostics.valid_normalized_events,
        "parser_error": diagnostics.parser_error,
        "pages_fetched": diagnostics.pages_fetched,
        "page_cap_hit": diagnostics.page_cap_hit,
        "snapshot_complete": diagnostics.snapshot_complete,
        "catalogue_status": diagnostics.catalogue_status,
        "source_total": diagnostics.source_total,
        "unique_event_ids": diagnostics.unique_event_ids,
        "duplicate_events": diagnostics.duplicate_events,
        "terminal_reason": diagnostics.terminal_reason,
        "capped_partitions": getattr(diagnostics, "capped_partitions", 0),
        "elapsed_seconds": diagnostics.elapsed_seconds,
    }


def _poll_bookmakers():
    return [
        ("SportPesa", sportpesa._poll_prematch),
        ("Betika", lambda: betika._poll(betika.PREMATCH_URLS, "PREMATCH")),
        ("1xBet", lambda: onexbet._poll((onexbet.PREMATCH_URL,) + onexbet.PREMATCH_EXTRA_URLS, "PREMATCH")),
        ("22Bet", lambda: bet22._poll((bet22.PREMATCH_URL,) + bet22.PREMATCH_EXTRA_URLS, "PREMATCH")),
    ]


def _sport_counts(matches):
    counts = Counter()
    for match in matches:
        counts[sport_key(match) or "unknown"] += 1
    return dict(counts)


def _http_stats(records, bookmaker):
    if bookmaker == "SportPesa":
        hosts = ("sportpesa",)
    elif bookmaker == "Betika":
        hosts = ("betika",)
    elif bookmaker == "1xBet":
        hosts = ("1xbet",)
    else:
        hosts = ("22bet",)
    subset = [row for row in records if any(host in (row["url"] or "") for host in hosts)]
    by_status = Counter()
    exceptions = 0
    json_ok = 0
    html = 0
    challenge = 0
    bytes_total = 0
    for row in subset:
        if row["status_code"] is None:
            exceptions += 1
        else:
            by_status[str(row["status_code"])] += 1
        bytes_total += row["response_size_bytes"] or 0
        if row["ok"] and row["looks_like_json"]:
            json_ok += 1
        if not row["looks_like_json"]:
            html += 1
        if row["bot_challenge"]:
            challenge += 1
    return {
        "requests_attempted": len(subset),
        "requests_successful_json": json_ok,
        "http_status_counts": dict(by_status),
        "exceptions": exceptions,
        "non_json_responses": html,
        "bot_challenge_responses": challenge,
        "bytes_total": bytes_total,
    }


def _raw_from_records(records, bookmaker):
    stats = _http_stats(records, bookmaker)
    raw_events = []
    unique_ids = []
    seen = set()
    dups = 0
    markets = 0
    selections = 0
    source_total = None
    partitions = []
    for row in records:
        if bookmaker == "SportPesa" and "sportpesa" not in row["url"]:
            continue
        if bookmaker == "Betika" and "betika" not in row["url"]:
            continue
        if bookmaker == "1xBet" and "1xbet" not in row["url"]:
            continue
        if bookmaker == "22Bet" and "22bet" not in row["url"]:
            continue
        compact = row.get("compact") or {}
        kind = compact.get("kind")
        if kind == "champs":
            gc = sum(int(champ.get("GC") or 0) for champ in compact.get("champs") or [])
            source_total = (source_total or 0) + gc
            partitions.append(
                {
                    "url": row["url"],
                    "kind": "champs_list",
                    "http_status": row["status_code"],
                    "ok": row["ok"],
                    "advertised_gc_sum": gc,
                    "champ_count": compact.get("count"),
                    "response_type": row["content_type"],
                    "bytes": row["response_size_bytes"],
                }
            )
            continue
        events = compact.get("events") or []
        if kind in {"vzip_events", "betika", "sportpesa_games"}:
            if kind == "betika" and compact.get("meta_total") is not None:
                try:
                    source_total = int(compact["meta_total"])
                except (TypeError, ValueError):
                    pass
            returned = len(events)
            ids = []
            for event in events:
                event_id = event.get("I") or event.get("match_id") or event.get("id")
                ids.append(event_id)
                markets += event.get("markets") or 0
                selections += event.get("selections") or 0
                raw_events.append(event)
                if event_id in seen:
                    dups += 1
                else:
                    seen.add(event_id)
                    unique_ids.append(event_id)
            advertised = None
            query = parse_qs(urlsplit(row["url"]).query)
            champ_id = (query.get("champs") or [None])[0]
            partitions.append(
                {
                    "url": row["url"],
                    "kind": kind,
                    "http_status": row["status_code"],
                    "ok": row["ok"],
                    "response_type": row["content_type"],
                    "bytes": row["response_size_bytes"],
                    "returned_events": returned,
                    "unique_ids": len({event_id for event_id in ids if event_id is not None}),
                    "champ_id": champ_id,
                    "requested_count": (query.get("count") or [None])[0],
                    "bot_challenge": row["bot_challenge"],
                    "error": row["error"],
                }
            )
        elif compact.get("kind") == "non_json":
            partitions.append(
                {
                    "url": row["url"],
                    "kind": "non_json",
                    "http_status": row["status_code"],
                    "ok": row["ok"],
                    "response_type": row["content_type"],
                    "bytes": row["response_size_bytes"],
                    "bot_challenge": row["bot_challenge"],
                    "error": row["error"],
                    "preview": compact.get("preview"),
                }
            )
    stats.update(
        {
            "raw_event_records": len(raw_events),
            "unique_source_event_ids": len(seen),
            "duplicate_source_event_ids": dups,
            "raw_markets_seen": markets,
            "raw_selections_seen": selections,
            "advertised_source_total": source_total,
            "pages_or_partitions": len(partitions),
        }
    )
    return stats, raw_events, partitions


def _reject_unparsed(bookmaker, raw_events, matches):
    parsed_ids = {getattr(match, "event_id", None) for match in matches}
    rejected = []
    reasons = Counter()
    for event in raw_events:
        event_id = event.get("I") or event.get("match_id") or event.get("id")
        if event_id is not None and str(event_id) in parsed_ids:
            continue
        if bookmaker in {"1xBet", "22Bet"}:
            reason = classify_vzip_event(
                {
                    "SI": event.get("SI"),
                    "O1": event.get("O1"),
                    "O2": event.get("O2"),
                    "S": event.get("S"),
                    "I": event.get("I"),
                }
            )
        elif bookmaker == "Betika":
            reason = classify_betika_event(event)
        else:
            reason = classify_sportpesa_game(
                {
                    "sport": {"id": event.get("SI")},
                    "competitors": [{"name": name} for name in (event.get("competitors") or [])],
                    "dateTimestamp": event.get("dateTimestamp"),
                    "id": event.get("id"),
                }
            )
        reasons[reason] += 1
        rejected.append(
            {
                "bookmaker": bookmaker,
                "stage": "parse",
                "reason": reason,
                "source_event_id": None if event_id is None else str(event_id),
                "home_team": event.get("O1") or event.get("home_team") or (event.get("competitors") or [None])[0],
                "away_team": event.get("O2") or event.get("away_team")
                or (event.get("competitors") or [None, None])[1],
                "sport_id": event.get("SI") or event.get("sport_id") or event.get("sport_name"),
                "start": event.get("S") or event.get("start_time") or event.get("dateTimestamp"),
            }
        )
    return rejected, dict(reasons)


def _matching_report(matches):
    matcher = KenyanEventMatcher()
    finder = KenyanMatchFinder()
    events = finder.find(matches)
    pair_counts = Counter()
    examples = defaultdict(list)
    original = KenyanEventMatcher.evaluate

    def counted(self, match1, match2):
        decision, reason, level = original(self, match1, match2)
        if getattr(match1, "bookmaker", None) != getattr(match2, "bookmaker", None):
            pair_counts[(decision, reason, level)] += 1
            bucket = examples[(decision, reason)]
            if len(bucket) < 8:
                bucket.append(
                    {
                        "left": {
                            "bookmaker": match1.bookmaker,
                            "sport": match1.sport,
                            "home": match1.home_team,
                            "away": match1.away_team,
                            "canonical_home": matcher.canonical_team(match1.home_team),
                            "canonical_away": matcher.canonical_team(match1.away_team),
                            "start": match1.start_time.isoformat() if match1.start_time else None,
                            "market": match1.market,
                            "line": match1.line,
                            "period": match1.period,
                            "event_id": match1.event_id,
                            "market_identity": list(kenyan_market_key(match1)),
                        },
                        "right": {
                            "bookmaker": match2.bookmaker,
                            "sport": match2.sport,
                            "home": match2.home_team,
                            "away": match2.away_team,
                            "canonical_home": matcher.canonical_team(match2.home_team),
                            "canonical_away": matcher.canonical_team(match2.away_team),
                            "start": match2.start_time.isoformat() if match2.start_time else None,
                            "market": match2.market,
                            "line": match2.line,
                            "period": match2.period,
                            "event_id": match2.event_id,
                            "market_identity": list(kenyan_market_key(match2)),
                        },
                        "decision": decision,
                        "reason": reason,
                        "level": level,
                        "code_path": "kenyan.matcher.KenyanEventMatcher.evaluate",
                    }
                )
        return decision, reason, level

    KenyanEventMatcher.evaluate = counted
    try:
        finder.find(matches)
    finally:
        KenyanEventMatcher.evaluate = original

    fixture_books = defaultdict(set)
    market_books = defaultdict(set)
    for match in matches:
        fixture = canonical_fixture_key(match)
        fixture_books[fixture["key"]].add(match.bookmaker)
        market_books[fixture["key"] + "|" + str(kenyan_market_key(match))].add(match.bookmaker)

    cluster_sizes = Counter()
    for event in events:
        books = {row.bookmaker for row in event.matches}
        cluster_sizes[len(books)] += 1

    return {
        "matched_clusters": len(events),
        "clusters_by_book_count": {str(key): value for key, value in sorted(cluster_sizes.items())},
        "unique_canonical_fixtures": len(fixture_books),
        "fixtures_with_two_or_more_books": sum(1 for books in fixture_books.values() if len(books) >= 2),
        "fixtures_with_three_or_more_books": sum(1 for books in fixture_books.values() if len(books) >= 3),
        "market_rows_with_two_or_more_books": sum(1 for books in market_books.values() if len(books) >= 2),
        "pair_evaluate_counts": {
            f"{decision}:{reason}:{level or '-'}": count
            for (decision, reason, level), count in sorted(pair_counts.items())
        },
        "examples": {f"{decision}:{reason}": rows for (decision, reason), rows in examples.items()},
        "counting_rules": {
            "canonical_fixture": "sport|canonical_home|canonical_away|start_minute; league equality is not required",
            "market_identity": "kenyan.markets.kenyan_market_key = (sport, market_type, period, line, family, outcome_arity)",
            "pair_evaluate": "KenyanEventMatcher.evaluate on comparable start-time pairs inside each market bucket",
            "swapped_home_away": "HOME_AWAY_ORDER_MISMATCH is a reject, not a match",
            "categories_not_exclusive": "A fixture may match on 1X2 and fail on a different Over/Under line",
        },
    }, events


def _probe_remainder(records, bookmaker):
    """Minimal confirmation of the 50-event window. Does not change workers."""
    if bookmaker not in {"1xBet", "22Bet"}:
        return []
    host = "1xbet" if bookmaker == "1xBet" else "22bet"
    champs = []
    champ_events = {}
    for row in records:
        if host not in row["url"]:
            continue
        compact = row.get("compact") or {}
        if compact.get("kind") == "champs":
            champs.extend(compact.get("champs") or [])
        if compact.get("kind") == "vzip_events":
            query = parse_qs(urlsplit(row["url"]).query)
            champ_id = (query.get("champs") or [None])[0]
            if champ_id:
                champ_events[champ_id] = compact
    probes = []
    capped = [
        champ
        for champ in champs
        if int(champ.get("GC") or 0) > CHAMP_EVENT_CAP
        and str(champ.get("LI")) in champ_events
    ]
    if not capped:
        return probes
    sample = capped[0]
    champ_id = sample.get("LI")
    compact = champ_events[str(champ_id)]
    returned_ids = [event.get("I") for event in compact.get("events") or [] if event.get("I") is not None]
    if bookmaker == "1xBet":
        base = onexbet.PREMATCH_URL
    else:
        base = bet22.PREMATCH_URL
    event_url = build_champ_events_url(base, champ_id)
    larger = with_query(event_url, count=400)
    after_url = event_url
    if returned_ids:
        after_url = with_query(event_url, after=returned_ids[-1])
    for label, url in (("count_400", larger), ("after_last_id", after_url)):
        result = original_fetch_json(url)
        events = []
        if isinstance(result.json_body, dict):
            events = result.json_body.get("Value") or []
        probes.append(
            {
                "hypothesis": "Get1x2_VZip returns at most 50 events per championship; continuation params are rejected",
                "bookmaker": bookmaker,
                "champ_id": champ_id,
                "advertised_gc": sample.get("GC"),
                "champ_type": sample.get("T"),
                "walk_returned": compact.get("count"),
                "probe": label,
                "url": sanitize_url(url),
                "http_status": result.status_code,
                "ok": result.ok,
                "content_type": result.content_type,
                "returned_events": len(events) if isinstance(events, list) else None,
                "error": result.error,
                "bot_challenge": looks_like_bot_challenge(result),
            }
        )
    return probes


def run_cycle(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    recorder = FetchRecorder()
    restored, _wrapped = _patch_fetch(recorder)
    book_results = {}
    all_matches = []
    all_rejects = []
    try:
        for bookmaker, poll_fn in _poll_bookmakers():
            started = time.monotonic()
            matches, diagnostics = poll_fn()
            duration = time.monotonic() - started
            http_stats, raw_events, partitions = _raw_from_records(recorder.records, bookmaker)
            parsed_rejects, parse_reasons = _reject_unparsed(bookmaker, raw_events, matches)
            now = time.time()
            records = merge_match_records(
                {},
                matches,
                now=now,
                retention_seconds=3600,
                acquired_seq=1,
                expire_unseen=bool(getattr(diagnostics, "snapshot_complete", True)),
            )
            visible = visible_matches(records, now=now, retention_seconds=3600)
            fixtures = {canonical_fixture_key(match)["key"] for match in visible}
            book_results[bookmaker] = {
                "duration_seconds": round(duration, 2),
                "diagnostics": _diagnostics_dict(diagnostics),
                "http": http_stats,
                "parsed_matchodds": len(matches),
                "parsed_matchodds_by_sport": _sport_counts(matches),
                "snapshot_records": len(records),
                "visible_matchodds": len(visible),
                "unique_canonical_fixtures": len(fixtures),
                "parse_reject_reasons": parse_reasons,
                "partitions_sample": partitions[:20],
                "partition_count": len(partitions),
                "capped_partitions_from_walk": [
                    row
                    for row in partitions
                    if row.get("kind") == "vzip_events"
                    and (row.get("returned_events") or 0) >= CHAMP_EVENT_CAP
                ],
            }
            book_results[bookmaker]["remainder_probes"] = _probe_remainder(recorder.records, bookmaker)
            all_matches.extend(matches)
            all_rejects.extend(parsed_rejects)
            with (output_dir / f"matchodds_{bookmaker.lower().replace(' ', '')}.jsonl").open(
                "w", encoding="utf-8"
            ) as handle:
                for match in matches:
                    handle.write(json.dumps(matchodds_record(match), ensure_ascii=True) + "\n")
    finally:
        _unpatch_fetch(restored)

    now = datetime.now(timezone.utc)
    before_dedupe = len(all_matches)
    deduped = dedupe_same_book_listings(all_matches)
    invalid = []
    stale = []
    usable = []
    for match in deduped:
        if not (_is_three_way(match) or _is_two_way(match)):
            invalid.append(match)
            all_rejects.append(
                {
                    "bookmaker": match.bookmaker,
                    "stage": "engine_validation",
                    "reason": "INVALID_ODDS",
                    "source_event_id": match.event_id,
                    "home_team": match.home_team,
                    "away_team": match.away_team,
                    "market": match.market,
                }
            )
            continue
        if _is_stale(match, now):
            stale.append(match)
            all_rejects.append(
                {
                    "bookmaker": match.bookmaker,
                    "stage": "engine_freshness",
                    "reason": "STALE_ODDS",
                    "source_event_id": match.event_id,
                    "home_team": match.home_team,
                    "away_team": match.away_team,
                    "collected_at": match.collected_at.isoformat() if match.collected_at else None,
                }
            )
            continue
        usable.append(match)

    matching, clusters = _matching_report(usable)
    engine = KenyanArbitrageEngine()
    computed = engine.compute_opportunities(all_matches, now=now)
    store = KenyanOpportunityStore(retention_seconds=3600)
    tracked = store.apply(computed, now=time.time())
    serialized = serialize_opportunities(tracked, now=now)
    serialize_dropped = len(tracked) - len(serialized)

    single_book_clusters = 0
    multi_book_clusters = 0
    compatible_markets = 0
    for event in clusters:
        books = {row.bookmaker for row in event.matches}
        if len(books) < 2:
            single_book_clusters += 1
        else:
            multi_book_clusters += 1
            compatible_markets += 1

    snapshot_identities = [match_identity(match) for match in all_matches]
    representative = []
    for match in all_matches[:12] + all_matches[-3:]:
        representative.append(
            {
                "bookmaker": match.bookmaker,
                "event_id": match.event_id,
                "home_team": match.home_team,
                "away_team": match.away_team,
                "collected_at": match.collected_at.isoformat() if match.collected_at else None,
                "confirmed_at": match.confirmed_at.isoformat() if match.confirmed_at else None,
                "start_time": match.start_time.isoformat() if match.start_time else None,
                "identity": match_identity(match),
                "note": "PREMATCH merge restamps collected_at to poll-end; confirmed_at is LIVE-only",
            }
        )

    summary = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "local_revision": _git_rev(),
        "running_backend_revision": "unknown_from_this_one_shot; production SHA is not exposed on /kenyan/status",
        "bookmakers": book_results,
        "pipeline": {
            "parsed_matchodds_all_books": before_dedupe,
            "after_same_book_dedupe": len(deduped),
            "dropped_same_book_duplicates": before_dedupe - len(deduped),
            "invalid_odds": len(invalid),
            "stale_odds": len(stale),
            "usable_for_matching": len(usable),
            "matched_clusters": matching["matched_clusters"],
            "single_book_clusters": single_book_clusters,
            "multi_book_clusters": multi_book_clusters,
            "arbitrage_candidates_examined": multi_book_clusters,
            "valid_arbitrage_opportunities": len(computed),
            "opportunities_after_store": len(tracked),
            "opportunities_serialized": len(serialized),
            "serialize_exceptions_dropped": serialize_dropped,
            "snapshot_identities": len(snapshot_identities),
        },
        "matching": matching,
        "freshness_samples": representative,
        "frontend": {
            "this_cycle_payload_length": len(serialized),
            "frontend_code": "frontend/src/routes/kenyan.tsx load() fetches /kenyan/opportunities?mode=prematch and setOpportunities(data) for the full JSON array, then opportunities.map renders every row",
            "frontend_received_this_cycle": "not observed; this command does not drive the browser. If the API returned this payload, rendered count would equal serialized count unless fetch failed (UI keeps last successful list).",
        },
        "api_swallow": {
            "file": "kenyan/api_router.py",
            "function": "serialize_opportunities",
            "note": "bare except Exception: continue can drop rows; serialize_exceptions_dropped measures that for this cycle",
        },
    }

    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2, default=str),
        encoding="utf-8",
    )
    with (output_dir / "rejected.jsonl").open("w", encoding="utf-8") as handle:
        for row in all_rejects:
            handle.write(json.dumps(row, ensure_ascii=True, default=str) + "\n")
    with (output_dir / "matching_examples.json").open("w", encoding="utf-8") as handle:
        json.dump(matching["examples"], handle, ensure_ascii=True, indent=2, default=str)
    (output_dir / "opportunities.json").write_text(
        json.dumps(serialized, ensure_ascii=True, indent=2, default=str),
        encoding="utf-8",
    )
    (output_dir / "http_requests.jsonl").open("w", encoding="utf-8").write(
        "".join(json.dumps({k: v for k, v in row.items() if k != "compact"}, ensure_ascii=True) + "\n" for row in recorder.records)
    )
    return summary


def _print_summary(summary: dict):
    print("PREMATCH forensic cycle")
    rev = summary.get("local_revision") or {}
    print(f"local HEAD {rev.get('head')} branch {rev.get('branch')} dirty={rev.get('dirty')}")
    print()
    print(f"{'Stage':<32} {'SportPesa':>10} {'Betika':>10} {'1xBet':>10} {'22Bet':>10}")
    books = ("SportPesa", "Betika", "1xBet", "22Bet")

    def cell(book, *keys, default=0):
        node = summary["bookmakers"].get(book) or {}
        for key in keys:
            if isinstance(node, dict):
                node = node.get(key, default)
            else:
                return default
        return node if node is not None else default

    rows = [
        ("HTTP attempted", lambda b: cell(b, "http", "requests_attempted")),
        ("HTTP JSON OK", lambda b: cell(b, "http", "requests_successful_json")),
        ("Raw event records", lambda b: cell(b, "http", "raw_event_records")),
        ("Unique source events", lambda b: cell(b, "http", "unique_source_event_ids")),
        ("Advertised source total", lambda b: cell(b, "http", "advertised_source_total", default=None)),
        ("Parsed MatchOdds", lambda b: cell(b, "parsed_matchodds")),
        ("Visible snapshot MatchOdds", lambda b: cell(b, "visible_matchodds")),
        ("Canonical fixtures", lambda b: cell(b, "unique_canonical_fixtures")),
        ("Catalogue status", lambda b: (cell(b, "diagnostics", "catalogue_status") or "")),
        ("Terminal reason", lambda b: (cell(b, "diagnostics", "terminal_reason") or "")),
    ]
    for label, getter in rows:
        values = [str(getter(book)) for book in books]
        print(f"{label:<32} {values[0]:>10} {values[1]:>10} {values[2]:>10} {values[3]:>10}")
    pipe = summary["pipeline"]
    print()
    print("Matching / arb")
    for key, value in pipe.items():
        print(f"  {key}: {value}")
    matching = summary["matching"]
    print(f"  unique canonical fixtures: {matching['unique_canonical_fixtures']}")
    print(f"  fixtures with 2+ books: {matching['fixtures_with_two_or_more_books']}")
    print(f"  fixtures with 3+ books: {matching['fixtures_with_three_or_more_books']}")
    print(f"  market rows with 2+ books: {matching['market_rows_with_two_or_more_books']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="One-shot Kenyan PREMATCH forensic export")
    parser.add_argument(
        "--output",
        default="",
        help="Output directory (default kenyan/diagnostics/runs/<timestamp>)",
    )
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output) if args.output else OUTPUT_ROOT / stamp
    summary = run_cycle(output_dir)
    _print_summary(summary)
    print(f"\nWrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
