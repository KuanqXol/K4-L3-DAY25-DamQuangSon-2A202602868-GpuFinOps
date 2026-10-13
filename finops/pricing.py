"""Pricing & purchasing economics — measure in $/1M-token, not $/GPU-hr.

Figures are June-2026 as-of snapshots from the deck's RESEARCH dossier; treat
live prices as fast-moving (re-baseline before each cohort).
"""
from __future__ import annotations


def request_cost(
    input_tok: int,
    output_tok: int,
    price_in_per_m: float,
    price_out_per_m: float,
    cached_in: int = 0,
    cache_discount: float = 0.10,   # Anthropic cached-read ~0.1x (=-90%)
    batch: bool = False,
    batch_discount: float = 0.50,   # Batch API ~ -50%
) -> float:
    """USD cost of a single request. Cached input billed at cache_discount x price."""
    cached_in = min(max(0, cached_in), input_tok)
    uncached_in = input_tok - cached_in
    cost = (
        (uncached_in / 1e6) * price_in_per_m
        + (cached_in / 1e6) * price_in_per_m * cache_discount
        + (output_tok / 1e6) * price_out_per_m
    )
    if batch:
        cost *= batch_discount
    return cost


def dollars_per_million(total_cost_usd: float, total_tokens: int) -> float:
    """Aggregate unit economics: $ per 1,000,000 tokens served."""
    if total_tokens <= 0:
        return 0.0
    return total_cost_usd / (total_tokens / 1e6)


def discount_stack(
    batch: bool = False,
    cache_hit_frac: float = 0.0,
    batch_discount: float = 0.50,
    cache_discount: float = 0.10,
) -> float:
    """Effective fraction of the naive bill after stacking discounts (input-heavy view).

    Discounts MULTIPLY: cache applies to the cached share of input, batch to the
    whole bill. batch + 100% cache-hit -> 0.5 * 0.1 = 0.05 (~95% off).
    """
    cache_mult = cache_hit_frac * cache_discount + (1.0 - cache_hit_frac)
    batch_mult = batch_discount if batch else 1.0
    return cache_mult * batch_mult


def break_even_utilization(discount_frac: float) -> float:
    """Utilization at which a commitment pays off ~= 1 - discount.

    A 45% reserved discount needs ~55% utilization (~13.2h/day) to beat on-demand.
    """
    return max(0.0, min(1.0, 1.0 - discount_frac))


def recommend_tier(hours_per_day: float, interruptible: bool, reserved_discount: float = 0.45,
                   gpu_type: str | None = None, job_days: int | None = None) -> str:
    """Pick a purchasing tier from a workload's duty cycle + interruptibility.

    ENHANCED policy (Extension 1) — adds two factors on top of the base rule:
      1. Interruption rate varies by GPU type (H100 spot is scarce → higher
         preemption risk; A10G/L4 spot is plentiful → lower risk).  When the
         effective spot-adjusted savings fall below 15%, prefer on_demand/reserved.
      2. For reserved, compare 1yr vs 3yr commitment cost.  Short jobs (< 180 days)
         should not lock into 3yr; if only 1yr is available the break-even bar is
         higher (smaller discount).

    Backward-compatible: when gpu_type/job_days are None, falls back to the original
    simple policy so existing tests still pass unchanged.
    """
    # --- GPU-type-specific interruption rates (Extension 1a) ---
    GPU_INTERRUPT_RATE = {
        "H100": 0.08,   # high demand → spot preempted more often
        "H200": 0.10,   # very high demand
        "A100": 0.05,   # moderate demand
        "A10G": 0.03,   # plentiful → rarely preempted
        "L4":   0.02,   # very plentiful
        "B200": 0.12,   # newest/scarcest
        "MI300X": 0.06,
    }

    # --- Reserved discount by commitment length (Extension 1b) ---
    # 1yr gives a smaller discount than 3yr
    RESERVED_1YR_DISCOUNT = 0.20   # ~20% off on-demand
    RESERVED_3YR_DISCOUNT = 0.45   # ~45% off on-demand (the default)

    duty = max(0.0, hours_per_day) / 24.0
    be = break_even_utilization(reserved_discount)

    # --- Original simple policy (backward compat) ---
    if interruptible and hours_per_day < 24:
        # Extension 1a: check if spot is truly worthwhile for this GPU type
        if gpu_type is not None:
            ir = GPU_INTERRUPT_RATE.get(gpu_type, 0.05)
            # Effective spot savings after accounting for rework:
            # spot_hr / on_demand_hr ≈ 0.55-0.60, but rework eats into it.
            # If interrupt rate > 10%, the rework overhead can erode spot savings
            # below the threshold where on_demand or reserved is better.
            rework_penalty = ir * 1.5  # reload overhead and compute rework
            ckpt_overhead = 0.05
            effective_cost_ratio = (1.0 + ckpt_overhead + rework_penalty) * 0.65
            if ir >= 0.10 or effective_cost_ratio > 0.85:
                # High interruption risk (≥10% preemption rate) erodes spot viability
                if duty >= be:
                    return "reserved"
                return "on_demand"
        return "spot"

    if duty >= be:
        # Extension 1b: for short jobs, 1yr reserved may be better than 3yr
        if job_days is not None and job_days < 180:
            be_1yr = break_even_utilization(RESERVED_1YR_DISCOUNT)
            if duty >= be_1yr:
                return "reserved"   # qualifies even under stricter 1yr break-even
            return "on_demand"      # doesn't meet 1yr break-even for short duration
        return "reserved"

    return "on_demand"


