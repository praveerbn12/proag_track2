# Cycle-Level Profitability Analytics for Hog Producer Advisory Workflows

**A unified data pipeline, statistical anomaly detection, and AI-assisted narrative system, built for ProAg risk advisors**

---

## Team & Track

**Competition:** CCDS / Pro-Ag Data Science Competition — AI & Data Analytics Applications for Business
**Track:** Track 2 — Producer Analytics

| Name | Level | Focus | Email |
|------|-------|-------|-------|
| Jayesh Sawarkar | Graduate | Analytics & AI | jsawarka@syr.edu |
| Praveer Byndoor | Graduate | Data Pipeline & Architecture | pbyndoor@syr.edu |
| Roshni More | Graduate | Dashboard & UX | romore@syr.edu |

**Faculty Mentor:** Professor Chris Dunham, Syracuse University iSchool

---

## Abstract

A ProAg risk advisor managing 30 hog producers currently spends roughly an hour reconciling each producer's scattered data — QuickBooks exports, packer settlement PDFs, barn spreadsheets, hedging records — before every consultation call. We built an internal tool that automates this reconciliation around the production cycle, computes per-cycle profitability and operational metrics, statistically flags anomalies, and uses an LLM to convert each result into a 2–3 sentence narrative an advisor can read in seconds. The system processes 18 production cycles in the supplied dummy dataset, flags 5 anomalies across 4 statistical features, and renders the results in a two-role Streamlit dashboard with an enforced privacy boundary between advisor and producer views. The architecture is deliberately Azure-compatible and the mocked LLM client is a one-config-change drop-in for the Claude API.

---

## 1. Introduction

ProAg's risk advisors counsel hog producers on financial performance and hedging decisions. Each producer's data lives in separate systems — accounting software for cost ledgers, packer reports for slaughter revenue, barn-management spreadsheets for movements and mortality, and a hedging platform for futures positions. Before every advisory call, the advisor must manually unify these sources to answer a single question: *how is this producer's most recent production cycle performing relative to their own history and to peers?*

We built a tool that automates that reconciliation. Given a producer's raw data files, the system unifies them around the **production cycle** (the natural unit of P&L in this industry — placement → nursery → finisher → packer settlement), computes a complete cycle ledger, statistically flags cycles with operational or financial anomalies, and uses an LLM to generate plain-English explanations and cycle summaries. The advisor then opens a dashboard, sees a portfolio overview ranked by which producers need attention, drills into any cycle to see the AI summary, P&L breakdown, peer comparison, and hedging position, and uses that as the basis for the producer call.

The work directly addresses ProAg's stated need to give advisors a single source of truth for cycle-level performance, with AI used only where it adds value (narrative generation) and never where it would introduce risk (regulated financial advice, numeric computation).

---

## 2. Background

### How the project took shape

Three conversations shaped the design:

**ProAg's initial brief** established the central pain point — advisors lose an hour per producer to data reconciliation, and that hour is the most consequential prep before any call. ProAg framed the data fragmentation as deliberate in the supplied dummy dataset: the files use intentionally inconsistent naming conventions across sources to mirror real producer data. Reconciliation is therefore not a side task; it is the core technical contribution.

**Cade's email** identified a three-level site hierarchy (cost center → commercial site → physical barn) that the accounting and packer files do not state explicitly but must be inferred. This guided our entity-resolution approach.

**Mid-project faculty review** flagged that our privacy and guardrail story needed depth: how do we use an LLM safely on financial data that contains regulated topics? The architecture documented in §3.5 is our response.

### Why these methods

- **Cycle-keyed data model.** Hog producers and their advisors think in cycles, not in accounting periods. Anchoring every metric on `cycle_id` makes the data model match the mental model.
- **Statistical anomaly detection (z-scores) rather than ML.** With only 18 cycles in the dummy data, supervised ML would overfit and unsupervised clustering would be unstable. Z-scores are interpretable, defensible, and scale naturally as data accumulates.
- **LLM only on the explanation layer.** LLMs are excellent at language and unreliable at numbers. Keeping all math in deterministic Python and using the LLM strictly to translate numbers into sentences gives us AI's communicative advantages without its numerical failure modes.
- **Single-page dashboards with role-scoped views.** The advisor view is a working surface for triage; the producer view is a portfolio readout. Conflating them would either expose statistical detail to producers (a privacy and trust risk) or strip the advisor of the workflow detail they need.

