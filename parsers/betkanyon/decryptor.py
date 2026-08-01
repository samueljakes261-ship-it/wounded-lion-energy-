import subprocess
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

NODE_SCRIPT = ROOT / "experiments" / "decrypt" / "test_decrypt.js"

PAYLOAD_FILE = ROOT / "experiments" / "decrypt" / "encrypted_payload.txt"

OUTPUT_FILE = ROOT / "experiments" / "decrypt" / "decrypted_output.json"


class BetkanyonDecryptor:

    def decrypt(self, encrypted_payload: str):

        PAYLOAD_FILE.write_text(
            encrypted_payload,
            encoding="utf-8"
        )

        subprocess.run(
            [
                "node",
                str(NODE_SCRIPT),
                str(PAYLOAD_FILE),
            ],
            check=True,
        )

        with open(
            OUTPUT_FILE,
            encoding="utf-8"
        ) as f:
            return json.load(f)