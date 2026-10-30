#!/usr/bin/env python3
"""Turn a folder of result records into the markdown summary for a results run.

score.py prints the detail for working on; this writes the short version meant
to be read cold, with the numbers coming straight from the records so the
summary cannot drift from what was actually run.
"""

import argparse
import glob
import json
import os
import statistics
from datetime import date

import score

LABELS = {
    "closedbook": "closed book (no retrieval)",
    "bm25": "BM25 (sparse lexical)",
    "raw": "raw (whole paper in context)",
    "rag": "RAG (dense, structured units)",
    "rag_flat": "RAG (dense, flat markdown)",
    "cli": "CLI agent (this work)",
    "lightrag": "LightRAG (graph)",
}

ORDER = ["closedbook", "bm25", "rag_flat", "rag", "lightrag", "cli", "raw"]


def load(results, questions):
    by_id = {question["id"]: question for question in questions["questions"]}
    scored = []
    for path in sorted(glob.glob(os.path.join(results, "*.json"))):
        with open(path) as handle:
            record = json.load(handle)
        question = by_id.get(record["question_id"])
        if question is None:
            continue
        entry = score.score_record(record, question)
        entry.update({
            "question_id": record["question_id"],
            "condition": record["condition"],
            "run": record["run"],
            "workspace": record.get("workspace", ""),
            "prompt_tokens": record.get("prompt_tokens", 0),
            "seconds": record.get("seconds", 0),
            "context_chars": record.get("context_chars", 0),
            "answer": record.get("answer", ""),
        })
        scored.append(entry)
    return scored


def mean(values):
    return statistics.mean(values) if values else 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results")
    parser.add_argument("--questions", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--title", default="Type A evaluation")
    args = parser.parse_args()

    with open(args.questions) as handle:
        questions = json.load(handle)
    scored = load(args.results, questions)
    if not scored:
        raise SystemExit(f"no records in {args.results}")

    conditions = [c for c in ORDER if any(e["condition"] == c for e in scored)]
    question_ids = [q["id"] for q in questions["questions"]]

    lines = []
    out = lines.append

    out(f"# {args.title}")
    out("")
    out(f"Run {date.today().isoformat()}. "
        f"{len(question_ids)} questions, "
        f"{sum(len(q['facets']) for q in questions['questions'])} scored facets, "
        f"{len(scored)} records.")
    out("")

    out("## Coverage by condition")
    out("")
    out("| condition | coverage | sd | runs | prompt tok | context chars | sec |")
    out("|---|---|---|---|---|---|---|")
    for condition in conditions:
        entries = [e for e in scored if e["condition"] == condition]
        values = [e["coverage"] for e in entries]
        spread = statistics.stdev(values) if len(values) > 1 else 0.0
        tokens = mean([e["prompt_tokens"] for e in entries])
        # LightRAG drives its own internal calls, so the harness never sees a
        # token count for it. Printing the zero would read as 'free'.
        shown_tokens = f"{tokens:.0f}" if tokens else "not counted"
        out(f"| {LABELS.get(condition, condition)} | **{mean(values):.1%}** | {spread:.3f} | "
            f"{len(entries)} | {shown_tokens} | "
            f"{mean([e['context_chars'] for e in entries]):.0f} | "
            f"{mean([e['seconds'] for e in entries]):.1f} |")
    out("")

    out("## Coverage by question")
    out("")
    header = "| question | paper | " + " | ".join(LABELS.get(c, c) for c in conditions) + " |"
    out(header)
    out("|" + "---|" * (len(conditions) + 2))
    papers = {q["id"]: os.path.basename(q.get("workspace", "").rstrip("/"))
              for q in questions["questions"]}

    for question_id in question_ids:
        rows = [e for e in scored if e["question_id"] == question_id]
        paper = papers.get(question_id) or (rows[0]["workspace"] if rows else "")
        cells = []
        for condition in conditions:
            values = [e["coverage"] for e in rows if e["condition"] == condition]
            cells.append(f"{mean(values):.0%}" if values else "-")
        out(f"| {question_id} | `{paper}` | " + " | ".join(cells) + " |")
    out("")

    out("## Where the misses come from")
    out("")
    out("A navigation miss means the fact never appeared in the text the model was "
        "shown. A generation miss means it was shown and left out.")
    out("")
    out("| condition | hit | generation miss | navigation miss |")
    out("|---|---|---|---|")
    for condition in conditions:
        verdicts = [facet["verdict"] for entry in scored if entry["condition"] == condition
                    for facet in entry["facets"]]
        total = len(verdicts) or 1
        out(f"| {LABELS.get(condition, condition)} | "
            f"{verdicts.count('hit') / total:.0%} | "
            f"{verdicts.count('generation miss') / total:.0%} | "
            f"{verdicts.count('navigation miss') / total:.0%} |")
    out("")

    with open(args.out, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
