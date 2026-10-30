## Point 8 explained: locating information loss

**Purpose.** The aim is to find where information is lost: during document ingestion, extraction into the graph, retrieval, or answer writing. Comparing answer scores alone cannot reliably distinguish these failures. The A/B/C runs are diagnostic comparisons; you do not need to build three different RAG systems.

**Pipeline.** Paper → ingestion/preprocessing → extraction into the graph → retrieval of relevant facts → answer generation.

**Key extraction check.** Check whether each expected fact was correctly stored in the graph before retrieval happens. Examine the relevant nodes, relationships and properties directly, including questions that the system answered correctly.

## What to supply in each run

| Run | Input to the answering LLM | Stages bypassed | What it tests |
| --- | --- | --- | --- |
| A — Original paper | The same question plus the complete approved paper text, including relevant figure captions and supplements, directly in the answering model’s context. Use text itself, not just a URL. | Graph extraction and retrieval. | Whether the answering model can answer from the original document. |
| B — Extracted graph | The question goes through your system’s graph retriever. The answering LLM receives the selected structured graph facts, relationships and properties. Log the final evidence context it actually receives. | None of the extraction/retrieval/answering stages. | Whether the full graph pipeline preserves, retrieves and uses the information. |
| C — Correct evidence supplied manually | The same question plus the original supporting passage selected using the benchmark’s evidence location. Do not include the reference answer. | Graph extraction and retrieval; most irrelevant document context is also removed. | Whether the answering model can answer when the necessary original evidence is definitely present. |

**Meaning of gold evidence.** Gold evidence means the supporting original passage or passages from the paper. It does not mean the gold/reference answer, answer elements, or a rewritten fact containing the expected answer. For synthesis questions, supply all necessary passages.

**Fair comparison.** Keep the question wording, answering model/version, system instructions and generation settings the same. Use a fresh context for each request and require answers grounded only in the supplied evidence. Change only the evidence supplied to the answering model. Record source versions and the exact final context for each run.

**Context limits.** For run A, verify that the complete approved text fits without silent truncation. If it does not fit, record run A as unavailable or label a source-retrieval variant separately; that variant also tests retrieval and is not the full-document baseline.

**Graph-only versus graph plus source.** For extraction-focused run B, use the extracted structured graph facts and their provenance. If your production system also retrieves original source paragraphs, label that run graph plus source and assess it separately. An answering model can recover a missing extracted value from the original paragraph, hiding an extraction failure. A value present only inside a linked raw paragraph has not necessarily been extracted as a structured fact.

## Worked example: Q040

**Question.** What fraction of autophagosomes underwent net retrograde movement, with what uncertainty and displacement threshold?

**Reference answer.** 82 ± 2% (SEM); net retrograde displacement ≥10 µm. These are Q040’s existing two content-scoring elements.

**Source location.** E014 — Results, distal initiation, paragraph 5. Exact JATS XPath: /article/body/sec[2]/sec[1]/p[5]. Source: https://www.ebi.ac.uk/europepmc/webservices/rest/PMC3283992/fullTextXML

**Original supporting paragraph for run C**

> GFP-LC3–positive rings in the distal process either remained stationary or displayed saltatory bidirectional motility in a constrained region within ∼150–200 µm of the neurite tip (Fig. 1 F). Occasionally, autophagosomes could be seen exiting this bidirectional pool to initiate travel toward the cell body (Fig. 1 F and Video 2). Along the axon shaft, autophagosomes exhibited a different type of movement. Within the axon (50–500 µm from the cell body), autophagosomes displayed robust and primarily unidirectional motility (Fig. 1, G–I; and Video 3), with 82 ± 2% (±SEM) moving a net distance of ≥10 µm in the retrograde direction. Anterograde movement was rarely observed (<1%), whereas <20% of autophagosomes exhibited nonprocessive bidirectional motility or remained stationary.

| Run | Concrete action for Q040 |
| --- | --- |
| A | Supply the approved article text and supplements directly to the answering model and ask Q040. |
| B | Ask Q040 through the graph pipeline. Save the relevant stored graph records, the exact final context sent to the answering model, and its answer. |
| C | Supply the original E014 paragraph above and ask Q040, without supplying the reference answer. |

## What to check in the stored graph for Q040

**Representation.** The information may be distributed across nodes, relationships or properties. The following is a schema-independent checklist; it does not prescribe a particular graph schema.

| Required information | Expected representation |
| --- | --- |
| Population/context | Autophagosomes in cultured mouse DRG axons. |
| Movement | Net retrograde movement, toward the cell soma. |
| Fraction | 82%. |
| Uncertainty | ±2 percentage points; the uncertainty statistic is SEM. |
| Classification threshold | Net displacement ≥10 µm. |
| Provenance | A link/locator supporting the measurement in E014. |

**Scoring boundary.** The context and provenance checks help diagnose extraction quality. They do not add points to Q040’s existing 2-point content rubric or change the 405-point benchmark total. Evidence credit remains separate.

## How to locate a failure

