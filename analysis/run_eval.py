#!/usr/bin/env python3
"""Run the raw / rag / rag_flat / cli conditions over a paper workspace.

Every condition is asked the same question from questions.json and records the
text it put in front of the model, which is what score.py needs to tell a
navigation miss from a generation miss.

rag and cli draw on the same pool of structured retrieval units, so rag is the
no-agency ablation of cli rather than a different system. rag_flat is the
earlier approach, top-k over slices of the rendered markdown, kept so the run
shows what that flattening cost.
"""

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import time

import bm25
import similar
from ollama_client import KEEP_ALIVE, MODEL, cosine, embed, post

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS = os.path.join(REPO, "analysis")

PGRAPH = os.path.join(REPO, "target", "release", "pgraph")

TEMPERATURE = 0.2
RAW_NUM_CTX = 32768
RAG_NUM_CTX = 8192
CLI_NUM_CTX = 16384
NUM_PREDICT = 500

CHUNK_CHARS = 900
RAG_TOP_K = 6
CLI_TOP_K = 5

CONDITIONS = ["closedbook", "bm25", "raw", "rag", "rag_flat", "cli"]


def generate(prompt, num_ctx, stop=None):
    options = {
        "num_ctx": num_ctx,
        "num_predict": NUM_PREDICT,
        "temperature": TEMPERATURE,
    }
    if stop:
        options["stop"] = stop

    started = time.time()
    response = post("/api/generate", {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "keep_alive": KEEP_ALIVE,
        "options": options,
    })
    return {
        "answer": response.get("response", "").strip(),
        "prompt_tokens": response.get("prompt_eval_count", 0),
        "output_tokens": response.get("eval_count", 0),
        "seconds": round(time.time() - started, 1),
    }


