"""Phase 4 — P&L engine.

Six functions, each short, all calling get_cycle().

1. compute_revenue(cycle)         — sum packer settlements
2. compute_cost_breakdown(cycle)  — attributed costs by category
3. compute_hedge_pnl(cycle)       — hedge gain/loss vs actual futures settle
4. compute_per_cwt_metrics(cycle) — revenue, cost, net per hundredweight
5. compute_pnl(cycle_id)          — master function combining 1-4
6. flag_anomalies(cycle_pnl, peer_pnls) — z-score outlier detection
"""
import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from pipeline.config import DB_PATH
from pipeline.cycles import get_cycle, build_all_cycles


def _engine():
    return create_engine(f"sqlite:///{DB_PATH}")


ASSUMED_CARCASS_WT_LB = 215.0   # fallback if no packer data
COST_CATEGORIES = [
    "Feed", "Labor", "Health", "Facilities",
    "Transportation", "Overhead", "Animal",
]


# ──────────────────────────────────────────────────────────────
# Step 1: Revenue
# ──────────────────────────────────────────────────────────────

def compute_revenue(cycle):
    """Sum net_payment across matched packer settlements.

    Args:
        cycle: dict returned by get_cycle(cycle_id)

    Returns:
        dict with total_revenue, total_paid_head, loads_matched,
        avg_base_price_cwt, avg_carc_wt_lb.
        If no settlements (in-flight), revenue fields are None.
    """
    settlements = cycle.get("packer_settlements", [])

    if not settlements:
        return {
            "total_revenue": None,
            "total_paid_head": 0,
            "loads_matched": 0,
            "avg_base_price_cwt": None,
            "avg_carc_wt_lb": None,
        }

    total_revenue = sum(s["net_payment"] for s in settlements)
    total_paid_head = sum(s["paid_head"] for s in settlements)
    loads = len(settlements)

    # Weighted average base price and carcass weight
    total_wt = sum(s["paid_head"] * s.get("avg_carc_wt_lb", 0) for s in settlements)
    total_price = sum(s["paid_head"] * s.get("base_price_cwt", 0) for s in settlements)

    avg_carc_wt = total_wt / total_paid_head if total_paid_head > 0 else None
    avg_base_price = total_price / total_paid_head if total_paid_head > 0 else None

    return {
        "total_revenue": round(total_revenue, 2),
        "total_paid_head": int(total_paid_head),
        "loads_matched": loads,
        "avg_base_price_cwt": round(avg_base_price, 2) if avg_base_price else None,
        "avg_carc_wt_lb": round(avg_carc_wt, 1) if avg_carc_wt else None,
    }


# ──────────────────────────────────────────────────────────────
# Step 2: Cost breakdown
# ──────────────────────────────────────────────────────────────

def compute_cost_breakdown(cycle):
    """Split attributed costs into standard categories.

    Args:
        cycle: dict returned by get_cycle(cycle_id)

    Returns:
        dict with:
          total_cost_attributed: float
          total_cost_raw: float (before confidence weighting)
          categories: {Feed: X, Labor: Y, ...}
          category_pct: {Feed: 45.2, Labor: 12.1, ...}
    """
    cost_events = cycle.get("cost_events", [])

    if not cost_events:
        return {
            "total_cost_attributed": 0,
            "total_cost_raw": 0,
            "categories": {cat: 0 for cat in COST_CATEGORIES},
            "category_pct": {cat: 0 for cat in COST_CATEGORIES},
        }

    total_attributed = sum(c["attributed_amount"] for c in cost_events)
    total_raw = sum(c["amount"] for c in cost_events)

    # Sum attributed amounts by category
    by_cat = {}
    for c in cost_events:
        cat = c["category"]
        by_cat[cat] = by_cat.get(cat, 0) + c["attributed_amount"]

    # Ensure all standard categories are present
    categories = {cat: round(by_cat.get(cat, 0), 2) for cat in COST_CATEGORIES}

    # Add any unexpected categories that exist in the data
    for cat, val in by_cat.items():
        if cat not in categories:
            categories[cat] = round(val, 2)

    # Percentages
    category_pct = {}
    for cat, val in categories.items():
        category_pct[cat] = round(val / total_attributed * 100, 1) if total_attributed > 0 else 0

    return {
        "total_cost_attributed": round(total_attributed, 2),
        "total_cost_raw": round(total_raw, 2),
        "categories": categories,
        "category_pct": category_pct,
    }

