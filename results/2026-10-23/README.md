# Retrieval evaluation, 23 October 2026

The Graph RAG MVP's Type A questions, plus a second corpus that discriminates.

Read this first.

- Type A tables: `typeA_tables.md` (the spec's questions; everything ties)
- Second corpus: `pmc11289285_tables.md` (**the result worth presenting**)
- Method and provenance: `METHOD.md`
- Raw records: `records/`, `records_pmc11289285/`

**If you have two minutes:** Type A cannot tell these systems apart, every
retrieval system ties at 91.7%. On harder multi-part questions the agent leads
the best one-shot RAG by 18.6 points, 88.8% against 70.2%, and its navigation
misses drop from 26% to 4%. Jump to "The second corpus".

## The one-paragraph version

We ran the three Type A (atomic retrieval) questions from the MVP spec across
six conditions. **The four retrieval systems scored identically: 91.7% each.**
BM25, dense RAG over flat chunks, dense RAG over structured units, and our CLI
agent are indistinguishable. Only two things separate at all: a closed-book
model with no retrieval gets 59.3%, and the whole paper in context gets 94.4%.
The conclusion is not that our system is good or bad. It is that **Type A does
not measure what the MVP is trying to decide.**

## Headline

| condition | coverage | prompt tok | sec |
|---|---|---|---|
| closed book (no retrieval) | 59.3% | 54 | 9.0 |
| BM25 (sparse lexical) | 91.7% | 677 | 5.2 |
| RAG (dense, flat markdown) | 91.7% | 796 | 5.0 |
| RAG (dense, structured units) | 91.7% | 612 | 23.8 |
| CLI agent (this work) | 91.7% | 35,817 | 44.3 |
| raw (whole paper in context) | 94.4% | 6,939 | 14.6 |

3 questions, 9 scored facets, 3 runs each, 54 records. Deterministic regex
scoring against the spec's own reference answers. No LLM judge.

## Four findings

**1. Type A does not discriminate between retrieval architectures.**
A1 and A2 are 100% for all five conditions that see the paper, retrieval or
otherwise. A single-sentence fact in
a single paper is found by anything that retrieves at all, including plain
keyword matching. The spec predicted this for BM25 ("BM25 should handle 'which
gene was deleted in Hara et al.?' well") and it held for every system.

**2. Retrieval is not the bottleneck. The generator is.**
Navigation misses are **0%** for every retrieval condition: the right text was
in front of the model every single time. All remaining error is generation
misses, where the model was shown the fact and left it out. Chasing better
retrieval cannot improve these scores.

**3. The one real failure is a lost qualifier, and it is near-universal.**
17 of the 25 total facet misses are the same thing: A3's answer should say the
70% drop was measured in **DRG neurons**, and almost nothing says it.

| | closedbook | bm25 | rag_flat | rag | cli | raw |
|---|---|---|---|---|---|---|
| missed `DRG neurons` | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 2/3 |

This maps directly onto the spec's own rubric: context preservation (15 points)
and the minus-5 penalty for omitting a qualifier that materially changes the
claim. Every architecture fails it about equally. **That is the measurable
problem in this corpus**, and it is a generation and prompting problem, not a
graph-versus-vector problem.

**4. Closed book answers 59.3%, which is a contamination warning.**
These are well-known 2006-2023 papers. The model already knows Atg5 was deleted
in Hara. Any Type A score has to be read against that floor, and the headroom
the corpus actually buys is about 32 points, not 92.

Where closed book does fail is telling: it never produces the 70% figure. It
knows the direction of the result and not the measurement.

## What this means for the MVP

The comparison the spec actually wants, Graph RAG versus matched vector RAG,
**cannot be made on Type A.** All six systems tie. It needs the Type B
multi-paper synthesis questions, where the evidence path spans papers and
retrieval has to combine rather than look up.

Honest statement of our position: our framework is single-paper today, so we
can run Type A and none of Type B. That is the gap to close, and it is the
thing worth arguing about in the meeting.

Also worth saying plainly: on atomic retrieval the CLI agent costs **55x the
prompt tokens of plain RAG for the same score**. An agent is the wrong tool for
a single-sentence lookup. Its case has to be made on harder questions, not
these.

## Corpus caveat, which is not a detail

The three papers are not available in the same form, and the spec says so.

| paper | question | route | what that means |
|---|---|---|---|
| Hara 2006 | A1 | abstract only | Paywalled, no PMC deposit. 3 retrieval units. |
| Maday 2012 | A2 | publisher JATS | Full body, figures, references. 151 units. |
| Tsong 2023 | A3 | rebuilt from PMC HTML | No reusable XML. No figures or references. 135 units. |

A1 is effectively a test against an abstract. Do not read it as a full-text
retrieval result.

## LightRAG never produced an answer

The graph comparator is missing, not bad. It ran to completion on both corpora,
30 records in all, and every single record holds the same string:

    Sorry, I'm not able to provide an answer to that question.

The graph built without error. Retrieval then returned `0 entities, 0
relations, 0 vector chunks` for every query, and `kg_query` returned no-result
before anything reached the model. The tables say `no answer` rather than 0%
for this reason: a comparator that never answered is not evidence about graph
retrieval, and it must not be read as one. Any comparison in this report is
between the five conditions that did run.

Two bugs, and only the first was fixed. **LightRAG's first attempt failed on
embedding dimensions and was restarted.** Its bundled ollama
embedding helper is hard-declared for `bge-m3` at 1024 dimensions, so every
call with `nomic-embed-text` at 768 failed the library's own shape check and
the graph build aborted. The log is kept as `lightrag.failed-dim-bug.log`.
The fix was to embed through ollama directly rather than swap to bge-m3,
because the spec requires every system to use the same embedding model, and
changing it for one comparator would have made that column meaningless.

That fix worked, and it hid the second bug. Checking for dimension errors in
the log was the wrong check: the errors stopped, the graph built, and the
retrieval still returned nothing. Whatever the cause, it is downstream of the
embedding call and was never diagnosed. Anyone picking this up should start by
querying the store in `/tmp/lightrag_store` directly to see whether entities
were written at all.

## The second corpus, which does discriminate

Because Type A came out flat, the same six conditions were also run on the
earlier **PMC11289285** corpus: 5 questions with several parts each, 34 facets,
90 records. Full tables in `pmc11289285_tables.md`.

| condition | coverage | navigation miss | prompt tok |
|---|---|---|---|
| closed book | 10.8% | 87% | 75 |
| BM25 (sparse lexical) | 52.2% | 44% | 804 |
| RAG (dense, structured units) | 63.8% | 32% | 837 |
| RAG (dense, flat markdown) | 70.2% | 26% | 1,184 |
| **CLI agent (this work)** | **88.8%** | **4%** | 56,035 |
| raw (whole paper) | 98.3% | 0% | 16,930 |

**This is the result worth presenting.** The agent beats the best one-shot
retrieval by **18.6 points**, and the mechanism is visible rather than assumed:
navigation misses fall from 26-44% to **4%**. One-shot top-k cannot reach every
part of a multi-part question; following up can.

**Closed book scores 10.8% here against 59.3% on Type A.** That is the
contamination argument with a number on it. These questions are not answerable
from model memory; the Type A ones substantially are.

### A claim of mine that this refutes

Earlier I argued that RAG's deficit was partly a *flattening handicap*, that
chunking the rendered markdown threw away structure and that dense retrieval
over structured units should therefore beat it. **It does not.** Flat 900-char
chunks beat the structured sentence windows by 6.4 points, 70.2% against 63.8%,
over 15 runs each.

That comparison only became fair this session. The flat pool had been missing
the abstract while the structured pool had it, a bias in favour of the
structured side, and removing it reversed the ordering.

The coherent reading is that addressability is worth nothing to a reader with
no agency. A 900-char chunk simply carries more context per hit than a 425-char
sentence window, which is what helps a system that gets one look. The
structured units earn their keep only through the agent, which is exactly where
`cli` is 18.6 points ahead.

Cost stays the honest counterweight: the agent spends **67x the prompt tokens
of plain RAG** for that gain.

## Separately: the agent got better this session

Measured on the PMC11289285 corpus (5 multi-part questions, 34 facets), not on
Type A:

- CLI coverage **84.6% to 88.8%** on the full 3-run matrix after the fixes
  (a single-run check immediately after the fixes read 92.5%).
- The agent now chooses semantic search on its own. It had **never** emitted
  `ACTION: similar` in any previous run; on A3 it used it for 5 of 6 actions.

The fixes: an exploration floor so the agent cannot answer after one lookup;
section scoping that works on parent sections; generated section ids for JATS
files that omit them (Maday had none, so every section was unaddressable);
and the abstract added to the flat chunk pool, which had been quietly
handicapping `rag_flat`.
