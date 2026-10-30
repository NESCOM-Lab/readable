# How this run was produced

## Questions

The three Type A (atomic retrieval) questions from *Graph RAG MVP Evaluation
Questions and Benchmarking*, v02 rev 2026.10.07, Table 1. Questions and
reference answers are quoted verbatim from that document. The six Type B
questions are not here: every one of them requires at least two papers, and
this framework is single-paper today.

## Papers

Each Type A question is about a different paper, and the three are not
available in the same form. `analysis/fetch_paper.py` takes the best route each
one allows and writes JATS either way.

| paper | question | PMCID | route | what that means |
|---|---|---|---|---|
| Hara 2006 | A1 | none | `abstract` | Paywalled Nature, no PMC deposit. Abstract only. The spec names the abstract as A1's gold source, so the question is still answerable. |
| Maday 2012 | A2 | PMC3283992 | `jats` | Publisher's own XML. Full body, figures, references. |
| Tsong 2023 | A3 | PMC10621248 | `html` | PMC serves the page but not reusable XML, as the spec warned. Rebuilt from the reading page; no figures or references. |

A score on Hara or Tsong says less about retrieval than the same score on
Maday, because there is less to retrieve from.

## Conditions

All of them use the same generator (`qwen3.5:9b`, temperature 0.2) and the same
embedding model (`nomic-embed-text`) where embeddings apply. Only the retrieval
representation differs, which is what the spec asks for.

| condition | what it is |
|---|---|
| `closedbook` | No retrieval. The control: whatever it answers came from the model's weights, not the corpus. |
| `bm25` | Okapi BM25 over the same unit pool as `rag`. Sparse, lexical, no embeddings. |
| `rag_flat` | Top-6 over 900-character slices of the rendered markdown. |
| `rag` | Top-6 over the structured units. The no-agency ablation of `cli`. |
| `lightrag` | LightRAG in hybrid mode, standing in for Graph RAG. Same ollama models. |
| `cli` | The ReAct agent, navigating with `pgraph` and `similar.py`. |
| `raw` | The whole paper in context. The coverage ceiling. |

## Scoring

Deterministic, no LLM judge. Each reference answer is restated as facets: one
regex family per content point the answer has to contain. A facet is checked
twice, against the answer and against the text the model was shown, which
separates a navigation miss (never saw it) from a generation miss (saw it,
dropped it).

`score.py` refuses to trust a stale rubric: before scoring it checks that every
facet still matches its paper and every named source section still exists.

This measures whether expected content is present. It does not measure whether
the surrounding claim is true, and it is not the 100-point weighted rubric in
the spec, which needs a judge.

## Reproducing

```sh
cargo build --release
python3 analysis/fetch_paper.py --pmcid PMC3283992 --out /tmp/maday.xml
./target/release/pgraph parse /tmp/maday.xml -o papers/maday2012
./target/release/pgraph index papers/maday2012
python3 analysis/embed.py papers/maday2012
python3 analysis/run_eval.py --questions analysis/questions_typeA.json --runs 3 --out <dir>
python3 analysis/report.py <dir> --questions analysis/questions_typeA.json --out summary.md
```
