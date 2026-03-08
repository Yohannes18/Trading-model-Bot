# Quantara v2 Hybrid Model

Institutional-style, multi-model trading engine with strict risk governance, competitive model selection, and adaptive meta-learning.

This README is designed to be the single source of truth for understanding, running, and operating the system.

---

## 1) What Quantara Is

Quantara is an event-driven trading engine that analyzes market structure, liquidity behavior, and macro context, then selects the best trade model through **model competition**.

Core goals:
- Find high-quality setups through layered market intelligence.
- Avoid overtrading through hard risk and ambiguity gates.
- Adapt model preference slowly via guarded meta-learning.
- Operate with production-style observability and operational controls.

---

## 2) Final Locked Decision Pipeline

This is the official pipeline order used by the engine:

1. Session Engine  
2. AMD Phase Detector  
3. Volatility Expansion Engine  
4. Liquidity Regime Engine  
5. Narrative Engine  
6. Liquidity Heatmap Engine  
7. Liquidity Map Engine  
8. Liquidity Raid Predictor  
9. Market Inefficiency Engine (IME)  
10. Trap Detector  
11. Macro Narrative Engine  
12. Displacement Engine  
13. Liquidity Magnet Engine  
14. Model Competition  
15. Confidence (per-model)  
16. Risk + Governance Gate  
17. Execution Engine  
18. Position Monitor  
19. Meta-Learning Update

Why this matters:
- Every layer adds a distinct signal family.
- Selection happens only after full context is assembled.
- Risk/governance is always downstream of strategy and cannot be bypassed.

---

## 3) Competitive Model Architecture (How Decisions Are Made)

Quantara runs multiple strategy models on the same market snapshot:
- Reversal model
- Continuation (Expansion) model
- Liquidity raid (Liquidity trap) model
- No-trade fallback

Each model computes confidence independently.

### Selection rules
1. Validate each model:
   - Confidence >= configured threshold
   - RR >= configured minimum
   - SL within limits (XAUUSD hard cap)
2. Rank valid models by confidence.
3. Ambiguity protection:
   - If top two valid models are too close, return NO_TRADE.
4. If no model qualifies, return NO_TRADE.

This avoids global-confidence bias and handles multi-interpretation markets correctly.

---

## 4) Hard Risk Rules (Non-negotiable)

The engine enforces the following:
- Minimum RR required: `>= 3`
- Preferred RR at high confidence: `>= 4`
- XAUUSD max stop-loss: `150 pips`
- Model confidence gate: below threshold => `NO_TRADE`
- Daily risk cap and max open trades are enforced by risk/governance layer

These are designed to protect capital first and strategy second.

---

## 5) Meta-Learning (Guarded Adaptation)

Meta-learning updates model preference weights from closed-trade outcomes.

Guardrails:
- Minimum trades per model before adaptation: `50`
- Weight bounds: `0.5` to `1.5`
- Conservative learning rate (small updates)
- Freeze behavior under adverse drawdown condition
- Risk/governance rules always have priority over learning

Confidence adjustment uses the bounded formula:

`adjusted_confidence = confidence * (1 + (weight - 1) * 0.25)`

This prevents runaway bias while still allowing gradual adaptation.

---

## 6) Operational Modes

Quantara supports three effective operational states through governance/execution behavior:

- **ACTIVE**: real execution (orders placed, monitored, and managed)
- **SHADOW**: paper-style decision logging (no live execution)
- **DISABLED**: analysis can run, trading blocked by governance

Recommended rollout:
1. Shadow period
2. Small live size
3. Gradual scale-up

---

## 7) Project Structure (High-Level)

- `quantara/` — application runtime (engine loop, API, execution, strategy, risk, governance)
- `engine/` — institutional intelligence and meta-learning modules
- `scheduler/` — scheduled maintenance/update tasks (meta updates)
- `config/` — runtime parameters and model weights
- `tests/` — regression and intelligence-layer tests
- `deploy/windows/` — Windows production helper scripts
- `docs/` — operations and architecture documents

---

## 8) Requirements

- Python 3.11+ (project currently tested in 3.13 venv)
- Windows production target (this repo is currently documented for Windows-first operations)
- Broker/platform connectivity for live execution (MT5 when not in simulation)

---

## 9) Quick Start (Windows)

### A) First-time setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If `requirements.txt` is not fully maintained in your branch, install missing runtime deps as needed:

```powershell
pip install fastapi uvicorn python-dotenv
```

### B) One-cycle smoke test (safe)

```powershell
.\.venv\Scripts\python.exe -m quantara.main --test --sim-only --no-telegram
```

### C) Full loop in simulation mode

```powershell
.\.venv\Scripts\python.exe -m quantara.main --all --sim-only --no-telegram
```

### D) API mode (monitoring)

```powershell
.\.venv\Scripts\python.exe -m quantara.main --api --sim-only --no-telegram
```

---

## 10) Configuration

Primary runtime controls are in:
- `config/trading_parameters.yaml`
- `config/model_weights.yaml`
- `.env`

Important parameters to know:
- `confidence_threshold`
- `model_confidence_threshold`
- `model_rr_min`
- `model_ambiguity_delta`
- `max_xau_sl_pips`
- daily risk and open trade limits (from config/env)

Change only intentionally and always re-test after edits.

---

## 11) Monitoring Endpoints

When API mode is running, key endpoints include:

- `/livez`
- `/readyz`
- `/health`
- `/stress`
- `/governance`
- `/meta`
- `/telemetry`

Additional detailed telemetry routes are available under `/telemetry/...` and meta status under `/meta/status`.

### Daily checks

- `risk_used_today`
- open positions/trades
- governance status (`ACTIVE/SHADOW/DISABLED`)
- model weights and sample counts
- readiness failure reasons (if `/readyz` returns NOT_READY)

---

## 12) Windows Production Operation

Use scripts in `deploy/windows/`:
- `install_task.ps1` — install engine startup task
- `uninstall_task.ps1` — remove startup task
- `install_log_cleanup_task.ps1` — schedule log cleanup
- `rotate_logs.ps1` — manual/automated log rotation

Runbook:
- `docs/PRODUCTION_RUNBOOK.md`

---

## 13) Testing

Run targeted tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_intelligence_layers.py -q
```

Run full suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

---

## 14) Typical Runtime Output (Briefing Concept)

Each cycle generates a market briefing with:
- session + AMD + volatility + liquidity regime
- raid target + inefficiency/trap context
- model competition scores
- selected model or no-trade reason
- action readiness and confidence

This is the primary human-readable decision artifact.

---

## 15) Safety Notes

- Never skip staged rollout (shadow -> small live -> scale).
- Do not remove ambiguity/risk guards to increase trade count.
- Keep secrets in `.env`, not in code.
- Reconcile execution state before live operations.

---

## 16) Final Reality Check

Even with strong architecture, outcomes remain probabilistic.

Healthy target behavior (not guarantees):
- Win rate roughly in the 40–55% range
- RR focused around 3–4
- Positive expectancy through disciplined filtering and risk enforcement

The edge comes from process consistency, not prediction certainty.
