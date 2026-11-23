from __future__ import annotations

import re
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models"
REPO = "DennisHuang648/VoxCPM2-GGUF"
FILES = {
    "VoxCPM2-BaseLM-Q8_0.gguf": 1_727_309_920,
    "VoxCPM2-Acoustic-F16.gguf": 1_825_096_352,
}
CHUNK_SIZE = 64 * 1024 * 1024


def fetch(name: str, expected_size: int) -> None:
    destination = MODEL_DIR / name
    if destination.exists() and destination.stat().st_size == expected_size:
        print(f"Already complete: {name}", flush=True)
        return
    destination.unlink(missing_ok=True)
    url = f"https://huggingface.co/{REPO}/resolve/main/{name}"
    offset = 0
    retries = 0
    while offset < expected_size:
        end = min(offset + CHUNK_SIZE, expected_size) - 1
        part = destination.with_suffix(destination.suffix + ".part")
        try:
            with requests.get(
                url,
                headers={"Range": f"bytes={offset}-{end}"},
                stream=True,
                timeout=(30, 120),
            ) as response:
                if response.status_code != 206:
                    raise RuntimeError(f"Expected HTTP 206 for byte range, got {response.status_code}")
                content_range = response.headers.get("Content-Range", "")
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                if not match or tuple(map(int, match.groups())) != (offset, end, expected_size):
                    raise RuntimeError(f"Unexpected Content-Range: {content_range!r}")
                part_size = 0
                with part.open("wb") as output:
                    for block in response.iter_content(1024 * 1024):
                        if block:
                            output.write(block)
                            part_size += len(block)
                if part_size != end - offset + 1:
                    raise RuntimeError(f"Short model chunk: expected {end-offset+1}, received {part_size}")
            with part.open("rb") as source, destination.open("ab") as output:
                while block := source.read(8 * 1024 * 1024):
                    output.write(block)
            part.unlink(missing_ok=True)
            offset = end + 1
            retries = 0
            print(f"{name}: {offset:,}/{expected_size:,} bytes", flush=True)
        except Exception:
            part.unlink(missing_ok=True)
            retries += 1
            if retries > 5:
                raise
            time.sleep(min(2**retries, 30))
    if destination.stat().st_size != expected_size:
        raise RuntimeError(f"Model size mismatch for {name}")
    with destination.open("rb") as model:
        if model.read(4) != b"GGUF":
            raise RuntimeError(f"Invalid GGUF header in {name}")


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in FILES.items():
        fetch(name, size)


if __name__ == "__main__":
    main()
