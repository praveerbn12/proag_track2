"""Smoke tests for Phase 3: cycle assembly works end-to-end."""
from pipeline.cycles import (
    get_cycle, get_cycle_base, get_cycle_hedges,
    get_cycle_packer_settlements, get_cycle_cost_events,
)


def test_base_lookup_works():
    base = get_cycle_base("PG-1014")
    assert base is not None
    assert base["cycle_id"] == "PG-1014"
    assert base["placed_head"] > 0


def test_hedges_return_list():
    hedges = get_cycle_hedges("PG-1014")
    assert isinstance(hedges, list)


def test_packer_match_returns_loads():
    settlements = get_cycle_packer_settlements("PG-1014")
    assert len(settlements) > 0
    total_head = sum(s["paid_head"] for s in settlements)
    base = get_cycle_base("PG-1014")
    # Match should be at least 70% of transferred head
    assert total_head >= 0.7 * base["transferred_head"]


def test_cost_events_have_confidence():
    costs = get_cycle_cost_events("PG-1014")
    assert len(costs) > 0
    for c in costs:
        assert 0 <= c["attribution_confidence"] <= 1


def test_master_get_cycle_returns_full_shape():
    cycle = get_cycle("PG-1014")
    assert "base" in cycle
    assert "hedge_positions" in cycle
    assert "packer_settlements" in cycle
    assert "cost_events" in cycle
    assert "totals" in cycle
    assert cycle["totals"]["total_revenue"] > 0


def test_unknown_cycle_returns_none():
    assert get_cycle("PG-9999") is None