# ──────────────────────────────────────────────────────────────
# Producer attribution
# ──────────────────────────────────────────────────────────────
DEMO_PRODUCERS = ["Demo Producer A", "Demo Producer B", "Demo Producer C"]
_PRODUCER_CACHE = None


def attribute_producer(cycle_id):
    """Return the producer who owns this cycle.

    Resolution strategy (real, data-driven):
    1. CLOSED cycles: pick the producer who received the largest share of
       net_payment across the cycle's matched packer settlements.
    2. IN-FLIGHT cycles: pick the producer most commonly associated with
       this cycle's nursery placement site across closed cycles.
    3. Fallback: deterministic hash if neither signal is available.
    """
    global _PRODUCER_CACHE
    if _PRODUCER_CACHE is None:
        _PRODUCER_CACHE = _build_producer_map()
    return _PRODUCER_CACHE.get(cycle_id, DEMO_PRODUCERS[0])


def _build_producer_map():
    """Compute producer attribution for every cycle in one pass."""
    engine = _engine()
    try:
        cycle_ids = pd.read_sql(
            "SELECT cycle_id FROM cycle_trail ORDER BY placement_date", engine
        )["cycle_id"].tolist()
    except Exception:
        return {}

    mapping = {}
    site_to_producer = {}

    # Pass 1: closed cycles → use the matched packer settlements
    for cid in cycle_ids:
        cycle = get_cycle(cid)
        if cycle is None:
            continue
        settlements = cycle.get("packer_settlements", [])
        if not settlements:
            continue

        # Sum net_payment by producer across this cycle's matched loads
        payments = {}
        for s in settlements:
            producer = s.get("producer") or s.get("Producer")
            if producer:
                payments[producer] = payments.get(producer, 0) + (s.get("net_payment") or 0)

        # If the settlement dict doesn't carry the producer field directly,
        # fall back to a kill-date range lookup on packer_settlement.
        if not payments:
            kill_dates = [s.get("kill_date") for s in settlements if s.get("kill_date")]
            if kill_dates:
                try:
                    df = pd.read_sql(
                        """SELECT Producer, SUM(Net_Payment) AS total
                           FROM packer_settlement
                           WHERE Kill_Date BETWEEN ? AND ?
                           GROUP BY Producer
                           ORDER BY total DESC""",
                        engine,
                        params=(str(min(kill_dates)), str(max(kill_dates))),
                    )
                    if not df.empty:
                        payments[df.iloc[0]["Producer"]] = df.iloc[0]["total"]
                except Exception:
                    pass

        if payments:
            top = max(payments, key=payments.get)
            mapping[cid] = top
            ns = (cycle.get("base") or {}).get("nursery_site")
            if ns:
                site_to_producer.setdefault(ns, {})
                site_to_producer[ns][top] = site_to_producer[ns].get(top, 0) + 1

    # Pass 2: in-flight cycles → use the nursery-site pattern from closed cycles
    for cid in cycle_ids:
        if cid in mapping:
            continue
        cycle = get_cycle(cid)
        if cycle is None:
            continue
        ns = (cycle.get("base") or {}).get("nursery_site")
        if ns and ns in site_to_producer:
            mapping[cid] = max(site_to_producer[ns], key=site_to_producer[ns].get)
        else:
            mapping[cid] = DEMO_PRODUCERS[abs(hash(cid)) % len(DEMO_PRODUCERS)]

    return mapping

# ──────────────────────────────────────────────────────────────
# Step 3: Hedge P&L
# ──────────────────────────────────────────────────────────────

