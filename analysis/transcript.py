#!/usr/bin/env python3
"""Print a recorded run: what the model did, what it saw back, what it answered."""

import argparse
import glob
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS = os.path.join(REPO, "analysis")


def show(path, width):
    with open(path) as handle:
        record = json.load(handle)

    print("=" * 78)
    print(f"{os.path.basename(path)}   {record['condition']}   "
          f"{record['prompt_tokens']} prompt tok, {record['seconds']}s")
    print("=" * 78)

    for number, step in enumerate(record.get("steps", [])):
        flag = f", truncated from {step['full_chars']}" if step["truncated"] else ""
        print(f"\n--- step {number}: {step['action']}  "
              f"({len(step['observation'])} chars{flag}) ---")
        observation = step["observation"]
        if width and len(observation) > width:
            observation = observation[:width] + f"\n  ... [{len(observation) - width} more chars]"
        print(observation)

    if not record.get("steps"):
        # raw and rag have no steps, only the context they were handed.
        print(f"\ncontext: {record['context_chars']} chars")
        if record.get("retrieved_from"):
            print("retrieved from: " + ", ".join(record["retrieved_from"]))

    print("\n=== ANSWER ===")
    print(record["answer"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", help="a record name such as q4_cli_run2, or a path")
    parser.add_argument("--results", default=os.path.join(ANALYSIS, "results"))
    parser.add_argument("--width", type=int, default=1200,
                        help="characters of each observation to print; 0 for all")
    args = parser.parse_args()

    if os.path.exists(args.run):
        show(args.run, args.width)
        return

    found = sorted(glob.glob(os.path.join(args.results, f"{args.run}*.json")))
    if not found:
        raise SystemExit(f"no record matching '{args.run}' in {args.results}")
    for path in found:
        show(path, args.width)


if __name__ == "__main__":
    main()
