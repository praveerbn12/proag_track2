"""Phase 3 — Canonical cycle model.

Builds one unified record per production cycle by combining:
  - Base trail (from Phase 2 cycle_trail table)
  - Packer settlements (matched by date + volume)
  - Cost events (attributed by date overlap + phase match)
  - Hedging positions (joined directly on Pig_Group_ID)
"""
import pandas as pd
from sqlalchemy import create_engine
from pipeline.config import DB_PATH


def _engine():
    return create_engine(f"sqlite:///{DB_PATH}")


def get_cycle_base(cycle_id):
    """Read the base trail record for one cycle from the cycle_trail table."""
    df = pd.read_sql(
        f"SELECT * FROM cycle_trail WHERE cycle_id = '{cycle_id}'",
        _engine(),
        parse_dates=["placement_date", "transfer_date"],
    )
    if df.empty:
        return None
    return df.iloc[0].to_dict()
def get_cycle_hedges(cycle_id):
    """Hedging positions for one cycle.

    The hedging table has Pig_Group_ID directly — no matching needed.
    Note: prices and premiums are in CWT (cents per hundredweight).
    """
    df = pd.read_sql(
        f"""
        SELECT
            Trade_Date                    AS trade_date,
            Expiration_Date               AS expiration_date,
            Instrument_Type               AS instrument,
            Buy_Sell                      AS buy_sell,
            Contract_Month                AS contract_month,
            Expected_Head_From_Nursery    AS expected_head,
            Head_Covered                  AS head_covered,
            Coverage_Percent              AS coverage_pct,
            Contracts                     AS contracts,
            Strike_or_Futures_Price_CWT   AS strike_cwt,
            Option_or_LRP_Premium_CWT     AS premium_cwt,
            Broker                        AS broker,
            Notes                         AS notes
        FROM hedging
        WHERE Pig_Group_ID = '{cycle_id}'
        ORDER BY Trade_Date
        """,
        _engine(),
        parse_dates=["trade_date", "expiration_date"],
    )
    return df.to_dict(orient="records")

def get_cycle_packer_settlements(cycle_id, kill_window_days=(100, 130)):
    """Match packer settlements to a cycle by date proximity + volume.

    Strategy:
      1. Find the cycle's transfer date (when it entered the finisher).
      2. Pull all packer kills in the expected window (transfer + 100-130 days).
      3. Score each load by date proximity (peak around 110-120 days post-transfer).
      4. Cumulatively pick highest-scoring loads until we approximate the
         cycle's transferred head count.
      5. Stop when we've matched ~80-100% of expected head.

    Returns the matched settlements with confidence scores.
    """
    base = get_cycle_base(cycle_id)
    if base is None or pd.isna(base.get("transfer_date")):
        return []

    transfer_date = pd.to_datetime(base["transfer_date"])
    transferred_head = base["transferred_head"]

    window_start = transfer_date + pd.Timedelta(days=kill_window_days[0])
    window_end = transfer_date + pd.Timedelta(days=kill_window_days[1] + 14)

    # Pull all packer settlements in the expected window
    df = pd.read_sql(
        f"""
        SELECT
            Settlement_ID         AS settlement_id,
            Kill_Date             AS kill_date,
            Packer                AS packer,
            Site                  AS packer_site,
            Producer              AS producer,
            Paid_Head             AS paid_head,
            Avg_Carc_Wt_lb        AS avg_carc_wt_lb,
            Base_Price_CWT        AS base_price_cwt,
            "Net_Payment_$"       AS net_payment
        FROM packer_settlement
        WHERE Kill_Date BETWEEN '{window_start.date()}' AND '{window_end.date()}'
        ORDER BY Kill_Date
        """,
        _engine(),
        parse_dates=["kill_date"],
    )

    if df.empty:
        return []

    # Score by date proximity — peak score at +115 days post-transfer
    ideal_kill_date = transfer_date + pd.Timedelta(days=115)
    df["days_off"] = (df["kill_date"] - ideal_kill_date).dt.days.abs()
    df["date_score"] = (1 - df["days_off"] / 30).clip(lower=0)

    # Sort by score and accumulate head until we hit ~95% of transferred head
    df = df.sort_values("date_score", ascending=False).reset_index(drop=True)
    df["cumulative_head"] = df["paid_head"].cumsum()
    target_head = int(transferred_head * 0.95)

    # Pick rows up to and including the one that crosses the target
    crossover = df[df["cumulative_head"] >= target_head].head(1).index
    keep_until = crossover[0] + 1 if len(crossover) > 0 else len(df)
    matched = df.iloc[:keep_until].copy()

    matched["match_confidence"] = matched["date_score"].round(2)

    # Return as list of dicts, sorted by date
    return matched.sort_values("kill_date").drop(
        columns=["days_off", "date_score", "cumulative_head"]
    ).to_dict(orient="records")

