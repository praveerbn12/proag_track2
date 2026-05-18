# Methods & Reasoning — Track 2 Producer Analytics

**Team:** Praveer, Jayesh, Roshni  
**Audience:** ProAg, faculty reviewer  
**Purpose:** Document the engineering and analytical decisions behind this project. Where we made design choices, why we made them, and what we deliberately did not build.

---

## 1. What this project does (one paragraph)

We built an internal tool for ProAg advisors. It ingests a hog producer's fragmented data sources (accounting, packer settlements, hedging records, barn data), unifies them around the production cycle, computes per-cycle profitability and operational metrics, flags anomalies statistically, and uses an LLM to generate plain-English explanations and cycle narratives. The advisor uses this tool during their producer consultations. The producer never logs in directly.

---

## 2. Architecture overview

Four stages, kept deliberately simple:

```
Sources (CSV, XLSX)
        ↓
Landing (raw files, never modified)
        ↓
Standardize & Stitch (canonical schema, cycle-level joining)
        ↓
Serve (SQLite tables → Streamlit dashboard + LLM modules)
```

**Stack:** Python, Pandas, SQLite, Streamlit, Anthropic-compatible LLM client (currently mocked). Deliberately minimal — every component is replaceable with its enterprise equivalent (Snowflake, dbt, Next.js, Claude via Azure or Bedrock) without architectural changes.

**Why this stack for the prototype:** runs on any laptop, no infrastructure dependencies, no API costs during development, reproducible from a single command (`python -m pipeline.load_all` rebuilds everything from raw data).

---

## 3. Solving the data fragmentation problem

ProAg told us early: the dummy data uses different naming conventions across sources intentionally — to mirror how real producer data looks. We treat reconciling this as the core intellectual contribution, not a side task.

### The hierarchy we inferred

Cade's email guided us to a 3-level hierarchy:

```
Cost Center (accounting layer)         Site A, B, C
       ↑ rolls up to
Commercial Site (packer layer)          Summer Creek, Riverside, Warbler, Hejlik
       ↑ rolls up to
Physical Barn (operational layer)       Nursery North/South, Finisher East/West
```

### How we inferred each level

| Level | Method | Confidence |
|---|---|---|
| Barn → Operational Site | Direct extraction from `nursery_intake` and `pig_flow` — the data states it | 1.0 |
| Cycle production trail | Direct join on `Pig_Group_ID` across nursery_intake → pig_flow | 1.0 |
| Producer ↔ Packer Site | Data-driven analysis of volume distribution per producer | High (descriptive) |
| Cost Center → Operational | Profile-based — examined cost category mix and production-phase distribution per Site A/B/C | Lower (inferential) |

Honest finding: cost centers in the dummy data do not cleanly map to specific physical sites. Site B shows the strongest "nursery-leaning" cost profile (32.6% of its spend tagged Nursery vs ~20% at other sites), but the signal isn't strong enough for a 1:1 mapping. **We document this as a limitation rather than force a fake answer** — real producer data would likely show clearer specialization.

### Packer settlement matching

The packer file has no Pig_Group_ID column. We had to figure out which loads belong to which cycle. The matcher uses two signals:

1. **Date proximity** — kills should occur 100-130 days after the cycle's nursery-to-finisher transfer date. Peak match weight at +115 days. Confidence falls off linearly outside that window.
2. **Volume cumulation** — we accumulate matched loads until total head reaches ~95% of the cycle's transferred head count, then stop.

For PG-1014 (transferred 2,340 head on April 11), the matcher found 13 packer loads totaling 2,251 head — a 96% match. The 4% gap accounts for finisher-phase mortality, which is normal.

### Cost attribution (the hardest piece)

Accounting Pig_Group_IDs in the dummy data don't overlap with production-side IDs at all (accounting has PG-5xxx range, production uses PG-1000–1017). A direct ID join is impossible.

Our approach uses two signals to attribute each cost event to a cycle with a confidence score:

1. **Date overlap** — was the cost dated within the cycle's active window (placement → final kill)?
2. **Phase match** — does the cost row's `Production_Phase` match where the cycle was at that date (Nursery before transfer, Finishing after)?

Costs that match both phase and date get a higher score. Costs whose phase doesn't match get 0.3 (low but non-zero — overhead categories legitimately span phases). The final score is divided by the number of other cycles also active on that date — so a feed bill from a week when 3 cycles are simultaneously in nursery only gets ~33% attribution to each.

**Result:** ~5.8% of any single cycle's window costs attribute to that cycle. This is honest — in a year with 18 overlapping cycles, no single cycle "owns" most of the producer's bills. In real ProAg data with fewer concurrent cycles, the attribution rate would naturally rise to 15-30%.

