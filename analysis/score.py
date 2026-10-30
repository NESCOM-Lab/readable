#!/usr/bin/env python3
"""Score the recorded runs against the gold facets in questions.json.

No model is involved. A facet counts as covered when one of its regexes matches
the answer. Each facet is also checked against the text the model was shown,
which separates a navigation miss (never saw it) from a generation miss (saw
it, left it out).
"""

import argparse
import glob
import json
import os
import re
import statistics
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS = os.path.join(REPO, "analysis")
PGRAPH = os.path.join(REPO, "target", "release", "pgraph")

CONDITION_ORDER = ["closedbook", "bm25", "raw", "rag", "rag_flat", "cli"]


def matches(patterns, text):
    for pattern in patterns:
        if re.search(pattern, text, re.I):
            return True
    return False


def load_questions(path):
    with open(path) as handle:
        return json.load(handle)


def paper_text(workspace):
    """The whole paper as one string, used to sanity-check the rubric."""
    parts = []
    with open(os.path.join(workspace, "metadata.json")) as handle:
        parts.append(json.load(handle).get("abstract_text", ""))
    for path in sorted(glob.glob(os.path.join(workspace, "sections", "*.md"))):
        with open(path) as handle:
            parts.append(handle.read())
    return "\n".join(parts)


def section_ids(workspace):
    """Every section id in the paper, including subsections."""
    result = subprocess.run(
        [PGRAPH, "query", "outline", workspace], capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"could not read {workspace}: {result.stderr.strip()}")

    found = set()
    pending = json.loads(result.stdout)
    while pending:
        node = pending.pop()
        if node.get("id"):
            found.add(node["id"])
        pending.extend(node.get("subsections", []))
    return found


def workspace_for(question, default):
    """The paper a question is about. An evaluation set usually spans several,
    so a question may name its own and fall back to the one on the command
    line when it does not."""
    workspace = question.get("workspace", default)
    if not os.path.isabs(workspace):
        workspace = os.path.join(REPO, workspace)
    return workspace


def check_rubric(questions, default_workspace):
    """A facet that no longer matches the paper means the rubric is stale, and
    any score built on it is meaningless."""
    cache = {}
    problems = []

    for question in questions["questions"]:
        workspace = workspace_for(question, default_workspace)
        if workspace not in cache:
            cache[workspace] = (paper_text(workspace), section_ids(workspace))
        text, ids = cache[workspace]

        for facet in question["facets"]:
            if not matches(facet["patterns"], text):
                problems.append(f"{question['id']}/{facet['id']}: no pattern matches the paper")
            source = facet["source_section"]
            # A paper with no public full text has an abstract and no sections,
            # so 'abstract' is a source in its own right rather than an id.
            if source != "abstract" and source not in ids:
                problems.append(
                    f"{question['id']}/{facet['id']}: source_section "
                    f"{source} is not a section in this paper"
                )
    return problems


SECTION_ACTION = re.compile(r"ACTION:\s*section\s+(\S+)", re.I)


def sections_read(record):
    """Section ids the cli condition opened, in order. Empty for raw and rag."""
    found = []
    for step in record.get("steps", []):
        match = SECTION_ACTION.search(step["action"])
        if not match:
            continue
        section = match.group(1).strip("\"'`.,")
        if section not in found:
            found.append(section)
    return found


