from datetime import datetime, timezone
import json

from parsers.betkanyon.parser import parse_json
from parsers.betkanyon_prematch.adapter import BetkanyonPrematchAdapter
from parsers.betkanyon_prematch.decrypt import PrematchDecryptor
from parsers.betkanyon_prematch.fetcher import BetkanyonPrematchFetcher
from parsers.betkanyon_prematch.tournaments import TOURNAMENT_IDS


def _as_decoded(payload):
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("{") or text.startswith("["):
            return json.loads(text)
    return None


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
        }

    def collect_once(self):
        payloads = self.fetcher.fetch_all(self.tournament_ids)
        print(
            f"[BETKANYON PREMATCH] encrypted payloads: "
            f"{len(payloads)}/{len(self.tournament_ids)}"
        )
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
            sample_dec = next(iter(decrypted.values()))
            if isinstance(sample_dec, dict):
                print(
                    "[BETKANYON PREMATCH] decrypted keys="
                    f"{list(sample_dec.keys())[:15]}"
                )

        matches = []
        parsed_events = 0
        for tournament_id, data in decrypted.items():
            try:
                parsed = parse_json(data)
            except Exception as exc:
                print(
                    f"[BETKANYON PREMATCH] tournament {tournament_id} "
                    f"parse failed ({type(exc).__name__}: {exc})"
                )
                continue
            parsed_events += len(parsed)
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

        self._match_odds = matches
        self._parsed_event_count = parsed_events
        self._odds_count = len(matches)
        self.last_stats = {
            "tournaments": len(self.tournament_ids),
            "events": parsed_events,
            "odds": len(matches),
        }
        return matches

    def get_match_odds(self):
        return self._match_odds

    def get_parsed_event_count(self):
        return self._parsed_event_count

    def close(self):
        self.fetcher.close()
