"""UI primitives: formatters, badges, alert workflow state.

No navigation helpers — pages are single-scroll, no routing needed.
"""
import pandas as pd
import streamlit as st


# ──────────────────────────────────────────────────────────────
# Formatters
# ──────────────────────────────────────────────────────────────

def money(x, dash="—"):
    if x is None or pd.isna(x):
        return dash
    if abs(x) >= 1_000_000:
        return f"${x/1_000_000:,.2f}M"
    if abs(x) >= 10_000:
        return f"${x:,.0f}"
    return f"${x:,.2f}"


def pct(x, dash="—"):
    if x is None or pd.isna(x):
        return dash
    return f"{x:.1f}%"


def head(x, dash="—"):
    if x is None or pd.isna(x):
        return dash
    return f"{int(x):,}"


def per_head(x, dash="—"):
    if x is None or pd.isna(x):
        return dash
    return f"${x:.2f}"


# ──────────────────────────────────────────────────────────────
# Alert workflow state (demo: session-only, no persistence)
# ──────────────────────────────────────────────────────────────

def _alert_key(cycle_id: str, metric: str) -> str:
    return f"{cycle_id}::{metric}"


def alert_status(cycle_id: str, metric: str) -> str:
    """Return 'open', 'acknowledged', or 'snoozed'."""
    acked = st.session_state.get("alerts_acked", set())
    snoozed = st.session_state.get("alerts_snoozed", set())
    key = _alert_key(cycle_id, metric)
    if key in acked:
        return "acknowledged"
    if key in snoozed:
        return "snoozed"
    return "open"


def acknowledge_alert(cycle_id: str, metric: str):
    st.session_state.setdefault("alerts_acked", set()).add(_alert_key(cycle_id, metric))


def snooze_alert(cycle_id: str, metric: str):
    st.session_state.setdefault("alerts_snoozed", set()).add(_alert_key(cycle_id, metric))


def get_note(cycle_id: str, metric: str) -> str:
    return st.session_state.get("alert_notes", {}).get(_alert_key(cycle_id, metric), "")


def set_note(cycle_id: str, metric: str, text: str):
    st.session_state.setdefault("alert_notes", {})[_alert_key(cycle_id, metric)] = text


# ──────────────────────────────────────────────────────────────
# Custom CSS — severity badges
# ──────────────────────────────────────────────────────────────

CSS = """
<style>
.sev-pill {
    display: inline-block; padding: 2px 10px; border-radius: 4px;
    font-size: 11px; font-weight: 600; letter-spacing: 0.5px;
}
.sev-HIGH    { background: #fcebeb; color: #791f1f; }
.sev-MEDIUM  { background: #faeeda; color: #633806; }
.sev-LOW     { background: #e6f1fb; color: #0c447c; }
.status-pill {
    display: inline-block; padding: 2px 10px; border-radius: 4px;
    font-size: 11px; background: #f1efe8; color: #5f5e5a;
}
.status-acknowledged { background: #eaf3de; color: #27500a; }
.status-snoozed      { background: #f1efe8; color: #5f5e5a; }
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def sev_pill(severity: str) -> str:
    return f'<span class="sev-pill sev-{severity}">{severity}</span>'


def status_pill(status: str) -> str:
    return f'<span class="status-pill status-{status}">{status}</span>'


# ──────────────────────────────────────────────────────────────
# Peer comparison strip
# ──────────────────────────────────────────────────────────────

def peer_strip(comparison: dict, label: str, formatter=money):
    """Three columns: this cycle / producer avg / all avg, with delta arrow."""
    if not comparison:
        return
    c1, c2, c3 = st.columns(3)
    delta = comparison.get("delta_vs_producer_pct")
    c1.metric(
        f"This cycle · {label}",
        formatter(comparison["this"]),
        delta=f"{delta:+.1f}% vs producer avg" if delta is not None else None,
        delta_color="normal",
    )
    c2.metric(f"Producer avg · {label}", formatter(comparison["producer_avg"]))
    c3.metric(f"All producers · {label}", formatter(comparison["all_avg"]))
