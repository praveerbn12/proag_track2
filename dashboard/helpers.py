"""Phase 5 — combined theme + data layer for the dashboard.

This module merges what was originally theme.py (palette, formatters,
KPI cards, custom CSS) and data.py (cached SQL loaders, anonymization,
sidebar controls) into a single helper module so the dashboard fits in
fewer files for upload.
"""

# Import hashlib early since we use it in anonymization
import hashlib
import streamlit as st


# ──────────────────────────────────────────────────────────────
# Color palette — pulled from ProAg's brand identity
# ──────────────────────────────────────────────────────────────
PROAG_FOREST = "#2D5F3F"        # primary — deep forest green
PROAG_FOREST_DARK = "#1B4028"   # hover / borders
PROAG_LEAF = "#7CB342"          # secondary — bright leaf green
PROAG_HARVEST = "#558B2F"       # accent — olive
PROAG_CREAM = "#FAFAF7"         # canvas
PROAG_SURFACE = "#FFFFFF"       # cards
PROAG_INK = "#1A1A1A"           # body text
PROAG_INK_MUTED = "#5C5C5C"     # secondary text
PROAG_LINE = "#E5E2DC"          # dividers

POSITIVE = "#2E7D32"
NEGATIVE = "#C62828"
WARNING = "#EF6C00"
INFO = "#1565C0"

# Plotly categorical palette — earth-tone, ag-friendly
PLOTLY_PALETTE = [
    "#2D5F3F", "#7CB342", "#558B2F", "#A1887F",
    "#EF6C00", "#1565C0", "#6A4C93", "#8D6E63",
]

# Cost-category palette (stable across pages)
CATEGORY_COLORS = {
    "Feed":           "#558B2F",
    "Labor":          "#EF6C00",
    "Health":         "#C62828",
    "Facilities":     "#1565C0",
    "Transportation": "#6A4C93",
    "Overhead":       "#8D6E63",
    "Animal":         "#2D5F3F",
}


# ──────────────────────────────────────────────────────────────
# Page setup + global CSS
# ──────────────────────────────────────────────────────────────
def setup_page(title="ProAg Producer Analytics", icon="🌾", layout="wide"):
    """Call once at the top of every page."""
    st.set_page_config(
        page_title=title,
        page_icon=icon,
        layout=layout,
        initial_sidebar_state="expanded",
    )
    _inject_css()


