"""Dashboard entry point.

Run: streamlit run dashboard/app.py

One page per role. No navigation. Sidebar picks role; if Producer, picks
which producer. That's it.
"""
import streamlit as st

from dashboard import db, ui, views


st.set_page_config(
    page_title="ProAg Cycle Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.inject_css()


# ──────────────────────────────────────────────────────────────
# Sidebar — role + identity
# ──────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ProAg")
    role = st.radio("View as", ["Advisor", "Producer"], key="role")

    cycles = db.load_cycles()
    producer = None
    if role == "Producer":
        names = db.producers(cycles)
        if not names:
            st.warning("No producers. Rebuild the data first.")
            st.stop()
        producer = st.selectbox("Account", names, key="producer")

    st.divider()

    if not cycles.empty:
        anomalies = db.load_anomalies()
        open_count = 0
        if not anomalies.empty:
            open_count = sum(
                1 for _, r in anomalies.iterrows()
                if ui.alert_status(r["cycle_id"], r["metric"]) == "open"
            )
        st.caption(f"{len(cycles)} cycles loaded")
        st.caption(f"{open_count} open alerts")

    st.divider()
    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ──────────────────────────────────────────────────────────────
# Render the one page
# ──────────────────────────────────────────────────────────────

if role == "Advisor":
    views.advisor_page()
else:
    views.producer_page(producer)