def get_cycle_cost_events(cycle_id, n_cycles_active_factor=True):
    """Attribute accounting cost events to a cycle by date overlap + phase match.

    For each cost row:
      - Is it dated within the cycle's active window? (placement -> last kill)
      - Does its Production_Phase match the cycle's phase on that date?
    Both signals contribute to a confidence score.

    Optionally divides confidence by the number of other cycles that were
    also active on that date — so a cost shared across 5 simultaneous cycles
    only gets ~20% attribution to each.
    """
    base = get_cycle_base(cycle_id)
    if base is None:
        return []

    placement_date = pd.to_datetime(base["placement_date"])
    transfer_date = pd.to_datetime(base["transfer_date"])

    # Approximate finishing end: 115 days after transfer (matches Step 3)
    finish_end = transfer_date + pd.Timedelta(days=130)

    # Pull accounting rows in the cycle's full active window
    df = pd.read_sql(
        f"""
        SELECT
            Date                AS date,
            Site                AS cost_center,
            Cost_Category       AS category,
            Cost_Subcategory    AS subcategory,
            Description         AS description,
            Total_Cost          AS amount,
            Vendor              AS vendor,
            Production_Phase    AS phase
        FROM accounting
        WHERE Date BETWEEN '{placement_date.date()}' AND '{finish_end.date()}'
        """,
        _engine(),
        parse_dates=["date"],
    )

    if df.empty:
        return []

    # Determine which phase the cycle was in for each cost row's date
    def cycle_phase_on(d):
        if d <= transfer_date:
            return "Nursery"
        return "Finishing"

    df["cycle_phase_at_date"] = df["date"].apply(cycle_phase_on)

    # Phase match score: 1.0 if matches, 0.3 if not (low but non-zero — overhead etc.
    # could legitimately span phases)
    df["phase_score"] = (
        df["phase"] == df["cycle_phase_at_date"]
    ).map({True: 1.0, False: 0.3})

    # Optional: divide by number of other cycles active on the same date
    if n_cycles_active_factor:
        all_cycles = pd.read_sql(
            "SELECT cycle_id, placement_date, transfer_date FROM cycle_trail",
            _engine(),
            parse_dates=["placement_date", "transfer_date"],
        )
        all_cycles["finish_end"] = (
            all_cycles["transfer_date"] + pd.Timedelta(days=130)
        )

        def cycles_active_on(d):
            return int(
                (
                    (all_cycles["placement_date"] <= d)
                    & (all_cycles["finish_end"] >= d)
                ).sum()
            )

        df["concurrent_cycles"] = df["date"].apply(cycles_active_on)
        df["concurrency_factor"] = (1 / df["concurrent_cycles"]).clip(upper=1.0)
    else:
        df["concurrency_factor"] = 1.0

    # Final confidence = phase score × concurrency factor
    df["attribution_confidence"] = (
        df["phase_score"] * df["concurrency_factor"]
    ).round(3)
    df["attributed_amount"] = (
        df["amount"] * df["attribution_confidence"]
    ).round(2)

    df = df.sort_values("date").reset_index(drop=True)

    return df.to_dict(orient="records")

