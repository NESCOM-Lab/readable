#!/usr/bin/env python3
"""Embed a workspace's retrieval units, once, into <workspace>/embeddings.json.

Run this after 'pgraph index'. The agent never calls it; only the query it types
is embedded at run time, against the vectors this writes.
"""

import argparse
import hashlib
import json
import os
import time

from ollama_client import EMBED_MODEL, embed

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fingerprint(units):
    """Identifies the unit texts, so a reindex invalidates the vectors."""
    joined = "\n".join(unit["text"] for unit in units)
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", nargs="?", default=os.path.join(REPO, "PMC11289285-test"))
    parser.add_argument("--force", action="store_true", help="re-embed even if cached")
    args = parser.parse_args()

    units_path = os.path.join(args.workspace, "units.json")
    if not os.path.exists(units_path):
        raise SystemExit(f"no units.json in {args.workspace}; run 'pgraph index' first")

    with open(units_path) as handle:
        units = json.load(handle)
    stamp = fingerprint(units)

    out_path = os.path.join(args.workspace, "embeddings.json")
    if os.path.exists(out_path) and not args.force:
        with open(out_path) as handle:
            cached = json.load(handle)
        if cached.get("fingerprint") == stamp:
            print(f"{len(cached['vectors'])} vectors already cached in {out_path}")
            return

    print(f"embedding {len(units)} units with {EMBED_MODEL} ...")
    started = time.time()
    vectors = []
    for number, unit in enumerate(units, start=1):
        vectors.append(embed(unit["text"]))
        if number % 25 == 0:
            print(f"  {number}/{len(units)}")

    with open(out_path, "w") as handle:
        json.dump({"fingerprint": stamp, "model": EMBED_MODEL, "vectors": vectors}, handle)

    print(f"wrote {len(vectors)} vectors to {out_path} in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
