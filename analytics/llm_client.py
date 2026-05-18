"""LLM client with privacy guardrails.

This module is the ONLY place that talks to an LLM. All other modules call
into this — that way, the privacy/anonymization logic is enforced in one place.

Current implementation: deterministic template-based mock. Designed as a
drop-in replacement for a real Claude or GPT API call. To swap in a real LLM:

    1. pip install anthropic
    2. Set ANTHROPIC_API_KEY environment variable
    3. In _call_llm(), replace the mock dispatch with:
           from anthropic import Anthropic
           client = Anthropic()
           response = client.messages.create(
               model="claude-sonnet-4-5",
               max_tokens=300,
               messages=[{"role": "user", "content": prompt}]
           )
           return response.content[0].text

The anonymization layer, prompt templates, refusal patterns, and tool-call
architecture are real production code. Only the model dispatch is mocked.
"""
import re
import hashlib


# ──────────────────────────────────────────────────────────────
# PII ANONYMIZATION
# ──────────────────────────────────────────────────────────────

# Patterns we anonymize before any prompt leaves this module
_NAME_PATTERNS = {
    "PRODUCER": [r"Demo Producer [A-Z]"],
    "VENDOR": [r"AgriFeed Co", r"VetHealth Inc", r"Midwest Transport"],
    "PACKER": [r"Tyson \(IBP\)", r"JBS", r"Smithfield", r"Seaboard"],
}


def anonymize(text):
    """Replace PII with stable tokens. Returns (anonymized_text, token_map)."""
    token_map = {}
    counter = {}
    out = text

    for entity_type, patterns in _NAME_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, out):
                real_value = match.group()
                if real_value not in token_map.values():
                    counter[entity_type] = counter.get(entity_type, 0) + 1
                    token = f"<{entity_type}_{counter[entity_type]}>"
                    token_map[token] = real_value
                    out = out.replace(real_value, token)
    return out, token_map


def detokenize(text, token_map):
    """Swap tokens back to real names. Reverse of anonymize()."""
    out = text
    for token, real_value in token_map.items():
        out = out.replace(token, real_value)
    return out


# ──────────────────────────────────────────────────────────────
# REFUSAL PATTERNS — hard-coded responses for regulated questions
# ──────────────────────────────────────────────────────────────

_REFUSAL_PATTERNS = {
    "should i hedge": (
        "Hedging recommendations come from your ProAg advisor (Series 3 "
        "licensed). I can show you current coverage and historical realized "
        "P&L, but the recommendation is theirs to make."
    ),
    "predict price": (
        "I don't forecast commodity prices. For market views, your ProAg "
        "advisor is the right person to consult."
    ),
    "what will prices do": (
        "I don't predict prices. I can show you historical ranges and "
        "current hedging coverage if useful."
    ),
}


def _check_refusal(prompt):
    """Return a refusal string if the prompt matches a hard-coded pattern."""
    lower = prompt.lower()
    for trigger, response in _REFUSAL_PATTERNS.items():
        if trigger in lower:
            return response
    return None


# ──────────────────────────────────────────────────────────────
# LLM DISPATCH (currently mocked)
# ──────────────────────────────────────────────────────────────

def _seeded_choice(seed_string, choices):
    """Pick one of `choices` deterministically based on `seed_string`.

    Same input always gives same output — so the mock is reproducible
    across runs. Replicates the variety a real LLM would produce.
    """
    h = int(hashlib.md5(seed_string.encode()).hexdigest(), 16)
    return choices[h % len(choices)]


def _mock_anomaly_response(context):
    """Generate an anomaly explanation from structured context."""
    metric = context["metric"]
    cycle_id = context["cycle_id"]
    value = context["value"]
    peer_avg = context["peer_avg"]
    z = context["z_score"]
    severity = context["severity"]

    delta_pct = abs((value - peer_avg) / peer_avg * 100) if peer_avg else 0
    direction = "above" if value > peer_avg else "below"

    if metric == "feed_cost_per_head":
        templates = [
            f"{cycle_id}'s feed cost ran ${value:.2f} per pig — {delta_pct:.1f}% {direction} this producer's typical cycle average of ${peer_avg:.2f}. The deviation suggests feed pricing during the nursery or finishing window drove the variance. Worth reviewing the delivery schedule and any feed contracts in effect during this cycle.",
            f"Feed cost per pig for {cycle_id} was ${value:.2f}, materially {direction} the peer average of ${peer_avg:.2f}. Most likely cause is commodity pricing on the corn deliveries during this cycle's active feeding window. Recommend examining the date alignment between corn futures movements and actual deliveries.",
        ]
    elif metric == "pnl_per_head":
        templates = [
            f"{cycle_id} netted ${value:.2f} per pig — {delta_pct:.1f}% {direction} this producer's recent average of ${peer_avg:.2f}. This {direction}-average result reflects the combined effect of revenue and cost variances on this cycle.",
            f"{cycle_id}'s margin came in at ${value:.2f}/head, {direction} the peer average of ${peer_avg:.2f}. Consistent with other flagged metrics on this cycle.",
        ]
    elif metric == "mortality_pct":
        templates = [
            f"Mortality on {cycle_id} reached {value:.2f}%, compared to a peer average of {peer_avg:.2f}%. Elevated mortality often correlates with health events or environmental stress during the nursery phase — review barn environmental records and health treatments around this cycle's window.",
            f"{cycle_id} recorded {value:.2f}% mortality, {direction} the typical {peer_avg:.2f}%. Worth pulling barn environment data for the affected period to see if temperature or ventilation deviations are visible.",
        ]
    elif metric == "cost_per_head":
        templates = [
            f"Total cost per head for {cycle_id} was ${value:.2f}, {delta_pct:.1f}% {direction} the producer's peer average of ${peer_avg:.2f}. The breakdown will show whether the gap is concentrated in feed, labor, or another category.",
            f"{cycle_id}'s cost per pig sits at ${value:.2f} versus an average of ${peer_avg:.2f}. Check the cost category breakdown to localize the source.",
        ]
    elif metric == "nursery_days":
        if value > peer_avg:
            templates = [
                f"{cycle_id} spent {value:.0f} days in nursery, longer than this producer's typical {peer_avg:.0f}. Extended nursery time can indicate health setbacks, undersized arrivals, or capacity holds — worth a conversation with the operations team.",
            ]
        else:
            templates = [
                f"{cycle_id} moved out of nursery faster than usual ({value:.0f} days vs typical {peer_avg:.0f}). Shorter nursery time can indicate strong early growth or earlier-than-planned transfer to finisher — confirm whether this was intentional.",
            ]
    else:
        templates = [
            f"{cycle_id}'s {metric} was {value:.2f}, {direction} the peer average of {peer_avg:.2f} (z={z:.2f}). Worth investigating the drivers.",
        ]

    return _seeded_choice(f"{cycle_id}-{metric}", templates)


