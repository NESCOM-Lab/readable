#!/bin/bash
# One-time setup for the evaluation on a CARC login node.
#
#   scp analysis/carc_bootstrap.sh kakolla@10.72.0.14:~
#   ssh kakolla@10.72.0.14
#   bash ~/carc_bootstrap.sh
#
# Safe to run again: every step checks for its own result first, so a run that
# died halfway picks up where it stopped. The model downloads are the slow part,
# about 12GB.

set -euo pipefail

PROJECT=/project2/jbouteil_621/$USER/pgraph
REPO=$PROJECT/readable
export OLLAMA_MODELS=$PROJECT/ollama-models
export PATH=$PROJECT/ollama/bin:$PATH

say() { echo; echo "=== $* ==="; }

say "project space"
mkdir -p "$PROJECT/ollama" "$OLLAMA_MODELS"
df -h "$PROJECT" | tail -1

say "ollama"
# Pinned, because ollama's download layout has already changed once under this
# script: the .tgz is gone and the releases are zstd tarballs now.
OLLAMA_VERSION=v0.40.13
OLLAMA_TARBALL=ollama-linux-amd64.tar.zst
OLLAMA_URL=https://github.com/ollama/ollama/releases/download/$OLLAMA_VERSION/$OLLAMA_TARBALL

if [ -x "$PROJECT/ollama/bin/ollama" ]; then
    echo "already installed"
else
    curl -fL --retry 3 -o "$PROJECT/$OLLAMA_TARBALL" "$OLLAMA_URL"

    # zstd is not always present, and not always wired into tar, so try the
    # ways it can work before giving up.
    if tar --help 2>&1 | grep -q zstd && tar --zstd -xf "$PROJECT/$OLLAMA_TARBALL" -C "$PROJECT/ollama" 2>/dev/null; then
        echo "extracted with tar --zstd"
    elif command -v unzstd >/dev/null && unzstd -c "$PROJECT/$OLLAMA_TARBALL" | tar -x -C "$PROJECT/ollama"; then
        echo "extracted with unzstd"
    elif command -v zstd >/dev/null && zstd -dc "$PROJECT/$OLLAMA_TARBALL" | tar -x -C "$PROJECT/ollama"; then
        echo "extracted with zstd"
    else
        module load zstd 2>/dev/null || true
        if command -v zstd >/dev/null; then
            zstd -dc "$PROJECT/$OLLAMA_TARBALL" | tar -x -C "$PROJECT/ollama"
            echo "extracted with zstd from a module"
        else
            echo "no zstd available to unpack $OLLAMA_TARBALL" >&2
            echo "try: module avail zstd" >&2
            exit 1
        fi
    fi
    rm -f "$PROJECT/$OLLAMA_TARBALL"
fi
ollama --version

say "ollama server"
if curl -sf http://127.0.0.1:11434/api/tags >/dev/null; then
    echo "already running"
else
    nohup ollama serve > "$PROJECT/ollama-serve.log" 2>&1 &
    for attempt in $(seq 1 60); do
        if curl -sf http://127.0.0.1:11434/api/tags >/dev/null; then
            echo "up after ${attempt}s"
            break
        fi
        if [ "$attempt" -eq 60 ]; then
            echo "server did not start, see $PROJECT/ollama-serve.log" >&2
            exit 1
        fi
        sleep 1
    done
fi

say "models, about 12GB"
for model in qwen3.5:9b nomic-embed-text gemma2:9b; do
    if ollama list | grep -q "^${model%%:*}"; then
        echo "$model already pulled"
    else
        ollama pull "$model"
    fi
done
ollama list

say "repo"
if [ -d "$REPO/.git" ]; then
    git -C "$REPO" pull --ff-only
else
    git clone -b testing https://github.com/NESCOM-Lab/readable "$REPO"
fi
cd "$REPO"

say "toolchain"
# No module purge here. Purging drops the python module the login shell already
# has, leaving the system python 3.6, which is too old to run the harness.
module load gcc 2>/dev/null || true
module load python/3.11.9 2>/dev/null || module load python 2>/dev/null || true

# Discovery has no rust module. rustup needs no root, but its lock files do not
# work on the VAST-backed project filesystem, so it lives in home.
export PATH=$HOME/.cargo/bin:$PATH
if ! command -v cargo >/dev/null; then
    echo "installing rustup into \$HOME/.cargo"
    curl -fsSL https://sh.rustup.rs | sh -s -- -y --no-modify-path
fi

command -v cargo >/dev/null || { echo "cargo still not on PATH" >&2; exit 1; }
cargo --version

PYTHON_VERSION=$(python3 -c 'import sys; print("%d%02d" % sys.version_info[:2])')
if [ "$PYTHON_VERSION" -lt 309 ]; then
    echo "python3 is $(python3 --version), too old; run 'module load python/3.11.9'" >&2
    exit 1
fi
python3 --version

say "build"
# Login nodes cap how many threads one user may spawn, and rustc and the linker
# both exceed it: the build dies with 'Resource temporarily unavailable'. Keep
# the job count down, and run this on a compute node if it still fails.
cargo build --release -j 4

say "corpus"
mkdir -p papers logs
cp Benchmark_Suite/source/PMC3283992.xml papers/maday2012.xml

# The benchmark fingerprints its own source; a mismatch means the evidence
# locators no longer point where the gold says they do.
EXPECTED=9517e5e8a026b6aeec60b2c5553e93f7556f0b0d4f4afc934f0e6865120e4b48
ACTUAL=$(sha256sum papers/maday2012.xml | cut -d' ' -f1)
if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "corpus sha256 mismatch" >&2
    echo "  expected $EXPECTED" >&2
    echo "  actual   $ACTUAL" >&2
    exit 1
fi
echo "sha256 matches the benchmark manifest"

./target/release/pgraph index maday2012
python3 analysis/embed.py maday2012

say "questions"
python3 analysis/benchmark_to_questions.py \
    --workspace papers/maday2012 --track XML --drop-unfindable \
    --out /tmp/questions_check.json

say "done"
echo "repo:    $REPO"
echo "next:    cd $REPO && sbatch analysis/carc_job.slurm"
echo "or try it interactively first:"
echo "  salloc --account=jbouteil_621 --partition=gpu --gres=gpu:a100:1 \\"
echo "         --cpus-per-task=8 --mem=32G --time=1:00:00"
echo "  bash analysis/carc_job.slurm"
