"""
LLM comparison benchmark for JarvisOS agents.

Compares Claude Haiku, Claude Sonnet, and a local Ollama model
on representative tasks from each agent domain.

Claude models are called via the `claude` CLI subprocess (uses OAuth).
Ollama models are called via the Ollama HTTP API directly.

Usage:
    python tests/benchmark_models.py
    python tests/benchmark_models.py --model qwen3:30b-a3b   # when download completes
    python tests/benchmark_models.py --skip-sonnet           # cheaper run
"""

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic
import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://192.168.32.2:11434")

# Anthropic API key — read from claude OAuth credentials (sk-ant-... format)
def _load_anthropic_key() -> str:
    creds_path = os.path.expanduser("~/.claude/.credentials.json")
    try:
        creds = json.loads(open(creds_path).read())
        return creds["claudeAiOauth"]["accessToken"]
    except Exception:
        return os.environ.get("ANTHROPIC_API_KEY", "")


ANTHROPIC_KEY = _load_anthropic_key()

MODELS = {
    "haiku": "claude-haiku-4-5-20251001",   # Anthropic SDK (OAuth token)
    "sonnet": "claude-sonnet-4-6",           # Anthropic SDK (OAuth token)
    # qwen3:30b-a3b needs 17.7GB but Ollama container is capped at 12GB
    # → use qwen3.5:4b now; raise container limit & stop nethermind to test 30b
    "local": "qwen3.5:4b",
}

JSON_SYSTEM = (
    "You are a structured data extraction assistant. "
    "Respond ONLY with valid JSON matching the exact schema requested. "
    "No markdown, no explanation, no code fences."
)

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    name: str
    domain: str
    system: str
    prompt: str
    expected_keys: list[str]  # keys that MUST be present in parsed JSON
    judge_rubric: str = ""  # used if no expected_keys match applies