---

## 4. Anomaly detection — feature selection

For our z-score-based anomaly detection (Phase 4), we picked five features. Each one is operationally meaningful, advisor-actionable, and computable cleanly from our canonical data.

### The five features

| Feature | What it captures | Why it matters |
|---|---|---|
| `pnl_per_head` | Net dollars per pig | The bottom-line metric advisors and producers actually use to compare cycles |
| `cost_per_head` | Attributed cost / placed head | When this is off, drill into the category breakdown to localize |
| `mortality_pct` | (placed − transferred) / placed | Leading operational health indicator; correlates with environmental or health events |
| `feed_cost_per_head` | Feed-category attributed cost / placed head | Feed is 60-70% of total cost — the biggest lever in hog production |
| `nursery_days` | Days between placement and finisher transfer | Proxy for nursery-phase efficiency; deviations point to health setbacks or capacity issues |

### Why z-scores instead of fixed thresholds

A fixed threshold ("flag if mortality > 5%") would require us to know industry-typical mortality for hog operations of this size. We don't, and it varies meaningfully across producer scale, geography, and barn type. Z-scores let the producer's own historical pattern define what "normal" looks like for *that producer*. That's both more accurate and more defensible.

### Why z = 2.0 as the threshold

z = 2.0 means "more unusual than 95% of cycles" under a normal distribution. Tighter (z = 3) misses too much in a small sample. Looser (z = 1) flags too much noise. Standard convention in statistical process control.

### Features we deliberately did not include

- **Average carcass weight** — mostly determined by genetics and target slaughter weight; not actionable in the short term.
- **Total revenue** — already captured implicitly via `pnl_per_head × paid_head`; adding it would create correlated alerts.
- **Days to market (total finisher days)** — would be useful but our data window cuts off some cycles before slaughter, making the metric noisy for the in-flight set.

### Honest limitation

With only 18 cycles in the dummy data, z-score-based detection is jumpy. A single unusual cycle (PG-1017) skews the standard deviation for all the others. With real ProAg data spanning multiple years across multiple producers, the same logic becomes substantially more reliable. We are demonstrating *the approach*, knowing the data will improve.

---

## 5. AI integration — what the LLM does and doesn't do

### The hard line: math finds, AI explains

Statistics (z-scores in Phase 4) is responsible for *finding* anomalies. The LLM is responsible for *describing* them in plain English. We never let the LLM decide what's anomalous, and we never let the LLM generate numbers.

This division matters because LLMs are excellent at language and unreliable at numbers. By keeping them on the language side and using deterministic Python for all math, we get the advantages of AI without its failure modes.

### Where AI is used

| Feature | Input to AI | Output |
|---|---|---|
| **Anomaly explanation** | A stats-flagged metric (e.g., "PG-1017 feed cost = $12.38, peer avg $2.87, z = 7.56") | 1-2 sentences describing the deviation and what to investigate |
| **Cycle summary** | A cycle's pre-computed P&L (revenue, costs, hedge, margin) | 2-3 sentences narrating the cycle's outcome and comparing to peer cycles |

### Where AI is deliberately not used

| Task | Why we don't use AI | What we use instead |
|---|---|---|
| Computing P&L, margins, totals | LLMs hallucinate numbers | Deterministic SQL and Python (Phase 4) |
| Joining data across tables | Reliability over creativity | SQL with confidence-scored attribution |
| Detecting anomalies | Math is more interpretable than ML | Z-scores |
| Predicting hog prices | Regulated activity; LLMs hallucinate confidently | Don't do it — out of scope |
| Recommending hedges or trades | Series 3 licensed activity | ProAg advisors retain this |
| Forecasting next cycle's outcome | Out of scope for this submission; planned for v2 | See README roadmap |

### Prompt design

Every LLM call uses the same architecture:

```
Structured context dict
        ↓
Anonymize PII (producer/vendor/packer names → tokens)
        ↓
Refusal check (does the prompt match a regulated-question pattern?)
        ↓
LLM call (currently mocked; drop-in for real Claude/GPT)
        ↓
Detokenize response (tokens → real names)
        ↓
Output to dashboard table
```

---

## 6. Privacy and guardrails

The professor's mid-project feedback flagged this as needing more depth. Here is our position.

### The honest framing

For an LLM to write *"Group PG-1003 finished with $14.28 net margin per head,"* it must receive those numbers in its prompt. We cannot keep all data away from the LLM and still have it write about the operation. The right question is not *how do we hide everything?* but rather **how do we make sure what the LLM does see is handled safely?**

### Four concrete protections

