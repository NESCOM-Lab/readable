#!/usr/bin/env python3
"""CLI condition, take 2: a minimal ReAct loop that drives the pgraph CLI with
qwen3.5:9b using a forgiving text protocol (the model failed opencode's strict
tool-calling, so we parse its plain text instead)."""
import json, time, re, subprocess, urllib.request

OLLAMA = "http://127.0.0.1:11434"
MODEL = "qwen3.5:9b"
WS = "PMC11289285-test"
PGRAPH = "target/release/pgraph"
MAX_STEPS = 6

QUESTION = (
    "Explain how adult neurogenesis improves spatial information encoding in the "
    "mouse hippocampus. Include (1) the experimental manipulations, (2) the measured "
    "neural effects, (3) the proposed mechanism, and (4) how it contrasts with prior "
    "views. Answer in under 200 words."
)

SYSTEM = f"""You are answering a question about a scientific paper by exploring it
through a command-line tool. You CANNOT see the paper directly. Each turn, emit
EXACTLY ONE line, either an action or your final answer:

ACTION: outline                 -> list the sections (ids + titles)
ACTION: section <id>            -> read one section's full text
ACTION: search <word>           -> find paragraphs containing a word
ANSWER: <your final answer>     -> when you have enough information

Rules: one line only, start with ACTION: or ANSWER:. Use section ids from the
outline. Gather evidence with a few actions, then give ANSWER. Question:
{QUESTION}"""

def generate(messages):
    prompt = ""
    for role, content in messages:
        prompt += f"{role.upper()}: {content}\n"
    prompt += "ASSISTANT:"
    req = urllib.request.Request(OLLAMA + "/api/generate",
        data=json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                         "think": False, "options": {"num_ctx": 16384,
                         "num_predict": 400, "temperature": 0.2, "stop": ["\nUSER:", "\nSYSTEM:"]}}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.load(r)
    return resp.get("response", "").strip(), resp.get("prompt_eval_count", 0), resp.get("eval_count", 0)

def run_pgraph(args):
    try:
        out = subprocess.run([PGRAPH, "query", *args, ], capture_output=True, text=True, timeout=20)
        text = out.stdout if out.returncode == 0 else f"(error: {out.stderr.strip()})"
    except Exception as e:
        text = f"(error: {e})"
    return text[:3000]  # keep observations bounded

def parse_action(line):
    line = line.strip()
    m = re.search(r"ANSWER:\s*(.*)", line, re.S)
    if m and m.group(1).strip():
        return ("answer", m.group(1).strip())
    m = re.search(r"ACTION:\s*(outline|section|search)\s*(\S+)?", line, re.I)
    if m:
        return (m.group(1).lower(), (m.group(2) or "").strip())
    return (None, line)

messages = [("system", SYSTEM)]
# seed with the outline so the model starts oriented (structure only, no answer content)
outline = run_pgraph(["outline", WS])
messages.append(("user", f"OBSERVATION (outline):\n{outline}\nChoose your next action."))

t0 = time.time()
total_prompt_tok = 0
total_out_tok = 0
transcript = []
final_answer = None

for step in range(1, MAX_STEPS + 1):
    reply, ptok, otok = generate(messages)
    total_prompt_tok += ptok; total_out_tok += otok
    first_line = next((l for l in reply.splitlines() if l.strip()), reply)
    kind, arg = parse_action(reply if "ANSWER:" in reply else first_line)
    transcript.append(f"[step {step}] model: {first_line[:200]}")
    print(f"[step {step}] {first_line[:120]}")

    if kind == "answer":
        final_answer = arg
        break
    elif kind == "outline":
        obs = run_pgraph(["outline", WS])
    elif kind == "section" and arg:
        obs = run_pgraph(["section", WS, arg])
    elif kind == "search" and arg:
        obs = run_pgraph(["search", WS, arg])
    else:
        obs = "(unrecognized action; reply with exactly ACTION: outline|section <id>|search <word>, or ANSWER: ...)"

    messages.append(("assistant", first_line))
    messages.append(("user", f"OBSERVATION:\n{obs}\nChoose your next action (or ANSWER: if ready)."))

elapsed = round(time.time() - t0, 1)
result = {
    "steps_used": step,
    "prompt_tokens": total_prompt_tok,
    "output_tokens": total_out_tok,
    "seconds": elapsed,
    "answer": final_answer or "(no ANSWER emitted within step budget)",
    "transcript": transcript,
}
json.dump(result, open("analysis/cli_react_result.json", "w"), indent=2)
print(f"\n=== steps={step} prompt_tok={total_prompt_tok} out_tok={total_out_tok} {elapsed}s ===")
print("\n=== CLI (ReAct) ANSWER ===")
print(result["answer"])
