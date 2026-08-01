from pathlib import Path


class BetfairSource:

    def load(self) -> str:

        json_file = Path("simulator/output/betfair.json")

        return json_file.read_text(encoding="utf-8")