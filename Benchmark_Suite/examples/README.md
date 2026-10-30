# Automated scoring example with DeepEval

This example scores answers already produced by your system. It uses the existing 200-question gold file and its numbered answer elements. It does not connect to, modify, or run your RAG system: save your system's outputs using the format below, then run the scorer.

The example uses [DeepEval G-Eval](https://deepeval.com/docs/metrics-llm-evals) and [LLMTestCase](https://deepeval.com/docs/evaluation-test-cases). DeepEval is pinned to version 4.3.1 in `requirements.txt`. Each required answer element receives a strict binary judgment, then Python adds those judgments into the existing question points. A floating-point similarity score is not rounded into the 405-point rubric.

## 1. Check the example without an API key

From the extracted package directory:

```powershell
python examples/score_with_deepeval.py --self-test
python examples/score_with_deepeval.py --responses examples/fictional_responses.jsonl --runs A,B,C --ids Q040 --allow-fixtures --dry-run
```

These commands do not import DeepEval, call a remote judge, or generate scientific benchmark scores. The included A/B/C responses are explicitly fictional. The A trace uses a placeholder instead of a real full-paper context. The B example deliberately omits the displacement threshold. Use the file to understand the format, not as evidence of your system's performance.

## 2. Save your own system's responses

Create a UTF-8 JSONL file, with one JSON object per line and one record per `(run, id)`. The minimum fields are:

```json
{"id":"Q040","run":"B","actual_output":"YOUR SYSTEM'S ACTUAL ANSWER"}
```

For evidence scoring and stage diagnosis, capture the richer record below. Replace all placeholder strings with real logs; do not copy the reference answer into `actual_output`.

```json
{
  "id": "Q040",
  "run": "B",
  "mode": "graph_only",
  "actual_output": "YOUR SYSTEM'S ACTUAL ANSWER",
  "citations": ["SOURCE LOCATORS ACTUALLY CITED BY YOUR SYSTEM"],
  "retrieval_context": ["EXACT FINAL EVIDENCE TEXT SENT TO THE ANSWERING LLM"],
  "graph_facts": ["ALL RELEVANT STORED STRUCTURED GRAPH FACTS BEFORE RETRIEVAL"],
  "graph_facts_complete": true,
  "source_reached_extractor": true
}
```

Write that object on one line in a JSONL file. Every entry in `citations`, `retrieval_context`, and `graph_facts` must be a string. Serialize graph records into readable strings that preserve subject, relation, object, numerical properties, qualifiers and provenance.

- `run`: A = full original paper supplied directly; B = graph pipeline; C = original supporting passage supplied manually.
- `mode`: for B, label whether the answering model saw `graph_only` facts or `graph_plus_source`. For A/C, use `original_text` or `gold_source_passage`.
- `retrieval_context`: the final evidence after filtering, reranking and truncation. For A/C this field records the supplied full text or gold passage even though retrieval was bypassed. Do not replace it with a summary.
- `graph_facts`: all relevant stored structured records, not only records returned by the retriever. Raw source paragraphs do not demonstrate structured extraction.
- `graph_facts_complete`: set true only after exporting all relevant stored records. The stage audit refuses incomplete traces rather than treating retrieval omissions as extraction failures.
- `source_reached_extractor`: true/false only when established from ingestion/extraction logs; omit it if unknown.
- `citations`: explicit locators actually included in the system's answer. An empty list earns zero when evidence scoring is requested.

Call your own RAG application using only the question and the approved source corpus. Save its answer and trace. Read the gold file only in this separate scorer. There is no universal RAG API, so the example deliberately leaves that application-specific capture step to your system.

## 3. Install the pinned library and configure a judge

Use an isolated environment:

```powershell
python -m venv .evalenv
.evalenv/Scripts/python -m pip install -r examples/requirements.txt
```

Configure the judge model/provider credentials in your process environment using [DeepEval's model instructions](https://deepeval.com/docs/metrics-introduction#using-any-llm). Replace `YOUR_JUDGE_MODEL` in the next commands with a model identifier supported by your configuration. As written, passing a model name uses DeepEval's OpenAI judge backend; another provider or local model can be supplied by adapting `DeepEvalJudge` to accept a `DeepEvalBaseLLM` instance.

The answering system can use any model. Its model and prompts stay fixed across A/B/C. Record the judge model separately and calibrate its decisions against a manually reviewed sample.

Real scoring sends the question, answer, required reference elements, and any selected source/trace evidence to the configured judge and incurs its normal API charges. This example uses standalone `metric.measure()` and writes local reports; it does not log into Confident AI. It disables DeepEval telemetry, dotenv autoload and legacy keyfile loading. Set provider credentials in the process environment rather than assuming a local `.env` file will be loaded.

## 4. Run a small real pilot

```powershell
.evalenv/Scripts/python examples/score_with_deepeval.py --responses my_responses.jsonl --runs A,B,C --ids Q040 --judge-model YOUR_JUDGE_MODEL --output-dir results/q040
```

That comparison has one question and two possible content points **per run**. It is not a full 405-point evaluation. Use the same `--ids` for every compared run.

To add citation scoring and provisional stage diagnosis:

```powershell
.evalenv/Scripts/python examples/score_with_deepeval.py --responses my_responses.jsonl --runs B --ids Q040 --judge-model YOUR_JUDGE_MODEL --score-evidence --audit-stages --output-dir results/q040_with_trace
```

`--audit-stages` also judges each required element against the supplied complete graph records and final answer context. It suggests ingestion/extraction/retrieval/generation failure locations from those judgments and logs. These suggestions depend on the completeness and correctness of the exported trace and need human review. Non-reporting/abstention items skip this audit: absence in a snippet is not proof of absence in the paper.

## 5. Run the complete benchmark

Omit `--ids` to select the complete 200-question, 405-point suite per run:

```powershell
.evalenv/Scripts/python examples/score_with_deepeval.py --responses my_responses.jsonl --runs A,B,C --judge-model YOUR_JUDGE_MODEL --score-evidence --output-dir results/full
```

Use `--track xml` for the conservative 159-question XML-only subset. The script recalculates the selected denominator. Missing responses count as zero in the fixed selected suite and reduce reported grading coverage. A valid empty answer is graded as zero; it does not count as a missing record. Duplicate `(run,id)` records and unknown IDs are rejected.

For a complete run, content scoring requires up to 405 binary judge calls. Citation scoring adds up to 200; stage audits add up to two calls per answer element for answerable B questions. Three complete A/B/C runs can therefore involve many calls. Use `--dry-run` to validate the file and show the planned scope before calling a judge.

## Outputs

| File | Contents |
|---|---|
| `summary.json` | Separate A/B/C scores, selected IDs/denominator, category scores, category macro average, grading coverage, package version and input fingerprints. |
| `question_scores.csv` | Per-question content points and optional evidence credit; filter by run before reviewing or transferring grades. |
| `question_scores.jsonl` | Question results with detailed judge decisions; also serves as a flushed progress checkpoint. |
| `element_scores.jsonl` | One entry per required answer element, with judge reasons and optional graph/context decisions. |

A judge error stops the run; it is not silently converted to a zero or omitted from a seemingly complete score. No completed summary is written on failure. Choose a new output folder for a rerun; the example does not implement automatic resume or judge caching. It leaves the scoring workbook unchanged. To transfer results, match by question ID and run, then copy content points/evidence credit into the corresponding workbook columns.

The automated evidence rule is conservative: the answer must receive full content points and cite the supporting source accurately. Other evidence cases can be reviewed manually. Scores are provisional LLM judgments, not independently adjudicated scientific truth. Review a representative sample—including correct answers and abstentions—before relying on the automated totals. The script audits expected facts; it does not calculate exhaustive graph precision/recall or identify every extra incorrect graph claim.

## Local verification

The script's self-tests and dry-run are independent of an LLM. The pinned library can also be imported and its strict G-Eval metric exercised with an offline test double. Those checks verify the API integration and scoring/reporting mechanics, not the accuracy of a remote scientific judge. No real RAG outputs or remote judge evaluations are supplied in this package.

Documentation checked 16 October 2026: [G-Eval](https://deepeval.com/docs/metrics-llm-evals), [test cases](https://deepeval.com/docs/evaluation-test-cases), [environment variables](https://deepeval.com/docs/environment-variables), [DeepEval 4.3.1 package](https://pypi.org/project/deepeval/4.3.1/).
