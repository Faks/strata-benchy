"""Needle-in-haystack recall probes (Strata fork).

Builds a filler prompt to a target depth, buries one exact sentence in the
middle, asks for it back, and checks the answer verbatim. Measures what
throughput benchmarks cannot: whether the model still retrieves at depth.

Cache discipline is load-bearing here (learned the hard way: repeats hit the
prompt/conversation cache and fake the numbers): every probe uses a fresh
corpus offset, and --strata implies --no-cache.
"""

import time
from dataclasses import dataclass, field
from typing import List, Optional

DEFAULT_NEEDLE = "The vault code is 739284."

QUESTION = "State the exact sentence about the vault code, word for word. Reply with that sentence only."


@dataclass
class NeedleResult:
    depth_requested: int
    prompt_tokens: int = 0
    prefill_srv_tps: Optional[float] = None
    wall_s: float = 0.0
    passed: bool = False
    answer_head: str = ""


def build_haystack(corpus_text: str, target_chars: int, needle: str, offset: int) -> str:
    """Filler of ~target_chars with the needle buried at the middle.

    offset rotates the corpus slice so repeated runs never share a prefix
    (prompt-cache artifacts otherwise).
    """
    n = len(corpus_text)
    o = offset % n
    fill = (corpus_text[o:] + corpus_text[:o])
    reps = target_chars // len(fill) + 2
    fill = (fill * reps)[:target_chars]
    half = target_chars // 2
    return fill[:half] + "\n" + needle + "\n" + fill[half:]


async def run_needle_suite(config, client, corpus_text: str) -> List[NeedleResult]:
    import aiohttp

    results: List[NeedleResult] = []
    timeout = aiohttp.ClientTimeout(total=1800)
    connector = aiohttp.TCPConnector(limit=2)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True) as session:
        for i, depth in enumerate(config.needle_depths):
            # ~4 chars/token is the working estimate; the server-reported
            # prompt_tokens is authoritative and printed per row.
            hay = build_haystack(corpus_text, depth * 4, config.needle_text, offset=i * 7919)
            t0 = time.perf_counter()
            res = await client.run_generation(
                session,
                context_text="",
                prompt_text=hay + "\n" + QUESTION,
                max_tokens=64,
                no_cache=True,
                tokenizer=None,
            )
            wall = time.perf_counter() - t0
            answer = res.answer_text or ""
            passed = (not res.error) and (config.needle_text in answer)
            row = NeedleResult(
                depth_requested=depth,
                prompt_tokens=res.prompt_tokens,
                prefill_srv_tps=res.server_pp_tps,
                wall_s=round(wall, 1),
                passed=passed,
                answer_head=answer[:80].replace("\n", " "),
            )
            results.append(row)
            status = "PASS" if passed else ("ERROR: " + (res.error or "?")[:100] if res.error else "FAIL")
            print(f"needle@{depth}: prompt~{row.prompt_tokens} prefill_srv={res.server_pp_tps} wall={row.wall_s}s -> {status}",
                  flush=True)
    return results


def print_needle_report(results: List[NeedleResult]) -> None:
    print("\n| depth | prompt_tok | srv prefill t/s | wall (s) | result |")
    print("|:------|-----------:|----------------:|---------:|:-------|")
    for r in results:
        ppt = f"{r.prefill_srv_tps:.1f}" if r.prefill_srv_tps else "?"
        print(f"| {r.depth_requested} | {r.prompt_tokens} | {ppt} | {r.wall_s} | {'PASS' if r.passed else 'FAIL'} |")
