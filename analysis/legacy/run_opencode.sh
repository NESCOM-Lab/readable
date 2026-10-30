#!/bin/bash
# CLI condition: opencode plan agent navigates the pgraph workspace files.
cd /Users/abhishekkakolla/code/curve/readable

export OPENCODE_CONFIG_CONTENT='{
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama local",
      "options": { "baseURL": "http://127.0.0.1:11434/v1" },
      "models": {
        "qwen3.5:9b": { "name": "Qwen 3.5 9B", "limit": { "context": 32768, "output": 4096 } }
      }
    }
  }
}'

START=$(date +%s)
timeout 330 opencode run \
  --model ollama/qwen3.5:9b \
  --agent plan \
  'Evaluate the paper workspace in PMC11289285-test/ without modifying files. Start with PMC11289285-test/README.md. Navigate using file listing, reading, and grep/search. Do NOT read paper.json or paper.jats.xml in full. Answer in under 200 words: Explain how adult neurogenesis improves spatial information encoding in the mouse hippocampus, including (1) the experimental manipulations, (2) the measured neural effects, (3) the proposed mechanism, and (4) how it contrasts with prior views. Cite the section filenames and reference IDs you used.' \
  2>&1
STATUS=$?
END=$(date +%s)
echo ""
echo "=== opencode exit=$STATUS elapsed=$((END-START))s ==="