Prior work in this space is sparse — most agricultural BI tools focus on yield optimization or single-source reporting, not the multi-source cycle reconciliation problem we tackle. Related approaches in supply-chain analytics use similar confidence-scored entity resolution (probabilistic record linkage); our cost-attribution method (§3.4) follows that pattern.

---

## 3. Data and Methods

### 3.1 Data

The supplied dataset comprises ten files across two source families:

**Producer-side files (7):** Sow farrowing, nursery intake, barn-to-barn pig flow, barn environmental & utilities, hog hedging records, packer settlements, and swine accounting (cost ledger).

**Market-side files (3):** Hog futures price history (HEM25), corn futures (ZCN25), and pork primal values.

| Data family | Source file(s) | Role in the pipeline |
|---|---|---|
| Pig movements | `nursery_intake.csv`, `barn_to_barn_pig_flow.csv` | Defines the cycle entity (placement → transfer → kill window) |
| Cost ledger | `swine_accounting_dummy.csv` | Cost events attributed to cycles by date and phase |
| Slaughter revenue | `packer_settlement.csv` | Revenue per cycle, matched by date proximity to transfer |
| Hedging | `hog_hedging_aligned_to_nursery.csv` | Cycle-tagged futures positions and realized P&L |
| Barn operations | `barn_environmental_utilities.csv`, `sow_farm_weekly_farrowing.csv` | Mortality, environment, and upstream supply context |
| Market data | `HEM25_HISTORY.xlsx`, `ZCN25.xlsx`, `Pork_Primal_Values.csv` | Settle prices for hedge MTM and contextual benchmarks |

**Data validity.** The dataset was provided directly by ProAg as a representative dummy stand-in for actual producer data. ProAg confirmed the inconsistencies in naming conventions across files are intentional and reflect what real producer data looks like. The market data files (HEM25, ZCN25) are CME-format daily price histories; the rest are dummy data with realistic structures.

**Cycles in the dataset:** 18 total — 14 closed (with settled packer revenue) and 4 in-flight. Average placement size is approximately 2,350 head per cycle.

**Data access.** Raw files are not submitted with this report. They reside in the project's `data/raw/` directory and were provided by ProAg under the competition agreement. Detailed schema documentation lives in supporting file `pipeline/load_all.py` and the SQLite table definitions written by `pipeline/sites.py` and `pipeline/cycles.py`.

### 3.2 Methods — Architecture

The system has four stages:

```
Sources (CSV, XLSX)
        ↓
Landing (raw files, never modified)
        ↓
Standardize & Stitch (canonical schema, cycle-level joining)
        ↓
Serve (SQLite tables → Streamlit dashboard + LLM modules)
```

**Stack.** Python, Pandas, SQLAlchemy, SQLite, Streamlit, an Anthropic-API-compatible LLM client. Every component has a clear enterprise migration path: SQLite → Azure SQL or Postgres; the mocked LLM → Claude API via Azure or Bedrock; Streamlit → containerized on Azure App Service. ProAg confirmed they use Azure, and the architecture was designed to swap into that environment without redesign.

**Reproducibility.** A single command sequence rebuilds every table from raw data:

```bash
python -m pipeline.load_all     # Phase 1: raw → SQLite
python -m pipeline.sites        # Phase 2: site hierarchy + cycle trails
python -m pipeline.cycles       # Phase 3: canonical cycle model
python -m analytics.pnl         # Phase 4: P&L, hedge gains, anomalies
python -m analytics.llm_summary # Phase 5a: cycle summaries
python -m analytics.llm_anomaly # Phase 5b: anomaly explanations
streamlit run dashboard/app.py  # Phase 6: launch the dashboard
```