def _mock_summary_response(context):
    """Generate a 2-3 sentence cycle narrative from structured context."""
    cycle_id = context["cycle_id"]
    status = context["status"]
    placed = context["placed_head"]
    mort = context["mortality_pct"]
    net_per_head = context.get("pnl_per_head")
    cost_per_head = context.get("cost_per_head")
    revenue = context.get("packer_revenue")
    hedge_pnl = context.get("hedge_pnl") or 0

    if status == "in_flight":
        return (
            f"{cycle_id} is currently in-flight with {placed:,} head placed. "
            f"Nursery mortality came in at {mort:.2f}%. Revenue and cost "
            f"attribution will close out once packer settlements arrive."
        )

    margin_word = "strong" if (net_per_head or 0) > 160 else \
                  "below-average" if (net_per_head or 0) < 150 else "in-line"

    hedge_phrase = ""
    if hedge_pnl != 0:
        hedge_phrase = (
            f" Hedging contributed ${hedge_pnl:,.0f} to the result."
        )

    return (
        f"{cycle_id} closed with {placed:,} head placed and ${revenue:,.0f} "
        f"in packer revenue. Net margin of ${net_per_head:.2f}/head is "
        f"{margin_word} versus this producer's recent cycles, with attributed "
        f"costs of ${cost_per_head:.2f}/head.{hedge_phrase}"
    )


def _call_llm(prompt_type, context):
    """Dispatch to the appropriate mock generator.

    To swap in a real LLM, replace this function with a single API call
    that takes a fully-formatted prompt string. The context dict already
    contains anonymized values, so the prompt going to the real API will
    have <PRODUCER_1>, <VENDOR_3> etc. instead of real names.
    """
    if prompt_type == "anomaly":
        return _mock_anomaly_response(context)
    elif prompt_type == "summary":
        return _mock_summary_response(context)
    else:
        raise ValueError(f"Unknown prompt type: {prompt_type}")


# ──────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────

def generate(prompt_type, context):
    """Public entry point. Handles refusals, anonymization, LLM call, detokenization.

    Args:
        prompt_type: "anomaly" or "summary"
        context: dict of structured data for the prompt

    Returns:
        str: the model's response, with PII restored to real names
    """
    # Step 1: check for hard refusal patterns in any string context value
    for v in context.values():
        if isinstance(v, str):
            refusal = _check_refusal(v)
            if refusal:
                return refusal

    # Step 2: anonymize string fields in context
    anonymized_context = {}
    full_token_map = {}
    for k, v in context.items():
        if isinstance(v, str):
            anon_v, token_map = anonymize(v)
            anonymized_context[k] = anon_v
            full_token_map.update(token_map)
        else:
            anonymized_context[k] = v

    # Step 3: call LLM (currently mocked, but the prompt would already
    # be free of PII at this point in a real implementation)
    response = _call_llm(prompt_type, anonymized_context)

    # Step 4: detokenize the response before returning
    response = detokenize(response, full_token_map)

    return response


# ──────────────────────────────────────────────────────────────
# Self-test
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("LLM Client — Self-test")
    print("=" * 60)

    # Test anonymization
    text = "Demo Producer A bought feed from AgriFeed Co and sold to Tyson (IBP)."
    anon, m = anonymize(text)
    print(f"\nAnonymization test:")
    print(f"  Original: {text}")
    print(f"  Anonymized: {anon}")
    print(f"  Token map: {m}")
    print(f"  Detokenized: {detokenize(anon, m)}")

    # Test refusal
    print(f"\nRefusal test:")
    print(f"  Q: 'Should I hedge now?'")
    print(f"  A: {_check_refusal('Should I hedge now?')}")

    # Test anomaly mock
    print(f"\nAnomaly explanation test:")
    result = generate("anomaly", {
        "cycle_id": "PG-1017",
        "metric": "feed_cost_per_head",
        "value": 58.0,
        "peer_avg": 43.0,
        "z_score": 2.8,
        "severity": "HIGH",
    })
    print(f"  {result}")

    # Test summary mock
    print(f"\nCycle summary test:")
    result = generate("summary", {
        "cycle_id": "PG-1014",
        "status": "closed",
        "placed_head": 2431,
        "mortality_pct": 3.74,
        "pnl_per_head": 156.16,
        "cost_per_head": 25.10,
        "packer_revenue": 412548.89,
        "hedge_pnl": 0,
    })
    print(f"  {result}")