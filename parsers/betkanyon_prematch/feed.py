from datetime import datetime, timezone
import json
import os
from pathlib import Path

from parsers.betkanyon_prematch.adapter import BetkanyonPrematchAdapter
from parsers.betkanyon_prematch.decrypt import PrematchDecryptor
from parsers.betkanyon_prematch.fetcher import BetkanyonPrematchFetcher
from parsers.betkanyon_prematch.parser import parse_prematch, summarize_structure
from parsers.betkanyon_prematch.tournaments import TOURNAMENT_IDS


_FORENSICS_FILE = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / (
    "arbscanner-bk-prematch-python-forensics.json"
)
_FORENSICS_PRINTED = False


def merge_incomplete_prematch_snapshot(
    previous, incoming, fetched_ids, tournament_universe
):
    """Keep last-good MatchOdds for tournaments this cycle did not fetch.

    A non-empty but partial HTTP batch used to replace the full snapshot
    and wipe previously valid events. Empty cycles already keep last-good
    in collect_once; this covers the incomplete-but-not-empty case.
    A complete cycle (every tournament id fetched) still replaces.
    """
    if not previous or not incoming:
        return incoming
    fetched = {str(tid) for tid in fetched_ids}
    universe = len(tournament_universe or [])
    if not fetched or (universe and len(fetched) >= universe):
        return incoming
    kept = [
        match
        for match in previous
        if str(getattr(match, "tournament_id", "") or "") not in fetched
    ]
    if not kept:
        return incoming
    print(
        f"[BETKANYON PREMATCH] incomplete cycle "
        f"payloads={len(fetched)}/{universe or '?'} ; "
        f"keeping {len(kept)} last-good MatchOdds from missing tournaments"
    )
    return list(incoming) + kept


def _as_decoded(payload):
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("{") or text.startswith("["):
            return json.loads(text)
    return None


