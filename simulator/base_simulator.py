from abc import ABC, abstractmethod
from pathlib import Path
import json


class BaseSimulator(ABC):

    def __init__(self, bookmaker_name: str):

        self.bookmaker_name = bookmaker_name

        self.output_dir = Path("simulator/output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def generate(self):

        """
        Generate the raw bookmaker response.
        """
        pass

    def export_json(self, data):

        output_file = self.output_dir / f"{self.bookmaker_name.lower()}.json"

        with open(output_file, "w", encoding="utf-8") as file:

            json.dump(
                data,
                file,
                indent=4,
                ensure_ascii=False
            )

        print(f"[{self.bookmaker_name}] JSON exported -> {output_file}")