from parsers.betkanyon.adapter import BetkanyonAdapter
from parsers.betkanyon.decryptor import BetkanyonDecryptor
from parsers.betkanyon.fetcher import BetkanyonFetcher, EmptyAcquisitionError
from parsers.betkanyon.parser import parse_json


class BetkanyonFeed:

    def __init__(self):

        self.fetcher = BetkanyonFetcher()

        self.decryptor = BetkanyonDecryptor()

        self._match_odds = []
        self._parsed_event_count = 0
        self.last_cycle_empty = False
        self.last_stats = {
            "events": 0,
            "odds": 0,
            "http_status": None,
            "content_type": None,
            "payload_bytes": 0,
        }

    def collect_once(self):
        """
        Run one full acquisition cycle: fetch the encrypted payload,
        decrypt it, parse it, and adapt it to MatchOdds.

        Deliberately quiet (no per-match prints) so this can be called
        repeatedly (every few seconds) by a persistent poller without
        flooding the terminal. Callers that want visible status lines
        should use parsers.betkanyon.worker.BetkanyonWorker, which logs
        one concise line per cycle instead of dumping every match.
        """

        encrypted = self.fetcher.fetch()
        meta = getattr(self.fetcher, "last_meta", {}) or {}
        if not encrypted:
            raise EmptyAcquisitionError("empty payload")

        decrypted = self.decryptor.decrypt(encrypted)

        parsed = parse_json(decrypted)

        matches = []

        for event in parsed:

            match = BetkanyonAdapter.to_match_odds(event)

            if match:

                matches.append(match)

        self.last_cycle_empty = not matches
        self._parsed_event_count = len(parsed)
        self.last_stats = {
            "events": len(parsed),
            "odds": len(matches),
            "http_status": meta.get("http_status"),
            "content_type": meta.get("content_type"),
            "payload_bytes": meta.get("payload_bytes") or 0,
        }

        if matches:
            self._match_odds = matches
        elif self._match_odds:
            print(
                "[BETKANYON] empty cycle ignored; "
                f"keeping {len(self._match_odds)} last MatchOdds"
            )
        else:
            self._match_odds = matches

        return self._match_odds

    def get_match_odds(self):

        return self._match_odds

    def get_parsed_event_count(self):
        """Event/odds-row count from the most recent collect_once() parse."""

        return self._parsed_event_count

    def close(self):

        self.fetcher.close()
