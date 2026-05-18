# ProAg Track 2 — Producer Analytics

A tool for ProAg advisors to centralize a hog producer's fragmented data, compute per-cycle profitability, flag operational anomalies, and generate plain-English explanations using AI.

**Course:** Track 2 — Producer Analytics  
**Client:** Professional Ag Marketing (ProAg)

---

## What this project does

A ProAg advisor manages 20-30 hog producers. Before each producer consultation, they currently spend around an hour reconciling fragmented data (accounting exports, packer settlement PDFs, hedging records, barn data) by hand. This tool reduces that to seconds: the advisor types a producer's name and sees their full cycle history, current performance, hedging coverage, and any cycles needing attention.

The tool is **advisor-facing**, not producer-facing. The producer continues to share data the way they always have. The advisor gains a unified view that improves the conversation.

---

## How it works (four stages)

```
Sources → Landing → Standardize & Stitch → Serve
```

1. **Sources** — 7 producer files (CSV) + 3 market reference files from disk.
2. **Landing** — files preserved untouched. Never modified.
3. **Standardize & Stitch** — each source cleaned, translated to a canonical schema, and joined around the production cycle.
4. **Serve** — dashboard reads from the unified database. AI modules write back plain-English explanations and summaries for the dashboard to display.

For full architectural reasoning and design decisions, see **[METHODS.md](METHODS.md)**.

---

## What the system does end-to-end

1. **Loads** raw producer data and market reference data into a unified database
2. **Infers** the site hierarchy (which barn rolls up to which commercial site to which accounting cost center)
3. **Stitches** each cycle's full lifecycle across all sources — placement, transfers, packer settlements, hedging, costs
4. **Computes** per-cycle profit and loss: revenue, attributed costs, hedge gain/loss, net margin per pig
5. **Flags** anomalies using statistics — five operationally meaningful metrics, z-score thresholds against the producer's own historical pattern
6. **Generates** plain-English explanations for each anomaly and 2-3 sentence narratives for each cycle, using a privacy-guarded AI layer
7. **Displays** all of this through a dashboard with both an advisor view and a simplified producer view

---

## Where AI is used (and where it isn't)

**The hard line: math finds, AI explains.**

Statistics is responsible for finding anomalies and computing all numbers. The AI is responsible for turning those numbers into plain-English sentences. The AI never decides what's anomalous and never generates numbers.

**Used for:**
- Generating cycle narratives ("PG-1014 closed with 2,431 head and a net margin of $162.82 per pig, strong versus this producer's recent cycles…")
- Explaining flagged anomalies ("PG-1017's feed cost ran 331% above the producer's typical cycle average. Worth reviewing the delivery schedule…")

**Deliberately not used for:**
- Computing P&L, margins, totals (deterministic math)
- Detecting anomalies (statistics)
- Predicting commodity prices (regulated activity; out of scope)
- Recommending hedges or trades (Series 3 licensed work; remains with ProAg advisors)

For the complete reasoning on AI integration, privacy, and guardrails, see **[METHODS.md](METHODS.md)**.

---

## Privacy and guardrails (summary)

Four protections layered into the AI pipeline:

1. **Enterprise-contracted LLM only** — no free public APIs in production
2. **Anonymization before prompts leave the system** — producer/vendor/packer names replaced with neutral tokens, restored after the response returns
3. **The LLM only sees pre-computed metrics** — it never queries the database directly
4. **Hard-coded refusal patterns** — regulated questions ("should I hedge?", "what will prices do?") receive scripted responses pointing back to the licensed advisor

The full guardrails design is documented in METHODS.md.

---

## Note on the AI layer

The LLM dispatch is **currently mocked** using deterministic templates. This is an explicit engineering decision for the student project:

- **Why mocked:** avoids API costs during development and makes the demo offline-reproducible.
- **Why it's still defensible:** the anonymization, refusal patterns, prompt structure, and architecture are real production-grade code. Only the model call itself is stubbed.
- **To switch to a real LLM:** one config change. The system is designed to drop in Claude via Azure or Anthropic API with no other modifications.

Privacy and guardrails (anonymization, refusal patterns) run before the LLM call regardless of whether it's mocked or real.

---

## What's not in this submission

- **Forecasting / projection of in-flight cycles.** Documented in METHODS.md as v2 scope. We chose to ship a smaller scope cleanly rather than a larger scope half-finished.
- **Real LLM API integration.** Mocked. One config change to switch on.
- **Production deployment.** Designed to be Azure-compatible (ProAg's stack); not actually deployed.

---

## Headline results from the dummy data

- **18 production cycles** tracked end-to-end (14 closed, 4 still in-flight)
- **Average net margin: $157.72 per pig** across closed cycles
- **Total revenue across closed cycles: $5,756,845**
- **4 anomalies flagged statistically** — 3 HIGH severity on one cycle, 1 MEDIUM on another
- Each anomaly receives a plain-English explanation
- Each cycle gets a 2-3 sentence narrative for advisor consumption

---

## Key document

**[METHODS.md](METHODS.md)** — the design decisions, anomaly feature selection, AI integration philosophy, privacy/guardrails approach, and forecasting roadmap. Read this for the reasoning behind every choice in the system.

---

Built as a Syracuse University capstone project for Professional Ag Marketing.
