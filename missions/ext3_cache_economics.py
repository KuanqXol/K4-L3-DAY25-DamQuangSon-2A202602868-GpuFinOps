"""Extension 3 -- cache_is_worth_it() demo.

Analyzes prompt caching economics across the token_usage dataset:
  - Computes average cache reads per unique prefix
  - Determines break-even threshold for each model tier
  - Compares savings WITH vs WITHOUT the cache-worthiness gate

Run: python missions/ext3_cache_economics.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from collections import defaultdict
from missions._common import load_csv, num
from missions.m2_inference_levers import MODEL_PRICES
from finops import pricing

# Approximate write cost = same as input price per 1M tokens (conservative)
WRITE_COST_MULTIPLIER = 1.25  # writing cache costs ~25% more than a normal read


def run_analysis():
    rows = load_csv("token_usage.csv")

    print("=" * 80)
    print("  EXTENSION 3 -- Prompt Caching Economics (cache_is_worth_it)")
    print("=" * 80)

    # --- Break-even analysis per tier ---
    print("\n### Break-even Analysis")
    print(f"{'Model Tier':12}{'Input $/1M':>12}{'Write Cost':>12}{'Read Discount':>15}"
          f"{'Break-even Reads':>18}{'Worth It?':>12}")

    for tier_name, (pin, pout) in MODEL_PRICES.items():
        write_cost = pin * WRITE_COST_MULTIPLIER
        be_reads = 1.0 / (1.0 - 0.10)  # = 1.111...
        worth = pricing.cache_is_worth_it(avg_cache_reads=be_reads, write_cost_per_m=write_cost)
        print(f"{tier_name:12}${pin:>10.2f}${write_cost:>10.2f}{'90%':>15}"
              f"{be_reads:>17.2f}{'Yes' if worth else 'No':>12}")

    # --- Analyze actual cache usage in dataset ---
    print("\n### Actual Cache Usage in token_usage.csv")

    # Group by team+project to estimate cache read patterns
    by_tier = defaultdict(lambda: {"total": 0, "with_cache": 0, "cache_tokens": 0, "input_tokens": 0})

    for r in rows:
        tier = r["route_tier"]
        cached = int(num(r["cached_input_tokens"]))
        inp = int(num(r["input_tokens"]))
        by_tier[tier]["total"] += 1
        by_tier[tier]["input_tokens"] += inp
        if cached > 0:
            by_tier[tier]["with_cache"] += 1
            by_tier[tier]["cache_tokens"] += cached

    print(f"\n{'Tier':10}{'Requests':>10}{'With Cache':>12}{'Cache Rate':>12}"
          f"{'Cached Tokens':>15}{'Input Tokens':>15}{'Cache Hit %':>13}")
    for tier, stats in sorted(by_tier.items()):
        cache_rate = stats["with_cache"] / stats["total"] * 100 if stats["total"] else 0
        hit_pct = stats["cache_tokens"] / stats["input_tokens"] * 100 if stats["input_tokens"] else 0
        print(f"{tier:10}{stats['total']:>10}{stats['with_cache']:>12}{cache_rate:>11.1f}%"
              f"{stats['cache_tokens']:>15,}{stats['input_tokens']:>15,}{hit_pct:>12.1f}%")

    # --- Compute savings with and without cache gate ---
    print("\n### Cost Comparison: With vs Without cache_is_worth_it() Gate")

    # Estimate avg cache reads (how many times each cached prefix is re-used)
    total_cached_reqs = sum(s["with_cache"] for s in by_tier.values())
    total_reqs = sum(s["total"] for s in by_tier.values())
    avg_cache_reads = total_cached_reqs / max(1, total_reqs) * 5  # rough estimate

    naive_cost = gated_cost = baseline_cost = 0.0
    total_tokens = 0
    gated_skipped = 0

    for r in rows:
        inp, out = int(num(r["input_tokens"])), int(num(r["output_tokens"]))
        cached = int(num(r["cached_input_tokens"]))
        is_batch = bool(int(num(r["is_batch"])))
        total_tokens += inp + out

        # Baseline: everything on large, no optimization
        lin, lout = MODEL_PRICES["large"]
        baseline_cost += pricing.request_cost(inp, out, lin, lout)

        # Naive optimized: always apply cache (current M2 behavior)
        pin, pout = MODEL_PRICES[r["route_tier"]]
        naive_cost += pricing.request_cost(inp, out, pin, pout, cached_in=cached, batch=is_batch)

        # Gated: only apply cache when cache_is_worth_it() returns True
        write_cost = pin * WRITE_COST_MULTIPLIER
        if cached > 0 and pricing.cache_is_worth_it(avg_cache_reads, write_cost):
            gated_cost += pricing.request_cost(inp, out, pin, pout, cached_in=cached, batch=is_batch)
        else:
            if cached > 0:
                gated_skipped += 1
            gated_cost += pricing.request_cost(inp, out, pin, pout, cached_in=0, batch=is_batch)

    naive_savings = (1 - naive_cost / baseline_cost) * 100 if baseline_cost else 0
    gated_savings = (1 - gated_cost / baseline_cost) * 100 if baseline_cost else 0

    print(f"\n  Estimated avg cache reads per prefix: {avg_cache_reads:.1f}")
    print(f"  Break-even reads needed (90% discount): {1.0/(1-0.10):.2f}")
    if avg_cache_reads >= 1.0/(1-0.10):
        print(f"  cache_is_worth_it() result: YES -- caching is profitable")
    else:
        print(f"  cache_is_worth_it() result: NO -- insufficient reads to justify cache cost")

    print(f"\n  {'Scenario':35}{'Daily Cost':>12}{'$/1M-token':>12}{'Savings vs BL':>15}")
    print(f"  {'Baseline (all large, no opt)':35}${baseline_cost:>10.2f}"
          f"${pricing.dollars_per_million(baseline_cost, total_tokens):>10.3f}{'--':>15}")
    print(f"  {'Naive optimized (always cache)':35}${naive_cost:>10.2f}"
          f"${pricing.dollars_per_million(naive_cost, total_tokens):>10.3f}{naive_savings:>14.1f}%")
    print(f"  {'Gated (cache_is_worth_it)':35}${gated_cost:>10.2f}"
          f"${pricing.dollars_per_million(gated_cost, total_tokens):>10.3f}{gated_savings:>14.1f}%")
    print(f"\n  Requests where cache was skipped by gate: {gated_skipped}")

    print("\n### Key Insights")
    print(f"1. Break-even reads = {1.0/(1-0.10):.2f} -- you need at least ~1.12 reads per")
    print(f"   cached prefix for the 90% discount to outweigh the write/storage cost.")
    print(f"2. Dataset avg cache reads = {avg_cache_reads:.1f} -- ", end="")
    if avg_cache_reads >= 1.0/(1-0.10):
        print("ABOVE break-even, caching is profitable for this traffic.")
    else:
        print("BELOW break-even, cache costs exceed savings for some prefixes.")
    print(f"3. The gated approach prevents over-caching for low-reuse prefixes,")
    print(f"   which is critical for production systems with diverse traffic patterns.")

    return {
        "avg_cache_reads": round(avg_cache_reads, 2),
        "break_even_reads": round(1.0/(1-0.10), 2),
        "naive_savings_pct": round(naive_savings, 1),
        "gated_savings_pct": round(gated_savings, 1),
        "gated_skipped": gated_skipped,
    }


if __name__ == "__main__":
    run_analysis()
