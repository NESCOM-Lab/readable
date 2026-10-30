#!/usr/bin/env python3
"""Check whether the claims in each recorded answer are supported by the paper.

score.py measures whether expected content appears; it cannot tell a correct
statement from a confident wrong one. This splits each answer into sentences,
retrieves the passages of the paper nearest each sentence, and asks a judge
model whether the passage actually says it.

The judge defaults to a different model family from the one under test, so it
is not grading its own output. It is still a model, so every verdict is written
out with the evidence it saw and is meant to be read, not trusted blindly.
"""

import argparse
import glob
import json
import os
import re
import urllib.request

import ollama_client

from run_eval import build_chunks, chunk_vectors, cosine, embed, load_paper

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS = os.path.join(REPO, "analysis")

JUDGE_MODEL = "gemma2:9b"
OLLAMA = ollama_client.ollama_url()
EVIDENCE_CHUNKS = 3

# Periods that do not end a sentence.
ABBREVIATIONS = ("et al.", "Fig.", "Figs.", "e.g.", "i.e.", "vs.", "approx.", "ca.", "Dr.")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")

JUDGE_PROMPT = """You are checking one claim against excerpts from a scientific paper.

EXCERPTS:
{evidence}

CLAIM: {claim}

Answer SUPPORTED only if the excerpts directly state the claim. Answer NOT_SUPPORTED
if the excerpts do not state it, only raise it as a possibility, or state something
different. Reply with one word: SUPPORTED or NOT_SUPPORTED."""


def split_claims(answer):
    """Split an answer into sentence-sized claims.

    Deterministic on purpose: an LLM splitting step would add a second place for
    the verification to go wrong, and these answers are only a paragraph long.
    """
    text = " ".join(answer.replace("**", "").split())
    for abbreviation in ABBREVIATIONS:
        text = text.replace(abbreviation, abbreviation.replace(".", "\0"))

    claims = []
    for piece in SENTENCE_END.split(text):
        piece = piece.replace("\0", ".").strip()
        # Drop the list scaffolding models put in front of a sentence.
        piece = re.sub(r"^[(\[]?\d+[)\].:]\s*", "", piece)
        piece = re.sub(r"^[-*•]\s*", "", piece)
        piece = piece.strip(" *_:")
        if len(piece) >= 30:
            claims.append(piece)
    return claims


def judge(claim, evidence, model):
    body = {
        "model": model,
        "prompt": JUDGE_PROMPT.format(evidence=evidence, claim=claim),
        "stream": False,
        "think": False,
        "options": {"num_predict": 10, "temperature": 0},
    }
    request = urllib.request.Request(
        OLLAMA + "/api/generate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        reply = json.load(response).get("response", "").strip().upper()

    if "NOT_SUPPORTED" in reply or "NOT SUPPORTED" in reply:
        return "not supported"
    if "SUPPORTED" in reply:
        return "supported"
    return "unclear"


def evidence_for(claim, chunks, vectors):
    claim_vector = embed(claim)
    ranked = sorted(
        range(len(chunks)),
        key=lambda index: cosine(claim_vector, vectors[index]),
        reverse=True,
    )
    top = [chunks[index] for index in ranked[:EVIDENCE_CHUNKS]]
    return "\n\n".join(f"[{section}] {text}" for section, text in top)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="?", default=os.path.join(ANALYSIS, "results"))
    parser.add_argument("--workspace", default=os.path.join(REPO, "PMC11289285-test"))
    parser.add_argument("--judge", default=JUDGE_MODEL)
    parser.add_argument("--out", default=os.path.join(ANALYSIS, "verification.json"))
    parser.add_argument("--condition", action="append")
    args = parser.parse_args()

    full_text, section_files, abstract = load_paper(args.workspace)
    chunks = build_chunks(section_files, abstract)
    vectors, _ = chunk_vectors(chunks, args.workspace)
    print(f"[setup] {len(chunks)} chunks, judging with {args.judge}\n")

    verdicts = []
    paths = sorted(glob.glob(os.path.join(args.results, "*.json")))
    for number, path in enumerate(paths, start=1):
        with open(path) as handle:
            record = json.load(handle)
        if args.condition and record["condition"] not in args.condition:
            continue

        claims = split_claims(record["answer"])
        print(f"[{number}/{len(paths)}] {os.path.basename(path)}: {len(claims)} claims")

        for claim in claims:
            evidence = evidence_for(claim, chunks, vectors)
            verdicts.append({
                "question_id": record["question_id"],
                "condition": record["condition"],
                "run": record["run"],
                "claim": claim,
                "verdict": judge(claim, evidence, args.judge),
                "evidence": evidence,
            })

    with open(args.out, "w") as handle:
        json.dump(verdicts, handle, indent=2)

    report(verdicts)
    print(f"\nwrote {len(verdicts)} judged claims to {args.out}")


def report(verdicts):
    conditions = []
    for verdict in verdicts:
        if verdict["condition"] not in conditions:
            conditions.append(verdict["condition"])

    print("\nCLAIM SUPPORT BY CONDITION")
    print(f"{'condition':<10} {'claims':>8} {'supported':>11} {'not supported':>15} {'unclear':>9}")
    for condition in sorted(conditions):
        entries = [v for v in verdicts if v["condition"] == condition]
        total = len(entries)
        counts = {name: sum(1 for v in entries if v["verdict"] == name)
                  for name in ["supported", "not supported", "unclear"]}
        print(f"{condition:<10} {total:>8} {counts['supported'] / total:>10.0%} "
              f"{counts['not supported'] / total:>14.0%} {counts['unclear'] / total:>8.0%}")

    unsupported = [v for v in verdicts if v["verdict"] == "not supported"]
    if unsupported:
        print(f"\nUNSUPPORTED CLAIMS ({len(unsupported)})")
        for verdict in unsupported:
            label = f"{verdict['question_id']}/{verdict['condition']}/run{verdict['run']}"
            print(f"  {label:<22} {verdict['claim'][:110]}")


if __name__ == "__main__":
    main()
