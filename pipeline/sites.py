"""Site hierarchy extraction and matching.

Phase 2 produces a unified site_hierarchy table by combining:
  1. Direct extraction (barn -> operational site) — high confidence
  2. Cycle trails (which sites each cycle touched)
  3. Producer/packer relationships
  4. Cost center heuristics
"""
import pandas as pd
from sqlalchemy import create_engine
from pipeline.config import DB_PATH


def extract_barn_to_site():
    """Tier 1: Extract the barn -> operational site mapping directly from data.

    Both nursery_intake and pig_flow record (barn, site) pairs explicitly.
    We deduplicate across both sources. Confidence is 1.0 because this is
    not inferred — it's stated.
    """
    engine = create_engine(f"sqlite:///{DB_PATH}")

    # Source 1: nursery_intake gives us nursery barn -> nursery site
    nursery = pd.read_sql(
        "SELECT DISTINCT Nursery_Barn AS barn_id, Nursery_Site AS site "
        "FROM nursery_intake WHERE Nursery_Barn IS NOT NULL",
        engine,
    )
    nursery["source"] = "nursery_intake"

    # Source 2: pig_flow records barn-site pairs on both sides of a movement
    flow_from = pd.read_sql(
        "SELECT DISTINCT From_Barn AS barn_id, From_Site AS site "
        "FROM pig_flow WHERE From_Barn IS NOT NULL AND From_Site != 'External Source'",
        engine,
    )
    flow_from["source"] = "pig_flow.from"

    flow_to = pd.read_sql(
        "SELECT DISTINCT To_Barn AS barn_id, To_Site AS site "
        "FROM pig_flow WHERE To_Barn IS NOT NULL",
        engine,
    )
    flow_to["source"] = "pig_flow.to"

    combined = pd.concat([nursery, flow_from, flow_to], ignore_index=True)

    # Deduplicate, keep all source attributions (helps with the diagnostic)
    grouped = (
        combined.groupby(["barn_id", "site"])["source"]
        .agg(lambda s: ", ".join(sorted(set(s))))
        .reset_index()
    )

    # Classify the site as nursery or finisher
    grouped["site_type"] = grouped["site"].apply(
        lambda s: "nursery" if "Nursery" in s
        else "finisher" if "Finisher" in s
        else "other"
    )
    grouped["confidence"] = 1.0  # direct extraction

    # Sanity check: each barn should map to exactly one site
    duplicates = grouped[grouped.duplicated("barn_id", keep=False)]
    if not duplicates.empty:
        print("⚠️  WARNING: barn appears in multiple sites:")
        print(duplicates.to_string(index=False))

    return grouped[["barn_id", "site", "site_type", "confidence", "source"]]


def write_site_hierarchy_table(df, table_name="site_barn_mapping"):
    """Write a hierarchy DataFrame to SQLite."""
    engine = create_engine(f"sqlite:///{DB_PATH}")
    df.to_sql(table_name, engine, if_exists="replace", index=False)
    print(f"  Wrote {len(df)} rows to table '{table_name}'")


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 2 — Step 1: Barn → Site extraction")
    print("=" * 60)
    barn_site = extract_barn_to_site()
    print(f"\nFound {len(barn_site)} barn-site pairs:\n")
    print(barn_site.to_string(index=False))
    print()
    write_site_hierarchy_table(barn_site)

def build_cycle_trail():
    """Tier 2: Trace each cycle's journey from nursery placement → finisher exit.

    For each Pig_Group_ID, combines:
      - Placement event: from nursery_intake (start of the cycle's life)
      - Transfer event: from pig_flow (nursery → finisher)
      - Head shrink: difference between received and transferred head

    Output: one row per cycle with the full operational trail.
    """
    engine = create_engine(f"sqlite:///{DB_PATH}")

    # Placement: from nursery_intake (one row per cycle)
    placement = pd.read_sql(
        """
        SELECT
            Pig_Group_ID      AS cycle_id,
            Placement_Date    AS placement_date,
            Nursery_Site      AS nursery_site,
            Nursery_Barn      AS nursery_barn,
            Pig_Source        AS pig_source,
            Production_Flow   AS production_flow,
            Received_Head     AS placed_head
        FROM nursery_intake
        """,
        engine,
        parse_dates=["placement_date"],
    )

    # Transfer: from pig_flow, the nursery → finisher movement
    transfer = pd.read_sql(
        """
        SELECT
            Pig_Group_ID    AS cycle_id,
            Movement_Date   AS transfer_date,
            From_Site       AS transfer_from_site,
            From_Barn       AS transfer_from_barn,
            To_Site         AS finisher_site,
            To_Barn         AS finisher_barn,
            Head_Moved      AS transferred_head,
            Avg_Weight_lb   AS transfer_avg_weight_lb
        FROM pig_flow
        WHERE Event = 'Transfer'
          AND From_Site LIKE 'Nursery%'
          AND To_Site LIKE 'Finisher%'
        """,
        engine,
        parse_dates=["transfer_date"],
    )

    # Join on cycle_id (left join so we keep cycles that haven't transferred yet)
    trail = placement.merge(transfer, on="cycle_id", how="left")

    # Compute derived metrics
    trail["nursery_shrink_head"] = trail["placed_head"] - trail["transferred_head"]
    trail["nursery_shrink_pct"] = (
        trail["nursery_shrink_head"] / trail["placed_head"] * 100
    ).round(2)
    trail["nursery_days"] = (
        (trail["transfer_date"] - trail["placement_date"]).dt.days
    )

    # Sort by placement date for readability
    trail = trail.sort_values("placement_date").reset_index(drop=True)
    # Count intra-nursery moves per cycle (barn shuffles within same nursery site)
    intra_moves = pd.read_sql(
        """
        SELECT Pig_Group_ID AS cycle_id, COUNT(*) AS intra_nursery_moves
        FROM pig_flow
        WHERE Event = 'Transfer'
          AND From_Site LIKE 'Nursery%'
          AND To_Site LIKE 'Nursery%'
        GROUP BY Pig_Group_ID
        """,
        engine,
    )
    trail = trail.merge(intra_moves, on="cycle_id", how="left")
    trail["intra_nursery_moves"] = trail["intra_nursery_moves"].fillna(0).astype(int)

    return trail