def _lookup_settle_price(expiration_date):
    """Look up the HEM25 close price on or nearest to expiration_date.

    Returns (settle_price, source_string) or (None, reason).
    """
    if pd.isna(expiration_date):
        return None, "no_expiration_date"

    engine = _engine()
    exp = pd.to_datetime(expiration_date)

    try:
        futures = pd.read_sql("SELECT date, close FROM hog_futures_hem25", engine)
        futures["date"] = pd.to_datetime(futures["date"], errors="coerce")
        futures = futures.dropna(subset=["date", "close"])

        if futures.empty:
            return None, "futures_table_empty"

        # Find the row closest to expiration date
        futures["days_off"] = (futures["date"] - exp).dt.days.abs()
        nearest = futures.nsmallest(1, "days_off")
        val = float(nearest.iloc[0]["close"])
        days_diff = int(nearest.iloc[0]["days_off"])

        return val, f"hem25_close (delta {days_diff}d)"

    except Exception as e:
        return None, f"lookup_error: {e}"


def _lookup_settle_fallback(expiration_date):
    """Fallback: average packer Eval_Price_CWT in the expiration month."""
    if pd.isna(expiration_date):
        return None, "no_expiration_date"

    engine = _engine()
    exp = pd.to_datetime(expiration_date)
    month_start = exp.replace(day=1)
    month_end = (month_start + pd.DateOffset(months=1)) - pd.Timedelta(days=1)

    try:
        result = pd.read_sql(
            f"""
            SELECT AVG(Eval_Price_CWT) AS avg_eval
            FROM packer_settlement
            WHERE Kill_Date BETWEEN '{month_start.date()}' AND '{month_end.date()}'
            """,
            engine,
        )
        val = result.iloc[0]["avg_eval"]
        if pd.notna(val):
            return float(val), "packer_eval_fallback"
    except Exception:
        pass

    return None, "no_fallback_available"


def compute_hedge_pnl(cycle):
    """Calculate realized hedge P&L for each position in the cycle.

    For each hedge position:
      - Lean Hog Futures (SELL): gain = (strike - settle) * head * wt / 100
      - Put Option: if settle < strike, payout = (strike - settle) * head * wt / 100
                    then subtract premium: premium * head * wt / 100
                    if settle >= strike, payout = 0, just lose the premium
      - LRP Policy: same as put option mechanics

    Args:
        cycle: dict returned by get_cycle(cycle_id)

    Returns:
        dict with:
          total_hedge_pnl: float
          positions: list of dicts per hedge with details + gain/loss
    """
    hedges = cycle.get("hedge_positions", [])

    if not hedges:
        return {"total_hedge_pnl": 0, "positions": []}

    # Get avg carcass weight from packer settlements, or use default
    settlements = cycle.get("packer_settlements", [])
    if settlements:
        total_wt = sum(s["paid_head"] * s.get("avg_carc_wt_lb", ASSUMED_CARCASS_WT_LB)
                       for s in settlements)
        total_hd = sum(s["paid_head"] for s in settlements)
        avg_wt = total_wt / total_hd if total_hd > 0 else ASSUMED_CARCASS_WT_LB
    else:
        avg_wt = ASSUMED_CARCASS_WT_LB

    positions = []

    for h in hedges:
        strike = h["strike_cwt"]
        head = h["head_covered"]
        instrument = h["instrument"]
        buy_sell = str(h.get("buy_sell", "")).upper()
        premium = h.get("premium_cwt") or 0
        expiration = h.get("expiration_date")

        # Look up settlement price
        settle, source = _lookup_settle_price(expiration)
        if settle is None:
            settle, source = _lookup_settle_fallback(expiration)

        if settle is None:
            positions.append({
                "instrument": instrument,
                "contract_month": h.get("contract_month", ""),
                "head_covered": head,
                "strike_cwt": strike,
                "settle_cwt": None,
                "settle_source": source,
                "premium_cwt": premium,
                "gain_loss": 0,
                "note": "No settlement price found",
            })
            continue

        # Calculate P&L based on instrument type
        multiplier = head * avg_wt / 100  # converts $/cwt to total $

        if "Futures" in instrument:
            # Futures: full gain/loss on the difference
            if buy_sell == "SELL":
                gain = (strike - settle) * multiplier
            else:
                gain = (settle - strike) * multiplier

        elif "Put" in instrument:
            # Put option: pays out only if market is below strike
            if settle < strike:
                intrinsic = (strike - settle) * multiplier
            else:
                intrinsic = 0
            premium_cost = premium * multiplier
            gain = intrinsic - premium_cost

        elif "LRP" in instrument:
            # LRP: similar to put option
            if settle < strike:
                intrinsic = (strike - settle) * multiplier
            else:
                intrinsic = 0
            premium_cost = premium * multiplier
            gain = intrinsic - premium_cost

        else:
            # Unknown instrument, treat conservatively as futures SELL
            gain = (strike - settle) * multiplier

        positions.append({
            "instrument": instrument,
            "contract_month": h.get("contract_month", ""),
            "head_covered": head,
            "strike_cwt": strike,
            "settle_cwt": round(settle, 2),
            "settle_source": source,
            "premium_cwt": premium,
            "gain_loss": round(gain, 2),
            "note": "",
        })

    total_hedge = sum(p["gain_loss"] for p in positions)

    return {
        "total_hedge_pnl": round(total_hedge, 2),
        "positions": positions,
    }