def cache_is_worth_it(
    avg_cache_reads: float,
    write_cost_per_m: float,
    read_discount: float = 0.10,
) -> bool:
    """Cache is worth it only when total savings from reads exceed write cost.

    Extension 3: Break-even analysis for prompt caching economics.

    A cached prefix costs `write_cost_per_m` to store. Each subsequent read saves
    `(1 - read_discount)` = 90% of the input price. Cache is profitable when:
        avg_cache_reads * (1 - read_discount) * read_price > write_cost
    Simplifying (assuming read_price ≈ write_cost_per_m):
        avg_cache_reads > 1 / (1 - read_discount)

    Args:
        avg_cache_reads: Average number of times each cached prefix is re-read.
        write_cost_per_m: Cost per 1M tokens to write/store the cache.
        read_discount: Fraction of original price charged for cached reads (0.10 = 90% off).

    Returns:
        True if caching is economically beneficial.
    """
    if write_cost_per_m <= 0 or read_discount >= 1.0:
        return True  # free cache or free reads → always worth it
    savings_per_read = (1.0 - read_discount)  # fraction saved per read
    # Break-even: need enough reads so total savings > write cost
    # Each read saves (1 - read_discount) * price; writing costs 1 * price
    # => break-even reads = 1 / (1 - read_discount)
    break_even_reads = 1.0 / savings_per_read
    return avg_cache_reads >= break_even_reads


def spot_checkpoint_cost(
    job_hours: float,
    spot_hr: float,
    on_demand_hr: float,
    interrupt_rate: float = 0.05,      # per-hour chance (H100 spot ~<5%)
    ckpt_overhead_frac: float = 0.03,  # steady cost of writing checkpoints
    rework_hours_per_interrupt: float = 0.5,
) -> dict:
    """Effective cost of running a checkpointable job on spot vs on-demand.

    Interruptions waste the compute since the last checkpoint (rework); checkpointing
    adds a small steady overhead. Spot still wins for interruptible jobs.
    """
    expected_interrupts = job_hours * interrupt_rate
    rework_hours = expected_interrupts * rework_hours_per_interrupt
    effective_hours = job_hours * (1.0 + ckpt_overhead_frac) + rework_hours
    spot_cost = effective_hours * spot_hr
    on_demand_cost = job_hours * on_demand_hr
    savings_pct = (1.0 - spot_cost / on_demand_cost) * 100.0 if on_demand_cost > 0 else 0.0
    return {
        "spot_effective_hours": round(effective_hours, 2),
        "spot_cost": round(spot_cost, 2),
        "on_demand_cost": round(on_demand_cost, 2),
        "savings_pct": round(savings_pct, 1),
    }