def run_phase2_step2():
    """Build cycle trails and write to SQLite."""
    print("=" * 60)
    print("Phase 2 — Step 2: Cycle production trail")
    print("=" * 60)
    trail = build_cycle_trail()

    print(f"\nBuilt trails for {len(trail)} cycles\n")

    # Show a compact view
    summary_cols = [
        "cycle_id", "placement_date", "nursery_site", "finisher_site",
        "placed_head", "transferred_head", "nursery_shrink_pct",
        "nursery_days", "intra_nursery_moves"
    ]
    print(trail[summary_cols].to_string(index=False))

    write_site_hierarchy_table(trail, table_name="cycle_trail")

    # Quick aggregate insights
    print("\nNursery → Finisher routing observed:")
    routing = trail.groupby(
        ["nursery_site", "finisher_site"]
    ).size().reset_index(name="cycles")
    print(routing.to_string(index=False))

def analyze_producer_packer_relationships():
    """Tier 3: Describe the producer ↔ packer-site relationship.

    The packer file shows each producer shipping to multiple packer sites.
    We compute, per (producer, packer site), how many loads, total head,
    and what share of that producer's volume goes to each site.
    """
    engine = create_engine(f"sqlite:///{DB_PATH}")

    pp = pd.read_sql(
        """
        SELECT
            Producer        AS producer,
            Site            AS packer_site,
            Packer          AS packer,
            COUNT(*)        AS loads,
            SUM(Paid_Head)  AS total_head,
            SUM(Net_Payment_$) AS total_payment
        FROM packer_settlement
        GROUP BY Producer, Site, Packer
        """,
        engine,
    )

    # Per-producer share: what % of this producer's volume goes to each site?
    pp["producer_share_pct"] = (
        pp.groupby("producer")["total_head"]
        .transform(lambda x: x / x.sum() * 100)
        .round(1)
    )

    # Per-site share: who's the dominant producer at each packer site?
    pp["site_share_pct"] = (
        pp.groupby("packer_site")["total_head"]
        .transform(lambda x: x / x.sum() * 100)
        .round(1)
    )

    # Sort: producer first, then biggest site for that producer
    pp = pp.sort_values(
        ["producer", "total_head"], ascending=[True, False]
    ).reset_index(drop=True)

    return pp


def run_phase2_step3():
    """Producer ↔ packer site analysis."""
    print("=" * 60)
    print("Phase 2 — Step 3: Producer ↔ Packer site relationships")
    print("=" * 60)

    pp = analyze_producer_packer_relationships()
    print(f"\n{len(pp)} producer × packer-site combinations\n")
    print(pp.to_string(index=False))

    write_site_hierarchy_table(pp, table_name="producer_packer_relationships")

    # Two follow-up insights
    print("\nDominant packer site per producer (largest share):")
    dominant = (
        pp.sort_values("producer_share_pct", ascending=False)
        .groupby("producer")
        .head(1)[["producer", "packer_site", "producer_share_pct", "total_head"]]
    )
    print(dominant.to_string(index=False))

    print("\nDominant producer per packer site:")
    dominant_site = (
        pp.sort_values("site_share_pct", ascending=False)
        .groupby("packer_site")
        .head(1)[["packer_site", "producer", "site_share_pct", "total_head"]]
    )
    print(dominant_site.to_string(index=False))

def producer_site_summary():
    """Cleaner view: producer × packer-site, ignoring packer company.

    This is the level we want in the site_hierarchy table — it tells us
    'how strongly is each producer linked to each packer site.'
    """
    engine = create_engine(f"sqlite:///{DB_PATH}")

    summary = pd.read_sql(
        """
        SELECT
            Producer        AS producer,
            Site            AS packer_site,
            COUNT(*)        AS loads,
            SUM(Paid_Head)  AS total_head,
            ROUND(SUM(Net_Payment_$), 2) AS total_payment
        FROM packer_settlement
        GROUP BY Producer, Site
        """,
        engine,
    )

    summary["producer_share_pct"] = (
        summary.groupby("producer")["total_head"]
        .transform(lambda x: x / x.sum() * 100)
        .round(1)
    )
    summary["site_share_pct"] = (
        summary.groupby("packer_site")["total_head"]
        .transform(lambda x: x / x.sum() * 100)
        .round(1)
    )

    summary = summary.sort_values(
        ["producer", "total_head"], ascending=[True, False]
    ).reset_index(drop=True)

    return summary

