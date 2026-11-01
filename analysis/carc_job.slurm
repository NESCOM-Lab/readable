#!/bin/bash -l
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
# Any of these is far more GPU than a 9B model needs, and pinning a100 meant
# queueing behind every a100 user while a40 and v100 nodes sat idle.
#SBATCH --gres=gpu:1
#SBATCH --constraint=a100|a40|v100
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

module load gcc 2>/dev/null || true
module load python/3.11.9 2>/dev/null || module load python 2>/dev/null || true
export PATH=$HOME/.cargo/bin:$PATH

echo "node       $(hostname)"
echo "python     $(python3 --version 2>&1)"

# Check this before generating anything. On python 3.6 subprocess.run has no
# capture_output, so every pgraph call inside the cli loop fails while the
# run still looks healthy: the agent keeps answering, just blind to the
# paper's structure. That cost a four hour run.
python3 - <<'VERSION' || exit 1
import sys
if sys.version_info < (3, 7):
    sys.stderr.write("python %s is too old; need 3.7+ for subprocess capture_output\n"
                     % ".".join(str(part) for part in sys.version_info[:3]))
    raise SystemExit(1)
VERSION
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

# The workspace is built by the bootstrap, but rebuild whatever is missing so
# this job does not depend on which setup steps happened to finish.
if [ ! -f papers/maday2012/units.json ]; then
    ./target/release/pgraph parse papers/maday2012.xml -o papers/maday2012
    ./target/release/pgraph index papers/maday2012
fi
if [ ! -s papers/maday2012/embeddings.json ]; then
    python3 analysis/embed.py papers/maday2012
fi

OUT=results/$(date +%Y-%m-%d)-carc
mkdir -p "$OUT"

# Build the questions file from the benchmark gold set. Regenerated here rather
# than committed, because the facets depend on units.json and have to match the
# workspace this job is about to query.
if [ -f "$OUT/questions_benchmark.json" ]; then
    echo "reusing the existing questions file, so a rerun scores the same rubric"
else
    python3 analysis/benchmark_to_questions.py \
        --workspace papers/maday2012 \
        --track XML \
        --drop-unfindable \
        --out "$OUT/questions_benchmark.json"
fi

# CONDITIONS lets a broken condition be regenerated on its own, instead of
# paying for the whole matrix again.
CONDITION_ARGS=""
for condition in ${CONDITIONS:-}; do
    CONDITION_ARGS="$CONDITION_ARGS --condition $condition"
done

python3 analysis/run_eval.py \
    --questions "$OUT/questions_benchmark.json" \
    --workspace papers/maday2012 \
    --out "$OUT/records" \
    --runs 3 $CONDITION_ARGS

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