| Observation | Where to investigate |
| --- | --- |
| The supporting passage never reached the extractor. | Document ingestion or preprocessing, such as an omitted caption or supplement. |
| The passage reached the extractor, but the graph lacks the percentage, uncertainty or threshold, or stores it incorrectly. | Extraction or graph representation. |
| The graph stores the correct facts, but they are missing from the final context sent to the answering model. | Retrieval or context assembly, including filtering, reranking or truncation. |
| The final context contains the necessary correct facts, but the answer is wrong or incomplete. | Answer generation. Inspect contradictory context as well as omissions. |

**Multiple failures.** A question may expose more than one failure. Record each observed failure rather than assuming the A/B/C score pattern uniquely identifies a stage. Correct answers also need graph inspection because source passages or prior model knowledge can mask extraction errors.

**Unanswerable items.** For the 15 abstention questions, absence from a retrieved snippet or graph does not prove absence from the paper. Judge whether the requested detail is unreported or unestablished against the complete approved source scope; do not supply the reference answer as evidence.

## A practical first evaluation

1. Select 20 representative questions, including numerical findings, relationships, experimental context, negative findings and uncertainty. Keep the selected IDs fixed.
2. Run B and inspect the stored graph for every selected question. For each expected answer element, record whether its source reached the extractor and whether the graph stores the element correctly.
3. Save the exact final evidence context sent to the answering model and its answer. Record whether the necessary facts reached the model and whether the answer is correct.
4. Use run C to investigate incorrect/incomplete answers. Use run A as an original-document comparison. Keep the same model and settings.
5. Grade A, B and C separately. Use a separate workbook copy per run or a results table keyed by question ID and run; do not overwrite one run’s grades with another. Record graph-only versus graph-plus-source mode.
6. Report the graph fact audit alongside the QA scores. Audit at the numbered answer-element level so a stored percentage does not hide a missing uncertainty or displacement threshold.

| Question / run | Source reached extractor? | Expected facts correctly stored? | Required facts in final answer context? | Answer correct? |
| --- | --- | --- | --- | --- |
| Q040 / B | Pending inspection | Pending inspection | Pending inspection | Pending grading |
| Q040 / A | Not applicable to this run | Not applicable to this run | Check full text is supplied | Pending grading |
| Q040 / C | Not applicable to this run | Not applicable to this run | Check E014 is supplied | Pending grading |

**Interpretation.** A failed QA response is a reason to inspect the graph, retrieval context and answer; it is not automatically an extraction failure. QA measures recoverable knowledge. A separate atomic-fact audit is needed to assess extraction coverage and incorrect stored claims; this benchmark is not an exhaustive gold graph.

## Automated scoring example with DeepEval

**Included example.** The package includes examples/score_with_deepeval.py, examples/requirements.txt, examples/README.md and fictional A/B/C response traces for Q040. The scorer reads the existing gold JSONL and your saved system answers. It does not connect to your RAG automatically; capture your system-specific outputs first.

**Library and scoring.** The example pins DeepEval 4.3.1 and uses GEval with LLMTestCase. It makes a strict binary judgment for each numbered answer element and adds the judgments into the existing question score. Citation scoring and graph/final-context audits are optional. Instructions and references: https://deepeval.com/docs/metrics-llm-evals and https://deepeval.com/docs/evaluation-test-cases

**No-network checks.** From the extracted package directory, run: python examples/score_with_deepeval.py --self-test
Then validate the fictional fixture without calling a judge: python examples/score_with_deepeval.py --responses examples/fictional_responses.jsonl --runs A,B,C --ids Q040 --allow-fixtures --dry-run

**Install and configure.** Create an isolated environment and install examples/requirements.txt. Configure credentials for your chosen DeepEval judge in the process environment. The included examples/README.md has the complete commands, response format and model setup links.

**Real scoring command.** After configuring the environment, an example one-question comparison is: python examples/score_with_deepeval.py --responses my_responses.jsonl --runs A,B,C --ids Q040 --judge-model YOUR_JUDGE_MODEL --output-dir results/q040
Replace YOUR_JUDGE_MODEL with your configured judge. Omit --ids for the full selected track; use --track xml for the conservative XML-only subset.

**Saved trace fields.** Each response needs id, run (A/B/C) and actual_output. For evidence scoring, also record citations. For stage audits, record the exact final retrieval_context, all relevant stored structured graph_facts before retrieval, and graph_facts_complete=true. Record source_reached_extractor only when known from logs.

**Optional diagnostics.** Add --score-evidence for source citation credit. Add --audit-stages to compare required answer elements with the complete graph records and final answer context for answerable B items. These are provisional diagnostic suggestions; a missing value in retrieved records alone cannot establish an extraction failure.

**Reports and denominators.** The script writes question_scores.csv, question_scores.jsonl, element_scores.jsonl and summary.json. It reports A/B/C separately, with category scores, category macro averages and grading coverage. The full track is 200 questions / 405 points per run; a selected subset gets its own fixed denominator. Missing responses count as zero. Judge errors stop the run without a completed summary.

**Practical limits.** A full content run can require 405 judge calls; citation and stage audits add calls. Real scoring sends selected data to your configured judge and incurs its normal charges. The fixture is fictional; local checks verify API/reporting mechanics, not scientific judge accuracy. Calibrate automatic grades with a manually reviewed sample. Keep all gold/example/evaluation files outside the indexed source corpus.
