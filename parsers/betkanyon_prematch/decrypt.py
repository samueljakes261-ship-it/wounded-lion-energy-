"""Prematch decryptor.

Uses the same WASM decryptor as live BetKanyon, but writes to its own
temp files so it cannot race the live worker's
experiments/decrypt/encrypted_payload.txt output.

Never decrypts hundreds of payloads as one-node-process-per-tournament:
that overlaps live's node WASM and crashes it on Windows.
"""

import json
import subprocess
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "decrypt_cli.js"
CHUNK_SIZE = 12


def _run_node(args):
    result = subprocess.run(
        ["node", str(SCRIPT), *args],
        capture_output=True,
        timeout=90,
    )
    if result.returncode != 0:
        err = (result.stderr or b"").decode("utf-8", "replace").strip()
        out = (result.stdout or b"").decode("utf-8", "replace").strip()
        detail = (err or out or f"exit {result.returncode}")[:400]
        raise RuntimeError(detail)
    return result


class PrematchDecryptor:
    def decrypt(self, encrypted_payload: str):
        with tempfile.TemporaryDirectory(prefix="bk-prematch-") as tmp:
            tmp_path = Path(tmp)
            payload_file = tmp_path / "encrypted_payload.txt"
            output_file = tmp_path / "decrypted_output.json"
            payload_file.write_text(encrypted_payload, encoding="utf-8")
            _run_node([str(payload_file), str(output_file)])
            return json.loads(output_file.read_text(encoding="utf-8"))

    def decrypt_batch(self, payloads_by_id: dict):
        """Decrypt many tournament payloads with one WASM boot."""
        if not payloads_by_id:
            return {}
        with tempfile.TemporaryDirectory(prefix="bk-prematch-batch-") as tmp:
            tmp_path = Path(tmp)
            payload_file = tmp_path / "payloads.json"
            output_file = tmp_path / "decrypted.json"
            payload_file.write_text(
                json.dumps(payloads_by_id),
                encoding="utf-8",
            )
            _run_node(["--batch", str(payload_file), str(output_file)])
            return json.loads(output_file.read_text(encoding="utf-8"))

    def decrypt_chunks(self, payloads_by_id: dict, pause_seconds=0.5):
        """Decrypt in small batches, pausing so live BetKanyon WASM can run."""
        import time

        decrypted = {}
        items = list(payloads_by_id.items())
        total = len(items)
        for offset in range(0, total, CHUNK_SIZE):
            chunk = dict(items[offset : offset + CHUNK_SIZE])
            try:
                decrypted.update(self.decrypt_batch(chunk))
            except Exception as exc:
                print(
                    f"[BETKANYON PREMATCH] decrypt chunk "
                    f"{offset + 1}-{offset + len(chunk)}/{total} failed "
                    f"({type(exc).__name__}: {exc})"
                )
            done = min(offset + CHUNK_SIZE, total)
            if done == total or done % 36 == 0 or offset == 0:
                print(
                    f"[BETKANYON PREMATCH] decrypt progress: "
                    f"{done}/{total} (ok={len(decrypted)})"
                )
            if offset + CHUNK_SIZE < total:
                time.sleep(pause_seconds)
        return decrypted
