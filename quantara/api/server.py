from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..database.db_manager import DatabaseManager
from ..engine import in_kill_zone, session_name
from ..execution.mt5_executor import MT5Executor
from ..governance.governance_engine import GovernanceEngine
from ..strategy.fundamental_filter import FundamentalFilter
from ..strategy.analysis_engine import AnalysisEngine
from ..strategy.sessions.session_engine import SessionEngine
from ..stress.stress_engine import StressEngine
from ..config import DAILY_RISK_CAP
from engine.meta_learning_engine import MetaLearningEngine
from engine.narrative_engine import NarrativeEngineV2
from engine.volatility_engine import VolatilityExpansionEngine


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def create_app(
    db: DatabaseManager,
    mt5: MT5Executor,
    stress_engine: StressEngine,
    governance_engine: GovernanceEngine,
    started_at: datetime,
):
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse

    app = FastAPI(title="Quantara")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def _load_signals() -> list[dict[str, Any]]:
        signal_file = Path("signals/signals.json")
        try:
            return json.loads(signal_file.read_text()) if signal_file.exists() else []
        except Exception:
            return []

    @app.get("/signals")
    def signals(min_score: int = 70, direction: str | None = None) -> dict[str, list[dict[str, Any]]]:
        sigs = _load_signals()
        if direction:
            sigs = [s for s in sigs if s.get("direction") == direction]
        sigs = [s for s in sigs if int(s.get("confidence", s.get("score", 0))) >= min_score]
        return {"signals": sigs[:30]}

    @app.get("/trades")
    def trades(limit: int = 20, shadow: bool = False) -> dict[str, list[dict[str, object]]]:
        return {"trades": db.get_recent_trades(limit, shadow)}

    @app.get("/performance")
    def performance() -> dict[str, object]:
        trades_data = db.get_closed_trades(100)
        if not trades_data:
            return {"total": 0, "win_rate": 0, "expectancy": 0, "total_r": 0}
        wins = [t for t in trades_data if _to_float(t.get("result_r"), 0.0) > 0]
        rs = [_to_float(t.get("result_r"), 0.0) for t in trades_data if t.get("result_r") is not None]
        return {
            "total": len(trades_data),
            "wins": len(wins),
            "losses": len(trades_data) - len(wins),
            "win_rate": round(len(wins) / len(trades_data), 3) if trades_data else 0,
            "expectancy": round(sum(rs) / len(rs), 3) if rs else 0,
            "total_r": round(sum(rs), 2),
        }

    @app.get("/stress")
    def stress() -> dict[str, object]:
        equity = mt5.get_equity()
        stress_state = stress_engine.evaluate(equity)
        return {
            "level": stress_state.level.value,
            "risk_multiplier": stress_state.risk_multiplier,
            "rolling_expectancy": stress_state.rolling_expectancy,
            "rolling_winrate": stress_state.rolling_winrate,
            "drawdown": stress_state.drawdown,
            "triggers": stress_state.triggers,
        }

    @app.get("/governance")
    def governance() -> dict[str, object]:
        equity = mt5.get_equity()
        stress_state = stress_engine.evaluate(equity)
        state = governance_engine.evaluate(stress_state)
        return {
            "status": state.status.value,
            "can_trade": state.can_trade,
            "severe_count_ytd": state.severe_count_ytd,
            "lock_until": state.lock_until.isoformat() if state.lock_until else None,
            "shadow_trades": state.shadow_trades,
            "reason": state.reason,
        }

    @app.get("/session")
    def session() -> dict[str, object]:
        hour = datetime.now(tz=timezone.utc).hour
        sessions = {
            "london": {"active": 6 <= hour < 12, "label": "London", "start": "06:00", "end": "12:00"},
            "ny": {"active": 12 <= hour < 17, "label": "New York", "start": "12:00", "end": "17:00"},
            "overlap": {"active": 12 <= hour < 13, "label": "Overlap", "start": "12:00", "end": "13:00"},
            "asian": {"active": 20 <= hour or hour < 1, "label": "Asian", "start": "20:00", "end": "07:00"},
        }
        return {"sessions": sessions, "in_kill_zone": in_kill_zone(), "session_name": session_name()}

    @app.get("/health")
    def health() -> dict[str, object]:
        stress_state = stress_engine.evaluate(mt5.get_equity())
        gov_state = governance_engine.evaluate(stress_state)
        return {
            "engine_status": "RUNNING",
            "mt5_status": "CONNECTED" if mt5.is_healthy() else "DEGRADED",
            "stress_level": stress_state.level.value,
            "governance_state": gov_state.status.value,
            "open_positions": len(mt5.list_open_positions()),
            "risk_used_today": db.get_today_risk(),
            "uptime_seconds": int((datetime.now(tz=timezone.utc) - started_at).total_seconds()),
        }

    @app.get("/livez")
    def livez() -> dict[str, str]:
        return {"status": "LIVE"}

    def _readiness_payload() -> tuple[bool, dict[str, object]]:
        stress_state = stress_engine.evaluate(mt5.get_equity())
        gov_state = governance_engine.evaluate(stress_state)
        reasons: list[str] = []

        mt5_healthy = mt5.is_healthy()
        if not mt5_healthy:
            reasons.append("mt5_unhealthy")

        reconciliation_ok = mt5.reconciliation_ok()
        if not reconciliation_ok:
            reasons.append("reconciliation_failed")

        governance_enabled = gov_state.status.value != "DISABLED"
        if not governance_enabled:
            reasons.append("governance_disabled")

        risk_used_today = db.get_today_risk()
        risk_within_cap = risk_used_today < DAILY_RISK_CAP
        if not risk_within_cap:
            reasons.append("daily_risk_cap_reached")

        ready = (
            mt5_healthy
            and reconciliation_ok
            and governance_enabled
            and risk_within_cap
        )
        payload = {
            "status": "READY" if ready else "NOT_READY",
            "checks": {
                "mt5_healthy": mt5_healthy,
                "reconciliation_ok": reconciliation_ok,
                "governance_enabled": governance_enabled,
                "risk_within_cap": risk_within_cap,
            },
            "risk_used_today": risk_used_today,
            "daily_risk_cap": DAILY_RISK_CAP,
            "governance_status": gov_state.status.value,
            "reasons": reasons,
        }
        return ready, payload

    @app.get("/readyz")
    def readyz() -> Any:
        ready, payload = _readiness_payload()
        if not ready:
            return JSONResponse(status_code=503, content=payload)
        return payload

    @app.get("/readiness")
    def readiness() -> Any:
        return readyz()

    @app.get("/fundamental")
    def fundamental() -> Any:
        try:
            ctx = FundamentalFilter().get_context()
            return {
                "risk_label": "BLACKOUT" if ctx.blackout_active else "NORMAL",
                "blackout_active": ctx.blackout_active,
                "blackout_reason": ctx.blackout_reason,
                "upcoming_events": [
                    {
                        "title": e.title,
                        "currency": e.currency,
                        "impact": e.impact.value,
                        "time_utc": e.event_time.strftime("%H:%M"),
                        "minutes_away": round(e.minutes_away, 1),
                        "forecast": e.forecast,
                        "previous": e.previous,
                    }
                    for e in ctx.events[:8]
                ],
                "cb_biases": [
                    {
                        "bank": cb.bank,
                        "currency": cb.currency,
                        "stance": cb.stance,
                        "rate": cb.rate,
                        "summary": cb.summary,
                    }
                    for cb in ctx.cb_biases
                ],
                "overall_sentiment": {k: v.value for k, v in ctx.overall_sentiment.items()},
                "top_headlines": [
                    {
                        "title": h.title,
                        "source": h.source,
                        "sentiment": h.sentiment.value,
                        "age_min": round((datetime.now(tz=timezone.utc) - h.published).total_seconds() / 60),
                    }
                    for h in ctx.headlines[:10]
                ],
            }
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/stats")
    def stats() -> dict[str, object]:
        closed = db.get_closed_trades(100)
        rs = [_to_float(t.get("result_r"), 0.0) for t in closed if t.get("result_r") is not None]
        wins = sum(1 for r in rs if r > 0)
        return {
            "total": len(closed),
            "wins": wins,
            "losses": len(closed) - wins,
            "win_rate": round(wins / len(closed), 3) if closed else 0,
            "avg_score": round(sum(_to_float(t.get("confidence"), 0.0) for t in closed) / len(closed)) if closed else 0,
            "buy_count": sum(1 for t in closed if t.get("direction") == "BUY"),
            "sell_count": sum(1 for t in closed if t.get("direction") == "SELL"),
            "expectancy": round(sum(rs) / len(rs), 3) if rs else 0,
        }

    @app.get("/blackout")
    def blackout() -> dict[str, object]:
        blackout_file = Path("signals/blackout.json")
        if blackout_file.exists():
            try:
                return json.loads(blackout_file.read_text())
            except Exception:
                pass
        return {"active": False, "reason": ""}

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        async def gen():
            last = None
            while True:
                sigs = _load_signals()
                if sigs and sigs[0].get("id") != last:
                    last = sigs[0].get("id")
                    yield f"data: {json.dumps(sigs[0])}\n\n"
                await asyncio.sleep(5)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/telemetry/volatility")
    def volatility_telemetry(pair: str = "XAUUSD", timeframe: str = "M30") -> Any:
        try:
            candles = mt5.get_candles(pair, timeframe, 300)
            session, _ = SessionEngine().get_session()
            vol = VolatilityExpansionEngine().analyze(candles, session)
            return {
                "regime": vol.regime.value,
                "atr": vol.atr,
                "atr_ratio": vol.atr_ratio,
                "range_ratio": vol.range_ratio,
                "expansion_probability": vol.expansion_probability,
            }
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/telemetry/narrative")
    def narrative_telemetry(pair: str = "XAUUSD", timeframe: str = "M30") -> Any:
        try:
            candles = mt5.get_candles(pair, timeframe, 300)
            session, _ = SessionEngine().get_session()
            narrative = NarrativeEngineV2().analyze(candles, session)
            return {
                "events": [e.value for e in narrative.events],
                "bias": narrative.bias,
                "strength": narrative.strength,
                "sweep_detected": narrative.sweep_detected,
                "displacement_detected": narrative.displacement_detected,
                "bos_detected": narrative.bos_detected,
                "inducement_detected": narrative.inducement_detected,
            }
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/telemetry/liquidity-raid")
    def liquidity_raid_telemetry(pair: str = "XAUUSD") -> Any:
        try:
            candles_m30 = mt5.get_candles(pair, "M30", 300)
            candles_h1 = mt5.get_candles(pair, "H1", 180)
            candles_h4 = mt5.get_candles(pair, "H4", 100)
            candles_d1 = mt5.get_candles(pair, "D1", 80)
            analysis = AnalysisEngine().analyze(candles_m30, candles_h1, candles_h4, candles_d1, pair, timeframe=timeframe)
            raid = analysis.raid_prediction
            return {
                "target_zone": raid.target_zone.zone_type,
                "direction": raid.raid_direction,
                "probability": raid.probability,
                "distance_r": raid.distance_r,
                "path_clear": raid.path_clear,
                "time_window": raid.estimated_time_window,
            }
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/meta/status")
    def meta_status() -> Any:
        try:
            meta = MetaLearningEngine()
            return meta.status()
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/meta")
    def meta_alias() -> Any:
        return meta_status()

    @app.get("/telemetry")
    def telemetry_overview(pair: str = "XAUUSD", timeframe: str = "M30") -> Any:
        try:
            return {
                "volatility": volatility_telemetry(pair=pair, timeframe=timeframe),
                "narrative": narrative_telemetry(pair=pair, timeframe=timeframe),
                "liquidity_raid": liquidity_raid_telemetry(pair=pair),
            }
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    return app


def run_api_server(
    db: DatabaseManager,
    mt5: MT5Executor,
    stress_engine: StressEngine,
    governance_engine: GovernanceEngine,
    host: str,
    port: int,
    started_at: datetime,
) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("uvicorn not installed") from exc

    app = create_app(db, mt5, stress_engine, governance_engine, started_at)
    uvicorn.run(app, host=host, port=port, log_level="warning")