# ──────────────────────────────────────────────────────────────
# Step 4: Per-CWT metrics
# ──────────────────────────────────────────────────────────────

def compute_per_cwt_metrics(cycle, revenue_result, cost_result, hedge_result):
    """Compute revenue, cost, and net on a per-hundredweight basis.

    CWT = hundredweight = 100 lbs. This is how hog pricing works in the industry.
    revenue_per_cwt tells you what you earned per 100 lbs of carcass sold.

    Args:
        cycle: dict from get_cycle()
        revenue_result: dict from compute_revenue()
        cost_result: dict from compute_cost_breakdown()
        hedge_result: dict from compute_hedge_pnl()

    Returns:
        dict with revenue_per_cwt, cost_per_cwt, hedge_per_cwt, net_per_cwt,
        total_carcass_cwt. None values if in-flight.
    """
    avg_carc_wt = revenue_result.get("avg_carc_wt_lb")
    paid_head = revenue_result.get("total_paid_head", 0)

    if avg_carc_wt is None or paid_head == 0:
        return {
            "revenue_per_cwt": None,
            "cost_per_cwt": None,
            "hedge_per_cwt": None,
            "net_per_cwt": None,
            "total_carcass_cwt": None,
        }

    total_carcass_cwt = paid_head * avg_carc_wt / 100  # convert lbs to cwt

    revenue = revenue_result.get("total_revenue", 0) or 0
    cost = cost_result.get("total_cost_attributed", 0) or 0
    hedge = hedge_result.get("total_hedge_pnl", 0) or 0
    net = revenue + hedge - cost

    return {
        "revenue_per_cwt": round(revenue / total_carcass_cwt, 2),
        "cost_per_cwt": round(cost / total_carcass_cwt, 2),
        "hedge_per_cwt": round(hedge / total_carcass_cwt, 2),
        "net_per_cwt": round(net / total_carcass_cwt, 2),
        "total_carcass_cwt": round(total_carcass_cwt, 1),
    }


# ──────────────────────────────────────────────────────────────
# Step 5: Master P&L function
# ──────────────────────────────────────────────────────────────

