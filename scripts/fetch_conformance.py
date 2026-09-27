"""Fetches the public fixtures of `duva-mail/duva-conformance` (generated and tested in the
`duva` repository: see `docs/bibliotheques-clientes.md` section 6). Never committed here (see
`.gitignore`): always the freshest version, never a copy that could silently drift.

    uv run --extra dev python scripts/fetch_conformance.py
"""

import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/duva-mail/duva-conformance/main"
FILES = ["webhooks.json", "requests.json", "retries.json"]
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "conformance"


def main() -> int:
    OUTPUT_DIR.mkdir(exist_ok=True)
    for name in FILES:
        with urllib.request.urlopen(f"{BASE}/{name}") as response:  # noqa: S310 (fixed https host)
            (OUTPUT_DIR / name).write_bytes(response.read())
        print(f"conformance/{name} fetched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
