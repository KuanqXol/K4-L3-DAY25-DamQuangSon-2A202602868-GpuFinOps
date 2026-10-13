"""Unit tests for Lab 25 Extensions:
- Extension 1: Improved recommend_tier() with GPU interruption rates and 1yr vs 3yr commitment.
- Extension 3: cache_is_worth_it() prompt caching break-even economics.

Run: python missions/test_extensions.py
"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from finops import pricing


def test_ext1_recommend_tier_backward_compat():
    """Verify that original signatures and behavior remain completely intact."""
    assert pricing.recommend_tier(2, True) == "spot"
    assert pricing.recommend_tier(24, False) == "reserved"
    assert pricing.recommend_tier(4, False) == "on_demand"


def test_ext1_recommend_tier_gpu_interruption_rate():
    """High preemption rate GPUs (e.g. B200 at 12%, H200 at 10%) should avoid spot

    when interruption risk / rework penalty erodes savings. Plentiful GPUs (L4, A10G)
    remain on spot.
    """
    # L4 has very low interruption rate (2%) -> recommend spot
    tier_l4 = pricing.recommend_tier(hours_per_day=10, interruptible=True, gpu_type="L4")
    assert tier_l4 == "spot"

    # A10G has low interruption rate (3%) -> recommend spot
    tier_a10g = pricing.recommend_tier(hours_per_day=8, interruptible=True, gpu_type="A10G")
    assert tier_a10g == "spot"

    # B200 has 12% interruption rate -> high rework cost erodes spot savings
    # For high-duty workload (e.g. 18h/d) where duty >= break_even, it prefers reserved
    tier_b200 = pricing.recommend_tier(hours_per_day=18, interruptible=True, gpu_type="B200")
    assert tier_b200 == "reserved"


def test_ext1_recommend_tier_job_duration_commitment():
    """Short-term jobs (< 180 days) should NOT commit to 3-year reserved (45% discount).

    1-year reserved requires higher duty cycle (80%) to break even vs 55% for 3-year.
    """
    # 18 hours/day (75% duty cycle):
    # Under standard 3yr reserved (55% break-even): qualifies for reserved
    tier_long = pricing.recommend_tier(hours_per_day=18, interruptible=False, job_days=365)
    assert tier_long == "reserved"

    # Under short job (30 days): evaluated against 1yr break-even (80% duty cycle)
    # 75% duty cycle < 80% break-even -> correctly selects on_demand
    tier_short = pricing.recommend_tier(hours_per_day=18, interruptible=False, job_days=30)
    assert tier_short == "on_demand"

    # 24 hours/day (100% duty cycle):
    # 100% >= 80% -> still qualifies for 1yr reserved even for short job
    tier_short_full = pricing.recommend_tier(hours_per_day=24, interruptible=False, job_days=30)
    assert tier_short_full == "reserved"


def test_ext3_cache_is_worth_it_breakeven():
    """At 90% discount (read_discount=0.10), savings per read is 0.90 * price.

    Break-even reads needed: 1 / (1 - 0.10) = 1.111... reads per prefix.
    """
    # Less than 1.11 reads -> caching is NOT worth it (write cost exceeds savings)
    assert pricing.cache_is_worth_it(avg_cache_reads=1.0, write_cost_per_m=3.75, read_discount=0.10) is False
    assert pricing.cache_is_worth_it(avg_cache_reads=0.5, write_cost_per_m=3.75, read_discount=0.10) is False

    # At or above 1.12 reads -> caching is worth it
    assert pricing.cache_is_worth_it(avg_cache_reads=1.12, write_cost_per_m=3.75, read_discount=0.10) is True
    assert pricing.cache_is_worth_it(avg_cache_reads=5.0, write_cost_per_m=3.75, read_discount=0.10) is True


def test_ext3_cache_is_worth_it_different_discounts():
    """With 50% discount (read_discount=0.50), savings per read is 0.50.

    Break-even reads needed: 1 / 0.50 = 2.0 reads per prefix.
    """
    assert pricing.cache_is_worth_it(avg_cache_reads=1.5, write_cost_per_m=2.0, read_discount=0.50) is False
    assert pricing.cache_is_worth_it(avg_cache_reads=2.0, write_cost_per_m=2.0, read_discount=0.50) is True
    assert pricing.cache_is_worth_it(avg_cache_reads=3.0, write_cost_per_m=2.0, read_discount=0.50) is True


def test_ext3_cache_is_worth_it_edge_cases():
    """Edge cases: zero write cost, free reads."""
    # Free cache writes -> always worth it
    assert pricing.cache_is_worth_it(avg_cache_reads=0.1, write_cost_per_m=0.0) is True
    # Zero reads but non-zero cost -> not worth it
    assert pricing.cache_is_worth_it(avg_cache_reads=0.0, write_cost_per_m=1.0) is False


def run_all_tests():
    tests = [
        test_ext1_recommend_tier_backward_compat,
        test_ext1_recommend_tier_gpu_interruption_rate,
        test_ext1_recommend_tier_job_duration_commitment,
        test_ext3_cache_is_worth_it_breakeven,
        test_ext3_cache_is_worth_it_different_discounts,
        test_ext3_cache_is_worth_it_edge_cases,
    ]
    print("=" * 60)
    print("  EXTENSION UNIT TESTS (Extensions 1 & 3)")
    print("=" * 60)
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  [PASS] {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: {e}")
    print("-" * 60)
    print(f"  {passed}/{len(tests)} tests passed")
    print("=" * 60)
    return passed == len(tests)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
