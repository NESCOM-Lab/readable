# Four ways to answer a question about one paper

Each diagram below is a standalone Mermaid block. Paste one at a time into
https://mermaid.live to view it.

Three of the four are implemented and measured in this repo. GraphRAG is drawn
as a reference baseline from the published method and has **not** been built or
run here; its diagram is marked accordingly.

---

## 1. raw - whole paper in context

No retrieval. The paper is flattened to text and handed over in full.

```mermaid
flowchart LR
    Q["Question"] --> P
    W["Workspace<br/>metadata.json + sections/*.md"] --> P["Prompt<br/>69,772 chars of paper<br/>+ question"]
    P --> M["qwen3.5:9b<br/>num_ctx 32768"]
    M --> A["Answer"]

    style P fill:#e8f0fe
    style A fill:#e6f4ea
```

Nothing can be missed for lack of reaching it, so this is the coverage ceiling.
It is also the cost ceiling, and it stops working the moment a paper does not
fit the context window.

---

## 2. rag - top-k, one shot, no agency

One embedding of the question, one ranking, one generation. Two variants differ
only in what the pool is made of.

```mermaid
flowchart TD
    Q["Question"] --> E["nomic-embed-text<br/>embed the question"]

    subgraph offline["Offline, once per paper"]
        direction TB
        SRC["Paper"]
        SRC --> FLAT["rag_flat pool<br/>900-char slices of markdown<br/>address = 1 of 5 file names<br/>no figures, no tables, no refs"]
        SRC --> UNITS["rag pool<br/>units.json, 250 units<br/>3-sentence windows, stride 2<br/>section id + provenance + citations"]
        FLAT --> VF["chunk vectors"]
        UNITS --> VU["embeddings.json<br/>250 x 768"]
    end

    E --> R["cosine rank<br/>take top 6"]
    VF -.->|"rag_flat"| R
    VU -.->|"rag, citations excluded<br/>162 unit pool"| R

    R --> CTX["Prompt<br/>~5,332 chars<br/>6 passages + question"]
    CTX --> M["qwen3.5:9b<br/>num_ctx 8192"]
    M --> A["Answer"]

    A --> X["If the needed passage was not<br/>in the top 6, it is unreachable.<br/>No second query is possible."]

    style CTX fill:#e8f0fe
    style A fill:#e6f4ea
    style X fill:#fce8e6
```

The red box is the whole story of RAG's deficit on the PMC11289285 corpus:
**32% of its facet-runs are navigation misses**, versus 3% generation misses.

It is not the story everywhere. On the Graph RAG MVP's Type A questions, where
the answer is one explicit sentence, RAG's navigation misses are **0%** and it
ties every other retrieval system. One-shot top-k fails when a question has
several parts, not when it has one.

---

## 3. GraphRAG - reference baseline, NOT implemented here

Drawn from the published method so the comparison is honest about what it does.
Nothing in this repo builds or runs it.

```mermaid
flowchart TD
    SRC["Paper, chunked"] --> EX

    subgraph build["Index build - many LLM calls, offline, expensive"]
        direction TB
        EX["LLM extracts entities<br/>and relations per chunk"]
        EX --> G["Knowledge graph<br/>nodes = entities<br/>edges = relations"]
        G --> CL["Leiden community detection<br/>hierarchical clusters"]
        CL --> SUM["LLM writes a summary<br/>per community, per level"]
    end

    Q["Question"] --> MODE{"query mode"}
    MODE -->|"local search"| LS["Entities near the query<br/>+ their text units"]
    MODE -->|"global search"| GS["Map-reduce over<br/>community summaries"]

    G --> LS
    SUM --> GS

    LS --> M["LLM"]
    GS --> M
    M --> A["Answer"]

    N["Structure is INFERRED by an LLM.<br/>Entities can be hallucinated,<br/>the build cost scales with corpus size,<br/>and it is still one retrieval pass:<br/>no navigation at answer time."]

    style build fill:#fef7e0
    style N fill:#fce8e6
    style A fill:#e6f4ea
```

The contrast worth naming in a meeting: GraphRAG spends LLM calls up front to
*guess* a structure. A JATS paper already ships with its structure - sections,
subsections, figures, tables, provenance, citation links - so `pgraph` reads it
for free and cannot hallucinate it.

---

## 4. cli - ReAct loop over pgraph (this work)

The agent cannot see the paper. It can only address it.

```mermaid
flowchart TD
    subgraph SEED["Step 0: seeding, no model call yet"]
        direction TB
        S1["pgraph query outline<br/>section ids, titles, files"]
        S2["similar.py top-5<br/>semantic hits over 162 units"]
        S1 --> S2
    end

    Q["Question"] --> S1
    S2 --> H["Message history<br/>system prompt<br/>+ every observation so far"]
    H --> GEN["qwen3.5:9b<br/>emit EXACTLY ONE line<br/>temperature 0.2"]
    GEN --> PARSE{"first line is..."}

    PARSE -->|"ANSWER: ..."| FLOOR{"made at least<br/>4 lookups?"}
    FLOOR -->|"yes"| DONE["Final answer"]
    FLOOR -->|"no"| DEFER["Turned down once:<br/>'you have read these sections,<br/>look up the part you have<br/>least evidence for'"]
    DEFER --> H
    PARSE -->|"ACTION: ..."| ACT{"which verb"}
    PARSE -->|"neither"| ERR["error observation,<br/>step still consumed"]

    ACT -->|"outline"| T1["pgraph query outline<br/>structure only, no content"]
    ACT -->|"section Sec12"| T2["pgraph query section<br/>full text of one section"]
    ACT -->|"search term"| T3["pgraph query search<br/>exact substring, byte-offset snippets"]
    ACT -->|"similar text"| T4["similar.py<br/>embed query, cosine, top-5<br/>each hit names its section"]
    ACT -->|"similar text in Sec8"| T5["similar.py scoped<br/>matches the whole ancestor chain,<br/>so a parent section works"]

    T1 --> BOUND
    T2 --> BOUND
    T3 --> BOUND
    T4 --> BOUND
    T5 --> BOUND
    ERR --> BOUND

    BOUND["Bound observation to 20,000 chars<br/>append an explicit truncation marker"] --> BUDGET{"step budget left?<br/>max 8 steps"}

    BUDGET -->|"yes"| H
    BUDGET -->|"no"| FORCE["Forced answer:<br/>'Stop exploring, answer now'<br/>recorded as forced_answer"]
    FORCE --> DONE

    style SEED fill:#fef7e0
    style DONE fill:#e6f4ea
    style BOUND fill:#e8f0fe
```

