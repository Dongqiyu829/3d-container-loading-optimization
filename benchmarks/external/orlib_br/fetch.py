"""Acquire exact OR-Library BR1--BR7 files and verify their committed hashes."""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path
from typing import Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from benchmarks.external.orlib_br.adapter import (  # noqa: E402
    load_source_manifest,
    sha256_file,
    verify_source_files,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "source_manifest.json"
DEFAULT_RAW_ROOT = ROOT / "raw"


def fetch_files(manifest_path: Path, output_root: Path) -> None:
    manifest = load_source_manifest(manifest_path)
    output_root.mkdir(parents=True, exist_ok=True)
    for entry in manifest["files"]:
        target = output_root / entry["filename"]
        if target.exists():
            if target.stat().st_size == entry["byte_count"] and sha256_file(target) == entry["sha256"]:
                continue
            raise FileExistsError(f"refusing to replace mismatched source file: {target}")
        url = f"{manifest['files_base_url']}/{entry['filename']}"
        try:
            with urllib.request.urlopen(url) as response, target.open("xb") as handle:
                handle.write(response.read())
        except Exception:
            if target.exists():
                target.unlink()
            raise
        if target.stat().st_size != entry["byte_count"] or sha256_file(target) != entry["sha256"]:
            raise RuntimeError(f"downloaded source failed integrity check: {entry['filename']}")
    verify_source_files(manifest, output_root)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_RAW_ROOT)
    args = parser.parse_args(argv)
    try:
        fetch_files(args.manifest.resolve(), args.output_root.resolve())
        print("OR-Library BR1--BR7 source files are present and checksum-verified.")
        return 0
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
