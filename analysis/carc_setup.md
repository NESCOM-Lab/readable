# Running the evaluation on CARC

Single paper only. The Benchmark_Suite covers one article (PMC3283992, Maday
2012), so every question in it is atomic or within-paper synthesis. Nothing here
needs the cross-paper support the CLI does not have.

The allocation is `jbouteil_621` (Multiscale Modeling). Compute is charged to
that slurm account; the ARMY project has storage but no slurm account, so it
cannot run jobs. Confirm with the PI which account should carry this.

## Step 0, on the laptop: push the work

This is the blocker. `origin` is https://github.com/NESCOM-Lab/readable and the
last commit on `testing` is `3176e82 analysis wip`, which predates all of the
harness. `run_eval.py`, `score.py`, `similar.py`, `bm25.py`, `src/units.rs` and
the parser fixes are untracked or unstaged, so a clone on the cluster builds
nothing usable. Commit and push before going anywhere.

`Benchmark_Suite/` is untracked too, and not ignored. It is about 4MB, mostly
the PDF and figures. Either commit it or copy it over separately:

```sh
scp -r Benchmark_Suite <username>@discovery.usc.edu:/project2/jbouteil_621/<username>/pgraph/
```

Committing it is simpler. It is evaluation material, so it must never be fed to
the indexer, but keeping it in git does not do that by itself.

## Step 1, login node: stage ollama and the models

The login node has internet and the compute nodes do not, so this has to happen
here. There is no root on CARC, so ollama comes from the release tarball rather
than the install script.

```sh
ssh <username>@discovery.usc.edu

PROJECT=/project2/jbouteil_621/$USER/pgraph
mkdir -p $PROJECT/ollama $PROJECT/ollama-models

curl -L https://ollama.com/download/ollama-linux-amd64.tgz \
    | tar -xz -C $PROJECT/ollama

export PATH=$PROJECT/ollama/bin:$PATH
export OLLAMA_MODELS=$PROJECT/ollama-models

ollama serve &
ollama pull qwen3.5:9b          # the generator
ollama pull nomic-embed-text    # the embedder
ollama pull gemma2:9b           # the judge, for the prose content points
ollama list                     # all three, about 12GB together
```

Leave the server running for step 2, which needs it to embed.

## Step 2, login node: the repo and the corpus

```sh
cd $PROJECT
git clone -b testing https://github.com/NESCOM-Lab/readable
cd readable

module load rust        # or whatever `module avail rust` lists
cargo build --release
```

Use the benchmark's own XML as the corpus, not a fresh download. `manifest.json`
fingerprints it with a sha256, so using that exact file is what makes the run
comparable to the benchmark's evidence locators:

```sh
mkdir -p papers
cp ../Benchmark_Suite/source/PMC3283992.xml papers/maday2012.xml   # if copied separately
cp Benchmark_Suite/source/PMC3283992.xml papers/maday2012.xml      # if committed

shasum -a 256 papers/maday2012.xml
# must equal 9517e5e8a026b6aeec60b2c5553e93f7556f0b0d4f4afc934f0e6865120e4b48

./target/release/pgraph index maday2012
python3 analysis/embed.py maday2012
```

Then build the questions file from the benchmark gold set. The job does this
itself, but run it once by hand to read what it reports:

```sh
python3 analysis/benchmark_to_questions.py --workspace papers/maday2012 \
    --track XML --drop-unfindable --out /tmp/questions_benchmark.json
```

Expect `145 questions, 288 content points`, split `184` regex and `104` judge,
with `15 regex facets dropped as unfindable in the corpus`. Those 15 are real
gold-versus-corpus gaps, not converter bugs: 13 are front matter (volume, pages,
DOI, dates, affiliation) which `pgraph index` does not carry, and 2 ask for
'CCD' in a camera model the XML names without it. Dropping them keeps the
denominator to what some condition could actually reach.

The suite's 10 unanswerable questions in this track are left out by default.
Abstention is scored by *not* producing content, which a coverage metric cannot
express; `--include-unanswerable` keeps them but nothing yet reports them
properly.

Only `source/` is corpus. Never index `Benchmark_Suite/benchmark/` or its
README: they contain the reference answers.

Then stop the ollama server from step 1, since the job starts its own:

```sh
pkill -u $USER ollama
```

## Step 3: submit

```sh
mkdir -p logs          # slurm opens the output file, so this must exist first
sbatch analysis/carc_job.slurm
squeue -u $USER
tail -f logs/eval-<jobid>.out
```

The job runs ollama and the harness on the same node over loopback, so it needs
no `OLLAMA_HOST`.

It writes to `results/<date>-carc/` and scores the same records twice:
`scores_regex_only.txt` is deterministic and reproducible, and
`scores_judged.txt` also covers the prose points. Compare them; a large gap
means the judge is doing most of the work and deserves checking by hand.

Budget: 145 questions x 6 conditions x 3 runs is about 2,600 generations, plus
roughly 7,000 judge calls on top. On one A100 expect a few hours, against about
21 hours on a laptop, which is the reason for doing this here.

## First run will probably fail

None of this has been tested against the real cluster. Rather than burning a
batch job per mistake, take an interactive node and run the steps by hand:

```sh
salloc --account=jbouteil_621 --partition=gpu --gres=gpu:a100:1 \
       --cpus-per-task=8 --mem=32G --time=1:00:00
```

Things most likely to be wrong: the scratch path `/scratch1/$USER`, the GPU
request form (`--gres=gpu:a100:1` vs `--constraint=a100-80gb`), which modules
provide `cargo` and a recent `python3`, and whether that ollama tarball URL is
current.

## Checking the allocation

```sh
sacctmgr show assoc user=$USER format=account,partition,qos,maxjobs
sinfo -p gpu -o "%n %G %t"     # which GPU nodes are idle
sacct -u $USER --format=jobid,jobname,state,elapsed,alloctres%40
```

## Running the models on one node and the harness on another

Not needed for the normal case. If the two are ever split, ollama has to bind
beyond loopback and the harness has to be pointed at it:

```sh
# on the GPU node
OLLAMA_HOST=0.0.0.0:11434 ollama serve

# wherever the harness runs
export OLLAMA_HOST=<gpu-node-hostname>:11434
```

The harness adds the `http://` when the value does not carry a scheme, so
either form works. `OLLAMA_HOST` means the bind address to ollama and the server
to reach to the harness, which is the same string only when the server is
reachable under the name it binds.

## Reproducibility

Results from CARC and results from a laptop should not share a table. The model
and temperature are the same, but a different backend can still produce
different token-level output, and the comparison between conditions is only
clean when every condition ran on the same machine. Each run writes its own
`results/<date>-carc/`, and `METHOD.md` should record which hardware produced
it.