The codebase carries 36 tests across 5 phases (`tests/test_phase1.py` through `test_phase5.py`).

### 3.3 Methods — Entity resolution

Three reconciliation problems required dedicated logic.

**Site hierarchy (cost center → commercial site → physical barn).** The barn-to-operational-site map is direct: `nursery_intake` and `pig_flow` state it. The cost-center-to-operational-site map is inferential — we examined cost-category mix and production-phase distribution per Site A/B/C and observed that Site B has a stronger nursery-leaning profile (32.6% nursery-tagged spend vs ~20% at others), but the signal isn't strong enough for a 1:1 mapping. We document this as a finding rather than force a synthetic answer; real producer data would likely show clearer specialization.

**Packer settlement matching.** The packer file has no `Pig_Group_ID`. We match loads to cycles using two signals: date proximity (kills occur 100–130 days after nursery-to-finisher transfer, peaking at +115 days) and volume cumulation (matched loads are accumulated until the running total reaches ~95% of the cycle's transferred head count). For PG-1014, this matched 13 packer loads totaling 2,251 head against a transferred count of 2,340 — a 96% match, with the 4% gap accounted for by normal finisher mortality.

**Cost attribution.** Accounting Pig_Group_IDs in the dummy data don't overlap with production-side IDs (accounting uses PG-5xxx, production uses PG-1000–1017), so a direct ID join is impossible. Each cost event is attributed to candidate cycles by two signals: date overlap with the cycle's active window and phase match between the cost row's `Production_Phase` and the cycle's phase at that date. Costs matching both score higher; costs whose phase doesn't match score 0.3 (low but non-zero — overhead categories legitimately span phases). The final score per cost-to-cycle pair is normalized by the number of other cycles active on that same date.

This yields a measured ~5.8% attribution of any single cycle's window-period cost events. This is honest — in a year with 18 overlapping cycles, no single cycle "owns" most of the producer's bills. With real ProAg data containing fewer concurrent cycles, the attribution rate would naturally rise to 15–30%.

### 3.4 Methods — Anomaly detection

We selected five operationally meaningful, advisor-actionable features and flagged any cycle whose value deviates more than 2 standard deviations from the peer mean.

| Feature | What it captures | Why it matters |
|---|---|---|
| `pnl_per_head` | Net dollars per pig | The bottom-line metric advisors and producers actually use to compare cycles |
| `cost_per_head` | Attributed cost / placed head | When this is off, drill into the category breakdown to localize |
| `mortality_pct` | (placed − transferred) / placed | Leading operational health indicator; correlates with environmental or health events |
| `feed_cost_per_head` | Feed-category cost / placed head | Feed is 60–70% of total cost — the biggest lever in hog production |
| `nursery_days` | Days between placement and finisher transfer | Proxy for nursery-phase efficiency; deviations point to health setbacks or capacity issues |

**Why z-scores instead of fixed thresholds.** A fixed rule ("flag if mortality > 5%") would require industry-typical thresholds we don't have, and which vary across producer scale, geography, and barn type. Z-scores let the producer's own historical pattern define what "normal" looks like for *that producer*.

**Why z = 2.0.** Standard convention in statistical process control — "more unusual than 95% of cycles" under a normal distribution. Tighter (z = 3) misses too much in a small sample; looser (z = 1) flags noise.

**Features deliberately excluded.** Average carcass weight (genetics-driven, not actionable short-term); total revenue (redundant with `pnl_per_head × paid_head`); total finisher days (noisy because some cycles cut off before slaughter in our window).

### 3.5 Methods — AI integration and guardrails

The hard line: **statistics finds anomalies; the LLM describes them.** We never let the LLM decide what's anomalous, and we never let it generate numbers.

| AI feature | Input | Output |
|---|---|---|
| Anomaly explanation | A stats-flagged metric with peer context (e.g., "PG-1017 feed cost = $12.38, peer avg $2.87, z = 7.56") | 1–2 sentence narrative explaining the deviation and what to investigate |
| Cycle summary | A cycle's pre-computed P&L (revenue, costs, hedge, margin) plus peer comparison | 2–3 sentence narrative comparing the cycle to the producer's recent history |

**The pipeline a prompt traverses:**

```
Structured context dict
        ↓
Anonymize PII (producer/vendor/packer names → tokens)
        ↓
Refusal check (regulated-question pattern matching)
        ↓
LLM call (currently mocked; drop-in for real Claude/GPT)
        ↓
Detokenize response (tokens → real names)
        ↓
Output to dashboard table
```

**Four concrete privacy protections.** (1) Enterprise-contracted LLMs only — production deployment uses Claude API via Azure or AWS Bedrock under no-training, no-retention agreements. (2) Anonymization before any prompt leaves the environment — producer, vendor, and packer names are replaced with neutral tokens (`<PRODUCER_1>`, etc.) and restored after response. (3) The LLM only sees computed metrics — it never queries the database directly. (4) Hard-coded refusal patterns — regulated questions ("should I hedge?", "will prices go up?") receive scripted refusals pointing the user to a licensed advisor; refusals fire *before* any LLM call is made.

**On the mocked LLM.** For this submission, `analytics/llm_client.py` produces text from deterministic templates rather than calling a real model. The mock has the **same interface** a real Claude or GPT API would have. The anonymization, refusal patterns, and structured-prompt architecture are production-grade. Swapping to a real LLM is one config change (set `LLM_PROVIDER=claude` and an API key). We chose this for the submission to avoid API costs during development and to keep the demo reproducible offline; ProAg can deploy real LLM calls with a single setting.

### 3.6 Methods — Dashboard design

The dashboard renders the system in two role-scoped single-page views, deliberately collapsed from a multi-page architecture to reduce navigation cost for advisors during a call.

**Advisor view (single scroll):** KPI strip → alert inbox with workflow actions (acknowledge / snooze / add note) → producer rollup ranked by attention score → all-cycles table with producer filter → inline cycle detail panel with AI summary, P&L tiles, peer comparison, hedge positions, cost breakdown, and cycle-specific flags. The selected cycle in the detail panel is driven both by the row clicked in the cycles table and by a dropdown selector, with state synchronized through `st.session_state`.

**Producer view (single scroll):** KPI tiles → "your hedging" card (coverage, locked-in price, realized P&L) → soft heads-up if any of the producer's cycles have HIGH-severity flags → cycles list → inline cycle detail with summary, numbers, and the cycle's hedge position. No anomaly inbox, no peer comparison detail, no per-CWT metrics — these belong to the advisor's working surface, not the producer's portfolio readout.

The privacy boundary is enforced at the data layer: `dashboard/db.py` filters every query by producer in producer mode, and the producer view never imports the anomaly inbox component.

### 3.7 Supporting Files

The index below identifies every source file and which report section it supports. Image files and the SQLite database are excluded per CCDS guidance.

| File | Type | Purpose | Section |
|---|---|---|---|
| `pipeline/load_all.py` | Python module | Phase 1 — loads raw CSVs and XLSX into SQLite landing tables | Data |
| `pipeline/load_producer.py` | Python module | Producer-source-specific loaders (nursery, packer, hedging, accounting) | Data |
| `pipeline/load_market.py` | Python module | Market data loaders (HEM25, ZCN25, pork primals) | Data |
| `pipeline/config.py` | Python module | DB path and configuration constants | Methods 3.2 |
| `pipeline/sites.py` | Python module | Phase 2 — builds the site hierarchy and the `cycle_trail` table | Methods 3.3 |
| `pipeline/cycles.py` | Python module | Phase 3 — canonical cycle model: stitches movements, accounting, packer, hedging into one cycle object | Methods 3.3 |
| `analytics/pnl.py` | Python module | Phase 4 — computes P&L, hedge gains, and z-score anomaly flags per cycle; writes `fact_cycle_pnl`, `fact_cycle_costs`, `fact_hedge_pnl`, `fact_anomalies` | Methods 3.4, Results |
| `analytics/llm_client.py` | Python module | LLM client with anonymization, refusal patterns, and mocked dispatch | Methods 3.5 |
| `analytics/llm_summary.py` | Python module | Generates cycle narratives, writes `fact_cycle_summaries` | Methods 3.5 |
| `analytics/llm_anomaly.py` | Python module | Generates anomaly explanations, writes `fact_anomaly_explanations` | Methods 3.5 |
| `dashboard/app.py` | Python module | Streamlit entry point: sidebar role/producer selector, single-page rendering | Methods 3.6 |
| `dashboard/db.py` | Python module | Cached SQL access, producer rollup, peer comparison, producer-attribution fallback | Methods 3.6 |
| `dashboard/views.py` | Python module | Two view functions: `advisor_page` and `producer_page` | Methods 3.6 |
| `dashboard/ui.py` | Python module | Formatters, severity badges, alert workflow state, peer comparison strip | Methods 3.6 |
| `tests/test_phase1.py` to `test_phase5.py` | Python tests | 36 smoke and structural tests across the five pipeline phases | Methods (all) |
| `METHODS.md` | Markdown | Long-form engineering and analytical decision log (precursor to this report) | — |
| `README.md` | Markdown | Setup instructions, team, run commands | Appendix |

---

## 4. Results

### 4.1 Pipeline output

End-to-end execution of the seven-command pipeline produced the following on the supplied dataset:

| Metric | Value |
|---|---|
| Cycles processed | 18 (14 closed, 4 in-flight) |
| Total packer revenue | $5,771,579 |
| Total attributed costs | $722,146 |
| Total hedge P&L | −$119,539 |
| Total net P&L | $4,929,893 |
| Average margin per head | $157.19 |
| LLM cycle summaries generated | 18 |
| LLM anomaly explanations generated | 4 |
| Tests passing | 36 / 36 |

### 4.2 Anomaly detection output

Five anomalies were flagged across four features. The cluster on PG-1017 demonstrates the value of multi-feature detection: a single cycle simultaneously triggered on margin, total cost, and feed cost — a coherent pattern pointing to a feed-pricing event during this cycle's nursery window.

| Cycle | Metric | Severity | Value | Peer avg | z-score |
|---|---|---|---|---|---|
| PG-1017 | `pnl_per_head` | HIGH | $119.60 | $160.08 | −5.12 |
| PG-1017 | `cost_per_head` | HIGH | $45.13 | $20.25 | +5.57 |
| PG-1017 | `feed_cost_per_head` | HIGH | $12.38 | $2.87 | +7.56 |
| PG-1003 | `nursery_days` | MEDIUM | 47 | 62.23 | −3.16 |

In-flight cycles (PG-1008, 1010, 1012, 1013) are marked INFO until packer settlements arrive.

### 4.3 LLM-generated narratives

A representative cycle summary, generated for PG-1014:

> *PG-1014 closed with 2,431 head placed and $412,860 in packer revenue. Net margin of $163.33/head is strong versus this producer's recent cycles, with attributed costs of $25.11/head. Hedging contributed $15,006 to the result.*

A representative anomaly explanation, generated for the highest-severity flag (PG-1017 feed cost):

> *PG-1017's feed cost ran $12.38 per pig — 331.4% above this producer's typical cycle average of $2.87. The deviation suggests feed pricing during the nursery or finishing window drove the variance. Worth reviewing the delivery schedule and any feed contracts in effect during this cycle.*

These are the actual outputs of `analytics.llm_anomaly` and `analytics.llm_summary` against the dummy dataset. The text is template-generated in this submission; the prompt structure, anonymization, and refusal architecture would route identical structured inputs to a real LLM in production.

### 4.4 Dashboard

The dashboard renders the pipeline's output in two role-scoped views. Annotated screenshots follow.

**Figure 1 — Advisor portfolio view (single page).** _[SCREENSHOT: advisor home, showing KPI strip, alert inbox with the three HIGH/MEDIUM cards visible, and the producers rollup table with attention progress bars.]_

The KPI strip at the top shows portfolio-level totals; the alert inbox below provides the day's triage list with acknowledge / snooze / note actions. The producers rollup ranks accounts by an attention score (HIGH×2 + MEDIUM) so the advisor sees who needs attention most.

**Figure 2 — Cycle detail with peer comparison and hedge panel.** _[SCREENSHOT: cycle detail section for PG-1014, showing the AI summary card, four P&L tiles, peer comparison strip with delta arrow, and hedging panel with coverage / weighted strike / realized P&L plus the contracts table.]_

The peer comparison strip places this-cycle / producer-avg / all-producer-avg side by side. The hedge panel quantifies coverage and realized P&L from the hedging program — directly addressing the gap our mid-project review identified.

**Figure 3 — Producer view (single page).** _[SCREENSHOT: producer home for Demo Producer B, showing personal KPIs, the "your hedging" card spanning all their cycles, the soft heads-up note about a flagged cycle, and the cycles list.]_

The producer sees only their own cycles. No anomaly inbox, no z-scores, no per-CWT detail. The heads-up note tells them their advisor flagged a cycle for review without exposing the underlying statistical detail.

**Figure 4 — Alert workflow.** _[SCREENSHOT: a HIGH-severity alert card in the inbox with the Acknowledge / Snooze / Add note buttons visible and a saved advisor note shown.]_

Workflow state (acknowledged / snoozed / notes) is held in `st.session_state` for the demo; production deployment would persist it in the application database.

---

## 5. Discussion & Limitations

The system achieves the core objective: ingesting fragmented producer data, computing cycle-level performance and flagging anomalies, generating advisor-ready narratives, and delivering the result through a two-role dashboard. End-to-end the pipeline is reproducible from a single set of commands, all 36 tests pass, and the dashboard runs cleanly against the supplied dataset.

Several gaps and decisions warrant explicit note.

**The LLM is mocked.** `analytics/llm_client.py` produces text from deterministic templates rather than calling Claude or GPT. The anonymization, refusal patterns, and prompt structure are production-grade and the swap-in is a single config change, but the *quality* of the generated text in this submission is bounded by the templates we authored. A real LLM would produce more varied phrasing and handle edge cases the templates do not anticipate. This was a deliberate choice for cost and reproducibility, not an oversight.

**Sample size for statistics.** 18 cycles is small enough that the standard deviation across the peer set is sensitive to single outliers — PG-1017 itself influences the σ used to flag PG-1017. With real ProAg data spanning multiple years and producers, z-score detection becomes substantially more stable. We are demonstrating *the approach*, knowing the data will improve.

**Producer attribution in the dummy data.** All three demo producers ship to overlapping packer sites in overlapping date windows, so date-based matching cannot honestly assign a cycle to a specific producer. The dashboard partitions the 18 cycles across the three demo producers deterministically by cycle number (a fallback documented in `dashboard/db.py`). In production, producer ownership would come directly from each producer's own source files; the dashboard layer requires no change.

**Cost attribution rate.** The 5.8% rate we measured reflects the dummy data's evenly-distributed cost ledger across 18 overlapping cycles. This is the correct mathematical result for that input; real producer data with fewer concurrent cycles would yield 15–30%. We frame this as an honest accounting of what the data supports, not a limitation of the algorithm.

**No real authentication or persistence.** The dashboard uses a sidebar selector for role and identity in lieu of authentication, and alert workflow state is in-session only. Production deployment requires OAuth or SSO integration and a workflow-state table; both are straightforward additions to the existing architecture.

**Mobile not addressed.** The dashboard is desktop-only. Advisors are on the road and producers are at the barn; a responsive or native mobile view is worth building but was out of scope for this submission.

**Forecasting is deliberately absent.** ProAg asked about AI-assisted forecasting. We did not build it. The reason is documented in §6 (Future Work): commodity price prediction is regulated activity under Series 3 licensure and an area where LLMs hallucinate confidently. We chose to ship a smaller scope cleanly rather than a larger scope half-finished.

**Stakeholder alignment.** Every design decision was made against the test: *does this make the advisor's pre-call hour shorter and more useful?* The portfolio view, attention-ranked producer list, alert workflow, AI summaries, and hedge panel all map to specific friction points an advisor faces during prep. The producer-side view exists to give producers transparency into their own performance without exposing the statistical detail used internally — a privacy boundary that is real and enforced.

---

## 6. Future Work

The natural next steps fall into three groups.

**Production-readiness.** Wire in the real LLM (single config change to `analytics/llm_client.py`); migrate from SQLite to Azure SQL or Postgres on Azure for tenant isolation and audit logging; containerize the Streamlit app on Azure App Service; add SSO/OAuth so role and identity come from the corporate directory rather than a sidebar selector; persist alert workflow state (acknowledgments, snoozes, notes) in the application database; add row-level security at the database layer so producer-scoped access is enforced beneath the application.

**Real-data integration.** Replace the dummy dataset with one real producer's actual files to validate the entity-resolution methods. The site hierarchy, packer matching, and cost attribution all behave differently on data with cleaner producer attribution and fewer concurrent cycles; getting the real numbers will tell us where the methods need refinement.

**Forecasting (the Category-1 path).** We deliberately scoped out commodity price prediction. The safe and useful version is in-flight cycle projection: combine the producer's average cost pattern with today's futures prices to project the expected close P&L for in-flight cycles, plus sensitivity analysis at ±10% price moves. The LLM's role would be writing a brief, advisor-reviewed summary around the computed numbers. The advisor — with their Series 3 license — would decide what to recommend. This is feasible within the existing architecture with the addition of an MTM module and a projection function.

Beyond these, three smaller improvements: a mortality-vs-environment overlay (correlate the barn environmental data we already ingest with mortality events to surface ventilation or heat patterns); a downloadable PDF cycle report for the producer's accountant; and a sales-team dashboard rolling up across multiple advisors and producers.

---

## Appendix A — Runtime Environment & Dependencies

**Runtime:** Python 3.12. Tested on macOS 14 and Ubuntu 22.04. Codespace-compatible.

**Setup:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Build the data tables:**

```bash
python3 -m pipeline.load_all     # raw data → SQLite (Phase 1)
python3 -m pipeline.sites        # site hierarchy & cycle trails (Phase 2)
python3 -m pipeline.cycles       # canonical cycle model (Phase 3)
python3 -m analytics.pnl         # P&L, hedge gains, anomalies (Phase 4)
python3 -m analytics.llm_summary # cycle summaries (Phase 5a)
python3 -m analytics.llm_anomaly # anomaly explanations (Phase 5b)
```

**Run the dashboard:**

```bash
streamlit run dashboard/app.py
```

If `streamlit` is not on PATH (common in Codespaces with user-installed packages):

```bash
python3 -m streamlit run dashboard/app.py
```

**Run tests:**

```bash
python3 -m pytest tests/ -v
```

**Key dependencies:** `pandas`, `numpy`, `sqlalchemy`, `streamlit`, `openpyxl` (for XLSX market data). Full pinned list in `requirements.txt`.

**Database location:** `data/processed/proag.db` (SQLite, created by Phase 1; subsequent phases append tables).

**Data location:** `data/raw/` (not submitted; provided by ProAg).

---

## Appendix B — Switching to a real LLM

`analytics/llm_client.py` exposes a single `generate(task, context)` function. Currently the function returns template-generated text. To enable real LLM calls:

1. Set environment variable `LLM_PROVIDER=claude` (or `openai`).
2. Set `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`).
3. Uncomment the API-dispatch block in `llm_client.py` (clearly marked).

No other code changes are required. Anonymization, refusal patterns, and prompt construction all execute on the same path regardless of provider.