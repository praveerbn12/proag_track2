"""Dashboard views — one page per role, no navigation.

advisor_page  — everything Maria needs on a single scroll
producer_page — everything Sam needs on a single scroll
"""
import pandas as pd
import streamlit as st

from . import db, ui


# ══════════════════════════════════════════════════════════════
# Advisor — single page
# ══════════════════════════════════════════════════════════════

def advisor_page():
    cycles = db.load_cycles()
    summaries = db.load_summaries()
    anomalies = db.load_anomalies()
    rollup = db.producer_rollup()
    trail = db.load_trail()

    if cycles.empty:
        st.error(
            "No cycle data yet. Run:\n\n"
            "```bash\npython -m analytics.pnl\n"
            "python -m analytics.llm_summary\n"
            "python -m analytics.llm_anomaly\n```"
        )
        return

    st.title("Portfolio overview")
    st.caption(
        f"{len(cycles)} cycles · {cycles['producer'].nunique()} producers · "
        f"{(cycles['status'] == 'in_flight').sum()} in-flight"
    )

    # ─── KPI strip ───────────────────────────────────────────
    closed = cycles[cycles["status"] == "closed"]
    open_alerts = _open_alerts(anomalies)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cycles closed", len(closed))
    c2.metric("Total net P&L", ui.money(closed["net_pnl"].sum()))
    c3.metric(
        "Avg P&L / head",
        ui.per_head(closed["pnl_per_head"].mean()) if len(closed) else "—",
    )
    high_count = (open_alerts["severity"] == "HIGH").sum() if not open_alerts.empty else 0
    c4.metric(
        "Open alerts",
        len(open_alerts),
        delta=f"{high_count} HIGH" if high_count else None,
        delta_color="inverse",
    )

    # ─── Alert inbox ─────────────────────────────────────────
    st.subheader("Cycles needing attention")
    if anomalies.empty:
        st.success("No anomalies flagged.")
    else:
        show_all = st.toggle("Show acknowledged / snoozed", value=False, key="show_all_alerts")
        visible = anomalies if show_all else open_alerts
        if visible.empty:
            st.info("All alerts acknowledged or snoozed.")
        else:
            for _, row in visible.iterrows():
                _render_alert_card(row, key_prefix="inbox")

    # ─── Producers rollup ────────────────────────────────────
    st.subheader("Producers")
    if not rollup.empty:
        display = pd.DataFrame({
            "Producer": rollup["producer"],
            "Cycles": rollup["cycles_total"].astype(str) + " (" + rollup["cycles_in_flight"].astype(str) + " in-flight)",
            "Net P&L": rollup["total_net_pnl"],
            "$ / head": rollup["avg_pnl_per_head"],
            "Flags": rollup["flag_count"],
            "Attention": rollup["attention"],
        })
        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Net P&L": st.column_config.NumberColumn(format="$%.0f"),
                "$ / head": st.column_config.NumberColumn(format="$%.2f"),
                "Attention": st.column_config.ProgressColumn(
                    format="%d", min_value=0,
                    max_value=int(max(display["Attention"].max(), 1)),
                ),
            },
        )

    # ─── All cycles table with producer filter ───────────────
    st.subheader("All cycles")
    producer_options = ["All producers"] + db.producers(cycles)
    selected_producer = st.selectbox(
        "Filter by producer", producer_options,
        key="advisor_producer_filter", label_visibility="collapsed",
    )

    filtered = cycles if selected_producer == "All producers" else cycles[cycles["producer"] == selected_producer]
    table_display = filtered[
        ["cycle_id", "producer", "status", "placed_head", "paid_head", "net_pnl", "pnl_per_head"]
    ].rename(columns={
        "cycle_id": "Cycle", "producer": "Producer", "status": "Status",
        "placed_head": "Placed", "paid_head": "Paid",
        "net_pnl": "Net P&L", "pnl_per_head": "$ / head",
    })

    event = st.dataframe(
        table_display, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            "Net P&L": st.column_config.NumberColumn(format="$%.0f"),
            "$ / head": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
    if event.selection.rows:
        st.session_state["advisor_selected_cycle"] = table_display.iloc[event.selection.rows[0]]["Cycle"]

    # ─── Cycle detail (inline) ───────────────────────────────
    cycle_ids = filtered["cycle_id"].tolist()
    if not cycle_ids:
        return

    st.subheader("Cycle detail")
    current = st.session_state.get("advisor_selected_cycle", cycle_ids[0])
    if current not in cycle_ids:
        current = cycle_ids[0]
    selected_cycle = st.selectbox(
        "Cycle", cycle_ids,
        index=cycle_ids.index(current),
        key="advisor_cycle_select",
        label_visibility="collapsed",
    )
    st.session_state["advisor_selected_cycle"] = selected_cycle

    _render_cycle_detail_advisor(selected_cycle, cycles, summaries, anomalies, trail)


def _render_cycle_detail_advisor(cycle_id, cycles, summaries, anomalies, trail):
    row = cycles[cycles["cycle_id"] == cycle_id]
    if row.empty:
        return
    row = row.iloc[0]

    # Timing
    trail_row = trail[trail["cycle_id"] == cycle_id] if not trail.empty else trail
    timing = ""
    if not trail_row.empty:
        tr = trail_row.iloc[0]
        if pd.notna(tr.get("placement_date")):
            timing = f" · placed {pd.to_datetime(tr['placement_date']).strftime('%b %d, %Y')}"
            if pd.notna(tr.get("transfer_date")):
                timing += f" → transferred {pd.to_datetime(tr['transfer_date']).strftime('%b %d, %Y')}"
    st.caption(f"{row['producer']} · {row['status']}{timing}")

    # AI summary
    summary = summaries[summaries["cycle_id"] == cycle_id] if not summaries.empty else summaries
    if not summary.empty:
        with st.container(border=True):
            st.markdown("**AI summary**")
            st.write(summary.iloc[0]["summary"])

    # P&L
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Revenue", ui.money(row.get("packer_revenue")))
    p2.metric("Costs", ui.money(row.get("cost_attributed")))
    p3.metric("Hedge P&L", ui.money(row.get("hedge_pnl")))
    p4.metric("Net P&L", ui.money(row.get("net_pnl")))

    o1, o2, o3, o4 = st.columns(4)
    o1.metric("Placed head", ui.head(row.get("placed_head")))
    o2.metric("Paid head", ui.head(row.get("paid_head")))
    o3.metric("Mortality", ui.pct(row.get("mortality_pct")))
    o4.metric("P&L / head", ui.per_head(row.get("pnl_per_head")))

    if pd.notna(row.get("net_per_cwt")):
        st.caption(
            f"Per CWT — revenue ${row['revenue_per_cwt']:.2f} · "
            f"cost ${row['cost_per_cwt']:.2f} · "
            f"net ${row['net_per_cwt']:.2f}"
        )

    # Peer comparison
    if row["status"] == "closed":
        st.markdown("**Peer comparison**")
        comp = db.peer_comparison(cycles, cycle_id, "pnl_per_head")
        ui.peer_strip(comp, "P&L per head", formatter=ui.per_head)

    # Hedge panel
    hedge = db.load_hedge(cycle_id)
    st.markdown("**Hedging**")
    if hedge.empty:
        st.info("No hedge positions recorded for this cycle.")
    else:
        _render_hedge_summary(hedge, row.get("placed_head"))
        cols = [c for c in
                ["instrument", "contract_month", "head_covered",
                 "strike_cwt", "settle_cwt", "gain_loss"]
                if c in hedge.columns]
        st.dataframe(
            hedge[cols].rename(columns={
                "instrument": "Instrument", "contract_month": "Contract",
                "head_covered": "Head", "strike_cwt": "Strike $/CWT",
                "settle_cwt": "Settle $/CWT", "gain_loss": "P&L",
            }),
            use_container_width=True, hide_index=True,
            column_config={
                "P&L": st.column_config.NumberColumn(format="$%.0f"),
                "Head": st.column_config.NumberColumn(format="%d"),
                "Strike $/CWT": st.column_config.NumberColumn(format="$%.2f"),
                "Settle $/CWT": st.column_config.NumberColumn(format="$%.2f"),
            },
        )

    # Cost breakdown
    costs = db.load_costs(cycle_id)
    if not costs.empty:
        st.markdown("**Cost breakdown**")
        st.bar_chart(
            costs.set_index("cost_category")["attributed_cost"],
            horizontal=True, height=220,
        )

    # Flags on this cycle
    cycle_flags = anomalies[anomalies["cycle_id"] == cycle_id] if not anomalies.empty else anomalies
    if not cycle_flags.empty:
        st.markdown("**Flags on this cycle**")
        for _, flag in cycle_flags.iterrows():
            _render_alert_card(flag, key_prefix="cycle")


# ══════════════════════════════════════════════════════════════
# Producer — single page
# ══════════════════════════════════════════════════════════════

def producer_page(producer: str):
    cycles = db.load_cycles()
    summaries = db.load_summaries()
    anomalies = db.load_anomalies()

    mine = cycles[cycles["producer"] == producer]
    if mine.empty:
        st.warning("No cycles found for this account.")
        return

    closed = mine[mine["status"] == "closed"]
    in_flight = mine[mine["status"] == "in_flight"]

    st.title(producer)
    st.caption(f"{len(closed)} closed · {len(in_flight)} in-flight · advisor: Maria Chen")

    # KPIs
    k1, k2, k3 = st.columns(3)
    k1.metric("Total net P&L", ui.money(closed["net_pnl"].sum()))
    k2.metric(
        "Avg P&L / head",
        ui.per_head(closed["pnl_per_head"].mean()) if len(closed) else "—",
    )
    k3.metric("Total head placed", ui.head(mine["placed_head"].sum()))

    # Your hedging (across all cycles)
    hedge_rows = []
    for cid in mine["cycle_id"]:
        h = db.load_hedge(cid)
        if not h.empty:
            hedge_rows.append(h.assign(cycle_id=cid))

    if hedge_rows:
        hedge_all = pd.concat(hedge_rows)
        with st.container(border=True):
            st.markdown("**Your hedging** · across all cycles")
            _render_hedge_summary(hedge_all, mine["placed_head"].sum())

    # Soft heads-up for HIGH flags
    my_high = anomalies[
        (anomalies.get("producer") == producer)
        & (anomalies["severity"] == "HIGH")
    ] if not anomalies.empty else anomalies
    if not my_high.empty:
        flagged_cycles = my_high["cycle_id"].unique().tolist()
        st.info(
            f"Your advisor has flagged {len(flagged_cycles)} cycle(s) for review: "
            f"{', '.join(flagged_cycles)}. They'll walk through the details on your next call."
        )

    # Cycles table
    st.subheader("Your cycles")
    table_display = mine[
        ["cycle_id", "status", "placed_head", "paid_head", "net_pnl", "pnl_per_head"]
    ].rename(columns={
        "cycle_id": "Cycle", "status": "Status",
        "placed_head": "Placed", "paid_head": "Paid",
        "net_pnl": "Net P&L", "pnl_per_head": "$ / head",
    })
    event = st.dataframe(
        table_display, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            "Net P&L": st.column_config.NumberColumn(format="$%.0f"),
            "$ / head": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
    if event.selection.rows:
        st.session_state["producer_selected_cycle"] = table_display.iloc[event.selection.rows[0]]["Cycle"]

    # Cycle detail (inline)
    cycle_ids = mine["cycle_id"].tolist()
    closed_ids = closed["cycle_id"].tolist()
    default_cid = closed_ids[-1] if closed_ids else cycle_ids[0]

    st.subheader("Cycle detail")
    current = st.session_state.get("producer_selected_cycle", default_cid)
    if current not in cycle_ids:
        current = default_cid
    selected = st.selectbox(
        "Cycle", cycle_ids,
        index=cycle_ids.index(current),
        key="producer_cycle_select",
        label_visibility="collapsed",
    )
    st.session_state["producer_selected_cycle"] = selected

    _render_cycle_detail_producer(selected, mine, summaries, anomalies)


def _render_cycle_detail_producer(cycle_id, mine, summaries, anomalies):
    row = mine[mine["cycle_id"] == cycle_id]
    if row.empty:
        return
    row = row.iloc[0]
    st.caption(row["status"])

    summary = summaries[summaries["cycle_id"] == cycle_id] if not summaries.empty else summaries
    if not summary.empty:
        with st.container(border=True):
            st.markdown("**Summary**")
            st.write(summary.iloc[0]["summary"])

    # Numbers (no per-CWT for producer)
    n1, n2, n3, n4 = st.columns(4)
    n1.metric("Revenue", ui.money(row.get("packer_revenue")))
    n2.metric("Costs", ui.money(row.get("cost_attributed")))
    n3.metric("Hedge P&L", ui.money(row.get("hedge_pnl")))
    n4.metric("Net P&L", ui.money(row.get("net_pnl")))

    o1, o2, o3 = st.columns(3)
    o1.metric("Placed head", ui.head(row.get("placed_head")))
    o2.metric("Mortality", ui.pct(row.get("mortality_pct")))
    o3.metric("P&L / head", ui.per_head(row.get("pnl_per_head")))

    # Hedge on this cycle
    hedge = db.load_hedge(cycle_id)
    if not hedge.empty:
        st.markdown("**Your hedge on this cycle**")
        _render_hedge_summary(hedge, row.get("placed_head"))

    # Soft flag note
    cycle_flags = anomalies[anomalies["cycle_id"] == cycle_id] if not anomalies.empty else anomalies
    high_flags = cycle_flags[cycle_flags["severity"] == "HIGH"] if not cycle_flags.empty else cycle_flags
    if not high_flags.empty:
        st.info(
            "Your advisor has flagged this cycle for review. "
            "They'll walk through the details on your next call."
        )


# ══════════════════════════════════════════════════════════════
# Shared helpers
# ══════════════════════════════════════════════════════════════

def _open_alerts(anomalies: pd.DataFrame) -> pd.DataFrame:
    if anomalies.empty:
        return anomalies
    mask = anomalies.apply(
        lambda r: ui.alert_status(r["cycle_id"], r["metric"]) == "open",
        axis=1,
    )
    return anomalies[mask]


def _render_hedge_summary(hedge: pd.DataFrame, placed_head):
    total_covered = hedge["head_covered"].sum() if "head_covered" in hedge.columns else 0
    coverage = (total_covered / placed_head * 100) if placed_head else None
    wstrike = (
        (hedge["strike_cwt"] * hedge["head_covered"]).sum() / total_covered
        if total_covered else None
    )
    realized = hedge["gain_loss"].sum() if "gain_loss" in hedge.columns else 0

    h1, h2, h3 = st.columns(3)
    h1.metric("Coverage", ui.pct(coverage))
    h2.metric(
        "Wtd. strike $/CWT",
        f"${wstrike:.2f}" if wstrike else "—",
    )
    h3.metric("Realized hedge P&L", ui.money(realized))


def _render_alert_card(row, key_prefix: str = "alert"):
    """Render one alert card. `key_prefix` namespaces the widgets so the same
    alert can appear in multiple places on a page (inbox + cycle detail)
    without colliding."""
    cid = row["cycle_id"]
    metric = row["metric"]
    sev = row["severity"]
    status = ui.alert_status(cid, metric)
    base = f"{key_prefix}_{cid}_{metric}"

    with st.container(border=True):
        st.markdown(
            f"{ui.sev_pill(sev)} &nbsp; **{cid}** · {row.get('producer', '—')} · _{metric}_ "
            + (f"&nbsp; {ui.status_pill(status)}" if status != "open" else ""),
            unsafe_allow_html=True,
        )
        st.write(row.get("explanation", ""))
        st.caption(row.get("note", ""))

        bcols = st.columns([1, 1, 4])
        if status == "open":
            if bcols[0].button("Acknowledge", key=f"ack_{base}"):
                ui.acknowledge_alert(cid, metric)
                st.rerun()
            if bcols[1].button("Snooze", key=f"snz_{base}"):
                ui.snooze_alert(cid, metric)
                st.rerun()
        else:
            bcols[0].caption(f"_{status}_")

        existing_note = ui.get_note(cid, metric)
        with st.expander("Add note" if not existing_note else "Edit note", expanded=False):
            new_note = st.text_area(
                "Note", value=existing_note,
                key=f"note_{base}",
                label_visibility="collapsed", height=80,
                placeholder="e.g. 'Called Sam, will revisit on next weekly'",
            )
            if st.button("Save", key=f"save_{base}"):
                ui.set_note(cid, metric, new_note)
                st.toast("Note saved")