def compute_pnl(cycle_id):
    """Top-level P&L for one cycle. Calls get_cycle() once, then 1-4.

    Returns:
        dict with cycle_id, status, base info, revenue, costs, hedge,
        per-head metrics, per-cwt metrics, net P&L. Or None if unknown cycle.
    """
    cycle = get_cycle(cycle_id)
    if cycle is None:
        return None

    base = cycle["base"]
    placed_head = base["placed_head"]
    transferred_head = base.get("transferred_head") or placed_head

    # Run each sub-function
    revenue = compute_revenue(cycle)
    costs = compute_cost_breakdown(cycle)
    hedge = compute_hedge_pnl(cycle)
    cwt_metrics = compute_per_cwt_metrics(cycle, revenue, costs, hedge)

    # Determine status
    is_in_flight = revenue["total_revenue"] is None
    status = "in_flight" if is_in_flight else "closed"

    # Net P&L
    if is_in_flight:
        net_pnl = None
        pnl_per_head = None
    else:
        net_pnl = round(
            revenue["total_revenue"]
            + hedge["total_hedge_pnl"]
            - costs["total_cost_attributed"],
            2,
        )
        head_for_calc = revenue["total_paid_head"] or placed_head
        pnl_per_head = round(net_pnl / head_for_calc, 2) if head_for_calc > 0 else 0

    # Mortality
    mortality_head = placed_head - transferred_head
    mortality_pct = round(mortality_head / placed_head * 100, 2) if placed_head > 0 else 0

    # Per-head views
    paid_head = revenue["total_paid_head"] or placed_head
    revenue_per_head = (
        round(revenue["total_revenue"] / paid_head, 2)
        if revenue["total_revenue"] and paid_head > 0 else None
    )
    cost_per_head = (
        round(costs["total_cost_attributed"] / placed_head, 2)
        if placed_head > 0 else 0
    )

    # Days to market
    placement_date = pd.to_datetime(base.get("placement_date"))
    transfer_date = pd.to_datetime(base.get("transfer_date"))
    nursery_days = base.get("nursery_days")

    return {
        "cycle_id": cycle_id,
        "status": status,

        # Head counts
        "placed_head": placed_head,
        "transferred_head": transferred_head,
        "paid_head": revenue["total_paid_head"],
        "mortality_head": mortality_head,
        "mortality_pct": mortality_pct,

        # Revenue
        "packer_revenue": revenue["total_revenue"],
        "loads_matched": revenue["loads_matched"],
        "avg_base_price_cwt": revenue["avg_base_price_cwt"],
        "avg_carc_wt_lb": revenue["avg_carc_wt_lb"],

        # Costs
        "cost_attributed": costs["total_cost_attributed"],
        "cost_raw_in_window": costs["total_cost_raw"],
        "cost_breakdown": costs["categories"],
        "cost_breakdown_pct": costs["category_pct"],

        # Hedge
        "hedge_pnl": hedge["total_hedge_pnl"],
        "hedge_positions": hedge["positions"],

        # Net
        "net_pnl": net_pnl,
        "pnl_per_head": pnl_per_head,
        "revenue_per_head": revenue_per_head,
        "cost_per_head": cost_per_head,

        # Per-CWT
        **cwt_metrics,

        # Timing
        "nursery_days": nursery_days,
        "placement_date": str(placement_date.date()) if pd.notna(placement_date) else None,
    }


# ──────────────────────────────────────────────────────────────
# Step 6: Anomaly detection
# ──────────────────────────────────────────────────────────────