def score_record(record, question):
    read = sections_read(record)

    facets = []
    for facet in question["facets"]:
        in_answer = matches(facet["patterns"], record["answer"])
        in_context = matches(facet["patterns"], record.get("context_text", ""))

        if in_answer:
            verdict = "hit"
        elif in_context:
            verdict = "generation miss"
        else:
            verdict = "navigation miss"

        facets.append({
            "id": facet["id"],
            "source_section": facet["source_section"],
            # Only meaningful for cli, where reaching a section is a choice.
            "source_read": facet["source_section"] in read if read else None,
            "in_context": in_context,
            "in_answer": in_answer,
            "verdict": verdict,
        })

    covered = sum(1 for facet in facets if facet["in_answer"])
    return {
        "covered": covered,
        "total": len(facets),
        "coverage": covered / len(facets),
        "sections_read": read,
        "facets": facets,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="?", default=os.path.join(ANALYSIS, "results"))
    parser.add_argument("--questions", default=os.path.join(ANALYSIS, "questions.json"))
    parser.add_argument("--workspace", default=os.path.join(REPO, "PMC11289285-test"))
    parser.add_argument("--json", help="also write the full per-facet scores here")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    by_id = {question["id"]: question for question in questions["questions"]}

    problems = check_rubric(questions, args.workspace)
    if problems:
        print("RUBRIC PROBLEMS (fix these before trusting any score):")
        for problem in problems:
            print("  -", problem)
        print()

    scored = []
    for path in sorted(glob.glob(os.path.join(args.results, "*.json"))):
        with open(path) as handle:
            record = json.load(handle)
        question = by_id.get(record["question_id"])
        if question is None:
            continue
        entry = score_record(record, question)
        entry.update({
            "question_id": record["question_id"],
            "condition": record["condition"],
            "run": record["run"],
            "prompt_tokens": record.get("prompt_tokens", 0),
            "seconds": record.get("seconds", 0),
            "context_chars": record.get("context_chars", 0),
        })
        scored.append(entry)

    if not scored:
        raise SystemExit(f"no result records found in {args.results}")

    conditions = [c for c in CONDITION_ORDER if any(e["condition"] == c for e in scored)]

    print("COVERAGE BY CONDITION")
    print(f"{'condition':<10} {'coverage':>10} {'sd':>7} {'runs':>6} {'prompt tok':>11} {'sec':>7}")
    for condition in conditions:
        entries = [e for e in scored if e["condition"] == condition]
        values = [e["coverage"] for e in entries]
        spread = statistics.stdev(values) if len(values) > 1 else 0.0
        print(f"{condition:<10} {statistics.mean(values):>9.1%} {spread:>7.3f} "
              f"{len(entries):>6} {statistics.mean([e['prompt_tokens'] for e in entries]):>11.0f} "
              f"{statistics.mean([e['seconds'] for e in entries]):>7.1f}")

    print("\nCOVERAGE BY QUESTION")
    header = f"{'question':<10}" + "".join(f"{c:>12}" for c in conditions)
    print(header)
    for question_id in [q["id"] for q in questions["questions"]]:
        row = f"{question_id:<10}"
        for condition in conditions:
            values = [e["coverage"] for e in scored
                      if e["question_id"] == question_id and e["condition"] == condition]
            row += f"{statistics.mean(values):>11.0%} " if values else f"{'-':>12}"
        print(row)

    print("\nMISS ATTRIBUTION (share of facet-runs)")
    print(f"{'condition':<10} {'hit':>8} {'generation miss':>18} {'navigation miss':>18}")
    for condition in conditions:
        verdicts = [facet["verdict"]
                    for entry in scored if entry["condition"] == condition
                    for facet in entry["facets"]]
        total = len(verdicts)
        counts = {v: verdicts.count(v) for v in ["hit", "generation miss", "navigation miss"]}
        print(f"{condition:<10} {counts['hit'] / total:>7.0%} "
              f"{counts['generation miss'] / total:>17.0%} "
              f"{counts['navigation miss'] / total:>17.0%}")

    print("\nNAVIGATION MISSES (facet never appeared in what the model saw)")
    any_navigation_miss = False
    for condition in conditions:
        misses = {}
        for entry in scored:
            if entry["condition"] != condition:
                continue
            for facet in entry["facets"]:
                if facet["verdict"] != "navigation miss":
                    continue
                key = (f"{entry['question_id']}/{facet['id']}",
                       facet["source_section"], facet["source_read"])
                misses[key] = misses.get(key, 0) + 1
        if misses:
            any_navigation_miss = True
            print(f"  {condition}:")
            for (name, source, was_read), count in sorted(misses.items(), key=lambda item: -item[1]):
                if was_read is None:
                    reach = ""
                elif was_read:
                    reach = f"  (read {source}, missed it there)"
                else:
                    reach = f"  (never opened {source})"
                print(f"    {name:<44} {count} run(s){reach}")
    if not any_navigation_miss:
        print("  none")

    if any(entry["sections_read"] for entry in scored):
        print("\nSECTIONS OPENED (cli)")
        for question_id in [q["id"] for q in questions["questions"]]:
            for entry in scored:
                if entry["question_id"] == question_id and entry["sections_read"]:
                    print(f"  {question_id}/run{entry['run']:<3} "
                          f"{entry['coverage']:>4.0%}  {', '.join(entry['sections_read'])}")

    if args.json:
        with open(args.json, "w") as handle:
            json.dump(scored, handle, indent=2)
        print(f"\nwrote per-facet scores to {args.json}")


if __name__ == "__main__":
    main()