def _print_forensics_once(payload):
    global _FORENSICS_PRINTED
    if _FORENSICS_PRINTED:
        return
    _FORENSICS_PRINTED = True
    root_type = type(payload).__name__
    root_keys = list(payload.keys()) if isinstance(payload, dict) else []
    print("[BETKANYON PREMATCH FORENSICS]")
    print(f"root type: {root_type}")
    print("root keys:")
    for key in root_keys[:30]:
        value = payload.get(key) if isinstance(payload, dict) else None
        print(f"    {key}: {type(value).__name__}")
    try:
        _FORENSICS_FILE.write_text(
            json.dumps(
                {
                    "root_type": root_type,
                    "root_keys": root_keys,
                    "structure": summarize_structure(payload),
                },
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"[BETKANYON PREMATCH FORENSICS] structure written to {_FORENSICS_FILE}")
    except Exception:
        pass


class BetkanyonPrematchFeed:
    def __init__(self, tournament_ids=None):
        self.tournament_ids = list(tournament_ids or TOURNAMENT_IDS)
        self.fetcher = BetkanyonPrematchFetcher()
        self.decryptor = PrematchDecryptor()
        self._match_odds = []
        self._parsed_event_count = 0
        self._odds_count = 0
        self.last_stats = {
            "tournaments": len(self.tournament_ids),
            "events": 0,
            "odds": 0,
            "match_odds_markets": 0,
        }

    def collect_once(self):
        print("[BETKANYON PREMATCH] RUNNING")
        payloads = self.fetcher.fetch_all(self.tournament_ids)
        print(
            f"[BETKANYON PREMATCH] encrypted payloads: "
            f"{len(payloads)}/{len(self.tournament_ids)}"
        )
        if payloads:
            print("[BETKANYON PREMATCH] encrypted payload received")
        sample = next(iter(payloads.values()), None)
        sample_kind = type(sample).__name__
        sample_prefix = (
            str(sample)[:12].replace("\n", " ") if sample is not None else ""
        )
        print(
            f"[BETKANYON PREMATCH] payload sample type={sample_kind} "
            f"prefix={sample_prefix!r}"
        )

        decoded_direct = {}
        needs_decrypt = {}
        for tournament_id, payload in payloads.items():
            direct = _as_decoded(payload)
            if direct is not None:
                decoded_direct[tournament_id] = direct
            else:
                needs_decrypt[tournament_id] = payload
        decrypted = dict(decoded_direct)
        if needs_decrypt:
            decrypted.update(self.decryptor.decrypt_chunks(needs_decrypt))
        print(
            f"[BETKANYON PREMATCH] decoded direct={len(decoded_direct)} "
            f"wasm={len(needs_decrypt)}"
        )
        if decrypted:
            print("[BETKANYON PREMATCH] decrypted successfully")
            sample_dec = next(iter(decrypted.values()))
            _print_forensics_once(sample_dec)

        matches = []
        parsed_events = 0
        match_odds_markets = 0
        complete_1x2 = 0
        for tournament_id, data in decrypted.items():
            try:
                parsed, stats = parse_prematch(data)
            except Exception as exc:
                print(
                    f"[BETKANYON PREMATCH] tournament {tournament_id} "
                    f"parse failed ({type(exc).__name__}: {exc})"
                )
                continue
            parsed_events += stats.get("events_discovered", 0)
            match_odds_markets += stats.get("match_odds_markets", 0)
            complete_1x2 += stats.get("complete_1x2", 0)
            if parsed and not getattr(self, "_1x2_forensics_printed", False):
                sample = parsed[0]
                self._1x2_forensics_printed = True
                print("[PREMATCH 1X2 FORENSICS]")
                print(f"event: {sample.get('home')} vs {sample.get('away')}")
                print(f"event_id: {sample.get('event_id')}")
                print(f"tournament_id: {tournament_id}")
                print(f"home selection coefficient: {sample.get('home_odds')}")
                print(f"draw selection coefficient: {sample.get('draw_odds')}")
                print(f"away selection coefficient: {sample.get('away_odds')}")
            for event in parsed:
                match = BetkanyonPrematchAdapter.to_match_odds(
                    event,
                    tournament_id=tournament_id,
                )
                if match:
                    matches.append(match)

        snapshot_at = datetime.now(timezone.utc)
        for match in matches:
            match.collected_at = snapshot_at

        fetched_ids = {str(tid) for tid in decrypted.keys()}
        unique_ids = {(m.home_team, m.away_team) for m in matches}
        print(f"[BETKANYON PREMATCH] events discovered: {parsed_events}")
        print(f"[BETKANYON PREMATCH] 1X2 markets discovered: {match_odds_markets}")
        print(f"[BETKANYON PREMATCH] MatchOdds produced: {len(matches)}")
        print(
            f"[BETKANYON PREMATCH] payloads={len(fetched_ids)}/"
            f"{len(self.tournament_ids)} unique_events={len(unique_ids)}"
        )

        if matches:
            matches = merge_incomplete_prematch_snapshot(
                self._match_odds,
                matches,
                fetched_ids,
                self.tournament_ids,
            )
            self._match_odds = matches
            self._parsed_event_count = parsed_events
            self._odds_count = len(matches)
            self.last_stats = {
                "tournaments": len(self.tournament_ids),
                "payloads": len(fetched_ids),
                "events": parsed_events,
                "odds": len(matches),
                "unique_events": len({(m.home_team, m.away_team) for m in matches}),
                "match_odds_markets": match_odds_markets,
                "complete_1x2": complete_1x2,
            }
        elif self._match_odds:
            print(
                "[BETKANYON PREMATCH] empty cycle ignored; "
                f"keeping {len(self._match_odds)} last MatchOdds"
            )
        else:
            self._match_odds = matches
            self._parsed_event_count = parsed_events
            self._odds_count = 0
            self.last_stats = {
                "tournaments": len(self.tournament_ids),
                "events": parsed_events,
                "odds": 0,
                "match_odds_markets": match_odds_markets,
                "complete_1x2": complete_1x2,
            }
        return self._match_odds

    def get_match_odds(self):
        return self._match_odds

    def get_parsed_event_count(self):
        return self._parsed_event_count

    def close(self):
        self.fetcher.close()
