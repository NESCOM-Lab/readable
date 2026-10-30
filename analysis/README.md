# Evaluation harness

Results live in `results/<date>/`. The most recent run is
`results/2026-10-23/`, which has the Type A evaluation against the Graph RAG
MVP spec; start from its `README.md`.


Compares several ways of letting a small local model read one paper:

- `closedbook` - no retrieval at all, the model answers from its own weights
- `bm25` - top-k over the retrieval units by Okapi BM25, sparse and lexical
- `raw` - the whole paper in context
- `rag` - top-k over the structured retrieval units, one query, no agency
- `rag_flat` - top-k over 900-char slices of the rendered markdown
- `cli` - a ReAct loop that navigates the paper with `pgraph` and `similar.py`
- `lightrag` - the graph comparator, run separately by `run_lightrag.py`

`closedbook` is the control: whatever it answers did not come from the corpus,
so it bounds how much of any other score the retrieval actually earned. `bm25`
and `rag` search the same pool by different means, which separates term overlap
from embedding similarity.

`rag` and `cli` draw on the *same* pool of units, so `rag` is the no-agency
ablation of `cli` rather than a separate system. `rag_flat` is the earlier
approach, kept so a run shows what the flattening cost: its chunks carry one of
only five file names as their address, for a 20-section paper, and figures,
tables and references are not in its pool at all.

`rag_flat` now also carries the abstract, which it did not before. The abstract
is in the unit pool the other conditions search, so leaving it out of the flat
pool was a difference in what the two pools held rather than in how they were
addressed, and it flattered the structured side.

Every condition gets the same question from the questions file, and each
records the text it put in front of the model.

## Papers

`fetch_paper.py` writes JATS for a paper by whichever route it allows, because
an evaluation set rarely has one format throughout. PMC serves reusable JATS
only when the licence permits, so a paper can have a PMCID and still return
front matter alone, and a paywalled one has no PMC record at all.

```sh
python3 analysis/fetch_paper.py --pmcid PMC3283992 --out /tmp/maday.xml
python3 analysis/fetch_paper.py --doi 10.1038/nature04724 --out /tmp/hara.xml
```

It reports which of the three routes it took, and records that in the XML as
`source_format`, since a page rebuilt into JATS is weaker evidence than a
publisher deposit and an abstract is weaker still.

## Setup

```sh
cargo build --release
./target/release/pgraph index PMC11289285-test     # -> units.json
python3 analysis/embed.py PMC11289285-test         # -> embeddings.json
```

`index` is a parse step and `embed.py` is a one-time pass over the units, cached
by a hash of their text. At run time only the agent's own query is embedded.

## Running

```sh
python3 analysis/run_eval.py       # every question x every condition x 3 runs
python3 analysis/score.py
python3 analysis/report.py <records> --questions <file> --out summary.md
```

A question may name its own `workspace`, so one questions file can span several
papers. Each paper is loaded and embedded once, whichever questions use it.

The graph comparator needs its own interpreter, since it pulls in a large
dependency tree that does not belong in the harness:

```sh
python3 -m venv /tmp/lrag_venv && /tmp/lrag_venv/bin/pip install lightrag-hku ollama
/tmp/lrag_venv/bin/python analysis/run_lightrag.py --questions <file> --out <records>
```

While iterating:

```sh
python3 analysis/run_eval.py --runs 1 --question q1 --condition cli --out /tmp/try
python3 analysis/run_eval.py --observation-budget 3000
python3 analysis/run_eval.py --no-seed-similar    # ablate the seeded hits
python3 analysis/score.py /tmp/try --json /tmp/facets.json
python3 analysis/transcript.py q2_cli_run1
```

## Retrieval units

`pgraph index` turns the parsed paper into addressable units: overlapping
three-sentence windows inside each paragraph, plus the abstract, figure and
table captions, and one unit per reference. Each keeps its section id,
provenance and citation ids, so a hit can be read in full with
`pgraph query section <id>`.

`similar.py` is the semantic counterpart to `pgraph query search`, which only
matches substrings:

```sh
python3 analysis/similar.py PMC11289285-test "how were tuning curves fit" --k 5
python3 analysis/similar.py PMC11289285-test "..." --in Sec8 --origin figure
```

`--in` takes a section id and covers everything under it. Each unit keeps the
chain of sections it sits inside, not just the one that owns it, because a
parent like Methods holds no paragraphs of its own and matching on the owner
alone would quietly return nothing.

Reference entries are left out by default. A reference title is dense topical
text that matches a question well while saying nothing about this paper, and in
the pool they crowd out the real answer.

The `cli` agent is seeded with the outline and with the passages closest to its
question, so it starts where `rag` stops and navigates from there. Its actions
are `outline`, `section <id>`, `search <term>` and `similar <text>`, the last
of which also takes `similar <text> in <id>` to search inside one section.

Two things shape how far it explores:

- `--min-steps` (default 4) is a floor. An ANSWER before the agent has made
  that many lookups is turned down once, with the sections it has read so far,
  and it picks another action. Answering after one or two lookups was the main
  way a run lost coverage, since the facts it missed were in sections it never
  opened. `--min-steps 0` turns the floor off.
- `--max-steps` (default 8) is the ceiling, after which an answer is forced.

Known limits: embedding a multi-part question gives a blended vector, so the
seeded hits cover the question's parts unevenly. And the agent navigates with
`section` almost exclusively; it has not been observed choosing `similar` on
its own, since the outline's titles are usually enough to guess where to look.

## Scoring

A facet is one content point the answer should contain, written as alternative
regexes and tagged with the section it comes from. `score.py` checks each one
twice: whether the model said it, and whether it was present in the text the
model was shown. The pair separates a navigation miss (retrieval never reached
it) from a generation miss (it was there and the model dropped it). For `cli` it
also reports whether the section a missed fact lives in was ever opened.

Before scoring anything, `score.py` verifies that every facet still matches the
paper and every `source_section` still exists, and prints `RUBRIC PROBLEMS` if
not. No model is used for scoring.

Coverage measures whether expected content appears, not whether the surrounding
claim is true. `verify.py` is an unfinished attempt at that check.

## legacy/

The first pass, kept for reference: three separate scripts that asked three
different questions, truncated CLI observations to 3000 characters of
pretty-printed JSON with no marker, wrote results to a dead scratchpad path, and
were scored by hand afterwards. `opencode.output` is the earlier attempt to use
opencode's tool-calling, which qwen3.5:9b could not drive.