def flag_anomalies(cycle_pnl, peer_pnls, z_threshold=2.0):
    """Flag anomalies for one cycle vs its peers.

    Checks z-score on:
      - feed_cost_per_head (is this cycle's feed cost unusually high/low?)
      - mortality_pct (is mortality unusually high?)
      - days_to_market / nursery_days (is this cycle unusually slow?)
      - pnl_per_head (is this cycle an outlier on profitability?)
      - cost_per_head (are total costs unusual?)

    Args:
        cycle_pnl: dict from compute_pnl() for the cycle being checked
        peer_pnls: list of dicts from compute_pnl() for all closed cycles

    Returns:
        list of anomaly dicts with metric, value, z_score, severity, note
    """
    flags = []

    if cycle_pnl is None or cycle_pnl["status"] == "in_flight":
        if cycle_pnl:
            flags.append({
                "metric": "status",
                "value": 0,
                "z_score": None,
                "severity": "INFO",
                "note": "Cycle in flight, no packer settlements yet",
            })
        return flags

    # Filter peers to closed only, exclude self
    peers = [
        p for p in peer_pnls
        if p and p["status"] == "closed" and p["cycle_id"] != cycle_pnl["cycle_id"]
    ]

    if len(peers) < 3:
        return flags  # not enough peers for meaningful stats

    def _check_metric(metric_name, value, peer_values, high_is_bad=True):
        """Check if value is a z-score outlier vs peers."""
        vals = [v for v in peer_values if v is not None]
        if not vals or value is None:
            return
        mean = np.mean(vals)
        std = np.std(vals)
        if std == 0:
            return
        z = (value - mean) / std

        if abs(z) >= z_threshold:
            severity = "HIGH" if (z > 0 and high_is_bad) or (z < 0 and not high_is_bad) else "MEDIUM"
            flags.append({
                "metric": metric_name,
                "value": round(value, 2),
                "z_score": round(z, 2),
                "severity": severity,
                "note": f"{value:.2f} vs peer avg {mean:.2f} (z={z:.2f})",
            })

    # Negative P&L (hard rule, no z-score needed)
    if cycle_pnl["net_pnl"] is not None and cycle_pnl["net_pnl"] < 0:
        flags.append({
            "metric": "net_pnl",
            "value": cycle_pnl["net_pnl"],
            "z_score": None,
            "severity": "HIGH",
            "note": f"Cycle lost ${abs(cycle_pnl['net_pnl']):,.0f}",
        })

    # Z-score checks
    _check_metric(
        "pnl_per_head",
        cycle_pnl["pnl_per_head"],
        [p["pnl_per_head"] for p in peers],
        high_is_bad=False,  # low P&L is bad
    )

    _check_metric(
        "cost_per_head",
        cycle_pnl["cost_per_head"],
        [p["cost_per_head"] for p in peers],
        high_is_bad=True,
    )

    _check_metric(
        "mortality_pct",
        cycle_pnl["mortality_pct"],
        [p["mortality_pct"] for p in peers],
        high_is_bad=True,
    )

    # Feed cost per head
    feed_cost = cycle_pnl["cost_breakdown"].get("Feed", 0)
    feed_per_head = feed_cost / cycle_pnl["placed_head"] if cycle_pnl["placed_head"] > 0 else 0
    peer_feed = []
    for p in peers:
        f = p["cost_breakdown"].get("Feed", 0)
        h = p["placed_head"]
        if h > 0:
            peer_feed.append(f / h)

    _check_metric(
        "feed_cost_per_head",
        feed_per_head,
        peer_feed,
        high_is_bad=True,
    )

    # Nursery days
    _check_metric(
        "nursery_days",
        cycle_pnl.get("nursery_days"),
        [p.get("nursery_days") for p in peers],
        high_is_bad=True,
    )

    return flags


# ──────────────────────────────────────────────────────────────
# Summary: all 18 cycles
# ──────────────────────────────────────────────────────────────

def build_full_pnl():
    """Compute P&L for all 18 cycles and return summary DataFrame + anomalies."""
    engine = _engine()
    cycle_ids = pd.read_sql(
        "SELECT cycle_id FROM cycle_trail ORDER BY placement_date", engine
    )["cycle_id"].tolist()

    # Compute P&L for every cycle
    all_pnl = []
    for cid in cycle_ids:
        pnl = compute_pnl(cid)
        if pnl:
            all_pnl.append(pnl)

    # Run anomaly detection for each cycle against its peers
    all_anomalies = []
    for pnl in all_pnl:
        flags = flag_anomalies(pnl, all_pnl)
        for f in flags:
            f["cycle_id"] = pnl["cycle_id"]
            f["producer"] = attribute_producer(pnl["cycle_id"])
            all_anomalies.append(f)

    # Build summary DataFrame
    rows = []
    for p in all_pnl:
        rows.append({
            "cycle_id": p["cycle_id"],
            "producer": attribute_producer(p["cycle_id"]), 
            "status": p["status"],
            "placed_head": p["placed_head"],
            "paid_head": p["paid_head"],
            "mortality_pct": p["mortality_pct"],
            "packer_revenue": p["packer_revenue"],
            "cost_attributed": p["cost_attributed"],
            "hedge_pnl": p["hedge_pnl"],
            "net_pnl": p["net_pnl"],
            "pnl_per_head": p["pnl_per_head"],
            "revenue_per_cwt": p.get("revenue_per_cwt"),
            "cost_per_cwt": p.get("cost_per_cwt"),
            "net_per_cwt": p.get("net_per_cwt"),
        })

    summary_df = pd.DataFrame(rows)
    anomaly_df = pd.DataFrame(all_anomalies) if all_anomalies else pd.DataFrame(
        columns=["cycle_id", "metric", "value", "z_score", "severity", "note"]
    )

    return summary_df, anomaly_df, all_pnl


