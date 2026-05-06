"""Smoke tests for Phase 4: P&L engine."""
from analytics.pnl import (
    compute_revenue,
    compute_cost_breakdown,
    compute_hedge_pnl,
    compute_per_cwt_metrics,
    compute_pnl,
    flag_anomalies,
    build_full_pnl,
)
from pipeline.cycles import get_cycle


# Use PG-1014 as the reference cycle (same as Phase 3 tests)
REF_CYCLE_ID = "PG-1014"


def _get_ref_cycle():
    return get_cycle(REF_CYCLE_ID)


# ── Step 1: Revenue ──

def test_revenue_returns_total():
    cycle = _get_ref_cycle()
    rev = compute_revenue(cycle)
    assert rev["total_revenue"] is not None
    assert rev["total_revenue"] > 0
    assert rev["total_paid_head"] > 0
    assert rev["loads_matched"] > 0


def test_revenue_in_flight_returns_none():
    """Fake an in-flight cycle by clearing settlements."""
    cycle = _get_ref_cycle()
    cycle["packer_settlements"] = []
    rev = compute_revenue(cycle)
    assert rev["total_revenue"] is None
    assert rev["total_paid_head"] == 0


# ── Step 2: Cost breakdown ──

def test_cost_breakdown_has_categories():
    cycle = _get_ref_cycle()
    costs = compute_cost_breakdown(cycle)
    assert costs["total_cost_attributed"] > 0
    assert isinstance(costs["categories"], dict)
    assert len(costs["categories"]) > 0


def test_cost_breakdown_pct_sums_to_100():
    cycle = _get_ref_cycle()
    costs = compute_cost_breakdown(cycle)
    total_pct = sum(costs["category_pct"].values())
    assert abs(total_pct - 100) < 1, f"Percentages sum to {total_pct}, expected ~100"


# ── Step 3: Hedge P&L ──

def test_hedge_pnl_returns_positions():
    cycle = _get_ref_cycle()
    hedge = compute_hedge_pnl(cycle)
    assert "total_hedge_pnl" in hedge
    assert isinstance(hedge["positions"], list)
    assert len(hedge["positions"]) > 0


def test_hedge_position_has_settle_price():
    cycle = _get_ref_cycle()
    hedge = compute_hedge_pnl(cycle)
    for p in hedge["positions"]:
        # Either has a settle price or a note explaining why not
        assert p["settle_cwt"] is not None or p["note"] != ""


# ── Step 4: Per-CWT metrics ──

def test_per_cwt_metrics_populated():
    cycle = _get_ref_cycle()
    rev = compute_revenue(cycle)
    costs = compute_cost_breakdown(cycle)
    hedge = compute_hedge_pnl(cycle)
    cwt = compute_per_cwt_metrics(cycle, rev, costs, hedge)
    assert cwt["revenue_per_cwt"] is not None
    assert cwt["revenue_per_cwt"] > 0
    assert cwt["total_carcass_cwt"] is not None


# ── Step 5: Master compute_pnl ──

def test_compute_pnl_has_all_fields():
    pnl = compute_pnl(REF_CYCLE_ID)
    assert pnl is not None
    required = [
        "cycle_id", "status", "packer_revenue", "cost_attributed",
        "hedge_pnl", "net_pnl", "pnl_per_head", "cost_per_head",
        "revenue_per_cwt", "cost_per_cwt", "net_per_cwt",
        "cost_breakdown", "hedge_positions", "mortality_pct",
    ]
    for field in required:
        assert field in pnl, f"Missing field: {field}"


def test_compute_pnl_net_is_correct():
    pnl = compute_pnl(REF_CYCLE_ID)
    expected_net = pnl["packer_revenue"] + pnl["hedge_pnl"] - pnl["cost_attributed"]
    assert abs(pnl["net_pnl"] - expected_net) < 0.1, (
        f"Net P&L {pnl['net_pnl']} != revenue {pnl['packer_revenue']} "
        f"+ hedge {pnl['hedge_pnl']} - cost {pnl['cost_attributed']}"
    )


def test_compute_pnl_unknown_cycle():
    assert compute_pnl("PG-9999") is None


# ── Step 6: Anomaly detection ──

def test_anomalies_returns_list():
    pnl = compute_pnl(REF_CYCLE_ID)
    _, _, all_pnl = build_full_pnl()
    flags = flag_anomalies(pnl, all_pnl)
    assert isinstance(flags, list)


def test_anomalies_have_required_fields():
    _, _, all_pnl = build_full_pnl()
    for p in all_pnl:
        flags = flag_anomalies(p, all_pnl)
        for f in flags:
            assert "metric" in f
            assert "severity" in f
            assert "note" in f


# ── Summary ──

def test_build_full_pnl_has_18_rows():
    summary, _, _ = build_full_pnl()
    assert len(summary) == 18, f"Expected 18 cycles, got {len(summary)}"


def test_closed_cycles_have_revenue():
    summary, _, _ = build_full_pnl()
    closed = summary[summary["status"] == "closed"]
    assert (closed["packer_revenue"] > 0).all(), "All closed cycles should have revenue > 0"
