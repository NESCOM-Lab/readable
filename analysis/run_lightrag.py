#!/usr/bin/env python3
"""Run the questions through LightRAG, as the graph-based comparator.

LightRAG builds a knowledge graph by asking an LLM to pull entities and
relations out of every chunk, then answers by retrieving over that graph. It is
the published method closest to what the evaluation spec calls Graph RAG, so it
stands in for that column rather than this repo reimplementing one.

It needs its own virtualenv, because it pulls in a large dependency tree that
does not belong in the harness. Point --python at that interpreter. The same
ollama models the rest of the evaluation uses are used here, so only the
retrieval representation differs.

Records are written in the shape score.py expects, so the result lands in the
same table as the other conditions.
"""

import argparse
import asyncio
import json
import os
import time
import urllib.request

import ollama_client

MODEL = "qwen3.5:9b"
EMBED_MODEL = "nomic-embed-text"
OLLAMA = ollama_client.ollama_url()

# Same budget as the other retrieval conditions, so the comparison is about
# representation and not about how much text each one is allowed to show.
TOP_K = 6


# LightRAG ships an ollama embedding helper, but it is declared for bge-m3 and
# carries a hard 1024 dimension, so every call with a 768-dimension model fails
# the library's own shape check. The rest of this evaluation embeds with
# nomic-embed-text, and the comparison is only fair if the graph system uses the
# same model, so the call is made here instead.
EMBED_DIM = 768


async def embed_texts(texts, **ignored):
    import numpy as np

    def fetch(text):
        request = urllib.request.Request(
            OLLAMA + "/api/embeddings",
            data=json.dumps({"model": EMBED_MODEL, "prompt": text,
                             "keep_alive": "30m"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)["embedding"]

    loop = asyncio.get_running_loop()
    vectors = await asyncio.gather(
        *(loop.run_in_executor(None, fetch, text) for text in texts)
    )
    return np.array(vectors, dtype=np.float32)


async def build(workspace, store):
    from lightrag import LightRAG
    from lightrag.llm.ollama import ollama_model_complete
    from lightrag.utils import EmbeddingFunc
    from lightrag.kg.shared_storage import initialize_pipeline_status

    rag = LightRAG(
        working_dir=store,
        llm_model_func=ollama_model_complete,
        llm_model_name=MODEL,
        llm_model_max_async=1,
        llm_model_kwargs={"host": OLLAMA, "options": {"num_ctx": 16384}},
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBED_DIM,
            func=embed_texts,
            model_name=EMBED_MODEL,
        ),
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    return rag


def paper_text(workspace):
    import glob
    import re

    with open(os.path.join(workspace, "metadata.json")) as handle:
        metadata = json.load(handle)

    parts = [metadata.get("title", ""), metadata.get("abstract_text", "") or ""]
    for path in sorted(glob.glob(os.path.join(workspace, "sections", "*.md"))):
        with open(path) as handle:
            parts.append(re.sub(r"<!--.*?-->", "", handle.read(), flags=re.S))
    return "\n\n".join(part for part in parts if part.strip())


async def main_async(args):
    from lightrag import QueryParam

    with open(args.questions) as handle:
        questions = json.load(handle)["questions"]
    if args.question:
        questions = [q for q in questions if q["id"] in args.question]

    os.makedirs(args.out, exist_ok=True)
    built = {}

    for question in questions:
        workspace = question.get("workspace", args.workspace)
        if not os.path.isabs(workspace):
            workspace = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), workspace)
        name = os.path.basename(workspace.rstrip("/"))

        if name not in built:
            store = os.path.join(args.store, name)
            fresh = not os.path.exists(os.path.join(store, "kv_store_full_docs.json"))
            os.makedirs(store, exist_ok=True)
            rag = await build(workspace, store)
            if fresh:
                started = time.time()
                print(f"[index] {name}: building the graph, this is the slow part")
                await rag.ainsert(paper_text(workspace))
                print(f"[index] {name}: built in {time.time() - started:.0f}s")
            else:
                print(f"[index] {name}: reusing the graph already in {store}")
            built[name] = rag
        rag = built[name]

        for run in range(1, args.runs + 1):
            print(f"[query] {question['id']} / lightrag / run {run}")
            started = time.time()
            try:
                answer = await rag.aquery(
                    question["question"],
                    param=QueryParam(mode=args.mode, top_k=TOP_K),
                )
                context = await rag.aquery(
                    question["question"],
                    param=QueryParam(mode=args.mode, top_k=TOP_K, only_need_context=True),
                )
            except Exception as error:
                answer = f"(lightrag error: {error})"
                context = ""

            context = context if isinstance(context, str) else str(context)
            record = {
                "question_id": question["id"],
                "condition": "lightrag",
                "run": run,
                "model": MODEL,
                "workspace": name,
                "answer": answer if isinstance(answer, str) else str(answer),
                "context_text": context,
                "context_chars": len(context),
                "prompt_tokens": 0,
                "output_tokens": 0,
                "seconds": round(time.time() - started, 1),
                "mode": args.mode,
            }
            path = os.path.join(args.out, f"{question['id']}_lightrag_run{run}.json")
            with open(path, "w") as handle:
                json.dump(record, handle, indent=2)
            print(f"    {record['seconds']}s -> {os.path.basename(path)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--store", default="/tmp/lightrag_store")
    parser.add_argument("--workspace", default="papers/maday2012")
    parser.add_argument("--question", action="append")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--mode", default="hybrid",
                        choices=["naive", "local", "global", "hybrid", "mix"])
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