**1. Enterprise-contracted LLMs only.**  
For production, we would use Claude API via Azure or AWS Bedrock under enterprise data-use terms — contractual no-training, no-retention agreements. No free public APIs.

**2. Anonymization before prompts leave our environment.**  
Producer names, vendor names, and packer names are replaced with neutral tokens (`<PRODUCER_1>`, `<VENDOR_1>`, etc.) before any prompt would be sent. The LLM never sees real identities. Tokens are swapped back only after the response returns to our system. Even in a worst-case provider breach, the leaked data would be anonymous.

**3. The LLM only sees computed metrics.**  
It never queries our database directly. It calls predefined functions that return only the small handful of numbers needed for the sentence being written. The full QuickBooks export and packer settlement details never reach the LLM.

**4. Hard-coded refusal patterns.**  
Regulated questions (*"should I hedge?"*, *"what will prices do?"*, *"compare me to other producers"*) receive scripted responses pointing the user back to a licensed advisor. These refusals fire *before* any LLM call is made.

### Additional safeguards in the architecture

- The LLM client is the *only* module in the codebase that would call an external API. Every other module calls *into* the client. This makes privacy logic enforceable in one place.
- All prompts and responses can be logged (when a real LLM is wired in) with user and producer identifiers, providing a forensic trail.
- For client-facing output (anything reaching the producer), advisor review is required as a workflow step. We frame this as a feature, not a limitation.

### On the mocked LLM

For this submission, the LLM dispatch is mocked using deterministic templates. This is an explicit engineering decision, not a missing piece:

- The mock has the **same interface** a real Claude or GPT API would have.
- The anonymization, refusal patterns, and tool-call architecture are real production-grade code.
- Swapping in a real LLM is a single change in `analytics/llm_client.py` (uncomment one block, set an environment variable).

We chose this for the student project to (a) avoid API costs and (b) make the demo reproducible offline. ProAg can deploy real LLM calls with one config change.

---

## 7. Hosting and security posture

ProAg confirmed they use Azure. Our architecture is Azure-compatible without modification:

- **Database**: SQLite locally for the prototype → Azure SQL Database or Postgres on Azure for production.
- **LLM**: Mocked locally → Azure OpenAI Service (or Claude via Azure Marketplace) with enterprise data terms.
- **App**: Streamlit locally → containerized on Azure App Service or Azure Container Apps.
- **Tenant isolation**: producer-scoped database access enforced via row-level security at the database layer, not the application layer.
- **Audit**: every read on producer data logged with user, role, query, and result count.

---

## 8. Forecasting — out of scope for v1, documented for v2

ProAg asked about AI-assisted forecasting. We did not build it in this submission. Here is what we would build, and why we are leaving it for v2:

### What we would not do
Predict commodity prices (hog futures, corn). This is regulated work under Series 3, and LLMs hallucinate confidently on financial predictions. ProAg's analysts already do this well.

### What we would do
Three Category-1 (safe) features:

1. **Project the in-flight cycle's expected close** based on the producer's average cost pattern and today's futures prices. Pure arithmetic, not prediction.
2. **Show current exposure** — head unhedged, contract month coverage, historical price ranges.
3. **Sensitivity analysis** — what if prices move ±10%? Apply to the projection.

The AI's role would be writing a brief, advisor-reviewed summary around these computed numbers. The advisor — with their Series 3 license and market view — would decide what to recommend.

### Why not now
Implementing this safely requires careful prompt design and additional anomaly handling for in-flight cycles. We chose to ship a smaller scope cleanly rather than a larger scope half-finished.

---

## 9. What this submission demonstrates

- A complete data pipeline ingesting fragmented producer data and unifying it around the production cycle
- Confidence-scored entity resolution for ambiguous data (site mappings, cost attribution)
- Honest accounting for what we can and cannot infer (e.g., 5.8% cost attribution rate is *correct*, not a bug)
- Statistical anomaly detection on five operationally meaningful features
- AI integration with a clear contract: math finds, AI explains
- Privacy and guardrail architecture suitable for enterprise deployment
- A clean separation between architecture (general) and implementation (commodity-specific) — the same design extends to cattle or crops with new domain logic but identical infrastructure

---

## 10. Honest limitations

- **18 cycles is a small sample.** Z-scores are jumpy at this scale; ML approaches would overfit. Statistics is the right choice now, not a permanent decision.
- **Cost attribution depends heavily on real data quality.** Our 5.8% rate reflects the dummy data's evenly-distributed cost structure. Real ProAg data will likely produce different rates.
- **Forecasting and producer-facing dashboard are not in this submission.** Both are documented as v2 work.
- **The LLM is mocked.** Real deployment requires uncommenting one block and adding an API key.
