"""Offline cache preparation command; production runtime never downloads models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .omniparser_v2 import (
    load_model_manifest,
    model_manifest_digest,
    packaged_model_manifest,
    prepare_model_cache,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="haykal-prepare-omniparser")
    parser.add_argument("--manifest")
    parser.add_argument("--cache", required=True)
    args = parser.parse_args()
    manifest = load_model_manifest(args.manifest) if args.manifest else packaged_model_manifest()
    files = prepare_model_cache(Path(args.cache), manifest)
    print(
        json.dumps(
            {
                "schema_version": "1.0",
                "manifest_sha256": model_manifest_digest(manifest),
                "verified_files": len(files),
                "cache": str(Path(args.cache).expanduser().resolve()),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
