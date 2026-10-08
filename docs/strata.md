# Benchmarking Strata (Qwen3.8-Flash-Next local engine)

Canonical repo: https://github.com/Faks/strata-benchy (public; CLI command remains
`llama-benchy`). Upstream PRs #34/#35 were closed without review — this fork is
the maintained home of Strata support.

Strata serves an OpenAI-compatible API with three behaviors stock benchy
misreads. This fork adapts them; use `--strata` and the rest is handled.

Contributions require honest disclosure of authorship (human / AI / mixed) —
see README. LLM-authored PRs welcome; all PRs face the same gates.

## Quick start

```bash
llama-benchy --base-url http://127.0.0.1:9797/v1 --api-key <any> \
  --model qwen3.8-flash-next --strata \
  --pp 512 --tg 64 --depth 0 8192 32768 --runs 2 --format md
```

`--strata` = `reasoning_effort=none` + `--no-cache` + artifact filtering.
Without it, thinking tokens pollute decode numbers and prompt/conversation
cache hits fake prefill numbers (measured: 512 tokens at 156,393 tok/s off a
3 ms keep-alive; true rate ~260).

## The standard protocol (R9700 reference)

```bash
# Serial speeds (client and srv columns must agree within ~10%)
llama-benchy ... --strata --pp 4096 32768 131072 --tg 256 --depth 0 --runs 1

# Concurrent pair (parallel rigs; per-request pp may show [N cached])
llama-benchy ... --strata --pp 32768 --tg 64 --concurrency 2 --runs 1

# Thinking level (medium/high add real reasoning tokens)
llama-benchy ... --no-cache --extra-body reasoning_effort=medium \
  --pp 512 --tg 512 --depth 0 --runs 1

# Recall at depth (the 262K reason Strata exists)
llama-benchy ... --strata --needle 32768 262144
```

## Reading the columns

- `t/s`, `ttfr`, `e2e_ttft`: client clocks (fixed to measure against the first
  TOKEN, never a keep-alive).
- `srv t/s`: the server's own `timings` object when the backend reports one.
  Disagreement with `t/s` is information, not error — investigate, don't average.
- `drafts`: speculative-decoding accepted/offered (Strata MTP).
- `[N cached]`: N requests reused server KV (cache_n>0) or reported absurd
  shared-window speeds — excluded from prefill stats, counted in the open.

## Rules that cost us real hours

1. Fresh prompts always (`--strata` implies `--no-cache`). Repeats hit the
   prompt/conversation cache: 4.3 tok/s artifacts, 1-second walls, 126M tok/s
   fantasy. Same template + same word pool is NOT fresh — the server shares
   engine batch slots across concurrent same-model requests.
2. Answers before numbers: a fast wrong answer is a failure. Spot-check content
   on new shapes (we run APPLES/ZEBRAS probes for concurrent sanity).
3. Over-window prompts get HTTP 400, not truncation. Size needle fill with margin.
4. Thinking defaults to high on Strata: any decode number without an explicit
   `reasoning_effort` is measuring thinking, not the engine.