def get_cycle(cycle_id):
    """Master function: return everything we know about a cycle as one dict.

    This is the contract for Phase 4 (P&L) and Phase 5 (dashboard).
    """
    base = get_cycle_base(cycle_id)
    if base is None:
        return None

    hedges = get_cycle_hedges(cycle_id)
    settlements = get_cycle_packer_settlements(cycle_id)
    cost_events = get_cycle_cost_events(cycle_id)

    # Quick rollups
    total_revenue = sum(s["net_payment"] for s in settlements)
    total_paid_head = sum(s["paid_head"] for s in settlements)
    total_cost_attributed = sum(c["attributed_amount"] for c in cost_events)
    total_cost_raw = sum(c["amount"] for c in cost_events)
    unattributed_share = (
        1 - (total_cost_attributed / total_cost_raw) if total_cost_raw else 0
    )

    return {
        "cycle_id": cycle_id,
        "base": base,
        "hedge_positions": hedges,
        "packer_settlements": settlements,
        "cost_events": cost_events,
        "totals": {
            "total_revenue": round(total_revenue, 2),
            "total_paid_head": int(total_paid_head),
            "total_cost_attributed": round(total_cost_attributed, 2),
            "total_cost_raw_in_window": round(total_cost_raw, 2),
            "unattributed_cost_share": round(unattributed_share, 3),
        },
    }

# def build_all_cycles():
#     """Return a summary table of get_cycle() output for every cycle."""
#     base = pd.read_sql("SELECT cycle_id FROM cycle_trail ORDER BY placement_date",
#                        _engine())
#     rows = []
#     for cycle_id in base["cycle_id"]:
#         c = get_cycle(cycle_id)
#         if c is None:
#             continue
#         t = c["totals"]
#         rows.append({
#             "cycle_id": cycle_id,
#             "placed_head": c["base"]["placed_head"],
#             "transferred_head": c["base"]["transferred_head"],
#             "loads_matched": len(c["packer_settlements"]),
#             "head_paid": t["total_paid_head"],
#             "revenue": t["total_revenue"],
#             "cost_attributed": t["total_cost_attributed"],
#             "rough_net": round(t["total_revenue"] - t["total_cost_attributed"], 2),
#             "rough_net_per_head":
#                 round((t["total_revenue"] - t["total_cost_attributed"])
#                       / max(t["total_paid_head"], 1), 2),
#         })
#     return pd.DataFrame(rows)

def build_all_cycles():
    """Return a summary table of get_cycle() output for every cycle."""
    base = pd.read_sql("SELECT cycle_id FROM cycle_trail ORDER BY placement_date",
                       _engine())
    rows = []
    for cycle_id in base["cycle_id"]:
        c = get_cycle(cycle_id)
        if c is None:
            continue
        t = c["totals"]
        loads = len(c["packer_settlements"])
        in_flight = loads == 0

        rows.append({
            "cycle_id": cycle_id,
            "status": "in_flight" if in_flight else "closed",
            "placed_head": c["base"]["placed_head"],
            "transferred_head": c["base"]["transferred_head"],
            "loads_matched": loads,
            "head_paid": t["total_paid_head"],
            "revenue": t["total_revenue"],
            "cost_attributed": t["total_cost_attributed"],
            "rough_net": (
                None if in_flight
                else round(t["total_revenue"] - t["total_cost_attributed"], 2)
            ),
            "rough_net_per_head": (
                None if in_flight or t["total_paid_head"] == 0
                else round(
                    (t["total_revenue"] - t["total_cost_attributed"])
                    / t["total_paid_head"], 2
                )
            ),
        })
    return pd.DataFrame(rows)