def write_outputs():
    """Run full pipeline and write tables to SQLite."""
    engine = _engine()

    summary_df, anomaly_df, all_pnl = build_full_pnl()

    summary_df.to_sql("fact_cycle_pnl", engine, if_exists="replace", index=False)
    print(f"  Wrote {len(summary_df)} rows to fact_cycle_pnl")

    anomaly_df.to_sql("fact_anomalies", engine, if_exists="replace", index=False)
    print(f"  Wrote {len(anomaly_df)} rows to fact_anomalies")

    # Cost breakdown detail
    cost_rows = []
    for p in all_pnl:
        for cat, val in p["cost_breakdown"].items():
            cost_rows.append({
                "cycle_id": p["cycle_id"],
                "cost_category": cat,
                "attributed_cost": val,
            })
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_sql("fact_cycle_costs", engine, if_exists="replace", index=False)
    print(f"  Wrote {len(cost_df)} rows to fact_cycle_costs")

    # Hedge detail
    hedge_rows = []
    for p in all_pnl:
        for h in p["hedge_positions"]:
            h["cycle_id"] = p["cycle_id"]
            hedge_rows.append(h)
    hedge_df = pd.DataFrame(hedge_rows) if hedge_rows else pd.DataFrame()
    if not hedge_df.empty:
        hedge_df.to_sql("fact_hedge_pnl", engine, if_exists="replace", index=False)
        print(f"  Wrote {len(hedge_df)} rows to fact_hedge_pnl")

    return summary_df, anomaly_df


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("Phase 4 — P&L Engine")
    print("=" * 70)

    summary_df, anomaly_df = write_outputs()

    closed = summary_df[summary_df["status"] == "closed"]
    in_flight = summary_df[summary_df["status"] == "in_flight"]

    print(f"\n{'=' * 70}")
    print("HEADLINE NUMBERS")
    print(f"{'=' * 70}")
    if not closed.empty:
        print(f"  Closed cycles:     {len(closed)}")
        print(f"  In-flight:         {len(in_flight)}")
        print(f"  Total revenue:     ${closed['packer_revenue'].sum():>12,.0f}")
        print(f"  Total costs:       ${closed['cost_attributed'].sum():>12,.0f}")
        print(f"  Total hedge P&L:   ${closed['hedge_pnl'].sum():>12,.0f}")
        print(f"  Total net P&L:     ${closed['net_pnl'].sum():>12,.0f}")
        print(f"  Avg $/head:        ${closed['pnl_per_head'].mean():>12.2f}")

    print(f"\n{'Cycle':<10} {'Status':<10} {'Revenue':>10} {'Costs':>10} "
          f"{'Hedge':>10} {'Net P&L':>10} {'$/Head':>8} {'$/CWT':>8}")
    print("-" * 80)
    for _, r in summary_df.sort_values("cycle_id").iterrows():
        rev = f"${r['packer_revenue']:>9,.0f}" if pd.notna(r['packer_revenue']) else "      N/A"
        net = f"${r['net_pnl']:>9,.0f}" if pd.notna(r['net_pnl']) else "      N/A"
        per_h = f"${r['pnl_per_head']:>7.2f}" if pd.notna(r['pnl_per_head']) else "    N/A"
        per_c = f"${r['net_per_cwt']:>7.2f}" if pd.notna(r['net_per_cwt']) else "    N/A"
        print(f"{r['cycle_id']:<10} {r['status']:<10} {rev} "
              f"${r['cost_attributed']:>9,.0f} ${r['hedge_pnl']:>9,.0f} "
              f"{net} {per_h} {per_c}")

    if not anomaly_df.empty:
        print(f"\n{'=' * 70}")
        print("ANOMALY FLAGS")
        print(f"{'=' * 70}")
        for _, a in anomaly_df.sort_values(["severity", "cycle_id"]).iterrows():
            print(f"  [{a['severity']:<6}] {a['cycle_id']}: {a['note']}")

    print(f"\n{'=' * 70}")
    print("Phase 4 complete. Tables written to proag.db.")
    print(f"{'=' * 70}")
