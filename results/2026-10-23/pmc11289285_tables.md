# PMC11289285: five multi-part questions

Run 2026-10-24. 5 questions, 34 scored facets, 105 records.

## Coverage by condition

| condition | coverage | sd | runs | prompt tok | context chars | sec |
|---|---|---|---|---|---|---|
| closed book (no retrieval) | **10.8%** | 0.163 | 15 | 75 | 0 | 8.2 |
| BM25 (sparse lexical) | **52.2%** | 0.254 | 15 | 804 | 3792 | 8.7 |
| RAG (dense, flat markdown) | **70.2%** | 0.304 | 15 | 1184 | 5131 | 10.0 |
| RAG (dense, structured units) | **63.8%** | 0.270 | 15 | 837 | 4194 | 9.6 |
| LightRAG (graph) | **no answer** | 0.000 | 15 | not counted | 70 | 66.7 |
| CLI agent (this work) | **88.8%** | 0.157 | 15 | 56035 | 39386 | 63.5 |
| raw (whole paper in context) | **98.3%** | 0.044 | 15 | 16930 | 69772 | 26.8 |

> **LightRAG did not answer.** Every one of its records is the string
> `"Sorry, I'm not able to provide an answer to that question."` Its graph
> built, but retrieval returned `0 entities, 0 relations, 0 vector chunks` on
> every query, so `kg_query` gave up before reaching the model. Read this as a
> comparator that failed to run, not as a 0% score for graph retrieval.

## Coverage by question

| question | paper | closed book (no retrieval) | BM25 (sparse lexical) | RAG (dense, flat markdown) | RAG (dense, structured units) | LightRAG (graph) | CLI agent (this work) | raw (whole paper in context) |
|---|---|---|---|---|---|---|---|---|
| q1 | `PMC11289285-test` | 17% | 50% | 100% | 62% | 0% | 92% | 100% |
| q2 | `PMC11289285-test` | 38% | 38% | 38% | 38% | 0% | 62% | 92% |
| q3 | `PMC11289285-test` | 0% | 40% | 80% | 100% | 0% | 100% | 100% |
| q4 | `PMC11289285-test` | 0% | 100% | 100% | 86% | 0% | 95% | 100% |
| q5 | `PMC11289285-test` | 0% | 33% | 33% | 33% | 0% | 94% | 100% |

## Where the misses come from

A navigation miss means the fact never appeared in the text the model was shown. A generation miss means it was shown and left out.

| condition | hit | generation miss | navigation miss |
|---|---|---|---|
| closed book (no retrieval) | 13% | 0% | 87% |
| BM25 (sparse lexical) | 53% | 3% | 44% |
| RAG (dense, flat markdown) | 71% | 3% | 26% |
| RAG (dense, structured units) | 62% | 6% | 32% |
| LightRAG (graph) | n/a | n/a | n/a |
| CLI agent (this work) | 87% | 9% | 4% |
| raw (whole paper in context) | 98% | 2% | 0% |

