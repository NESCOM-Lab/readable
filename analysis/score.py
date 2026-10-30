#!/usr/bin/env python3
"""Score the recorded runs against the gold facets in questions.json.

A facet counts as covered when its regexes match the answer: any one of them by
default, or all of them when the facet says require 'all', which is how a
content point like '82 +/- 2% (SEM)' keeps its uncertainty instead of being
awarded to an answer that said only '82%'.

Facets converted from the Benchmark_Suite may instead ask to be scored by a
judge, because a claim about mechanism or polarity cannot be pattern matched
without penalising paraphrase. Those need --judge; without it they are counted
as unscored rather than as misses, so a run without a judge does not quietly
report a third of the points as missing. Each facet is also checked against the text the model was shown,
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

import ollama_client

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS = os.path.join(REPO, "analysis")
PGRAPH = os.path.join(REPO, "target", "release", "pgraph")

CONDITION_ORDER = ["closedbook", "bm25", "raw", "rag", "rag_flat", "cli"]


def matches(patterns, text, require="any"):
    if require == "all":
        for pattern in patterns:
            if not re.search(pattern, text, re.I):
                return False
        return bool(patterns)

    for pattern in patterns:
        if re.search(pattern, text, re.I):
            return True
    return False


def facet_matches(facet, text):
    return matches(facet["patterns"], text, facet.get("require", "any"))


def load_questions(path):
    with open(path) as handle:
        return json.load(handle)


def paper_text(workspace):
    """The whole paper as one string, used to sanity-check the rubric.

    Includes the retrieval units as well as the rendered sections. Figure
    captions and reference entries are units but are not in the section
    markdown, so checking the markdown alone reported a facet sourced from a
    caption as stale when it was correct.
    """
    parts = []
    with open(os.path.join(workspace, "metadata.json")) as handle:
        parts.append(json.load(handle).get("abstract_text", ""))
    for path in sorted(glob.glob(os.path.join(workspace, "sections", "*.md"))):
        with open(path) as handle:
            parts.append(handle.read())

    units_path = os.path.join(workspace, "units.json")
    if os.path.exists(units_path):
        with open(units_path) as handle:
            for unit in json.load(handle):
                parts.append(unit["text"])
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
            if facet.get("scoring") == "judge":
                # Nothing to check: the gold sentence is the rubric.
                pass
            elif not facet_matches(facet, text):
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



JUDGE_PROMPT = """You are checking whether a piece of text states one specific
content point. Accept a faithful paraphrase and equivalent units. Do not accept
it if the text omits it, hedges it away, or states the opposite. Polarity,
context, units and uncertainty all have to survive.

CONTENT POINT:
{element}

TEXT:
{text}

Answer with one word, YES if the text states the content point, NO if it does
not."""


class Judge:
    """Asks a local model whether a text states one gold content point.

    Answers are cached on the exact pair, because the same element is checked
    against the same answer and context repeatedly across conditions and runs.
    """

    def __init__(self, model):
        self.model = model
        self.cache = {}
        self.calls = 0

    def says(self, element, text):
        if not text.strip():
            return False

        key = (element, text)
        if key in self.cache:
            return self.cache[key]

        response = ollama_client.post("/api/generate", {
            "model": self.model,
            "prompt": JUDGE_PROMPT.format(element=element, text=text),
            "stream": False,
            "think": False,
            "keep_alive": ollama_client.KEEP_ALIVE,
            # A one-word verdict, and no sampling, so the same pair always
            # scores the same way.
            "options": {"num_ctx": 8192, "num_predict": 4, "temperature": 0},
        })
        self.calls += 1

        reply = response.get("response", "")
        verdict = "YES" in reply.strip().upper()
        self.cache[key] = verdict
        return verdict


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


def score_record(record, question, judge=None):
    read = sections_read(record)
    context = record.get("context_text", "")

    facets = []
    for facet in question["facets"]:
        if facet.get("scoring") == "judge":
            if judge is None:
                # Counting these as misses would understate every condition by
                # the same large amount and look like a result.
                facets.append({
                    "id": facet["id"],
                    "source_section": facet["source_section"],
                    "scoring": "judge",
                    "verdict": "unscored",
                })
                continue
            in_answer = judge.says(facet["element"], record["answer"])
            in_context = judge.says(facet["element"], context)
        else:
            in_answer = facet_matches(facet, record["answer"])
            in_context = facet_matches(facet, context)

        if in_answer:
            verdict = "hit"
        elif in_context:
            verdict = "generation miss"
        else:
            verdict = "navigation miss"

        facets.append({
            "id": facet["id"],
            "source_section": facet["source_section"],
            "scoring": facet.get("scoring", "regex"),
            # Only meaningful for cli, where reaching a section is a choice.
            "source_read": facet["source_section"] in read if read else None,
            "in_context": in_context,
            "in_answer": in_answer,
            "verdict": verdict,
        })

    scored = [facet for facet in facets if facet["verdict"] != "unscored"]
    covered = sum(1 for facet in scored if facet["in_answer"])
    return {
        "covered": covered,
        "total": len(scored),
        "unscored": len(facets) - len(scored),
        "coverage": covered / len(scored) if scored else 0.0,
        "sections_read": read,
        "facets": facets,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="?", default=os.path.join(ANALYSIS, "results"))
    parser.add_argument("--questions", default=os.path.join(ANALYSIS, "questions.json"))
    parser.add_argument("--workspace", default=os.path.join(REPO, "PMC11289285-test"))
    parser.add_argument("--json", help="also write the full per-facet scores here")
    parser.add_argument("--judge", nargs="?", const="gemma2:9b", default=None,
                        metavar="MODEL",
                        help="score the judge facets with this local model "
                             "(default gemma2:9b). Without it they are left "
                             "unscored and reported separately.")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    by_id = {question["id"]: question for question in questions["questions"]}

    judge = Judge(args.judge) if args.judge else None

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
        entry = score_record(record, question, judge)
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
