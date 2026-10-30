"""The bits of ollama that both the harness and the retrieval tools need."""

import json
import os
import urllib.request

# Where ollama is listening. Set OLLAMA_HOST to run the models on another
# machine, which is how this runs on a cluster: ollama serves on the GPU node
# and the harness talks to it over the network.
#
# ollama itself reads OLLAMA_HOST too, and accepts a bare 'host:port' there,
# so add the scheme back when it is missing rather than failing in urllib.
def ollama_url():
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host.rstrip("/")


OLLAMA = ollama_url()
MODEL = "qwen3.5:9b"
EMBED_MODEL = "nomic-embed-text"

# Keep the models loaded between calls. The cli loop alternates the generating
# model with the embedding one on every step, and letting ollama evict either
# one makes each step pay for a reload.
KEEP_ALIVE = "30m"


def post(path, payload):
    request = urllib.request.Request(
        OLLAMA + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.load(response)


def embed(text):
    return post("/api/embeddings", {
        "model": EMBED_MODEL, "prompt": text, "keep_alive": KEEP_ALIVE,
    })["embedding"]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    length_a = sum(x * x for x in a) ** 0.5
    length_b = sum(x * x for x in b) ** 0.5
    return dot / (length_a * length_b + 1e-9)
