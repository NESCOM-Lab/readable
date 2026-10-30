#!/usr/bin/env python3
"""Compare Raw vs RAG for reading one paper with qwen3.5:9b via ollama."""
import json, time, re, glob, os, urllib.request, math

OLLAMA = "http://127.0.0.1:11434"
MODEL = "qwen3.5:9b"
EMBED_MODEL = "nomic-embed-text"
WS = "PMC11289285-test"

QUESTION = (
    "Explain how adult neurogenesis improves spatial information encoding in the "
    "mouse hippocampus. Include: (1) the experimental manipulations used, "
    "(2) the measured neural effects, (3) the proposed mechanism, and "
    "(4) how this contrasts with prior views. Answer in under 200 words."
)

def post(path, payload):
    req = urllib.request.Request(OLLAMA + path,
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)

def generate(prompt, num_ctx):
    t = time.time()
    resp = post("/api/generate", {
        "model": MODEL, "prompt": prompt, "stream": False, "think": False,
        "options": {"num_ctx": num_ctx, "num_predict": 500, "temperature": 0.2},
    })
    return {
        "answer": resp.get("response", "").strip(),
        "prompt_tokens": resp.get("prompt_eval_count", 0),
        "output_tokens": resp.get("eval_count", 0),
        "seconds": round(time.time() - t, 1),
    }

def embed(text):
    return post("/api/embeddings", {"model": EMBED_MODEL, "prompt": text})["embedding"]

def cosine(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(x*x for x in b))
    return dot / (na*nb + 1e-9)

# --- assemble full paper text from the parsed workspace ---
meta = json.load(open(f"{WS}/metadata.json"))
parts = [f"# {meta.get('title','')}", f"\nAbstract: {meta.get('abstract_text','')}\n"]
section_files = sorted(glob.glob(f"{WS}/sections/*.md"))
for path in section_files:
    text = open(path).read()
    text = re.sub(r"<!--.*?-->", "", text)          # strip provenance comments
    parts.append(text.strip())
full_text = "\n\n".join(p for p in parts if p.strip())
print(f"[setup] full paper text: {len(full_text)} chars, {len(section_files)} section files")

# --- build RAG chunks (~700 chars, paragraph-aware) ---
chunks = []
for path in section_files:
    sec = os.path.basename(path)
    body = re.sub(r"<!--.*?-->", "", open(path).read())
    for para in re.split(r"\n\s*\n", body):
        para = " ".join(para.split())
        if len(para) < 40:
            continue
        while len(para) > 900:
            chunks.append((sec, para[:900])); para = para[900:]
        chunks.append((sec, para))
print(f"[setup] {len(chunks)} RAG chunks")

results = {}

# ================= CONDITION 1: RAW =================
print("\n[raw] generating...")
raw_prompt = (
    "You are reading a scientific paper. Use ONLY the paper below.\n\n"
    f"=== PAPER ===\n{full_text}\n=== END PAPER ===\n\nQuestion: {QUESTION}"
)
results["raw"] = generate(raw_prompt, num_ctx=32768)
results["raw"]["context_chars"] = len(raw_prompt)
print(f"[raw] {results['raw']['prompt_tokens']} prompt tok, {results['raw']['seconds']}s")

# ================= CONDITION 2: RAG =================
print("\n[rag] embedding chunks...")
t0 = time.time()
chunk_vecs = [embed(c[1]) for c in chunks]
qvec = embed(QUESTION)
scored = sorted(range(len(chunks)), key=lambda i: cosine(qvec, chunk_vecs[i]), reverse=True)
topk = scored[:6]
retrieved = [chunks[i] for i in topk]
embed_secs = round(time.time() - t0, 1)
context = "\n\n".join(f"[{sec}] {txt}" for sec, txt in retrieved)
rag_prompt = (
    "Answer using ONLY these retrieved excerpts from a paper.\n\n"
    f"=== EXCERPTS ===\n{context}\n=== END ===\n\nQuestion: {QUESTION}"
)
results["rag"] = generate(rag_prompt, num_ctx=8192)
results["rag"]["context_chars"] = len(rag_prompt)
results["rag"]["embed_seconds"] = embed_secs
results["rag"]["retrieved_from"] = [sec for sec, _ in retrieved]
print(f"[rag] retrieved from {results['rag']['retrieved_from']}")
print(f"[rag] {results['rag']['prompt_tokens']} prompt tok, {results['rag']['seconds']}s (+{embed_secs}s embed)")

json.dump(results, open("/private/tmp/claude-501/-Users-abhishekkakolla-code-curve-readable/a11cc026-592d-43f1-b19e-09be5652dcc3/scratchpad/results.json", "w"), indent=2)

for name in ["raw", "rag"]:
    print(f"\n========== {name.upper()} ANSWER ==========")
    print(results[name]["answer"])
