# Type A: atomic retrieval (Graph RAG MVP spec, Table 1)

Run 2026-10-24. 3 questions, 9 scored facets, 63 records.

## Coverage by condition

| condition | coverage | sd | runs | prompt tok | context chars | sec |
|---|---|---|---|---|---|---|
| closed book (no retrieval) | **59.3%** | 0.169 | 9 | 54 | 0 | 9.0 |
| BM25 (sparse lexical) | **91.7%** | 0.125 | 9 | 677 | 2842 | 5.2 |
| RAG (dense, flat markdown) | **91.7%** | 0.125 | 9 | 796 | 3451 | 5.0 |
| RAG (dense, structured units) | **91.7%** | 0.125 | 9 | 612 | 2761 | 23.8 |
| LightRAG (graph) | **no answer** | 0.000 | 9 | not counted | 55 | 4153.2 |
| CLI agent (this work) | **91.7%** | 0.125 | 9 | 35817 | 24658 | 44.3 |
| raw (whole paper in context) | **94.4%** | 0.110 | 9 | 6939 | 27967 | 14.6 |

> **LightRAG did not answer.** Every one of its records is the string
> `"Sorry, I'm not able to provide an answer to that question."` Its graph
> built, but retrieval returned `0 entities, 0 relations, 0 vector chunks` on
> every query, so `kg_query` gave up before reaching the model. Read this as a
> comparator that failed to run, not as a 0% score for graph retrieval.

## Coverage by question

| question | paper | closed book (no retrieval) | BM25 (sparse lexical) | RAG (dense, flat markdown) | RAG (dense, structured units) | LightRAG (graph) | CLI agent (this work) | raw (whole paper in context) |
|---|---|---|---|---|---|---|---|---|
| A1 | `hara2006` | 78% | 100% | 100% | 100% | 0% | 100% | 100% |
| A2 | `maday2012` | 50% | 100% | 100% | 100% | 0% | 100% | 100% |
| A3 | `tsong2023` | 50% | 75% | 75% | 75% | 0% | 75% | 83% |

## Where the misses come from

A navigation miss means the fact never appeared in the text the model was shown. A generation miss means it was shown and left out.

| condition | hit | generation miss | navigation miss |
|---|---|---|---|
| closed book (no retrieval) | 59% | 0% | 41% |
| BM25 (sparse lexical) | 89% | 11% | 0% |
| RAG (dense, flat markdown) | 89% | 11% | 0% |
| RAG (dense, structured units) | 89% | 11% | 0% |
| LightRAG (graph) | n/a | n/a | n/a |
| CLI agent (this work) | 89% | 11% | 0% |
| raw (whole paper in context) | 93% | 7% | 0% |