# if __name__ == "__main__":
#     print("=" * 60)
#     print("Phase 2 — Step 1: Barn → Site extraction")
#     print("=" * 60)
#     barn_site = extract_barn_to_site()
#     print(f"\nFound {len(barn_site)} barn-site pairs:\n")
#     print(barn_site.to_string(index=False))
#     print()
#     write_site_hierarchy_table(barn_site, table_name="site_barn_mapping")

#     print()
#     run_phase2_step2()
def profile_cost_centers():
    """Tier 4: Profile each accounting cost center (Site A/B/C).

    The dummy data doesn't cleanly map cost centers to operational sites.
    Instead of forcing a fake mapping, we characterize each cost center by
    its cost composition, time pattern, and dominant categories.

    This profile becomes input to Phase 3 cycle attribution.
    """
    engine = create_engine(f"sqlite:///{DB_PATH}")

    # Total spend and basic stats per cost center
    totals = pd.read_sql(
        """
        SELECT
            Site                               AS cost_center,
            COUNT(*)                           AS cost_events,
            ROUND(SUM(Total_Cost), 2)          AS total_spend,
            ROUND(AVG(Total_Cost), 2)          AS avg_event,
            MIN(Date)                          AS earliest_date,
            MAX(Date)                          AS latest_date
        FROM accounting
        GROUP BY Site
        ORDER BY Site
        """,
        engine,
    )

    # Cost mix per cost center (which categories are biggest)
    mix = pd.read_sql(
        """
        SELECT
            Site                       AS cost_center,
            Cost_Category              AS category,
            ROUND(SUM(Total_Cost), 2)  AS spend,
            COUNT(*)                   AS events
        FROM accounting
        GROUP BY Site, Cost_Category
        """,
        engine,
    )
    # Compute share within each cost center
    mix["share_pct"] = (
        mix.groupby("cost_center")["spend"]
        .transform(lambda x: x / x.sum() * 100)
        .round(1)
    )
    mix = mix.sort_values(
        ["cost_center", "spend"], ascending=[True, False]
    ).reset_index(drop=True)

    # Production-phase distribution per cost center
    phase = pd.read_sql(
        """
        SELECT
            Site                       AS cost_center,
            Production_Phase           AS phase,
            ROUND(SUM(Total_Cost), 2)  AS spend,
            COUNT(*)                   AS events
        FROM accounting
        GROUP BY Site, Production_Phase
        """,
        engine,
    )
    phase["share_pct"] = (
        phase.groupby("cost_center")["spend"]
        .transform(lambda x: x / x.sum() * 100)
        .round(1)
    )

    return totals, mix, phase


def run_phase2_step4():
    """Profile cost centers."""
    print("=" * 60)
    print("Phase 2 — Step 4: Cost center profiling")
    print("=" * 60)

    totals, mix, phase = profile_cost_centers()

    print("\nCost center totals:")
    print(totals.to_string(index=False))

    print("\nCost mix per center (category share %):")
    pivot_mix = mix.pivot(
        index="cost_center", columns="category", values="share_pct"
    ).fillna(0)
    print(pivot_mix.to_string())

    print("\nProduction-phase distribution per center (% of spend):")
    pivot_phase = phase.pivot(
        index="cost_center", columns="phase", values="share_pct"
    ).fillna(0)
    print(pivot_phase.to_string())

    write_site_hierarchy_table(totals, table_name="cost_center_profile")
    write_site_hierarchy_table(mix, table_name="cost_center_category_mix")
    write_site_hierarchy_table(phase, table_name="cost_center_phase_mix")

    print("\nNote: dummy accounting data spreads costs roughly evenly across")
    print("phases and centers. In real ProAg data, these profiles would show")
    print("clearer specializations (e.g., 'Site A is mostly nursery feed').")

if __name__ == "__main__":
    print("=" * 60)
    print("Phase 2 — Step 1: Barn → Site extraction")
    print("=" * 60)
    barn_site = extract_barn_to_site()
    print(f"\nFound {len(barn_site)} barn-site pairs:\n")
    print(barn_site.to_string(index=False))
    print()
    write_site_hierarchy_table(barn_site, table_name="site_barn_mapping")

    print()
    run_phase2_step2()

    print()
    run_phase2_step3()
    # Cleaner aggregate: collapse across packer companies
    print("\nCleaner view (producer × site, ignoring packer company):")
    summary = producer_site_summary()
    print(summary.to_string(index=False))
    write_site_hierarchy_table(summary, table_name="producer_site_summary")
    print()
    run_phase2_step4()