def strip_provenance(text):
    """Drop the provenance HTML comments, which are noise in a prompt."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def load_paper(workspace):
    """Title, abstract and every section file, joined into one document."""
    with open(os.path.join(workspace, "metadata.json")) as handle:
        metadata = json.load(handle)

    abstract = metadata.get("abstract_text", "") or ""

    parts = [
        f"# {metadata.get('title', '')}",
        f"\nAbstract: {metadata.get('abstract_text', '')}\n",
    ]
    section_files = sorted(glob.glob(os.path.join(workspace, "sections", "*.md")))
    for path in section_files:
        with open(path) as handle:
            parts.append(strip_provenance(handle.read()).strip())

    full_text = "\n\n".join(part for part in parts if part.strip())
    return full_text, section_files, abstract


def build_chunks(section_files, abstract=""):
    """Paragraph-aware chunks, splitting anything longer than CHUNK_CHARS.

    The abstract is a chunk of its own. It is not one of the rendered section
    files, but the unit pool the other conditions search does contain it, and
    leaving it out here would be a difference in what the two pools hold rather
    than in how they are addressed.
    """
    chunks = []
    abstract = " ".join(abstract.split())
    if len(abstract) >= 40:
        remaining = abstract
        while len(remaining) > CHUNK_CHARS:
            chunks.append(("abstract", remaining[:CHUNK_CHARS]))
            remaining = remaining[CHUNK_CHARS:]
        chunks.append(("abstract", remaining))

    for path in section_files:
        section = os.path.basename(path)
        with open(path) as handle:
            body = strip_provenance(handle.read())

        for paragraph in re.split(r"\n\s*\n", body):
            paragraph = " ".join(paragraph.split())
            if len(paragraph) < 40:
                continue
            while len(paragraph) > CHUNK_CHARS:
                chunks.append((section, paragraph[:CHUNK_CHARS]))
                paragraph = paragraph[CHUNK_CHARS:]
            chunks.append((section, paragraph))
    return chunks


def chunk_vectors(chunks, workspace):
    """Embed the chunks, reusing a cached run when the chunks are unchanged."""
    fingerprint = hashlib.sha256(
        "\n".join(text for _, text in chunks).encode()
    ).hexdigest()[:16]
    cache_dir = os.path.join(ANALYSIS, ".embed_cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(
        cache_dir, f"{os.path.basename(workspace.rstrip('/'))}_{fingerprint}.json"
    )

    if os.path.exists(cache_path):
        with open(cache_path) as handle:
            return json.load(handle), 0.0

    started = time.time()
    vectors = [embed(text) for _, text in chunks]
    with open(cache_path, "w") as handle:
        json.dump(vectors, handle)
    return vectors, round(time.time() - started, 1)


def run_raw(question, paper):
    prompt = (
        "You are reading a scientific paper. Use ONLY the paper below.\n\n"
        f"=== PAPER ===\n{paper['full_text']}\n=== END PAPER ===\n\n"
        f"Question: {question}"
    )
    record = generate(prompt, RAW_NUM_CTX)
    record["context_chars"] = len(prompt)
    record["context_text"] = paper["full_text"]
    return record


def run_rag(question, paper):
    """Top-k over the same structured units the cli condition searches, with no
    agency: one query, one answer. The ablation of the cli loop."""
    hits, _ = similar.search(question, paper["units"], paper["unit_vectors"], RAG_TOP_K)
    context = "\n\n".join(f"[{hit['location'] or hit['origin']}] {hit['text']}" for hit in hits)

    prompt = (
        "Answer using ONLY these retrieved excerpts from a paper.\n\n"
        f"=== EXCERPTS ===\n{context}\n=== END ===\n\nQuestion: {question}"
    )
    record = generate(prompt, RAG_NUM_CTX)
    record["context_chars"] = len(prompt)
    record["context_text"] = context
    record["retrieved_from"] = [hit["id"] for hit in hits]
    return record


def run_rag_flat(question, paper):
    """The original condition: top-k over 900-char slices of the rendered
    markdown, whose only address is one of five file names."""
    question_vector = embed(question)
    ranked = sorted(
        range(len(paper["chunks"])),
        key=lambda index: cosine(question_vector, paper["chunk_vectors"][index]),
        reverse=True,
    )
    retrieved = [paper["chunks"][index] for index in ranked[:RAG_TOP_K]]
    context = "\n\n".join(f"[{section}] {text}" for section, text in retrieved)

    prompt = (
        "Answer using ONLY these retrieved excerpts from a paper.\n\n"
        f"=== EXCERPTS ===\n{context}\n=== END ===\n\nQuestion: {question}"
    )
    record = generate(prompt, RAG_NUM_CTX)
    record["context_chars"] = len(prompt)
    record["context_text"] = context
    record["retrieved_from"] = [section for section, _ in retrieved]
    return record


def run_closedbook(question, paper):
    """No retrieval at all. Whatever this answers came out of the model's own
    weights, which is the measure of how much of a score the corpus earned."""
    prompt = (
        "Answer this question about the scientific literature. "
        "If you do not know, say so.\n\n"
        f"Question: {question}"
    )
    record = generate(prompt, RAG_NUM_CTX)
    record["context_chars"] = 0
    record["context_text"] = ""
    return record


def run_bm25(question, paper):
    """Sparse lexical retrieval over the same units as 'rag', so the pair
    separates what the embeddings earned from what term overlap alone gets."""
    ranked = paper["bm25"].score(question, RAG_TOP_K)
    hits = [paper["units"][index] for index in ranked]
    context = "\n\n".join(
        f"[{hit.get('location') or hit['origin']}] {hit['text']}" for hit in hits
    )

    prompt = (
        "Answer using ONLY these retrieved excerpts from a paper.\n\n"
        f"=== EXCERPTS ===\n{context}\n=== END ===\n\nQuestion: {question}"
    )
    record = generate(prompt, RAG_NUM_CTX)
    record["context_chars"] = len(prompt)
    record["context_text"] = context
    record["retrieved_from"] = [hit["id"] for hit in hits]
    return record


CLI_SYSTEM = """You are answering a question about a scientific paper by exploring it
through a command-line tool. You CANNOT see the paper directly. Each turn, emit
EXACTLY ONE line, either an action or your final answer:

ACTION: outline                 -> list the sections (ids, file names, titles)
ACTION: section <id>            -> read one section's full text
ACTION: similar <text>          -> find passages that mean the same thing
ACTION: similar <text> in <id>  -> the same, inside one section and its parts
ACTION: search <term>           -> find passages containing a term, exactly
ANSWER: <your final answer>     -> when you have enough information

Rules: one line only, start with ACTION: or ANSWER:. Use section ids from the
outline. Prefer 'similar' when you do not know the author's wording, and
'search' when you know the exact term. Every 'similar' hit names the section it
came from, so you can read that section in full next.

