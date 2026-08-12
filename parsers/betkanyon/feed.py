from parsers.betkanyon.fetcher import BetkanyonFetcher
from parsers.betkanyon.decryptor import BetkanyonDecryptor
from parsers.betkanyon.parser import parse_json
from parsers.betkanyon.adapter import BetkanyonAdapter


class BetkanyonFeed:

    def __init__(self):

        self.fetcher = BetkanyonFetcher()

        self.decryptor = BetkanyonDecryptor()

        self._match_odds = []
        self._parsed_event_count = 0

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

        decrypted = self.decryptor.decrypt(encrypted)

        parsed = parse_json(decrypted)

        matches = []

        for event in parsed:

            match = BetkanyonAdapter.to_match_odds(event)

            if match:

                matches.append(match)

        self._match_odds = matches
        self._parsed_event_count = len(parsed)

        return matches

    def get_match_odds(self):

        return self._match_odds

    def get_parsed_event_count(self):
        """Raw event count from the most recent collect_once() call
        (before the MatchOdds adapter filter), for status logging."""

        return self._parsed_event_count

    def close(self):

        self.fetcher.close()