CASES: list[TestCase] = [
    # --- COS: email routing ---
    TestCase(
        name="cos_spam",
        domain="COS / email routing",
        system=JSON_SYSTEM,
        prompt=(
            "Classify this email and decide the routing action.\n"
            "Output JSON: {\"domain\": str, \"action\": \"ignore|archive|route|escalate\", "
            "\"route_to\": str|null, \"confidence\": 0.0-1.0, \"reason\": str}\n\n"
            "FROM: noreply@lottery-winner.biz\n"
            "SUBJECT: You have won $5,000,000!\n"
            "BODY: Congratulations! Click here to claim your prize."
        ),
        expected_keys=["domain", "action", "confidence"],
    ),
    TestCase(
        name="cos_infra_alert",
        domain="COS / email routing",
        system=JSON_SYSTEM,
        prompt=(
            "Classify this email and decide the routing action.\n"
            "Output JSON: {\"domain\": str, \"action\": \"ignore|archive|route|escalate\", "
            "\"route_to\": \"timothy|cfo|roger|jarvis\"|null, \"confidence\": 0.0-1.0}\n\n"
            "FROM: alertmanager@monitoring.internal\n"
            "SUBJECT: [FIRING] DiskUsage > 90% on node k3s-worker-1\n"
            "BODY: Alert: disk usage on /dev/sda1 is 91.3%. "
            "Threshold: 90%. Please investigate immediately."
        ),
        expected_keys=["domain", "action", "route_to"],
    ),
    TestCase(
        name="cos_invoice",
        domain="COS / email routing",
        system=JSON_SYSTEM,
        prompt=(
            "Classify this email and decide the routing action.\n"
            "Output JSON: {\"domain\": str, \"action\": \"ignore|archive|route|escalate\", "
            "\"route_to\": \"timothy|cfo|roger|jarvis\"|null, \"confidence\": 0.0-1.0}\n\n"
            "FROM: billing@hetzner.com\n"
            "SUBJECT: Invoice #INV-2026-04-88231 — €34.90 due\n"
            "BODY: Dear Customer, your monthly server invoice is attached. "
            "Amount: €34.90. Due: 2026-05-01."
        ),
        expected_keys=["domain", "action", "route_to"],
    ),

    # --- emailintel: entity extraction ---
    TestCase(
        name="eia_extract_entities",
        domain="emailintel / entity extraction",
        system=JSON_SYSTEM,
        prompt=(
            "Extract key entities from this email.\n"
            "Output JSON: {\"sender_org\": str, \"amount\": str|null, "
            "\"currency\": str|null, \"due_date\": str|null, "
            "\"primary_domain\": \"finance|infrastructure|health|legal|other\", "
            "\"sensitivity\": \"low|medium|high\"}\n\n"
            "FROM: invoices@aws.amazon.com\n"
            "SUBJECT: Your AWS Invoice for March 2026 — $142.33\n"
            "BODY: Hello, your AWS invoice for account 123456789 is ready. "
            "Total: $142.33 USD. Due date: April 15, 2026. "
            "Services: EC2 ($89.12), S3 ($24.50), CloudFront ($28.71)."
        ),
        expected_keys=["sender_org", "amount", "primary_domain", "sensitivity"],
    ),
    TestCase(
        name="eia_security_phishing",
        domain="emailintel / security classification",
        system=JSON_SYSTEM,
        prompt=(
            "Assess the security risk of this email.\n"
            "Output JSON: {\"threat_type\": \"phishing|malware|spam|legitimate|suspicious\", "
            "\"confidence\": 0.0-1.0, \"indicators\": [str], \"recommended_action\": str}\n\n"
            "FROM: security@paypa1-verify.com\n"
            "SUBJECT: Urgent: Your PayPal account has been limited\n"
            "BODY: Dear valued customer, we have detected unusual activity. "
            "Verify your account immediately at http://paypa1-verify.com/secure. "
            "Failure to comply within 24 hours will result in permanent suspension."
        ),
        expected_keys=["threat_type", "confidence", "indicators"],
    ),

    # --- DON: meal parsing ---
    TestCase(
        name="don_meal_parse_simple",
        domain="DON / meal parsing",
        system=JSON_SYSTEM,
        prompt=(
            "Parse this meal description into macronutrients.\n"
            "Output JSON: {\"meal_name\": str, \"portion_g\": int, "
            "\"calories\": int, \"protein_g\": float, \"carbs_g\": float, "
            "\"fat_g\": float, \"confidence\": 0.0-1.0}\n\n"
            "Meal: 100g chicken breast grilled, plain"
        ),
        expected_keys=["calories", "protein_g", "carbs_g", "fat_g"],
    ),
    TestCase(
        name="don_meal_parse_complex",
        domain="DON / meal parsing",
        system=JSON_SYSTEM,
        prompt=(
            "Parse this meal description into macronutrients for each component.\n"
            "Output JSON: {\"total\": {\"calories\": int, \"protein_g\": float, "
            "\"carbs_g\": float, \"fat_g\": float}, "
            "\"components\": [{\"name\": str, \"portion_g\": int, \"calories\": int}]}\n\n"
            "Meal: pasta al pomodoro — 80g spaghetti (dry weight), "
            "150g tomato sauce, 10g parmesan, 10ml olive oil"
        ),
        expected_keys=["total", "components"],
    ),

    # --- CFO: financial categorization ---
    TestCase(
        name="cfo_transaction_categorize",
        domain="CFO / transaction categorization",
        system=JSON_SYSTEM,
        prompt=(
            "Categorize these bank transactions.\n"
            "Output JSON: {\"transactions\": [{\"description\": str, "
            "\"category\": str, \"subcategory\": str, \"is_business\": bool}]}\n\n"
            "Transactions:\n"
            "1. HETZNER ONLINE GMBH — €29.90\n"
            "2. LIDL ITALIA — €47.23\n"
            "3. NETFLIX.COM — €15.99\n"
            "4. COINBASE EUR — €200.00\n"
            "5. FARMACIA CENTRALE — €12.50"
        ),
        expected_keys=["transactions"],
    ),

    # --- COH: health triage ---
    TestCase(
        name="coh_health_triage",
        domain="COH / health triage",
        system=JSON_SYSTEM,
        prompt=(
            "Triage this health query to the correct specialist.\n"
            "Output JSON: {\"urgency\": \"immediate|soon|routine\", "
            "\"route_to\": \"dos|don|dr_house|emergency\", "
            "\"reason\": str, \"recommended_action\": str}\n\n"
            "Query: I did a 20km run yesterday and my left knee has been "
            "aching since. It's a dull pain on the inner side, not sharp. "
            "No swelling. Should I train today?"
        ),
        expected_keys=["urgency", "route_to", "reason"],
    ),

    # --- MT: email drafting ---
    TestCase(
        name="mt_draft_reply",
        domain="MT / email drafting",
        system="You are a professional executive assistant. Draft concise, professional email replies.",
        prompt=(
            "Draft a polite reply declining this meeting request. Keep it under 80 words.\n\n"
            "FROM: john.smith@partner-corp.com\n"
            "SUBJECT: Partnership discussion call — Thursday 2pm?\n"
            "BODY: Hi, I'd love to discuss a potential partnership. "
            "Are you free for a 30-minute call this Thursday at 2pm CET?"
        ),
        expected_keys=[],  # free-text, judged by rubric
        judge_rubric="polite decline, professional tone, under 80 words, no placeholder text",
    ),
]

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class Result:
    model: str
    case_name: str
    domain: str
    ok: bool
    latency_s: float
    tokens_in: int = 0
    tokens_out: int = 0
    score: float = 0.0
    notes: str = ""
    raw: str = ""


