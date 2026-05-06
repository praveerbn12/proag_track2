"""Phase 5 — Streamlit dashboard (compact single-file build).

Combines the home page and all five drilldown pages into one app, navigated
from the sidebar. Same code, fewer files to upload.

Run from the project root:

    streamlit run dashboard/app.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard import helpers as h


h.setup_page("ProAg Producer Analytics", icon="🌾")



# ══════════════════════════════════════════════════════════════
# 🏠 Portfolio
# ══════════════════════════════════════════════════════════════
def render_portfolio(filters, mtime):
    import sys
    from pathlib import Path

    # Make sibling packages (pipeline, analytics) importable when Streamlit
    # launches this file directly.
    ROOT = Path(__file__).resolve().parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    # Sidebar
    # Data
    data = h.load_all(mtime)
    summary = h.apply_filters(data["summary"], filters, data["producer_map"])

    if summary.empty:
        st.warning("No cycles match the current filters.")
        st.stop()


    # ──────────────────────────────────────────────────────────────
    # Top-line KPIs
    # ──────────────────────────────────────────────────────────────
    closed = summary[summary["status"] == "closed"]
    in_flight = summary[summary["status"] == "in_flight"]

    total_revenue = closed["packer_revenue"].sum()
    total_cost = closed["cost_attributed"].sum()
    total_hedge = closed["hedge_pnl"].sum()
    total_net = closed["net_pnl"].sum()
    avg_per_head = closed["pnl_per_head"].mean() if not closed.empty else None
    total_head = int(closed["paid_head"].sum())

    h.kpi_row([
        {"label": "Cycles in view", "value": f"{len(summary)}",
         "delta": f"{len(closed)} closed · {len(in_flight)} in-flight",
         "delta_kind": "neutral"},
        {"label": "Hogs marketed", "value": f"{total_head:,}",
         "accent": "leaf"},
        {"label": "Packer revenue", "value": h.fmt_money(total_revenue),
         "delta": f"on {len(closed)} closed cycles", "delta_kind": "neutral"},
        {"label": "Hedge P&L", "value": h.fmt_money_signed(total_hedge),
         "delta_kind": "positive" if total_hedge >= 0 else "negative",
         "accent": "positive" if total_hedge >= 0 else "negative"},
        {"label": "Net P&L", "value": h.fmt_money(total_net),
         "delta": f"avg {h.fmt_money(avg_per_head, dp=2)}/head",
         "delta_kind": "positive" if total_net >= 0 else "negative",
         "accent": "positive" if total_net >= 0 else "negative"},
    ])

    st.write("")  # spacing


    # ──────────────────────────────────────────────────────────────
    # Two-column row: P&L per cycle bar + per-head distribution
    # ──────────────────────────────────────────────────────────────
    left, right = st.columns([2, 1])

    with left:
        st.subheader("Net P&L per cycle")
        st.caption("Sorted highest to lowest. In-flight cycles excluded — no settlements yet.")

        bar_df = closed.sort_values("net_pnl", ascending=True).copy()
        if not bar_df.empty:
            bar_df["color"] = bar_df["net_pnl"].apply(
                lambda v: h.POSITIVE if v >= 0 else h.NEGATIVE
            )
            fig = go.Figure(go.Bar(
                x=bar_df["net_pnl"],
                y=bar_df["cycle_id"],
                orientation="h",
                marker_color=bar_df["color"],
                hovertemplate="<b>%{y}</b><br>Net P&L: $%{x:,.0f}<extra></extra>",
            ))
            fig.update_layout(**h.plotly_layout(height=max(320, 28 * len(bar_df))))
            fig.update_xaxes(tickformat="$,.0f", title=None)
            fig.update_yaxes(title=None)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No closed cycles in view.")

    with right:
        st.subheader("$ / head distribution")
        st.caption("Across closed cycles in the current filter.")

        if not closed.empty:
            per_head_vals = closed["pnl_per_head"].dropna()
            fig = go.Figure(go.Histogram(
                x=per_head_vals,
                nbinsx=12,
                marker_color=h.PROAG_LEAF,
                marker_line_color=h.PROAG_FOREST,
                marker_line_width=1,
            ))
            # Mean line
            if len(per_head_vals) > 0:
                mean_v = per_head_vals.mean()
                fig.add_vline(
                    x=mean_v, line_dash="dash", line_color=h.PROAG_FOREST,
                    annotation_text=f"avg ${mean_v:.0f}",
                    annotation_position="top right",
                )
            fig.update_layout(**h.plotly_layout(height=320, showlegend=False))
            fig.update_xaxes(tickformat="$,.0f", title="Net $/head")
            fig.update_yaxes(title="cycles")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data.")


    # ──────────────────────────────────────────────────────────────
    # Revenue → Cost → Net waterfall (portfolio level)
    # ──────────────────────────────────────────────────────────────
    st.subheader("Portfolio P&L composition")
    st.caption("How packer revenue, hedging, and attributed costs roll up to net.")

    if not closed.empty:
        fig = go.Figure(go.Waterfall(
            orientation="v",
            measure=["relative", "relative", "relative", "total"],
            x=["Packer revenue", "Hedge P&L", "Attributed costs", "Net P&L"],
            y=[total_revenue, total_hedge, -total_cost, 0],
            text=[
                h.fmt_money(total_revenue),
                h.fmt_money_signed(total_hedge),
                h.fmt_money(-total_cost),
                h.fmt_money(total_net),
            ],
            textposition="outside",
            connector={"line": {"color": h.PROAG_LINE}},
            increasing={"marker": {"color": h.POSITIVE}},
            decreasing={"marker": {"color": h.NEGATIVE}},
            totals={"marker": {"color": h.PROAG_FOREST}},
        ))
        fig.update_layout(**h.plotly_layout(height=380, showlegend=False))
        fig.update_yaxes(tickformat="$,.0f", title=None)
        st.plotly_chart(fig, use_container_width=True)


    # ──────────────────────────────────────────────────────────────
    # Cycle table — full list with click-through
    # ──────────────────────────────────────────────────────────────
    st.subheader("Cycles")

    # Merge producer info
    table = summary.merge(data["producer_map"], on="cycle_id", how="left")

    # Optional anonymization
    if filters["anon"]:
        table = h.anonymize_df(table, {"producer": "PROD"})

    display = table[[
        "cycle_id", "status", "producer", "placed_head", "paid_head",
        "mortality_pct", "packer_revenue", "cost_attributed", "hedge_pnl",
        "net_pnl", "pnl_per_head", "net_per_cwt",
    ]].rename(columns={
        "cycle_id": "Cycle",
        "status": "Status",
        "producer": "Producer",
        "placed_head": "Placed",
        "paid_head": "Paid",
        "mortality_pct": "Mort %",
        "packer_revenue": "Revenue",
        "cost_attributed": "Cost",
        "hedge_pnl": "Hedge",
        "net_pnl": "Net P&L",
        "pnl_per_head": "$/head",
        "net_per_cwt": "$/cwt",
    })

    # Sort + format
    display = display.sort_values("Cycle")

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Status": st.column_config.TextColumn(width="small"),
            "Placed": st.column_config.NumberColumn(format="%d"),
            "Paid": st.column_config.NumberColumn(format="%d"),
            "Mort %": st.column_config.NumberColumn(format="%.2f%%"),
            "Revenue": st.column_config.NumberColumn(format="$%.0f"),
            "Cost": st.column_config.NumberColumn(format="$%.0f"),
            "Hedge": st.column_config.NumberColumn(format="$%.0f"),
            "Net P&L": st.column_config.NumberColumn(format="$%.0f"),
            "$/head": st.column_config.NumberColumn(format="$%.2f"),
            "$/cwt": st.column_config.NumberColumn(format="$%.2f"),
        },
        height=min(560, 60 + 36 * len(display)),
    )

    c1, c2, c3 = st.columns([1, 1, 4])
    with c1:
        csv = display.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Download CSV", csv,
            file_name="proag_cycles.csv", mime="text/csv",
        )
    with c2:
        if st.button("🔍 Open cycle detail →"):
            st.session_state["page_nav"] = "📊 Cycle Detail"
            st.rerun()


    # ──────────────────────────────────────────────────────────────
    # Footer info
    # ──────────────────────────────────────────────────────────────
    st.divider()
    with st.expander("About this dashboard"):
        st.markdown(
            "**ProAg Producer Analytics** — built for the Spring 2026 AI & Analytics "
            "Innovation Challenge (Track 2).\n\n"
            "This is the advisor view. It centralizes seven producer files and three "
            "market data feeds into a single canonical cycle model, then layers a P&L "
            "engine on top with hedge P&L, attributed costs, per-CWT metrics, and "
            "z-score anomaly detection.\n\n"
            "**Pages**\n"
            "- **📊 Cycle Detail** — drill into one cycle's full P&L, hedges, settlements, and flags.\n"
            "- **⚖️ Compare Cycles** — side-by-side comparison of any 2–5 cycles.\n"
            "- **🏭 Producer View** — aggregate view per producer with packer site allocation.\n"
            "- **📈 Market Data** — HEM25 hog futures, ZCN25 corn, Pork Primal cuts.\n"
            "- **🚩 Anomalies** — every flagged metric across the portfolio.\n\n"
            "Toggle **🔒 Anonymize** in the sidebar to replace producer/site names with "
            "stable aliases — safe for screen sharing or copy-paste to an LLM."
        )



# ══════════════════════════════════════════════════════════════
# 📊 Cycle Detail
# ══════════════════════════════════════════════════════════════
def render_cycle_detail(filters, mtime):
    cycle_id = filters["cycle"]

    # Load
    cycle = h.get_cycle_full(cycle_id)
    pnl = h.get_cycle_pnl(cycle_id)

    if cycle is None or pnl is None:
        st.error(f"Cycle {cycle_id} not found in database.")
        st.stop()

    base = cycle["base"]

    # Cycle metadata strip
    prod_map = h.cycle_producer_table(mtime)
    producer_raw = prod_map[prod_map["cycle_id"] == cycle_id]["producer"]
    producer = producer_raw.iloc[0] if len(producer_raw) > 0 else "—"

    if filters["anon"]:
        producer_disp = h.anon_value(producer, "PROD") if producer else "—"
        nursery_disp = h.anon_value(base.get("nursery_site"), "SITE")
        finisher_disp = h.anon_value(base.get("finisher_site"), "SITE")
    else:
        producer_disp = producer or "—"
        nursery_disp = base.get("nursery_site", "—")
        finisher_disp = base.get("finisher_site", "—")

    status = pnl["status"]
    status_html = h.status_badge(status)

    st.markdown(
        f"""
        <div style="background:{h.PROAG_SURFACE};border:1px solid {h.PROAG_LINE};
                    border-radius:8px;padding:14px 18px;margin-bottom:18px;
                    display:flex;flex-wrap:wrap;gap:24px;align-items:center;">
          <div><strong>Status</strong><br>{status_html}</div>
          <div><strong>Producer</strong><br>{producer_disp}</div>
          <div><strong>Nursery</strong><br>{nursery_disp}</div>
          <div><strong>Finisher</strong><br>{finisher_disp}</div>
          <div><strong>Placement</strong><br>{base.get('placement_date')}</div>
          <div><strong>Transfer</strong><br>{base.get('transfer_date')}</div>
          <div><strong>Nursery days</strong><br>{base.get('nursery_days', '—')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


    # ──────────────────────────────────────────────────────────────
    # KPI strip
    # ──────────────────────────────────────────────────────────────
    def _kind(v):
        if v is None:
            return "neutral"
        return "positive" if v >= 0 else "negative"


    h.kpi_row([
        {"label": "Placed head", "value": h.fmt_int(pnl["placed_head"]),
         "delta": f"{h.fmt_pct(pnl['mortality_pct'])} mortality",
         "delta_kind": "negative" if (pnl["mortality_pct"] or 0) > 5 else "neutral"},
        {"label": "Paid head", "value": h.fmt_int(pnl["paid_head"]),
         "delta": f"{pnl['loads_matched']} loads matched"},
        {"label": "Revenue", "value": h.fmt_money(pnl["packer_revenue"]),
         "delta": f"{h.fmt_money(pnl['revenue_per_head'], dp=2)}/head"
                  if pnl["revenue_per_head"] else None,
         "accent": "leaf"},
        {"label": "Hedge P&L", "value": h.fmt_money_signed(pnl["hedge_pnl"]),
         "delta": f"{len(pnl['hedge_positions'])} positions",
         "delta_kind": _kind(pnl["hedge_pnl"]),
         "accent": "positive" if (pnl["hedge_pnl"] or 0) >= 0 else "negative"},
        {"label": "Net P&L", "value": h.fmt_money(pnl["net_pnl"]),
         "delta": f"{h.fmt_money(pnl['pnl_per_head'], dp=2)}/head"
                  if pnl["pnl_per_head"] else None,
         "delta_kind": _kind(pnl["net_pnl"]),
         "accent": "positive" if (pnl["net_pnl"] or 0) >= 0 else "negative"},
    ])

    st.write("")


    # ──────────────────────────────────────────────────────────────
    # Tabs
    # ──────────────────────────────────────────────────────────────
    tab_overview, tab_pnl, tab_costs, tab_hedges, tab_settle, tab_anom = st.tabs([
        "Overview", "P&L Waterfall", "Costs", "Hedges", "Settlements", "Anomalies",
    ])


    # ── Overview ──────────────────────────────────────────────────
    with tab_overview:
        c1, c2 = st.columns([1, 1])

        with c1:
            st.markdown("##### Head flow")
            funnel_df = pd.DataFrame({
                "stage": ["Placed (nursery intake)",
                          "Transferred to finisher",
                          "Paid by packer"],
                "head": [
                    pnl["placed_head"],
                    pnl["transferred_head"],
                    pnl["paid_head"] or 0,
                ],
            })
            fig = go.Figure(go.Funnel(
                y=funnel_df["stage"],
                x=funnel_df["head"],
                textinfo="value+percent initial",
                marker={"color": [h.PROAG_FOREST, h.PROAG_LEAF, h.PROAG_HARVEST]},
            ))
            fig.update_layout(**h.plotly_layout(height=320, showlegend=False))
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            st.markdown("##### Per-CWT economics")
            cwt_rows = [
                ("Total carcass weight", pnl.get("total_carcass_cwt"), "cwt"),
                ("Avg carcass weight", pnl.get("avg_carc_wt_lb"), "lb"),
                ("Avg base price", pnl.get("avg_base_price_cwt"), "$/cwt"),
                ("Revenue", pnl.get("revenue_per_cwt"), "$/cwt"),
                ("Cost", pnl.get("cost_per_cwt"), "$/cwt"),
                ("Hedge", pnl.get("hedge_per_cwt"), "$/cwt"),
                ("Net", pnl.get("net_per_cwt"), "$/cwt"),
            ]
            cwt_df = pd.DataFrame(cwt_rows, columns=["Metric", "Value", "Unit"])
            cwt_df["Value"] = cwt_df["Value"].apply(
                lambda v: f"{v:,.2f}" if v is not None else "—"
            )
            st.dataframe(cwt_df, hide_index=True, use_container_width=True)


    # ── P&L Waterfall ─────────────────────────────────────────────
    with tab_pnl:
        if pnl["status"] == "in_flight":
            st.info("Cycle is in-flight (no packer settlements yet). Hedge P&L only.")
        measures = ["relative", "relative", "relative", "total"]
        fig = go.Figure(go.Waterfall(
            orientation="v",
            measure=measures,
            x=["Packer revenue", "Hedge P&L", "Attributed cost", "Net P&L"],
            y=[
                pnl["packer_revenue"] or 0,
                pnl["hedge_pnl"] or 0,
                -(pnl["cost_attributed"] or 0),
                0,
            ],
            text=[
                h.fmt_money(pnl["packer_revenue"]),
                h.fmt_money_signed(pnl["hedge_pnl"]),
                h.fmt_money(-(pnl["cost_attributed"] or 0)),
                h.fmt_money(pnl["net_pnl"]),
            ],
            textposition="outside",
            connector={"line": {"color": h.PROAG_LINE}},
            increasing={"marker": {"color": h.POSITIVE}},
            decreasing={"marker": {"color": h.NEGATIVE}},
            totals={"marker": {"color": h.PROAG_FOREST}},
        ))
        fig.update_layout(**h.plotly_layout(
            title=f"{cycle_id} — Revenue → Cost → Net", height=420, showlegend=False
        ))
        fig.update_yaxes(tickformat="$,.0f")
        st.plotly_chart(fig, use_container_width=True)


    # ── Costs ─────────────────────────────────────────────────────
    with tab_costs:
        breakdown = pnl["cost_breakdown"]
        cat_df = pd.DataFrame({
            "Category": list(breakdown.keys()),
            "Attributed cost": list(breakdown.values()),
        })
        cat_df = cat_df[cat_df["Attributed cost"] > 0].sort_values(
            "Attributed cost", ascending=False
        )

        c1, c2 = st.columns([1, 1])

        with c1:
            st.markdown("##### Cost breakdown")
            if not cat_df.empty:
                colors = [h.CATEGORY_COLORS.get(c, h.PROAG_FOREST)
                          for c in cat_df["Category"]]
                fig = go.Figure(go.Pie(
                    labels=cat_df["Category"],
                    values=cat_df["Attributed cost"],
                    hole=0.55,
                    marker=dict(colors=colors,
                                line=dict(color=h.PROAG_SURFACE, width=2)),
                    textinfo="label+percent",
                    hovertemplate="<b>%{label}</b><br>$%{value:,.0f}<extra></extra>",
                ))
                fig.update_layout(**h.plotly_layout(height=380, showlegend=False))
                # Center label
                fig.add_annotation(
                    text=f"<b>{h.fmt_money(pnl['cost_attributed'])}</b><br>"
                         f"<span style='font-size:11px;color:{h.PROAG_INK_MUTED}'>"
                         f"attributed</span>",
                    x=0.5, y=0.5, showarrow=False, align="center",
                    font=dict(family="Source Serif Pro", size=18, color=h.PROAG_INK),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No attributed costs.")

        with c2:
            st.markdown("##### Per-head & confidence")
            st.metric("Cost per head (placed)", h.fmt_money(pnl["cost_per_head"], dp=2))
            st.metric("Total raw cost in window", h.fmt_money(pnl["cost_raw_in_window"]))
            unattr = 1 - (pnl["cost_attributed"] / pnl["cost_raw_in_window"]) \
                if pnl["cost_raw_in_window"] else 0
            st.metric("Unattributed share",
                      h.fmt_pct(unattr * 100),
                      help="Costs in this cycle's window that didn't fully match "
                           "by phase or had to be split across concurrent cycles.")

        # Detailed cost events
        st.markdown("##### Cost events ledger")
        events = pd.DataFrame(cycle.get("cost_events", []))
        if not events.empty:
            events_show = events[[
                "date", "category", "subcategory", "phase", "vendor",
                "amount", "attributed_amount", "attribution_confidence",
            ]].rename(columns={
                "date": "Date", "category": "Category", "subcategory": "Subcategory",
                "phase": "Phase", "vendor": "Vendor", "amount": "Raw $",
                "attributed_amount": "Attributed $", "attribution_confidence": "Conf",
            })
            # Filter controls
            cc1, cc2, cc3 = st.columns([2, 2, 1])
            with cc1:
                cat_filter = st.multiselect(
                    "Category", options=sorted(events_show["Category"].unique()),
                    key="costs_cat",
                )
            with cc2:
                phase_filter = st.multiselect(
                    "Phase", options=sorted(events_show["Phase"].dropna().unique()),
                    key="costs_phase",
                )
            with cc3:
                min_conf = st.slider("Min conf", 0.0, 1.0, 0.0, 0.05, key="costs_conf")

            filt = events_show.copy()
            if cat_filter:
                filt = filt[filt["Category"].isin(cat_filter)]
            if phase_filter:
                filt = filt[filt["Phase"].isin(phase_filter)]
            filt = filt[filt["Conf"] >= min_conf]

            st.dataframe(
                filt.sort_values("Date"),
                use_container_width=True, hide_index=True,
                column_config={
                    "Raw $": st.column_config.NumberColumn(format="$%.2f"),
                    "Attributed $": st.column_config.NumberColumn(format="$%.2f"),
                    "Conf": st.column_config.ProgressColumn(
                        min_value=0, max_value=1, format="%.2f"
                    ),
                },
                height=320,
            )
        else:
            st.info("No cost events found in cycle window.")


    # ── Hedges ────────────────────────────────────────────────────
    with tab_hedges:
        hedges = pnl.get("hedge_positions", [])
        if not hedges:
            st.info("No hedge positions for this cycle.")
        else:
            # Summary
            total_pnl = pnl["hedge_pnl"]
            kind = "positive" if total_pnl >= 0 else "negative"
            st.markdown(
                f"##### Total hedge P&L: "
                f"<span style='color:{h.POSITIVE if total_pnl >= 0 else h.NEGATIVE}'>"
                f"{h.fmt_money_signed(total_pnl)}</span>"
                f" across {len(hedges)} positions",
                unsafe_allow_html=True,
            )

            h_df = pd.DataFrame(hedges)

            # Strike vs settle scatter
            fig = go.Figure()
            for _, row in h_df.iterrows():
                color = h.POSITIVE if row["gain_loss"] >= 0 else h.NEGATIVE
                fig.add_trace(go.Scatter(
                    x=[row["strike_cwt"]],
                    y=[row["settle_cwt"]],
                    mode="markers",
                    marker=dict(
                        size=max(8, min(40, (row["head_covered"] or 0) / 50)),
                        color=color,
                        line=dict(color=h.PROAG_FOREST_DARK, width=1),
                        opacity=0.75,
                    ),
                    hovertemplate=(
                        f"<b>{row['instrument']}</b><br>"
                        f"Contract: {row['contract_month']}<br>"
                        f"Head: {int(row['head_covered']) if pd.notna(row['head_covered']) else '—'}<br>"
                        f"Strike: $%{{x:.2f}}/cwt<br>"
                        f"Settle: $%{{y:.2f}}/cwt<br>"
                        f"P&L: ${row['gain_loss']:,.0f}<extra></extra>"
                    ),
                    name=row["contract_month"],
                    showlegend=False,
                ))
            # Diagonal break-even line (strike == settle)
            if not h_df.empty:
                mn = float(min(h_df["strike_cwt"].min(), h_df["settle_cwt"].min())) - 5
                mx = float(max(h_df["strike_cwt"].max(), h_df["settle_cwt"].max())) + 5
                fig.add_trace(go.Scatter(
                    x=[mn, mx], y=[mn, mx], mode="lines",
                    line=dict(color=h.PROAG_INK_MUTED, dash="dash"),
                    hoverinfo="skip", showlegend=False,
                ))
            fig.update_layout(**h.plotly_layout(
                title="Strike vs settle — bubble size = head covered",
                height=380, showlegend=False,
            ))
            fig.update_xaxes(title="Strike ($/cwt)")
            fig.update_yaxes(title="Actual settle ($/cwt)")
            st.plotly_chart(fig, use_container_width=True)

            # Detail table
            h_show = h_df[[
                "instrument", "contract_month", "head_covered",
                "strike_cwt", "settle_cwt", "premium_cwt",
                "gain_loss", "settle_source",
            ]].rename(columns={
                "instrument": "Instrument", "contract_month": "Contract",
                "head_covered": "Head", "strike_cwt": "Strike $/cwt",
                "settle_cwt": "Settle $/cwt", "premium_cwt": "Premium $/cwt",
                "gain_loss": "P&L $", "settle_source": "Source",
            })
            st.dataframe(
                h_show, use_container_width=True, hide_index=True,
                column_config={
                    "Head": st.column_config.NumberColumn(format="%d"),
                    "Strike $/cwt": st.column_config.NumberColumn(format="$%.2f"),
                    "Settle $/cwt": st.column_config.NumberColumn(format="$%.2f"),
                    "Premium $/cwt": st.column_config.NumberColumn(format="$%.2f"),
                    "P&L $": st.column_config.NumberColumn(format="$%.0f"),
                },
            )


    # ── Settlements ───────────────────────────────────────────────
    with tab_settle:
        settlements = cycle.get("packer_settlements", [])
        if not settlements:
            st.info("Cycle is in-flight — no packer settlements matched yet.")
        else:
            s_df = pd.DataFrame(settlements)

            # Anonymize if needed
            if filters["anon"]:
                s_df["packer"] = s_df["packer"].apply(lambda v: h.anon_value(v, "PKR"))
                s_df["packer_site"] = s_df["packer_site"].apply(
                    lambda v: h.anon_value(v, "SITE"))
                s_df["producer"] = s_df["producer"].apply(
                    lambda v: h.anon_value(v, "PROD"))

            # Timeline scatter
            fig = px.scatter(
                s_df, x="kill_date", y="net_payment",
                size="paid_head", color="packer_site",
                color_discrete_sequence=h.PLOTLY_PALETTE,
                hover_data=["packer", "paid_head", "avg_carc_wt_lb",
                            "base_price_cwt", "match_confidence"],
                title="Settlement loads over time",
            )
            fig.update_layout(**h.plotly_layout(height=380))
            fig.update_xaxes(title="Kill date")
            fig.update_yaxes(tickformat="$,.0f", title="Net payment ($)")
            st.plotly_chart(fig, use_container_width=True)

            # Table
            s_show = s_df[[
                "kill_date", "packer", "packer_site", "producer", "paid_head",
                "avg_carc_wt_lb", "base_price_cwt", "net_payment", "match_confidence",
            ]].rename(columns={
                "kill_date": "Kill date", "packer": "Packer",
                "packer_site": "Site", "producer": "Producer",
                "paid_head": "Head", "avg_carc_wt_lb": "Avg wt (lb)",
                "base_price_cwt": "Base $/cwt", "net_payment": "Net payment",
                "match_confidence": "Match conf",
            })
            st.dataframe(
                s_show, use_container_width=True, hide_index=True,
                column_config={
                    "Net payment": st.column_config.NumberColumn(format="$%.2f"),
                    "Base $/cwt": st.column_config.NumberColumn(format="$%.2f"),
                    "Avg wt (lb)": st.column_config.NumberColumn(format="%.1f"),
                    "Match conf": st.column_config.ProgressColumn(
                        min_value=0, max_value=1, format="%.2f"),
                },
            )


    # ── Anomalies ─────────────────────────────────────────────────
    with tab_anom:
        anomalies = h.load_anomalies(mtime)
        cycle_anomalies = anomalies[anomalies["cycle_id"] == cycle_id]
        if cycle_anomalies.empty:
            st.success("✓ No anomaly flags for this cycle.")
        else:
            st.markdown(
                f"##### {len(cycle_anomalies)} flag(s) for {cycle_id}"
            )
            for _, a in cycle_anomalies.iterrows():
                sev = a["severity"]
                badge = h.status_badge(sev)
                z_html = f" · z = <code>{a['z_score']:.2f}</code>" \
                    if pd.notna(a.get("z_score")) else ""
                st.markdown(
                    f"""
                    <div style="background:{h.PROAG_SURFACE};border:1px solid {h.PROAG_LINE};
                                border-left:4px solid {h.WARNING if sev != 'HIGH' else h.NEGATIVE};
                                padding:10px 14px;border-radius:6px;margin-bottom:8px;">
                      {badge} &nbsp; <strong>{a['metric']}</strong>{z_html}<br>
                      <span style="color:{h.PROAG_INK_MUTED};">{a['note']}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )



# ══════════════════════════════════════════════════════════════
# ⚖️ Compare Cycles
# ══════════════════════════════════════════════════════════════
def render_compare_cycles(filters, mtime):
    summary = h.load_pnl_summary(mtime)
    prod_map = h.cycle_producer_table(mtime)


    # ──────────────────────────────────────────────────────────────
    # Selector
    # ──────────────────────────────────────────────────────────────
    ids_all = summary["cycle_id"].tolist()
    ids_closed = summary[summary["status"] == "closed"]["cycle_id"].tolist()

    c1, c2 = st.columns([3, 1])
    with c2:
        pool = st.radio(
            "Pool",
            options=["Closed only", "All cycles"],
            index=0,
            horizontal=False,
            key="cmp_pool",
        )
    options = ids_closed if pool == "Closed only" else ids_all

    with c1:
        selected = st.multiselect(
            "Select cycles to compare (2–5)",
            options=options,
            default=options[:3] if len(options) >= 3 else options,
            max_selections=5,
            key="cmp_selected",
        )

    if len(selected) < 2:
        st.warning("Pick at least 2 cycles to compare.")
        st.stop()

    # Compute P&L for each selected
    pnls = {cid: h.get_cycle_pnl(cid) for cid in selected}
    pnls = {k: v for k, v in pnls.items() if v is not None}


    # ──────────────────────────────────────────────────────────────
    # Side-by-side metric grid
    # ──────────────────────────────────────────────────────────────
    st.subheader("Headline metrics")

    rows = []
    for cid, p in pnls.items():
        rows.append({
            "Cycle": cid,
            "Status": p["status"].replace("_", " ").title(),
            "Placed head": p["placed_head"],
            "Paid head": p["paid_head"],
            "Mortality %": p["mortality_pct"],
            "Revenue": p["packer_revenue"],
            "Cost": p["cost_attributed"],
            "Hedge P&L": p["hedge_pnl"],
            "Net P&L": p["net_pnl"],
            "$/head": p["pnl_per_head"],
            "$/cwt": p["net_per_cwt"],
            "Revenue $/cwt": p.get("revenue_per_cwt"),
            "Cost $/cwt": p.get("cost_per_cwt"),
            "Avg base $/cwt": p["avg_base_price_cwt"],
            "Nursery days": p.get("nursery_days"),
        })
    table = pd.DataFrame(rows).set_index("Cycle").T

    st.dataframe(
        table,
        use_container_width=True,
        height=min(560, 60 + 36 * len(table)),
    )


    # ──────────────────────────────────────────────────────────────
    # Grouped revenue / cost / hedge / net bar
    # ──────────────────────────────────────────────────────────────
    st.subheader("Revenue · Cost · Hedge · Net")
    st.caption("Negative cost shown in red. Bars grouped per cycle.")

    bar_rows = []
    for cid, p in pnls.items():
        bar_rows.extend([
            {"Cycle": cid, "Component": "Revenue", "Value": p["packer_revenue"] or 0},
            {"Cycle": cid, "Component": "Hedge",   "Value": p["hedge_pnl"] or 0},
            {"Cycle": cid, "Component": "Cost",    "Value": -(p["cost_attributed"] or 0)},
            {"Cycle": cid, "Component": "Net",     "Value": p["net_pnl"] or 0},
        ])
    bar_df = pd.DataFrame(bar_rows)

    color_map = {
        "Revenue": h.PROAG_LEAF,
        "Hedge":   h.INFO,
        "Cost":    h.NEGATIVE,
        "Net":     h.PROAG_FOREST,
    }
    fig = px.bar(
        bar_df, x="Cycle", y="Value", color="Component", barmode="group",
        color_discrete_map=color_map,
        text_auto=".2s",
    )
    fig.update_layout(**h.plotly_layout(height=420))
    fig.update_yaxes(tickformat="$,.0f", title=None)
    fig.update_xaxes(title=None)
    st.plotly_chart(fig, use_container_width=True)


    # ──────────────────────────────────────────────────────────────
    # Cost-category comparison
    # ──────────────────────────────────────────────────────────────
    st.subheader("Cost composition")

    cost_rows = []
    for cid, p in pnls.items():
        for cat, val in p["cost_breakdown"].items():
            cost_rows.append({"Cycle": cid, "Category": cat, "Cost": val})
    cost_df = pd.DataFrame(cost_rows)

    fig = px.bar(
        cost_df, x="Cycle", y="Cost", color="Category",
        color_discrete_map=h.CATEGORY_COLORS,
        barmode="stack",
    )
    fig.update_layout(**h.plotly_layout(height=420))
    fig.update_yaxes(tickformat="$,.0f", title="Attributed cost")
    fig.update_xaxes(title=None)
    st.plotly_chart(fig, use_container_width=True)


    # ──────────────────────────────────────────────────────────────
    # Per-CWT radar
    # ──────────────────────────────────────────────────────────────
    st.subheader("Per-CWT economics — radar")
    st.caption("Standardized so each axis spans the min–max range across the selection.")

    cwt_metrics = ["revenue_per_cwt", "cost_per_cwt", "net_per_cwt", "avg_base_price_cwt"]
    cwt_labels = ["Revenue/cwt", "Cost/cwt", "Net/cwt", "Base price/cwt"]

    # Min/max per axis for normalization
    metric_vals = {m: [pnls[c].get(m) for c in pnls if pnls[c].get(m) is not None]
                   for m in cwt_metrics}

    fig = go.Figure()
    for i, (cid, p) in enumerate(pnls.items()):
        color = h.PLOTLY_PALETTE[i % len(h.PLOTLY_PALETTE)]
        raw = [p.get(m) or 0 for m in cwt_metrics]
        # Normalize 0–1 across selection
        norm = []
        for m, v in zip(cwt_metrics, raw):
            vals = metric_vals.get(m, [v])
            lo, hi = min(vals), max(vals)
            if hi == lo:
                norm.append(0.5)
            else:
                norm.append((v - lo) / (hi - lo))
        fig.add_trace(go.Scatterpolar(
            r=norm + [norm[0]],
            theta=cwt_labels + [cwt_labels[0]],
            fill="toself",
            name=cid,
            line=dict(color=color, width=2),
            opacity=0.6,
            hovertemplate=(
                f"<b>{cid}</b><br>" +
                "<br>".join(f"{l}: ${v:.2f}/cwt" for l, v in zip(cwt_labels, raw)) +
                "<extra></extra>"
            ),
        ))
    fig.update_layout(
        polar=dict(
            bgcolor=h.PROAG_SURFACE,
            radialaxis=dict(visible=True, range=[0, 1], showticklabels=False,
                            gridcolor=h.PROAG_LINE),
            angularaxis=dict(gridcolor=h.PROAG_LINE),
        ),
        height=460,
        paper_bgcolor=h.PROAG_SURFACE,
        font=dict(family="Inter, sans-serif"),
        legend=dict(orientation="h", y=-0.1),
    )
    st.plotly_chart(fig, use_container_width=True)



# ══════════════════════════════════════════════════════════════
# 🏭 Producer View
# ══════════════════════════════════════════════════════════════
def render_producer_view(filters, mtime):
    summary = h.load_pnl_summary(mtime)
    prod_map = h.cycle_producer_table(mtime)
    site_summary = h.load_producer_site_summary(mtime)

    producers = sorted([p for p in prod_map["producer"].dropna().unique()])

    if not producers:
        st.error("No producers found in packer settlement data.")
        st.stop()

    # Selector
    display_producers = (
        [h.anon_value(p, "PROD") for p in producers]
        if filters["anon"] else producers
    )
    prod_lookup = dict(zip(display_producers, producers))

    selected_disp = st.selectbox(
        "Producer",
        options=display_producers,
        index=0,
        key="prod_pick",
    )
    producer = prod_lookup[selected_disp]

    # Cycles for this producer
    prod_cycles = prod_map[prod_map["producer"] == producer]["cycle_id"].tolist()
    prod_summary = summary[summary["cycle_id"].isin(prod_cycles)]

    if prod_summary.empty:
        st.warning(f"No cycles found for {selected_disp}.")
        st.stop()


    # ──────────────────────────────────────────────────────────────
    # Top KPIs for this producer
    # ──────────────────────────────────────────────────────────────
    closed = prod_summary[prod_summary["status"] == "closed"]
    total_head = int(closed["paid_head"].sum())
    total_revenue = closed["packer_revenue"].sum()
    total_net = closed["net_pnl"].sum()
    total_hedge = closed["hedge_pnl"].sum()
    avg_per_head = closed["pnl_per_head"].mean() if not closed.empty else None

    h.kpi_row([
        {"label": "Cycles", "value": f"{len(prod_summary)}",
         "delta": f"{len(closed)} closed · {len(prod_summary) - len(closed)} in-flight"},
        {"label": "Hogs marketed", "value": f"{total_head:,}",
         "accent": "leaf"},
        {"label": "Revenue", "value": h.fmt_money(total_revenue)},
        {"label": "Net P&L", "value": h.fmt_money(total_net),
         "accent": "positive" if total_net >= 0 else "negative",
         "delta": f"{h.fmt_money(avg_per_head, dp=2)}/head avg",
         "delta_kind": "positive" if (avg_per_head or 0) >= 0 else "negative"},
        {"label": "Hedge P&L", "value": h.fmt_money_signed(total_hedge),
         "accent": "positive" if total_hedge >= 0 else "negative"},
    ])

    st.write("")


    # ──────────────────────────────────────────────────────────────
    # Two-up: site allocation + per-cycle trajectory
    # ──────────────────────────────────────────────────────────────
    left, right = st.columns([1, 1])

    with left:
        st.subheader("Packer site allocation")
        if not site_summary.empty:
            psum = site_summary[site_summary["producer"] == producer].copy()
            if filters["anon"]:
                psum["packer_site"] = psum["packer_site"].apply(
                    lambda v: h.anon_value(v, "SITE"))

            fig = go.Figure(go.Pie(
                labels=psum["packer_site"],
                values=psum["total_head"],
                hole=0.5,
                marker=dict(
                    colors=h.PLOTLY_PALETTE[:len(psum)],
                    line=dict(color=h.PROAG_SURFACE, width=2),
                ),
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>Head: %{value:,}<br>"
                              "Share: %{percent}<extra></extra>",
            ))
            fig.update_layout(**h.plotly_layout(height=400, showlegend=False))
            fig.add_annotation(
                text=f"<b>{int(psum['total_head'].sum()):,}</b><br>"
                     f"<span style='font-size:11px;color:{h.PROAG_INK_MUTED}'>"
                     f"head total</span>",
                x=0.5, y=0.5, showarrow=False, align="center",
                font=dict(family="Source Serif Pro", size=18, color=h.PROAG_INK),
            )
            st.plotly_chart(fig, use_container_width=True)

            st.caption(
                f"Top site: **{psum.iloc[0]['packer_site']}** at "
                f"**{psum.iloc[0]['producer_share_pct']:.0f}%** of paid head."
            )
        else:
            st.info("Site summary unavailable.")

    with right:
        st.subheader("Per-cycle trajectory")
        if not closed.empty:
            traj = closed.merge(
                h.load_cycle_trail(mtime)[["cycle_id", "placement_date"]],
                on="cycle_id", how="left",
            ).sort_values("placement_date")

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=traj["placement_date"], y=traj["pnl_per_head"],
                mode="lines+markers",
                line=dict(color=h.PROAG_FOREST, width=2),
                marker=dict(size=10, color=traj["pnl_per_head"].apply(
                    lambda v: h.POSITIVE if v >= 0 else h.NEGATIVE
                ), line=dict(color=h.PROAG_FOREST_DARK, width=1)),
                hovertemplate="<b>%{customdata}</b><br>%{x}<br>$/head: $%{y:,.2f}<extra></extra>",
                customdata=traj["cycle_id"],
                name="$/head",
            ))
            # Zero line
            fig.add_hline(y=0, line_dash="dot", line_color=h.PROAG_INK_MUTED)
            fig.update_layout(**h.plotly_layout(height=400, showlegend=False))
            fig.update_xaxes(title="Placement date")
            fig.update_yaxes(tickformat="$,.0f", title="Net $/head")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No closed cycles for trajectory yet.")


    # ──────────────────────────────────────────────────────────────
    # Cycle list table
    # ──────────────────────────────────────────────────────────────
    st.subheader(f"Cycles for {selected_disp}")
    display = prod_summary[[
        "cycle_id", "status", "placed_head", "paid_head", "mortality_pct",
        "packer_revenue", "cost_attributed", "hedge_pnl", "net_pnl",
        "pnl_per_head", "net_per_cwt",
    ]].rename(columns={
        "cycle_id": "Cycle", "status": "Status", "placed_head": "Placed",
        "paid_head": "Paid", "mortality_pct": "Mort %",
        "packer_revenue": "Revenue", "cost_attributed": "Cost",
        "hedge_pnl": "Hedge", "net_pnl": "Net P&L",
        "pnl_per_head": "$/head", "net_per_cwt": "$/cwt",
    }).sort_values("Cycle")

    st.dataframe(
        display, use_container_width=True, hide_index=True,
        column_config={
            "Placed": st.column_config.NumberColumn(format="%d"),
            "Paid": st.column_config.NumberColumn(format="%d"),
            "Mort %": st.column_config.NumberColumn(format="%.2f%%"),
            "Revenue": st.column_config.NumberColumn(format="$%.0f"),
            "Cost": st.column_config.NumberColumn(format="$%.0f"),
            "Hedge": st.column_config.NumberColumn(format="$%.0f"),
            "Net P&L": st.column_config.NumberColumn(format="$%.0f"),
            "$/head": st.column_config.NumberColumn(format="$%.2f"),
            "$/cwt": st.column_config.NumberColumn(format="$%.2f"),
        },
    )

    st.download_button(
        "📥 Download CSV",
        display.to_csv(index=False).encode("utf-8"),
        file_name=f"proag_producer_{producer}_cycles.csv",
        mime="text/csv",
    )



# ══════════════════════════════════════════════════════════════
# 📈 Market Data
# ══════════════════════════════════════════════════════════════
def render_market_data(filters, mtime):
    ASSETS = {
        "Lean Hog Futures (HEM25)": ("hog_futures_hem25", "$/cwt"),
        "Corn Futures (ZCN25)":     ("corn_futures_zcn25", "¢/bu"),
        "Pork Primal Values":        ("pork_primal", "$/cwt"),
    }

    # ──────────────────────────────────────────────────────────────
    # Asset & view options
    # ──────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        asset = st.selectbox("Asset", list(ASSETS.keys()), index=0, key="mkt_asset")
    table_name, unit = ASSETS[asset]

    df = h.load_market(table_name, mtime)

    if df.empty:
        st.error(f"No data found for {asset}. Has the pipeline been run?")
        st.stop()

    # Identify the date column — Phase 1 lowercased market columns; some
    # tables (HEM25 futures) use 'time', others 'date' or 'report_date'.
    date_col = None
    for c in ("date", "report_date", "time", "timestamp"):
        if c in df.columns:
            date_col = c
            break
    if date_col is None:
        date_col = df.columns[0]

    # Date range filter
    date_range = None
    if date_col in df.columns:
        valid_dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
        if not valid_dates.empty:
            min_d, max_d = valid_dates.min(), valid_dates.max()

            with c2:
                date_range = st.date_input(
                    "Date range",
                    value=(min_d.date(), max_d.date()),
                    min_value=min_d.date(),
                    max_value=max_d.date(),
                    key="mkt_dates",
                )
            if isinstance(date_range, tuple) and len(date_range) == 2:
                start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
                df = df[(df[date_col] >= start) & (df[date_col] <= end)].copy()
        else:
            with c2:
                st.caption("⚠️ No parseable dates in this table.")

    with c3:
        chart_type = st.selectbox(
            "Chart", ["Candlestick", "Line", "Area"], index=0, key="mkt_chart"
        )


    # ──────────────────────────────────────────────────────────────
    # Main chart — branches by asset/columns available
    # ──────────────────────────────────────────────────────────────
    st.subheader(asset)

    # OHLC futures path
    ohlc_cols = ["open", "high", "low", "close"]
    has_ohlc = all(c in df.columns for c in ohlc_cols)

    if has_ohlc:
        if chart_type == "Candlestick":
            fig = go.Figure(go.Candlestick(
                x=df[date_col],
                open=df["open"], high=df["high"], low=df["low"], close=df["close"],
                increasing=dict(line=dict(color=h.POSITIVE),
                                fillcolor=h.POSITIVE),
                decreasing=dict(line=dict(color=h.NEGATIVE),
                                fillcolor=h.NEGATIVE),
                name="OHLC",
            ))
        elif chart_type == "Area":
            fig = go.Figure(go.Scatter(
                x=df[date_col], y=df["close"], fill="tozeroy",
                line=dict(color=h.PROAG_FOREST, width=2),
                fillcolor=f"rgba(45,95,63,0.18)",
                name="Close",
            ))
        else:  # Line
            fig = go.Figure(go.Scatter(
                x=df[date_col], y=df["close"], mode="lines",
                line=dict(color=h.PROAG_FOREST, width=2),
                name="Close",
            ))

        # Hedge strike overlay — only meaningful for HEM25
        if table_name == "hog_futures_hem25":
            st.caption("Hedge strikes are overlaid as horizontal lines if the date "
                       "range covers them.")
            hedges = h.load_hedge_pnl(mtime)
            if not hedges.empty and "strike_cwt" in hedges.columns:
                for _, hedge_row in hedges.iterrows():
                    if pd.notna(hedge_row.get("strike_cwt")):
                        fig.add_hline(
                            y=hedge_row["strike_cwt"],
                            line=dict(color=h.PROAG_HARVEST,
                                      dash="dot", width=1),
                            opacity=0.4,
                        )

        fig.update_layout(**h.plotly_layout(height=480, showlegend=False))
        fig.update_yaxes(title=unit)
        fig.update_xaxes(title=None, rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

        # KPI strip for OHLC
        last = df.iloc[-1] if not df.empty else None
        first = df.iloc[0] if not df.empty else None
        if last is not None and first is not None:
            change = last["close"] - first["close"]
            pct = (change / first["close"]) * 100 if first["close"] else 0
            # Robust date formatting: column may come back as string or NaT
            last_date = pd.to_datetime(last[date_col], errors="coerce")
            last_date_str = last_date.strftime("%Y-%m-%d") if pd.notna(last_date) else str(last[date_col])[:10]
            h.kpi_row([
                {"label": "Latest close", "value": f"{last['close']:.2f}",
                 "delta": last_date_str},
                {"label": "Range close", "value": f"{first['close']:.2f} → {last['close']:.2f}",
                 "delta": f"{change:+.2f} ({pct:+.1f}%)",
                 "delta_kind": "positive" if change >= 0 else "negative",
                 "accent": "positive" if change >= 0 else "negative"},
                {"label": "Period high", "value": f"{df['high'].max():.2f}"},
                {"label": "Period low", "value": f"{df['low'].min():.2f}"},
                {"label": "Avg volume", "value":
                    f"{df['volume'].mean():,.0f}" if "volume" in df.columns else "—"},
            ])
    else:
        # Pork Primal — many price columns
        st.caption(
            "Pork primal: each cut tracked over time. Pick which cuts to show."
        )
        numeric_cols = [c for c in df.columns
                        if c != date_col and pd.api.types.is_numeric_dtype(df[c])]
        default_cuts = numeric_cols[:5]
        chosen = st.multiselect(
            "Cuts / metrics", numeric_cols, default=default_cuts, key="primal_cols"
        )
        if chosen:
            fig = go.Figure()
            for i, col in enumerate(chosen):
                color = h.PLOTLY_PALETTE[i % len(h.PLOTLY_PALETTE)]
                fig.add_trace(go.Scatter(
                    x=df[date_col], y=df[col], mode="lines",
                    name=col.replace("_", " ").title(),
                    line=dict(color=color, width=2),
                ))
            fig.update_layout(**h.plotly_layout(height=460))
            fig.update_yaxes(title=unit)
            st.plotly_chart(fig, use_container_width=True)


    # ──────────────────────────────────────────────────────────────
    # Raw table view
    # ──────────────────────────────────────────────────────────────
    with st.expander("Raw data"):
        st.dataframe(df.tail(200), use_container_width=True, hide_index=True,
                     height=400)
        st.download_button(
            "📥 Download CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name=f"proag_market_{table_name}.csv",
            mime="text/csv",
        )



# ══════════════════════════════════════════════════════════════
# 🚩 Anomalies
# ══════════════════════════════════════════════════════════════
def render_anomalies(filters, mtime):
    anomalies = h.load_anomalies(mtime)
    summary = h.load_pnl_summary(mtime)

    if anomalies.empty:
        st.success("✓ No anomaly flags in the current dataset.")
        st.stop()


    # ──────────────────────────────────────────────────────────────
    # Filter row
    # ──────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([2, 2, 2])

    with c1:
        severity_options = sorted(anomalies["severity"].dropna().unique())
        sev_sel = st.multiselect(
            "Severity", options=severity_options,
            default=[s for s in severity_options if s != "INFO"],
            key="anom_sev",
        )

    with c2:
        metric_options = sorted(anomalies["metric"].dropna().unique())
        metric_sel = st.multiselect(
            "Metric", options=metric_options, default=[],
            key="anom_metric",
        )

    with c3:
        z_min = st.slider(
            "Min |z-score|", 0.0, 5.0, 2.0, 0.1,
            help="Filter out flags with absolute z-score below this threshold "
                 "(does not affect HIGH severity hard rules with no z-score).",
            key="anom_zmin",
        )

    # Apply filters
    filt = anomalies.copy()
    if sev_sel:
        filt = filt[filt["severity"].isin(sev_sel)]
    if metric_sel:
        filt = filt[filt["metric"].isin(metric_sel)]
    # z-score filter (NaN passes through — those are hard rules)
    mask = filt["z_score"].abs() >= z_min
    mask = mask | filt["z_score"].isna()
    filt = filt[mask]


    # ──────────────────────────────────────────────────────────────
    # Headline KPIs
    # ──────────────────────────────────────────────────────────────
    high = filt[filt["severity"] == "HIGH"]
    medium = filt[filt["severity"] == "MEDIUM"]
    info_n = filt[filt["severity"] == "INFO"]
    flagged_cycles = filt["cycle_id"].nunique()

    h.kpi_row([
        {"label": "Flagged cycles", "value": str(flagged_cycles),
         "delta": f"of {summary['cycle_id'].nunique()} total"},
        {"label": "HIGH severity", "value": str(len(high)),
         "accent": "negative" if len(high) > 0 else "leaf"},
        {"label": "MEDIUM severity", "value": str(len(medium)),
         "accent": "warning" if len(medium) > 0 else "leaf"},
        {"label": "INFO", "value": str(len(info_n))},
    ])


    # ──────────────────────────────────────────────────────────────
    # Overview chart — flags per cycle
    # ──────────────────────────────────────────────────────────────
    st.subheader("Flag count per cycle")

    flag_counts = (
        filt.groupby(["cycle_id", "severity"]).size()
            .reset_index(name="flags")
            .sort_values("cycle_id")
    )
    if not flag_counts.empty:
        fig = px.bar(
            flag_counts, x="cycle_id", y="flags", color="severity",
            color_discrete_map={
                "HIGH":   h.NEGATIVE,
                "MEDIUM": h.WARNING,
                "INFO":   h.INFO,
            },
            category_orders={"severity": ["HIGH", "MEDIUM", "INFO"]},
        )
        fig.update_layout(**h.plotly_layout(height=320))
        fig.update_xaxes(title=None)
        fig.update_yaxes(title="Flags")
        st.plotly_chart(fig, use_container_width=True)


    # ──────────────────────────────────────────────────────────────
    # Flag detail — grouped by cycle
    # ──────────────────────────────────────────────────────────────
    st.subheader("Flag detail")

    if filt.empty:
        st.info("No flags match the current filters.")
    else:
        # Group by cycle and render
        for cid, grp in filt.groupby("cycle_id"):
            with st.expander(
                f"**{cid}** — {len(grp)} flag(s)",
                expanded=(len(grp) > 0 and "HIGH" in grp["severity"].values),
            ):
                for _, a in grp.iterrows():
                    sev = a["severity"]
                    badge = h.status_badge(sev)
                    z_html = (
                        f"<code>z = {a['z_score']:.2f}</code> · "
                        if pd.notna(a.get("z_score")) else ""
                    )
                    accent = (
                        h.NEGATIVE if sev == "HIGH"
                        else h.WARNING if sev == "MEDIUM"
                        else h.INFO
                    )
                    st.markdown(
                        f"""
                        <div style="background:{h.PROAG_SURFACE};
                                    border:1px solid {h.PROAG_LINE};
                                    border-left:4px solid {accent};
                                    padding:10px 14px;border-radius:6px;
                                    margin-bottom:8px;">
                          {badge} &nbsp; <strong>{a['metric']}</strong> · {z_html}
                          value <code>{a['value']}</code><br>
                          <span style="color:{h.PROAG_INK_MUTED};">
                            {a['note']}
                          </span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

    # Export
    st.divider()
    st.download_button(
        "📥 Download flagged anomalies as CSV",
        filt.to_csv(index=False).encode("utf-8"),
        file_name="proag_anomalies.csv",
        mime="text/csv",
    )



# ──────────────────────────────────────────────────────────────
# Sidebar navigation + dispatch
# ──────────────────────────────────────────────────────────────
PAGE_LABELS = [
    "🏠 Portfolio",
    "📊 Cycle Detail",
    "⚖️ Compare Cycles",
    "🏭 Producer View",
    "📈 Market Data",
    "🚩 Anomalies",
]

st.sidebar.markdown("### 📑 Pages")
page = st.sidebar.radio(
    "Navigate",
    options=PAGE_LABELS,
    index=PAGE_LABELS.index(st.session_state.get("page_nav", PAGE_LABELS[0])),
    key="page_nav",
    label_visibility="collapsed",
)
st.sidebar.divider()

# Sidebar filters (cycle picker only on Cycle Detail)
filters = h.sidebar_controls(show_cycle_select=(page == "📊 Cycle Detail"))
mtime = h._db_mtime()

# Header strip — title is dynamic on Cycle Detail, fixed elsewhere
HEADERS = {
    "🏠 Portfolio":      ("Producer Analytics",
                           "Hog cycle P&L, hedging, costs and anomalies — one view per producer"),
    "📊 Cycle Detail":   (f"Cycle {filters['cycle']}" if filters.get("cycle") else "Cycle Detail",
                           "Single-cycle P&L, hedging, settlements, and flags"),
    "⚖️ Compare Cycles": ("Compare Cycles",
                           "Stack any 2–5 cycles head-to-head on revenue, costs, hedging, and per-CWT economics"),
    "🏭 Producer View":  ("Producer View",
                           "Aggregate cycles, packer site allocation, and per-cycle trajectory"),
    "📈 Market Data":    ("Market Data",
                           "Hog futures · corn futures · pork primal — overlay hedge strikes"),
    "🚩 Anomalies":      ("Anomaly Flags",
                           "Z-score outliers across cost, mortality, and P&L vs peer cycles"),
}
title, subtitle = HEADERS[page]
h.header(title, subtitle=subtitle)

# Dispatch
DISPATCH = {
    "🏠 Portfolio":      render_portfolio,
    "📊 Cycle Detail":   render_cycle_detail,
    "⚖️ Compare Cycles": render_compare_cycles,
    "🏭 Producer View":  render_producer_view,
    "📈 Market Data":    render_market_data,
    "🚩 Anomalies":      render_anomalies,
}
DISPATCH[page](filters, mtime)