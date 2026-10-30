#!/bin/bash
# Run the evaluation matrix on a CARC GPU node.
#
# Both ollama and the harness run on the same node, so the harness talks to
# ollama over loopback and needs no OLLAMA_HOST. Submit with:
#
#   sbatch analysis/carc_job.slurm
#
# One-time setup on the login node first, see carc_setup.md. The compute nodes
# have no outbound internet, so the models must already be in OLLAMA_MODELS.
#
# logs/ must exist before submitting. Slurm opens the output file itself, so a
# mkdir inside this script would run too late and the job would fail silently.

#SBATCH --account=jbouteil_621
#SBATCH --partition=gpu
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --job-name=pgraph-eval
#SBATCH --output=logs/eval-%j.out

set -euo pipefail

PROJECT=/project2/jbouteil_621/$USER/pgraph
export OLLAMA_MODELS=$PROJECT/ollama-models
export PATH=$PROJECT/ollama/bin:$PATH

# Keep ollama's scratch off the shared filesystem, but do not die if the node
# names its scratch something else.
if [ -d /scratch1 ]; then
    export TMPDIR=/scratch1/$USER
    mkdir -p "$TMPDIR"
fi

echo "node       $(hostname)"
echo "gpu        $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"
echo "started    $(date)"

ollama serve &
OLLAMA_PID=$!
trap 'kill $OLLAMA_PID 2>/dev/null || true' EXIT

# Wait for the server rather than sleeping a fixed amount, since a cold start
# off the shared filesystem is much slower than a warm one.
for attempt in $(seq 1 60); do
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null; then
        echo "ollama up after ${attempt}s"
        break
    fi
    if [ "$attempt" -eq 60 ]; then
        echo "ollama did not come up in 60s" >&2
        exit 1
    fi
    sleep 1
done

ollama list

# Fail early and loudly if the models were never staged, instead of letting
# every single generation fail one at a time.
for model in qwen3.5:9b nomic-embed-text gemma2:9b; do
    if ! ollama list | grep -q "${model%%:*}"; then
        echo "model $model missing from $OLLAMA_MODELS, run the setup first" >&2
        exit 1
    fi
done

OUT=results/$(date +%Y-%m-%d)-carc
mkdir -p "$OUT"

# Build the questions file from the benchmark gold set. Regenerated here rather
# than committed, because the facets depend on units.json and have to match the
# workspace this job is about to query.
python3 analysis/benchmark_to_questions.py \
    --workspace papers/maday2012 \
    --track XML \
    --drop-unfindable \
    --out "$OUT/questions_benchmark.json"

python3 analysis/run_eval.py \
    --questions "$OUT/questions_benchmark.json" \
    --workspace papers/maday2012 \
    --out "$OUT/records" \
    --runs 3

# Two scorings of the same records. The regex-only pass is deterministic and
# reproducible; the judged pass also covers the prose content points, which is
# about a third of them.
python3 analysis/score.py "$OUT/records" \
    --questions "$OUT/questions_benchmark.json" \
    --workspace papers/maday2012 \
    --json "$OUT/facets_regex_only.json" \
    > "$OUT/scores_regex_only.txt"

python3 analysis/score.py "$OUT/records" \
    --questions "$OUT/questions_benchmark.json" \
    --workspace papers/maday2012 \
    --judge gemma2:9b \
    --json "$OUT/facets_judged.json" \
    > "$OUT/scores_judged.txt"

tail -40 "$OUT/scores_judged.txt"

echo "finished   $(date)"