The loop is what RAG does not have: a `similar` hit returns `Sec15/p1/w2` with
its section id, so the next turn can read that section in full, follow its
citations, or scope a search inside it. Retrieval becomes a move rather than
the whole game.

---

## 5. Side by side

```mermaid
flowchart TD
    subgraph CB["closed book: the control"]
        direction TB
        b1["question"] --> b2["model weights only"] --> b3["answer"]
    end

    subgraph BM["bm25: sparse lexical"]
        direction TB
        m1["question"] --> m2["term overlap,<br/>no embeddings"] --> m3["top 6"] --> m4["answer"]
    end

    subgraph RAG["rag: dense, one shot"]
        direction TB
        g1["question"] --> g2["embed"] --> g3["top 6"] --> g4["answer"]
    end

    subgraph GRAPH["lightrag: graph"]
        direction TB
        p1["question"] --> p2["LLM-built graph<br/>+ community summaries"] --> p3["one retrieval pass"] --> p4["answer"]
    end

    subgraph CLI["cli: agency"]
        direction TB
        c1["question"] --> c2["outline + seeded hits"]
        c2 --> c3["choose a verb"]
        c3 --> c4["observe"]
        c4 --> c3
        c4 --> c5["answer"]
    end

    subgraph RAW["raw: the ceiling"]
        direction TB
        r1["question"] --> r2["entire paper"] --> r3["answer"]
    end

    style CB fill:#fce8e6
    style BM fill:#e8f0fe
    style RAG fill:#e8f0fe
    style GRAPH fill:#fef7e0
    style CLI fill:#e6f4ea
    style RAW fill:#e8f0fe
```

Scores are left off deliberately: they differ by corpus, and on the Type A set
the middle four are identical. See `results/<date>/` for the numbers.

---

## 6. Ingestion routes, and why they differ per paper

An evaluation set does not arrive in one format. PMC serves JATS only when the
licence permits reuse, so a paper can carry a PMCID and still return front
matter alone, and a paywalled one has no PMC record at all. `fetch_paper.py`
takes the best route each paper allows and writes JATS either way, recording
which route it used.

```mermaid
flowchart TD
    Q["A paper in the evaluation set"] --> T{"what does it expose?"}

    T -->|"licensed JATS deposit"| R1["EuropePMC fullTextXML<br/>used as published"]
    T -->|"PMC page, no reusable XML"| R2["PMC reading page<br/>rebuilt into JATS<br/>section ids recovered from<br/>the id naming, s0002-s2001"]
    T -->|"paywalled, no PMCID"| R3["abstract only<br/>from the EuropePMC record"]

    R1 --> M["Maday 2012<br/>3 sections, 5 figures, 30 refs<br/>151 units"]
    R2 --> N["Tsong 2023<br/>6 sections, no figures or refs<br/>135 units"]
    R3 --> H["Hara 2006<br/>abstract only<br/>3 units"]

    M --> P["pgraph parse, index"]
    N --> P
    H --> P
    P --> U["one unit pool per paper,<br/>every condition draws on it"]

    style R1 fill:#e6f4ea
    style R2 fill:#fef7e0
    style R3 fill:#fce8e6
```

The colours are a fidelity warning, not decoration. Only the green route is the
publisher's own structure. A conversion is weaker evidence, and an abstract is
weaker still, so a score on those papers says less about retrieval than the
same score on Maday would.

---

## 7. What the numbers were

These are from the **PMC11289285** corpus (5 questions, 34 facets, 3 runs,
deterministic regex scoring, no LLM judge), and they predate the agent fixes
made on 2026-10-23. They are kept because they are the run that motivated those
fixes.

| condition | coverage | navigation miss | generation miss | prompt tok | context chars |
|---|---|---|---|---|---|
| `raw` | 99.2% | 0% | 1% | 16,930 | 69,772 |
| `cli` | 84.6% | 9% | 9% | 13,874 | 22,164 |
| `rag` | 65.2% | 32% | 3% | 1,249 | 5,332 |

After the fixes (exploration floor, scoped semantic search, quote stripping),
one run of the same 5 questions put `cli` at **92.5%**.

For the Type A evaluation against the Graph RAG MVP spec, and for `bm25`,
`closedbook` and `lightrag`, see `results/2026-10-23/`. Do not quote the table
above for that evaluation: different papers, different questions.

Caveats that belong next to any of these diagrams: one paper, a rubric that has
not been reviewed, coverage measuring presence rather than truth, and identical
navigation paths across the three runs, so n=3 samples wording and not routing.