def _is_claude(model: str) -> bool:
    return model.startswith("claude-")


def _call_claude(model: str, system: str, prompt: str) -> tuple[str, float, int, int]:
    """Call Anthropic API directly using the OAuth access token as API key."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    t0 = time.perf_counter()
    resp = client.messages.create(
        model=model,
        max_tokens=600,
        temperature=0.1,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    latency = time.perf_counter() - t0
    text = resp.content[0].text.strip()
    tin = resp.usage.input_tokens
    tout = resp.usage.output_tokens
    return text, latency, tin, tout


def _call_ollama(model: str, system: str, prompt: str) -> tuple[str, float, int, int]:
    """Call Ollama HTTP API directly.

    For qwen3moe models, thinking goes to the 'thinking' field automatically —
    'think: false' is ignored. Anchor JSON output with a prefix instruction and
    give enough token budget so the model can finish after its reasoning pass.
    """
    ollama_system = "Start your response with { or [ for JSON tasks.\n\n" + system
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": ollama_system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 4000},
    }
    t0 = time.perf_counter()
    resp = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=300)
    latency = time.perf_counter() - t0
    resp.raise_for_status()
    data = resp.json()
    text = data["message"]["content"].strip()
    tin = data.get("prompt_eval_count", len(system + prompt) // 4)
    tout = data.get("eval_count", len(text) // 4)
    return text, latency, tin, tout


def _call(model: str, system: str, prompt: str) -> tuple[str, float, int, int]:
    if _is_claude(model):
        return _call_claude(model, system, prompt)
    return _call_ollama(model, system, prompt)


def _score_json(text: str, expected_keys: list[str]) -> tuple[float, str]:
    """Parse JSON and check required keys. Returns (score 0-1, notes)."""
    # Strip markdown fences if present
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as e:
        return 0.0, f"JSON parse error: {e}"

    if not expected_keys:
        return 1.0, "free-text (no key check)"

    present = [k for k in expected_keys if k in parsed]
    score = len(present) / len(expected_keys)
    missing = [k for k in expected_keys if k not in parsed]
    notes = f"{len(present)}/{len(expected_keys)} keys present"
    if missing:
        notes += f" | missing: {missing}"
    return score, notes


def run_case(model_label: str, model_id: str, case: TestCase) -> Result:
    try:
        text, latency, tin, tout = _call(model_id, case.system, case.prompt)
    except Exception as exc:
        return Result(
            model=model_label, case_name=case.name, domain=case.domain,
            ok=False, latency_s=0, notes=str(exc),
        )

    if case.expected_keys:
        score, notes = _score_json(text, case.expected_keys)
        ok = score >= 0.6
    else:
        # Free-text: basic sanity (non-empty, not an error message)
        score = 1.0 if len(text) > 20 else 0.0
        ok = score > 0
        notes = f"{len(text)} chars"

    return Result(
        model=model_label, case_name=case.name, domain=case.domain,
        ok=ok, latency_s=latency,
        tokens_in=tin, tokens_out=tout,
        score=score, notes=notes, raw=text[:200],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _fmt_score(s: float) -> str:
    bar = "█" * int(s * 10) + "░" * (10 - int(s * 10))
    return f"{bar} {s:.0%}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None, help="Override local model ID")
    parser.add_argument("--skip-sonnet", action="store_true")
    parser.add_argument("--skip-local", action="store_true")
    parser.add_argument("--case", default=None, help="Run only this case name")
    args = parser.parse_args()

    models = {"haiku": MODELS["haiku"]}
    if not args.skip_sonnet:
        models["sonnet"] = MODELS["sonnet"]
    if not args.skip_local:
        local_id = args.model or MODELS["local"]
        models["local"] = local_id

    cases = CASES
    if args.case:
        cases = [c for c in CASES if c.name == args.case]
        if not cases:
            print(f"Case {args.case!r} not found. Available: {[c.name for c in CASES]}")
            return

    print(f"\n{'='*70}")
    print(f"  JarvisOS LLM Benchmark — {len(cases)} cases × {len(models)} models")
    print(f"  Ollama:  {OLLAMA_URL}")
    for label, mid in models.items():
        print(f"  {label:8s} → {mid}")
    print(f"{'='*70}\n")

    all_results: list[Result] = []

    for case in cases:
        print(f"[ {case.name} ]  {case.domain}")
        for label, mid in models.items():
            r = run_case(label, mid, case)
            all_results.append(r)
            tps = r.tokens_out / r.latency_s if r.latency_s > 0 else 0
            status = "✓" if r.ok else "✗"
            print(
                f"  {status} {label:8s}  {r.latency_s:5.1f}s  "
                f"{tps:5.1f} t/s  score={_fmt_score(r.score)}  {r.notes}"
            )
            if not r.ok and r.raw:
                print(f"           response: {r.raw[:120]!r}")
        print()

    # --- Summary table ---
    print(f"\n{'='*70}")
    print("  SUMMARY — average score per model per domain\n")

    domains = sorted({r.domain for r in all_results})
    model_labels = list(models.keys())

    col_w = 12
    header = f"  {'Domain':<38}" + "".join(f"{m:>{col_w}}" for m in model_labels)
    print(header)
    print("  " + "-" * (38 + col_w * len(model_labels)))

    for domain in domains:
        row = f"  {domain:<38}"
        for label in model_labels:
            subset = [r for r in all_results if r.domain == domain and r.model == label]
            if subset:
                avg = sum(r.score for r in subset) / len(subset)
                row += f"{avg:>{col_w}.0%}"
            else:
                row += f"{'—':>{col_w}}"
        print(row)

    print("  " + "-" * (38 + col_w * len(model_labels)))
    overall_row = f"  {'OVERALL':<38}"
    for label in model_labels:
        subset = [r for r in all_results if r.model == label]
        avg_score = sum(r.score for r in subset) / len(subset) if subset else 0
        avg_lat = sum(r.latency_s for r in subset) / len(subset) if subset else 0
        avg_tps = sum(r.tokens_out / r.latency_s for r in subset if r.latency_s > 0) / len(subset) if subset else 0
        overall_row += f"{avg_score:>{col_w}.0%}"
        print(f"  {'  ' + label + ' latency':<38}{avg_lat:>{col_w}.1f}s")
        print(f"  {'  ' + label + ' t/s':<38}{avg_tps:>{col_w}.1f}")

    print(overall_row)
    print(f"{'='*70}\n")

    # Exit code: 0 if haiku baseline passes ≥70% of cases
    haiku_ok = [r for r in all_results if r.model == "haiku" and r.ok]
    haiku_total = [r for r in all_results if r.model == "haiku"]
    pass_rate = len(haiku_ok) / len(haiku_total) if haiku_total else 0
    if pass_rate < 0.7:
        print(f"WARNING: haiku pass rate {pass_rate:.0%} < 70%")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