A question usually has several parts. Take them one at a time: look up the part
you have the least evidence for, read what you find, and only answer once every
part is covered. Question:
{question}"""


def run_pgraph(args, budget):
    """One pgraph call, bounded by 'budget' characters."""
    try:
        finished = subprocess.run(
            [PGRAPH, "query", *args], capture_output=True, text=True, timeout=30
        )
        text = finished.stdout if finished.returncode == 0 else f"(error: {finished.stderr.strip()})"
    except Exception as error:
        text = f"(error: {error})"

    return bound(text, budget)


def bound(text, budget):
    """Cut an observation to the budget, saying so when it bites. Slicing
    pretty-printed JSON silently would leave the model holding invalid JSON with
    nothing to show that anything was missing."""
    full_chars = len(text)
    truncated = budget > 0 and full_chars > budget
    if truncated:
        text = text[:budget] + (
            f"\n\n[truncated: showed {budget} of {full_chars} characters. "
            "Narrow the query, or read one section at a time.]"
        )
    return text, full_chars, truncated


def run_similar(query, paper, budget, section=None):
    """One semantic search, formatted like a pgraph observation."""
    hits, searched = similar.search(
        query, paper["units"], paper["unit_vectors"], CLI_TOP_K, section,
    )
    if searched == 0 and section:
        text = (f"(no units under section '{section}'; check the id against the "
                "outline, or drop the 'in' to search the whole paper)")
        return bound(text, budget)

    result = {"searched": searched, "shown": len(hits), "hits": hits}
    if section:
        result["scope"] = section
    return bound(json.dumps(result, indent=2), budget)


SCOPE_SUFFIX = re.compile(r"\s+in\s+([A-Za-z]+\d+)\s*$", re.I)


def split_scope(argument):
    """Peel a trailing 'in Sec12' off a similar query.

    Anchored at the end and limited to an id-shaped word, so an ordinary query
    that happens to contain ' in ' keeps all of its words.
    """
    match = SCOPE_SUFFIX.search(argument)
    if not match:
        return argument, None
    return argument[: match.start()].strip(), match.group(1)


def parse_action(reply):
    match = re.search(r"ANSWER:\s*(.*)", reply, re.S)
    if match and match.group(1).strip():
        return ("answer", match.group(1).strip())

    # Take the rest of the line as the argument, so multi-word searches work.
    match = re.search(r"ACTION:\s*(outline|section|search|similar)[ \t]*([^\n]*)", reply, re.I)
    if match:
        return (match.group(1).lower(), clean_argument(match.group(2)))
    return (None, reply)


def clean_argument(argument):
    """Strip the quoting a model tends to put around its own search terms.

    Quotes otherwise reach pgraph as part of the pattern, so a quoted search
    matches nothing at all.
    """
    argument = argument.strip()
    while len(argument) >= 2 and argument[0] == argument[-1] and argument[0] in "\"'`":
        argument = argument[1:-1].strip()
    return argument.strip(" .,;:")


def run_cli(question, paper, budget, max_steps, seed_similar=True, min_steps=0):
    workspace = paper["workspace"]
    messages = [("system", CLI_SYSTEM.format(question=question))]

    # Seed with the outline so the model starts oriented: structure, no content.
    observation, full_chars, truncated = run_pgraph(["outline", workspace], budget)
    steps = [{
        "action": "outline (seeded)",
        "observation": observation,
        "full_chars": full_chars,
        "truncated": truncated,
    }]
    messages.append(("user", f"OBSERVATION (outline):\n{observation}"))

    # Then with the passages closest to the question, so the agent starts where
    # the rag condition stops and navigates on from there. Each hit names its
    # section, which is the handle for reading further.
    if seed_similar:
        observation, full_chars, truncated = run_similar(question, paper, budget)
        steps.append({
            "action": "similar (seeded)",
            "observation": observation,
            "full_chars": full_chars,
            "truncated": truncated,
        })
        messages.append((
            "user",
            f"OBSERVATION (passages closest to the question):\n{observation}",
        ))

    messages.append(("user", "Choose your next action."))

    started = time.time()
    prompt_tokens = 0
    output_tokens = 0
    final_answer = None
    step = 0
    actions_taken = 0
    deferrals = 0
    opened = []

    for step in range(1, max_steps + 1):
        prompt = ""
        for role, content in messages:
            prompt += f"{role.upper()}: {content}\n"
        prompt += "ASSISTANT:"

        reply = generate(prompt, CLI_NUM_CTX, stop=["\nUSER:", "\nSYSTEM:"])
        prompt_tokens += reply["prompt_tokens"]
        output_tokens += reply["output_tokens"]

        text = reply["answer"]
        first_line = next((line for line in text.splitlines() if line.strip()), text)
        kind, argument = parse_action(text if "ANSWER:" in text else first_line)
        print(f"    [step {step}] {first_line[:100]}")

        # Answering after one or two lookups is the main way a run loses
        # coverage: the facts it misses sit in sections it never opened. Hold
        # it to a floor of exploration, while there is still room to explore.
        if kind == "answer" and actions_taken < min_steps and step < max_steps - 1:
            deferrals += 1
            seen = ", ".join(opened) if opened else "none yet"
            observation = (
                f"Not yet. You have taken {actions_taken} of at least {min_steps} "
                f"lookups, and the sections you have read in full are: {seen}. "
                "Pick the part of the question you have the least evidence for and "
                "look it up: 'similar <text>' finds passages by meaning when you do "
                "not know the wording, and 'similar <text> in <id>' searches inside "
                "one section."
            )
            steps.append({
                "action": first_line,
                "observation": observation,
                "full_chars": len(observation),
                "truncated": False,
                # Scoring asks whether a fact was in the text the model was
                # shown. This step is the harness talking, not the paper, so it
                # is kept out of that text.
                "from_paper": False,
            })
            messages.append(("assistant", first_line))
            messages.append(("user", f"OBSERVATION:\n{observation}\nChoose your next action."))
            continue

        if kind == "answer":
            final_answer = argument
            break
        elif kind == "outline":
            command = ["outline", workspace]
        elif kind == "section" and argument:
            command = ["section", workspace, argument]
            if argument not in opened:
                opened.append(argument)
        elif kind == "search" and argument:
            command = ["search", workspace, argument]
        else:
            command = None

        if kind == "similar" and argument:
            query, scope = split_scope(argument)
            observation, full_chars, truncated = run_similar(query, paper, budget, scope)
        elif command is None:
            observation, full_chars, truncated = (
                "(unrecognized action; reply with exactly ACTION: outline | "
                "section <id> | similar <text> | search <term>, or ANSWER: ...)",
                0, False,
            )
        else:
            observation, full_chars, truncated = run_pgraph(command, budget)

        actions_taken += 1

        steps.append({
            "action": first_line,
            "observation": observation,
            "full_chars": full_chars,
            "truncated": truncated,
        })
        # No point asking for another action on the last turn.
        if step >= max_steps - 1:
            nudge = "This is your final turn. Reply now with ANSWER: and your best answer."
        else:
            nudge = "Choose your next action (or ANSWER: if ready)."

        messages.append(("assistant", first_line))
        messages.append(("user", f"OBSERVATION:\n{observation}\n{nudge}"))

    # A run that spent its whole budget exploring still has what it read in
    # context, so ask once for an answer rather than recording nothing.
    forced = False
    if final_answer is None:
        forced = True
        messages.append((
            "user",
            "Stop exploring. Reply now with ANSWER: and your best answer from what you have read.",
        ))
        prompt = ""
        for role, content in messages:
            prompt += f"{role.upper()}: {content}\n"
        prompt += "ASSISTANT:"

        reply = generate(prompt, CLI_NUM_CTX, stop=["\nUSER:", "\nSYSTEM:"])
        prompt_tokens += reply["prompt_tokens"]
        output_tokens += reply["output_tokens"]
        kind, argument = parse_action(reply["answer"])
        if kind == "answer":
            final_answer = argument
        else:
            # Still no answer; keep whatever it said rather than an empty string.
            final_answer = reply["answer"].strip() or None
        print(f"    [forced answer] {(final_answer or '(none)')[:90]}")

    # Coverage is scored against what the model saw, so the observations as
    # delivered, not the full CLI output behind them.
    context_text = "\n\n".join(entry["observation"] for entry in steps
                                if entry.get("from_paper", True))

    return {
        "answer": final_answer or "(no ANSWER emitted within step budget)",
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "seconds": round(time.time() - started, 1),
        "context_chars": len(context_text),
        "context_text": context_text,
        "steps_used": step,
        "actions_taken": actions_taken,
        "answer_deferrals": deferrals,
        "min_steps": min_steps,
        "steps": steps,
        "answered": final_answer is not None,
        "forced_answer": forced,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=os.path.join(REPO, "PMC11289285-test"))
    parser.add_argument("--questions", default=os.path.join(ANALYSIS, "questions.json"))
    parser.add_argument("--out", default=os.path.join(ANALYSIS, "results"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--condition", action="append", choices=CONDITIONS,
                        help="restrict to one condition; repeatable")
    parser.add_argument("--question", action="append",
                        help="restrict to one question id; repeatable")
    parser.add_argument("--observation-budget", type=int, default=20000,
                        help="characters of CLI output shown per step; 0 for no limit")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--min-steps", type=int, default=4,
                        help="lookups required before an ANSWER is accepted; 0 disables")
    parser.add_argument("--no-seed-similar", action="store_true",
                        help="do not hand the cli agent the semantic hits up front")
    args = parser.parse_args()

    conditions = args.condition or CONDITIONS

    with open(args.questions) as handle:
        questions = json.load(handle)["questions"]
    if args.question:
        questions = [q for q in questions if q["id"] in args.question]
    if not questions:
        parser.error("no questions selected")

    # Questions can name their own paper, since an evaluation set usually asks
    # about several. Loading is cached, so a paper shared by two questions is
    # read and embedded once.
    loaded = {}

    def paper_for(question):
        workspace = question.get("workspace", args.workspace)
        if not os.path.isabs(workspace):
            workspace = os.path.join(REPO, workspace)
        if workspace in loaded:
            return loaded[workspace]

        full_text, section_files, abstract = load_paper(workspace)
        paper = {"workspace": workspace, "full_text": full_text}
        name = os.path.basename(workspace.rstrip("/"))
        print(f"[setup] {name}: {len(full_text)} chars across {len(section_files)} section files")

        if {"rag", "cli", "bm25"} & set(conditions):
            paper["units"], paper["unit_vectors"] = similar.load_index(workspace)
            print(f"[setup] {name}: {len(paper['units'])} retrieval units")

        if "bm25" in conditions:
            paper["bm25"] = bm25.Index([unit["text"] for unit in paper["units"]])

        if "rag_flat" in conditions:
            paper["chunks"] = build_chunks(section_files, abstract)
            paper["chunk_vectors"], embed_seconds = chunk_vectors(paper["chunks"], workspace)
            print(f"[setup] {name}: {len(paper['chunks'])} markdown chunks, "
                  f"embedded in {embed_seconds}s{' (cached)' if embed_seconds == 0 else ''}")

        loaded[workspace] = paper
        return paper

    os.makedirs(args.out, exist_ok=True)
    total = len(questions) * len(conditions) * args.runs
    done = 0

    for question in questions:
        for condition in conditions:
            for run in range(1, args.runs + 1):
                done += 1
                print(f"\n[{done}/{total}] {question['id']} / {condition} / run {run}")

                paper = paper_for(question)

                if condition == "raw":
                    record = run_raw(question["question"], paper)
                elif condition == "closedbook":
                    record = run_closedbook(question["question"], paper)
                elif condition == "bm25":
                    record = run_bm25(question["question"], paper)
                elif condition == "rag":
                    record = run_rag(question["question"], paper)
                elif condition == "rag_flat":
                    record = run_rag_flat(question["question"], paper)
                else:
                    record = run_cli(question["question"], paper,
                                     args.observation_budget, args.max_steps,
                                     not args.no_seed_similar, args.min_steps)

                record["question_id"] = question["id"]
                record["condition"] = condition
                record["run"] = run
                record["model"] = MODEL
                record["workspace"] = os.path.basename(paper["workspace"].rstrip("/"))
                record["observation_budget"] = args.observation_budget

                path = os.path.join(args.out, f"{question['id']}_{condition}_run{run}.json")
                with open(path, "w") as handle:
                    json.dump(record, handle, indent=2)

                print(f"    {record['prompt_tokens']} prompt tok, "
                      f"{record['output_tokens']} out tok, {record['seconds']}s "
                      f"-> {os.path.basename(path)}")

    print(f"\nwrote {total} records to {args.out}/")


if __name__ == "__main__":
    main()