def _inject_css():
    st.markdown(
        f"""
        <style>
        /* Typography — load distinctive fonts */
        @import url('https://fonts.googleapis.com/css2?family=Source+Serif+Pro:wght@600;700&family=Inter:wght@400;500;600;700&display=swap');

        html, body, [class*="css"] {{
            font-family: 'Inter', -apple-system, sans-serif;
        }}

        h1, h2, h3 {{
            font-family: 'Source Serif Pro', Georgia, serif !important;
            color: {PROAG_FOREST_DARK};
            letter-spacing: -0.01em;
        }}

        /* App background */
        .stApp {{
            background-color: {PROAG_CREAM};
        }}

        /* Sidebar */
        [data-testid="stSidebar"] {{
            background-color: {PROAG_SURFACE};
            border-right: 1px solid {PROAG_LINE};
        }}
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {{
            color: {PROAG_FOREST};
        }}

        /* KPI card */
        .kpi-card {{
            background: {PROAG_SURFACE};
            border: 1px solid {PROAG_LINE};
            border-left: 4px solid {PROAG_FOREST};
            border-radius: 8px;
            padding: 18px 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
            height: 100%;
        }}
        .kpi-card .label {{
            font-size: 0.78rem;
            font-weight: 500;
            color: {PROAG_INK_MUTED};
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 4px;
        }}
        .kpi-card .value {{
            font-family: 'Source Serif Pro', Georgia, serif;
            font-size: 1.75rem;
            font-weight: 700;
            color: {PROAG_INK};
            line-height: 1.1;
        }}
        .kpi-card .delta {{
            font-size: 0.82rem;
            font-weight: 500;
            margin-top: 4px;
        }}
        .kpi-card .delta.positive {{ color: {POSITIVE}; }}
        .kpi-card .delta.negative {{ color: {NEGATIVE}; }}
        .kpi-card .delta.neutral  {{ color: {PROAG_INK_MUTED}; }}
        .kpi-card.accent-leaf      {{ border-left-color: {PROAG_LEAF}; }}
        .kpi-card.accent-positive  {{ border-left-color: {POSITIVE}; }}
        .kpi-card.accent-negative  {{ border-left-color: {NEGATIVE}; }}
        .kpi-card.accent-warning   {{ border-left-color: {WARNING}; }}

        /* Status badges */
        .badge {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .badge.closed    {{ background: #E8F5E9; color: {POSITIVE}; }}
        .badge.in_flight {{ background: #FFF3E0; color: {WARNING}; }}
        .badge.high      {{ background: #FFEBEE; color: {NEGATIVE}; }}
        .badge.medium    {{ background: #FFF3E0; color: {WARNING}; }}
        .badge.info      {{ background: #E3F2FD; color: {INFO}; }}

        /* Header strip */
        .pa-header {{
            background: linear-gradient(135deg, {PROAG_FOREST} 0%, {PROAG_FOREST_DARK} 100%);
            color: white;
            padding: 18px 24px;
            border-radius: 8px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .pa-header .title {{
            font-family: 'Source Serif Pro', Georgia, serif;
            font-size: 1.4rem;
            font-weight: 700;
            color: white !important;
            margin: 0;
        }}
        .pa-header .subtitle {{
            font-size: 0.85rem;
            opacity: 0.85;
            margin-top: 2px;
        }}
        .pa-header .meta {{
            text-align: right;
            font-size: 0.78rem;
            opacity: 0.85;
        }}

        /* Tighter Streamlit defaults */
        .block-container {{ padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1400px; }}
        [data-testid="stMetricValue"] {{ font-family: 'Source Serif Pro', serif; }}
        .stTabs [data-baseweb="tab"] {{ font-weight: 500; }}
        .stTabs [aria-selected="true"] {{ color: {PROAG_FOREST} !important; }}
        button[kind="primary"] {{ background-color: {PROAG_FOREST}; }}

        /* DataFrame zebra */
        [data-testid="stDataFrame"] {{
            border: 1px solid {PROAG_LINE};
            border-radius: 6px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────────────────────────────
# Header strip
# ──────────────────────────────────────────────────────────────
def header(title, subtitle="", advisor_name="ProAg Advisor"):
    from datetime import datetime
    st.markdown(
        f"""
        <div class="pa-header">
            <div>
                <div class="title">🌾 {title}</div>
                <div class="subtitle">{subtitle}</div>
            </div>
            <div class="meta">
                <div><strong>{advisor_name}</strong></div>
                <div>{datetime.now().strftime('%A, %B %d, %Y')}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────────────────────────────
# KPI cards
# ──────────────────────────────────────────────────────────────
def kpi(label, value, delta=None, delta_kind="neutral", accent=""):
    """Render a single KPI card."""
    delta_html = ""
    if delta:
        arrow = {"positive": "▲", "negative": "▼", "neutral": "•"}.get(delta_kind, "")
        delta_html = f'<div class="delta {delta_kind}">{arrow} {delta}</div>'
    accent_cls = f"accent-{accent}" if accent else ""
    st.markdown(
        f"""
        <div class="kpi-card {accent_cls}">
            <div class="label">{label}</div>
            <div class="value">{value}</div>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_row(items):
    """Render a row of KPI cards.

    items: list of dicts with keys {label, value, delta?, delta_kind?, accent?}
    """
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        with col:
            kpi(
                item["label"],
                item["value"],
                delta=item.get("delta"),
                delta_kind=item.get("delta_kind", "neutral"),
                accent=item.get("accent", ""),
            )


def status_badge(status):
    cls = status.lower().replace(" ", "_")
    return f'<span class="badge {cls}">{status.replace("_", " ").title()}</span>'


# ──────────────────────────────────────────────────────────────
# Formatters
# ──────────────────────────────────────────────────────────────
def fmt_money(x, dp=0, na="—"):
    if x is None:
        return na
    try:
        if dp == 0:
            return f"${x:,.0f}"
        return f"${x:,.{dp}f}"
    except (TypeError, ValueError):
        return na


def fmt_money_signed(x, dp=0, na="—"):
    """Money with explicit sign — useful for hedge P&L, net P&L."""
    if x is None:
        return na
    try:
        if x >= 0:
            return f"+${x:,.{dp}f}"
        return f"-${abs(x):,.{dp}f}"
    except (TypeError, ValueError):
        return na


def fmt_int(x, na="—"):
    if x is None:
        return na
    try:
        return f"{int(x):,}"
    except (TypeError, ValueError):
        return na


def fmt_pct(x, dp=1, na="—"):
    if x is None:
        return na
    try:
        return f"{x:.{dp}f}%"
    except (TypeError, ValueError):
        return na


def fmt_num(x, dp=2, na="—"):
    if x is None:
        return na
    try:
        return f"{x:,.{dp}f}"
    except (TypeError, ValueError):
        return na


# ──────────────────────────────────────────────────────────────
# Plotly defaults
# ──────────────────────────────────────────────────────────────
def plotly_layout(title=None, height=420, showlegend=True):
    """Return a layout dict to apply to every Plotly chart for consistency."""
    return dict(
        title=dict(text=title, font=dict(family="Source Serif Pro, serif",
                                          size=16, color=PROAG_FOREST_DARK)) if title else None,
        font=dict(family="Inter, sans-serif", color=PROAG_INK, size=12),
        plot_bgcolor=PROAG_SURFACE,
        paper_bgcolor=PROAG_SURFACE,
        margin=dict(l=40, r=20, t=50 if title else 20, b=40),
        height=height,
        showlegend=showlegend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(gridcolor=PROAG_LINE, zerolinecolor=PROAG_LINE),
        yaxis=dict(gridcolor=PROAG_LINE, zerolinecolor=PROAG_LINE),
    )


# ──────────────────────────────────────────────────────────────
# DATA LAYER (was data.py)
# ──────────────────────────────────────────────────────────────
import hashlib
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

from pipeline.config import DB_PATH
from pipeline.cycles import get_cycle, build_all_cycles
from analytics.pnl import compute_pnl, flag_anomalies, build_full_pnl


# ──────────────────────────────────────────────────────────────
# Engine + raw SQL helpers (cached)
# ──────────────────────────────────────────────────────────────
@st.cache_resource
def _engine():
    return create_engine(f"sqlite:///{DB_PATH}")


def _db_mtime():
    """Used as a cache key — invalidates caches when the DB is rebuilt."""
    p = Path(DB_PATH)
    return p.stat().st_mtime if p.exists() else 0


@st.cache_data(show_spinner=False)
def list_tables(mtime=None):
    df = pd.read_sql(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        _engine(),
    )
    return df["name"].tolist()


def _has_table(name):
    return name in list_tables(_db_mtime())


# ──────────────────────────────────────────────────────────────
# Phase 4 fact tables (fast aggregates)
# ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Loading P&L summary...")
def load_pnl_summary(mtime=None):
    """fact_cycle_pnl — one row per cycle with all top-line metrics."""
    if _has_table("fact_cycle_pnl"):
        df = pd.read_sql("SELECT * FROM fact_cycle_pnl", _engine())
    else:
        # Fall back to recomputing if Phase 4 hasn't written outputs yet
        summary, _, _ = build_full_pnl()
        df = summary
    return df


@st.cache_data(show_spinner="Loading anomalies...")
def load_anomalies(mtime=None):
    if _has_table("fact_anomalies"):
        return pd.read_sql("SELECT * FROM fact_anomalies", _engine())
    return pd.DataFrame(
        columns=["cycle_id", "metric", "value", "z_score", "severity", "note"]
    )


@st.cache_data(show_spinner="Loading cost breakdown...")
def load_cost_breakdown(mtime=None):
    if _has_table("fact_cycle_costs"):
        return pd.read_sql("SELECT * FROM fact_cycle_costs", _engine())
    return pd.DataFrame(columns=["cycle_id", "cost_category", "attributed_cost"])


@st.cache_data(show_spinner="Loading hedge P&L...")
def load_hedge_pnl(mtime=None):
    if _has_table("fact_hedge_pnl"):
        return pd.read_sql("SELECT * FROM fact_hedge_pnl", _engine())
    return pd.DataFrame()


# ──────────────────────────────────────────────────────────────
# Cycle metadata (for selectors)
# ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Loading cycles...")
def load_cycle_trail(mtime=None):
    """cycle_trail — Phase 2 base records with placement/transfer info."""
    return pd.read_sql(
        "SELECT * FROM cycle_trail ORDER BY placement_date",
        _engine(),
        parse_dates=["placement_date", "transfer_date"],
    )


@st.cache_data(show_spinner=False)
def cycle_ids(mtime=None):
    return load_cycle_trail(mtime)["cycle_id"].tolist()


# ──────────────────────────────────────────────────────────────
# Producer lookup (from packer settlements)
# ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_producer_site_summary(mtime=None):
    if _has_table("producer_site_summary"):
        return pd.read_sql("SELECT * FROM producer_site_summary", _engine())
    return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_cycle_producer_map(mtime=None):
    """For each cycle, the dominant producer (by paid head from packer settlements)."""
    df = pd.read_sql(
        """
        SELECT
            ps.Producer       AS producer,
            ps.Paid_Head      AS paid_head,
            ps.Kill_Date      AS kill_date,
            ps.Site           AS packer_site
        FROM packer_settlement ps
        """,
        _engine(),
        parse_dates=["kill_date"],
    )
    return df


@st.cache_data(show_spinner="Resolving producer per cycle...")
def cycle_producer_table(mtime=None):
    """Match each cycle to its dominant producer.

    A cycle's producer is the one whose name appears most on its matched
    packer settlements. We get that mapping by walking get_cycle() once.
    """
    rows = []
    for cid in cycle_ids(mtime):
        c = get_cycle(cid)
        if c is None:
            continue
        prods = {}
        for s in c.get("packer_settlements", []):
            p = s.get("producer") or "Unknown"
            prods[p] = prods.get(p, 0) + s.get("paid_head", 0) or 0
        if prods:
            top = max(prods.items(), key=lambda kv: kv[1])[0]
        else:
            top = None
        rows.append({"cycle_id": cid, "producer": top})
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────
# Per-cycle drilldown (NOT cached — small + may need fresh data)
# ──────────────────────────────────────────────────────────────
def get_cycle_pnl(cycle_id):
    """Compute P&L for one cycle on demand. Lightweight enough not to cache."""
    return compute_pnl(cycle_id)


def get_cycle_full(cycle_id):
    """Get the raw cycle dict (base + hedges + settlements + cost events)."""
    return get_cycle(cycle_id)


def get_anomalies_for(cycle_id, all_pnls=None):
    """Run flag_anomalies for one cycle against all closed peers."""
    cycle_pnl = compute_pnl(cycle_id)
    if cycle_pnl is None:
        return []
    if all_pnls is None:
        # Build peer set from fact table — avoids recomputing all 18
        summary = load_pnl_summary(_db_mtime())
        all_pnls = []
        for _, r in summary.iterrows():
            if r["status"] == "closed" and r["cycle_id"] != cycle_id:
                pnl = compute_pnl(r["cycle_id"])
                if pnl:
                    all_pnls.append(pnl)
    return flag_anomalies(cycle_pnl, all_pnls)


# ──────────────────────────────────────────────────────────────
# Market data
# ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Loading market data...")
def load_market(table, mtime=None):
    """Load a market table with date-parsed columns.

    SQLite has no native datetime, so dates come back as strings. We try
    several common formats so dates work whether they were stored as ISO,
    Excel-serial-rendered, or US-style.
    """
    if not _has_table(table):
        return pd.DataFrame()
    df = pd.read_sql(f"SELECT * FROM {table}", _engine())

    # Find the date column — try known names, then any column whose name
    # contains date-like keywords.
    date_col = None
    for c in ("date", "report_date", "time", "timestamp"):
        if c in df.columns:
            date_col = c
            break
    if date_col is None:
        for c in df.columns:
            cl = c.lower()
            if "date" in cl or cl in ("time", "timestamp"):
                date_col = c
                break

    if date_col is not None:
        # Try ISO first, then plain to_datetime, then with infer
        parsed = pd.to_datetime(df[date_col], errors="coerce")
        if parsed.isna().all():
            # Try common explicit formats
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
                parsed = pd.to_datetime(df[date_col], format=fmt, errors="coerce")
                if parsed.notna().any():
                    break
        if parsed.isna().all():
            # Last resort: keep original strings, don't sort
            return df
        df[date_col] = parsed
        df = df.sort_values(date_col).reset_index(drop=True)
    return df


# ──────────────────────────────────────────────────────────────
# Anonymization (privacy guardrail from spec)
# ──────────────────────────────────────────────────────────────
def _anon_hash(s, prefix):
    """Stable short hash so 'Producer B' always maps to the same alias."""
    if s is None or pd.isna(s):
        return s
    h = hashlib.sha1(str(s).encode("utf-8")).hexdigest()[:4].upper()
    return f"{prefix}-{h}"


def anonymize_df(df, columns_map):
    """Apply consistent anonymization to a DataFrame.

    columns_map: {column_name: prefix}, e.g. {"producer": "PROD"}.
    Returns a new DataFrame.
    """
    if df is None or df.empty:
        return df
    df = df.copy()
    for col, prefix in columns_map.items():
        if col in df.columns:
            df[col] = df[col].apply(lambda v: _anon_hash(v, prefix))
    return df


def anon_value(value, prefix):
    """Anonymize a single string."""
    return _anon_hash(value, prefix)


# ──────────────────────────────────────────────────────────────
# Sidebar controls (shared across pages)
# ──────────────────────────────────────────────────────────────
def sidebar_controls(show_cycle_select=False):
    """Render the standard sidebar controls. Returns a dict of selections.

    Pages can call this once and use the returned filters.
    """
    st.sidebar.markdown("### 🌾 ProAg Advisor")
    st.sidebar.caption("Producer Analytics — Track 2")
    st.sidebar.divider()

    # Anonymize toggle (privacy guardrail)
    anon = st.sidebar.toggle(
        "🔒 Anonymize identifiers",
        value=st.session_state.get("anon", False),
        help="Replace producer & site names with stable aliases. "
             "Safe to use when sharing screens or copying to LLMs.",
        key="anon",
    )

    st.sidebar.divider()
    st.sidebar.markdown("**Filters**")

    # Status filter
    status = st.sidebar.radio(
        "Cycle status",
        options=["All", "Closed only", "In-flight only"],
        index=0,
        horizontal=False,
    )

    # Producer filter
    prod_map = cycle_producer_table(_db_mtime())
    producers = sorted([p for p in prod_map["producer"].dropna().unique()])
    if anon:
        prod_display = [_anon_hash(p, "PROD") for p in producers]
        prod_lookup = dict(zip(prod_display, producers))
    else:
        prod_display = producers
        prod_lookup = dict(zip(producers, producers))

    selected_disp = st.sidebar.multiselect(
        "Producers",
        options=prod_display,
        default=[],
        help="Empty = include all producers.",
    )
    selected_producers = [prod_lookup[d] for d in selected_disp]

    # Cycle picker (only on detail pages)
    cycle = None
    if show_cycle_select:
        st.sidebar.divider()
        ids = cycle_ids(_db_mtime())
        cycle = st.sidebar.selectbox(
            "Cycle",
            options=ids,
            index=ids.index(st.session_state["selected_cycle"])
                if st.session_state.get("selected_cycle") in ids else 0,
            key="cycle_picker",
        )
        st.session_state["selected_cycle"] = cycle

    return {
        "anon": anon,
        "status": status,
        "producers": selected_producers,
        "cycle": cycle,
    }


def apply_filters(summary_df, filters, producer_map=None):
    """Filter a P&L summary DataFrame using sidebar selections."""
    df = summary_df.copy()
    if filters["status"] == "Closed only":
        df = df[df["status"] == "closed"]
    elif filters["status"] == "In-flight only":
        df = df[df["status"] == "in_flight"]

    if filters["producers"]:
        if producer_map is None:
            producer_map = cycle_producer_table(_db_mtime())
        keep_ids = producer_map[producer_map["producer"].isin(filters["producers"])][
            "cycle_id"
        ].tolist()
        df = df[df["cycle_id"].isin(keep_ids)]
    return df


# ──────────────────────────────────────────────────────────────
# Convenience: load everything a page typically needs
# ──────────────────────────────────────────────────────────────
def load_all(mtime=None):
    """Load summary, anomalies, costs, and producer map together."""
    return {
        "summary": load_pnl_summary(mtime),
        "anomalies": load_anomalies(mtime),
        "costs": load_cost_breakdown(mtime),
        "hedges": load_hedge_pnl(mtime),
        "producer_map": cycle_producer_table(mtime),
        "trail": load_cycle_trail(mtime),
    }