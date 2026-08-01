from pathlib import Path


class OrbitSource:

    def load(self) -> str:

        json_file = Path("simulator/output/orbit.json")

        return json_file.read_text(encoding="utf-8")