# if __name__ == "__main__":
#     print("Step 1: Cycle base lookup")
#     print("=" * 60)
#     base = get_cycle_base("PG-1014")
#     for k, v in base.items():
#         print(f"  {k:30s} {v}")
if __name__ == "__main__":
    cycle_id = "PG-1014"

    print("=" * 60)
    print(f"Step 1: Cycle base lookup ({cycle_id})")
    print("=" * 60)
    base = get_cycle_base(cycle_id)
    for k, v in base.items():
        print(f"  {k:30s} {v}")

    print("\n" + "=" * 60)
    print(f"Step 2: Hedging positions ({cycle_id})")
    print("=" * 60)
    hedges = get_cycle_hedges(cycle_id)
    print(f"Found {len(hedges)} hedging position(s)\n")
    for h in hedges:
        print(f"  {h['trade_date'].date()} | {h['instrument']:25s} | "
              f"{h['contract_month']:6s} | {h['head_covered']:>5} head | "
              f"strike ${h['strike_cwt']}/cwt | premium ${h['premium_cwt']}/cwt")
    
    print("\n" + "=" * 60)
    print(f"Step 3: Packer settlements ({cycle_id})")
    print("=" * 60)
    settlements = get_cycle_packer_settlements(cycle_id)
    print(f"Matched {len(settlements)} packer load(s)\n")
    total_head = sum(s["paid_head"] for s in settlements)
    total_payment = sum(s["net_payment"] for s in settlements)
    print(f"  Total head matched: {total_head} (target ~{base['transferred_head']})")
    print(f"  Total payment:      ${total_payment:,.2f}\n")
    for s in settlements[:8]:  # show first 8 only
        print(f"  {s['kill_date'].date()} | {s['packer']:15s} | "
              f"{s['packer_site']:30s} | {s['paid_head']:>4} head | "
              f"${s['net_payment']:>10,.2f} | conf {s['match_confidence']}")
    if len(settlements) > 8:
        print(f"  ... and {len(settlements) - 8} more")
    
    print("\n" + "=" * 60)
    print(f"Step 4: Attributed cost events ({cycle_id})")
    print("=" * 60)
    costs = get_cycle_cost_events(cycle_id)
    print(f"Considered {len(costs)} cost event(s) in the cycle window\n")

    total_amount = sum(c["amount"] for c in costs)
    total_attributed = sum(c["attributed_amount"] for c in costs)
    attribution_rate = total_attributed / total_amount if total_amount else 0

    print(f"  Sum of raw amounts:    ${total_amount:>12,.2f}")
    print(f"  Sum attributed:        ${total_attributed:>12,.2f}")
    print(f"  Attribution rate:      {attribution_rate*100:>12.1f}%\n")

    # Show a few high-confidence rows
    high_conf = sorted(costs, key=lambda c: c["attribution_confidence"], reverse=True)[:6]
    print("Top 6 highest-confidence attributions:")
    for c in high_conf:
        print(f"  {c['date'].date()} | {c['category']:14s} | "
              f"{c['phase']:16s} | ${c['amount']:>9,.2f} → "
              f"${c['attributed_amount']:>9,.2f} | conf {c['attribution_confidence']}")

    print("\n" + "=" * 60)
    print(f"Step 5: Master get_cycle({cycle_id}) summary")
    print("=" * 60)
    cycle = get_cycle(cycle_id)
    t = cycle["totals"]
    print(f"  cycle_id              {cycle['cycle_id']}")
    print(f"  hedge_positions       {len(cycle['hedge_positions'])}")
    print(f"  packer_settlements    {len(cycle['packer_settlements'])}")
    print(f"  cost_events           {len(cycle['cost_events'])}")
    print(f"  total_revenue         ${t['total_revenue']:>12,.2f}")
    print(f"  total_paid_head       {t['total_paid_head']:>12,}")
    print(f"  total_cost_attributed ${t['total_cost_attributed']:>12,.2f}")
    print(f"  unattributed_share    {t['unattributed_cost_share']*100:>11.1f}%")