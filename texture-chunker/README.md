# Conversation Chunker

Extracts contiguous Human+Assistant pairs from exported `conversation.md` files and
emits JSONL chunks ready for re-ingestion, then provides tools to clean, tag, and
shard them.

## What it does

- Parses `=== H ===` and `=== C ===` blocks (also supports legacy `=== Human ===` / `=== Assistant ===`).
- Ignores any other role headers and their content.
- Emits chunks containing N contiguous W+C pairs.
- Rewrites role labels to `Voice A` / `Voice B` by default.
- Coalesces consecutive same-role turns to preserve alternation.

## Usage

```powershell
python texture-chunker/chunk_conversation_md.py --pair-count 3
```

### Common options

```powershell
python texture-chunker/chunk_conversation_md.py `
  --exports-root export-pipeline/exports `
  --output texture-chunker/chunks.jsonl `
  --pair-count 4 `
  --stride 2 `
  --human-label "Voice A" `
  --assistant-label "Voice B"
```

## Multiple sizes + overlap

Generate multiple chunk sizes in one pass. If the output ends with `.jsonl`,
files are written as `<prefix>_size-N.jsonl`.

```powershell
python texture-chunker/chunk_conversation_md.py `
  --pair-counts 1,2,3,5 `
  --overlap 1 `
  --output texture-chunker/chunks.jsonl
```

Or write to a directory (one file per size):

```powershell
python texture-chunker/chunk_conversation_md.py `
  --pair-counts 1,2,3,5 `
  --overlap 1 `
  --output texture-chunker/chunks
```

Use a per-size overlap map:

```powershell
python texture-chunker/chunk_conversation_md.py `
  --pair-counts 1,2,3,5 `
  --overlap-map 1:0,2:1,3:1,5:2 `
  --output texture-chunker/chunks
```

## Output

Each JSONL record includes:

- `text`: ready-to-ingest chunk with role headers
- `pairs`: per-pair raw text (`voice_a` / `voice_b`)
- `source_path` and `conversation_name` for traceability
- `tags_primary` and `scale` after tagging (see pipeline)

## Mismatch warnings

If you want to log role pairing mismatches while parsing, add:

```powershell
python texture-chunker/chunk_conversation_md.py --warn-mismatches
```

## Pipeline

1) Chunk exports:

```powershell
python texture-chunker/chunk_conversation_md.py `
  --pair-counts 1,2,3,5 `
  --overlap-map "1:0,2:1,3:1,5:2" `
  --output texture-chunker/chunks
```

2) Clean chunks (strip <thinking> and attachment lines by default):

```powershell
python texture-chunker/clean_chunks.py `
  --input texture-chunker/chunks `
  --output texture-chunker/chunks_clean
```

3) Tag chunks via OpenRouter:

Synchronous version:
```powershell
python texture-chunker/classify_chunks_openrouter.py `
  --input texture-chunker/chunks_clean `
  --output texture-chunker/chunks_tagged `
  --model openai/gpt-4o-mini
```

Async parallelized version (recommended for large batches):
```powershell
python texture-chunker/classify_chunks_openrouter_async.py `
  --input texture-chunker/chunks_clean `
  --output texture-chunker/chunks_tagged `
  --model openai/gpt-4o-mini `
  --workers 10 `
  --error-log texture-chunker/error_logs `
  --preserve-order
```

Notes:
- `--error-log` can be a file path or a directory. If it points to a directory (or exists as one), per-input `*.errors.jsonl` files are created.
- `--preserve-order` buffers output to keep input order; failed lines are skipped to avoid stalling.

4) Score for feels (deterministic):

```powershell
python texture-chunker/feels_scorer.py `
  --input texture-chunker/chunks_tagged `
  --output texture-chunker/chunks_scored
```

5) Sample shards for a pulse (decay + weighted selection):

```powershell
python texture-chunker/shard_sampler.py `
  --input texture-chunker/chunks_scored `
  --state texture-chunker/decay_state.json `
  --out texture-chunker/pulse_injection.txt
```

6) Optional sanity stats:

```powershell
python texture-chunker/feels_stats.py `
  --input texture-chunker/chunks_scored `
  --top-percentile 0.3
```

Optional antagonism:

```powershell
python texture-chunker/shard_sampler.py `
  --input texture-chunker/chunks_scored `
  --state texture-chunker/decay_state.json `
  --out texture-chunker/pulse_injection.txt `
  --antagonism-prob 0.1 `
  --antagonism-percentile 0.1
```

Scale filtering and per-size percentile:

```powershell
python texture-chunker/shard_sampler.py `
  --input texture-chunker/chunks_scored `
  --state texture-chunker/decay_state.json `
  --out texture-chunker/pulse_injection.txt `
  --scale meso
```

Notes:
- Per-size percentile selection is enabled by default; disable with `--no-per-size-percentile`.
- `--scale` accepts a comma-separated list: `micro,meso,macro`.

7) Filter + shard (alternative path):

```powershell
python texture-chunker/filter_and_shard.py `
  --input texture-chunker/chunks_tagged `
  --output texture-chunker/style_shards.jsonl
```

8) Sample per pulse (legacy shard path):

```powershell
python texture-chunker/pulse_sampler.py --count 1
```

### Recommended run (current setup)

```powershell
python texture-chunker/chunk_conversation_md.py `
  --pair-counts "1,2,3,5" `
  --overlap-map "1:0,2:1,3:1,5:2" `
  --output texture-chunker/chunks

python texture-chunker/clean_chunks.py `
  --input texture-chunker/chunks `
  --output texture-chunker/chunks_clean

python texture-chunker/classify_chunks_openrouter_async.py `
  --input texture-chunker/chunks_clean `
  --output texture-chunker/chunks_tagged `
  --model openai/gpt-4o-mini `
  --workers 10 `
  --error-log texture-chunker/error_logs `
  --preserve-order

python texture-chunker/feels_scorer.py `
  --input texture-chunker/chunks_tagged `
  --output texture-chunker/chunks_scored

python texture-chunker/shard_sampler.py `
  --input texture-chunker/chunks_scored `
  --state texture-chunker/decay_state.json `
  --out texture-chunker/pulse_injection.txt
```

### Daily production runner (incremental)

Processes only new `conversation.md` exports and appends into the existing
`chunks*`, `chunks_clean`, `chunks_tagged`, and `chunks_scored` directories.

```powershell
python texture-chunker/run_texture_pipeline.py `
  --exports-root export-pipeline/exports `
  --model openai/gpt-4o-mini `
  --workers 10 `
  --preserve-order
```

## Dependencies

For synchronous scripts:
```powershell
pip install python-dotenv requests
```

For async classifier (`classify_chunks_openrouter_async.py`):
```powershell
pip install python-dotenv aiohttp aiofiles
```

Or install all dependencies:
```powershell
pip install python-dotenv requests aiohttp aiofiles
```
