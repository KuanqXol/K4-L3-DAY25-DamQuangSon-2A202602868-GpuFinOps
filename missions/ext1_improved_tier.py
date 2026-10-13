"""Extension 1 -- Improved recommend_tier() demo.

Compares the original simple tier policy vs the enhanced policy that considers:
  1. GPU-type-specific spot interruption rates
  2. 1yr vs 3yr reserved commitment based on job duration

Run: python missions/ext1_improved_tier.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from missions._common import load_csv, num, catalog_by_type
from finops import pricing

DAYS = 30


def run_comparison():
    jobs = load_csv("workloads.csv")
    cat = catalog_by_type()

    print("=" * 80)
    print("  EXTENSION 1 -- Improved recommend_tier() Comparison")
    print("=" * 80)

    # --- GPU Interrupt Rate Table ---
    print("\n### GPU-Type Spot Interruption Rates")
    print(f"{'GPU Type':10}{'Interrupt Rate':>16}{'Risk Level':>14}")
    for gpu, rate in [("L4", 0.02), ("A10G", 0.03), ("A100", 0.05),
                      ("MI300X", 0.06), ("H100", 0.08), ("H200", 0.10), ("B200", 0.12)]:
        level = "Low" if rate <= 0.03 else ("Medium" if rate <= 0.06 else "High")
        print(f"{gpu:10}{rate:>14.0%}{level:>14}")

    print(f"\n{'job':18}{'gpu':7}{'h/d':>5}{'days':>6}{'int?':>6}"
          f"{'OLD tier':>12}{'NEW tier':>12}{'OLD cost':>12}{'NEW cost':>12}{'Diff':>10}")

    old_total = new_total = od_total = 0.0
    for j in jobs:
        gtype = j["gpu_type"]
        ngpu = int(num(j["num_gpus"]))
        hpd = num(j["hours_per_day"])
        jdays = int(num(j["days"]))
        interruptible = bool(int(num(j["interruptible"])))
        c = cat[gtype]
        gpu_hours = hpd * DAYS * ngpu
        od = num(c["on_demand_hr"])
        on_demand_cost = gpu_hours * od

        # OLD: simple policy (no gpu_type, no job_days)
        old_tier = pricing.recommend_tier(hpd, interruptible)
        # NEW: enhanced policy
        new_tier = pricing.recommend_tier(hpd, interruptible, gpu_type=gtype, job_days=jdays)

        def cost_for_tier(tier):
            if tier == "spot":
                sim = pricing.spot_checkpoint_cost(gpu_hours, num(c["spot_hr"]), od)
                return sim["spot_cost"]
            elif tier == "reserved":
                return gpu_hours * num(c["reserved_3yr_hr"])
            return on_demand_cost

        old_cost = cost_for_tier(old_tier)
        new_cost = cost_for_tier(new_tier)
        od_total += on_demand_cost
        old_total += old_cost
        new_total += new_cost
        delta = new_cost - old_cost
        marker = " <-- CHANGED" if old_tier != new_tier else ""

        print(f"{j['job_id']:18}{gtype:7}{hpd:>5.0f}{jdays:>6}{str(interruptible):>6}"
              f"{old_tier:>12}{new_tier:>12}${old_cost:>10,.0f}${new_cost:>10,.0f}"
              f"{'${:+,.0f}'.format(delta):>10}{marker}")

    old_savings_pct = (1 - old_total / od_total) * 100 if od_total else 0
    new_savings_pct = (1 - new_total / od_total) * 100 if od_total else 0

    print(f"\n{'SUMMARY':18}{'':7}{'':5}{'':6}{'':6}"
          f"{'OLD':>12}{'NEW':>12}{'on-demand':>12}")
    print(f"{'Total monthly':18}{'':7}{'':5}{'':6}{'':6}"
          f"${old_total:>10,.0f}${new_total:>10,.0f}${od_total:>10,.0f}")
    print(f"{'Savings vs OD':18}{'':7}{'':5}{'':6}{'':6}"
          f"{old_savings_pct:>11.1f}%{new_savings_pct:>11.1f}%")

    print("\n### Key Insights")
    print("1. Jobs with high-interrupt GPUs (B200 12%, H200 10%) should avoid spot")
    print("   when rework overhead erodes savings below 15%.")
    print("2. Short jobs (< 180 days) should not lock into 3yr reserved -- 1yr break-even")
    print("   requires higher utilization (~80% duty cycle vs 55%).")
    print("3. The enhanced policy is more conservative but avoids hidden costs from")
    print("   spot interruptions and premature commitment lock-in.")

    return {
        "old_total": round(old_total),
        "new_total": round(new_total),
        "on_demand_total": round(od_total),
        "old_savings_pct": round(old_savings_pct, 1),
        "new_savings_pct": round(new_savings_pct, 1),
    }


if __name__ == "__main__":
    run_comparison()
