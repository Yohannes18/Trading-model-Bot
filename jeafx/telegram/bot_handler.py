from __future__ import annotations

import json
import asyncio
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional
from urllib.request import Request, urlopen

from ..config import (
    CONFIRM_TIMEOUT,
    DAILY_RISK_CAP,
    MAX_OPEN_TRADES,
    PAIRS,
    RISK_PERCENT,
    SCAN_INTERVAL,
    TG_CHAT_ID,
    TG_TOKEN,
    log,
)
from engine.meta_learning_engine import MetaLearningEngine
from ..state_machine import GovernanceState, StressState, Trade, TradeSetup


class TelegramBot:
    API = "https://api.telegram.org/bot{t}/{m}"

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None, enabled: bool = True) -> None:
        self.token = token or TG_TOKEN
        self.chat_id = chat_id or TG_CHAT_ID
        self.enabled = enabled and bool(self.token)

    def _post(self, method: str, data: dict[str, object]) -> dict[str, object]:
        if not self.enabled:
            return {}
        url = self.API.format(t=self.token, m=method)
        try:
            req = Request(
                url,
                data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=10) as response:
                return json.loads(response.read())
        except Exception as exc:
            log.warning("tg_post method=%s error=%s", method, exc)
            return {}

    def send(self, text: str) -> bool:
        if not self.enabled or not self.chat_id:
            return False
        return bool(self._post("sendMessage", {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}).get("ok", False))

    def get_updates(self, offset: int = 0) -> list[dict[str, object]]:
        if not self.enabled:
            return []
        response = self._post("getUpdates", {"offset": offset, "timeout": 5, "allowed_updates": ["message"]})
        result = response.get("result", [])
        return result if isinstance(result, list) else []

    def get_chat_id(self) -> str:
        updates = self.get_updates()
        if not updates:
            return ""
        message = updates[-1].get("message")
        if not isinstance(message, dict):
            return ""
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return ""
        chat_id = chat.get("id")
        return str(chat_id) if chat_id is not None else ""

    def send_confirmation(self, trade: Trade, components: dict[str, int], stress: StressState, gov: GovernanceState) -> bool:
        setup = trade.setup
        dp = {"XAUUSD": 2, "EURUSD": 5, "GBPUSD": 5}.get(setup.pair, 5)
        direction_emoji = "🟢" if setup.direction == "BUY" else "🔴"
        bars = "█" * (setup.confidence // 10) + "░" * (10 - setup.confidence // 10)
        shadow_note = "\n👻 _SHADOW MODE — no real execution_" if setup.is_shadow else ""
        comp = "\n".join(f"   {k}: {v}" for k, v in components.items())
        message = (
            f"🔔 *SETUP FOUND — AWAITING CONFIRMATION*{shadow_note}\n\n"
            f"*{setup.pair}* {direction_emoji} `{setup.direction}`\n"
            f"`{setup.timeframe}` | {setup.session}\n\n"
            f"📊 *Confidence: {setup.confidence}/100*\n"
            f"`{bars}`\n{comp}\n\n"
            f"📍 Entry `{setup.entry:.{dp}f}` | SL `{setup.sl:.{dp}f}` | TP2 `{setup.tp2:.{dp}f}`\n"
            f"R:R `1:{setup.rr}` | Lot `{trade.lot}`\n"
            f"Stress `{stress.level.value}` | Model `{gov.status.value}`\n\n"
            f"_Reply /confirm_{setup.id[:8]} or /reject_{setup.id[:8]}_\n"
            f"⏳ Expires in {CONFIRM_TIMEOUT // 60} minutes"
        )
        return self.send(message)


    def send_confirmation_v2(self, trade: Trade, analysis, stress, gov) -> bool:
        """Rich confirmation message using full MarketAnalysis briefing."""
        setup = trade.setup
        dp = {"XAUUSD": 2, "EURUSD": 5, "GBPUSD": 5}.get(setup.pair, 5)
        direction_emoji = "🟢" if setup.direction == "BUY" else "🔴"
        shadow_note = "\n👻 _SHADOW — no real execution_" if setup.is_shadow else ""
        conf_bar = "█" * (setup.confidence // 10) + "░" * (10 - setup.confidence // 10)
        msg = (
            f"🔔 *SETUP FOUND — AWAITING CONFIRMATION*{shadow_note}\n\n"
            f"*{setup.pair}* {direction_emoji} `{setup.direction}`\n"
            f"`{setup.timeframe}` | {setup.session}\n\n"
            f"📊 *Confidence: {setup.confidence}/100* [{analysis.recommended_model.value}]\n"
            f"`{conf_bar}`\n\n"
            f"📍 Entry `{setup.entry:.{dp}f}` | SL `{setup.sl:.{dp}f}` | TP `{setup.tp2:.{dp}f}`\n"
            f"R:R `1:{setup.rr}` | Lot `{trade.lot}` | Risk `{trade.risk_pct:.1f}%`\n\n"
            f"🌊 Narrative: _{analysis.narrative_pattern.value.replace('_',' ')}_\n"
            f"   Events: `{', '.join(e.value for e in analysis.narrative.events)}`\n"
            f"   Bias: `{analysis.narrative.bias}` | Strength `{analysis.narrative.strength:.2f}`\n"
            f"   Sweep `{analysis.narrative.sweep_detected}` | Displacement `{analysis.narrative.displacement_detected}` | BOS `{analysis.narrative.bos_detected}`\n"
            f"🎯 Raid Target: `{analysis.raid_prediction.target_zone.zone_type}` | Dir `{analysis.raid_prediction.raid_direction}` | Prob `{analysis.raid_prediction.probability:.0%}` | Dist `{analysis.raid_prediction.distance_r:.1f}R`\n"
            f"🧲 Inefficiency: `{analysis.inefficiency_map.nearest_inefficiency.type if analysis.inefficiency_map.nearest_inefficiency else 'NONE'}` | Magnet `{analysis.inefficiency_map.magnet_score:.2f}`\n"
            f"🪤 Trap: `{analysis.trap_analysis.trap_probability:.0f}%` ({analysis.trap_analysis.risk_level})\n"
            f"✅ Trade Confidence: `{analysis.confidence_result.score:.1f}%` [{analysis.confidence_result.confidence_level}]\n"
            f"🧠 AMD: `{analysis.amd_phase.value}` ({analysis.amd_confidence:.0%})\n"
            f"📊 Volatility: `{analysis.volatility.regime.value}` | ATR Ratio `{analysis.volatility.atr_ratio:.2f}` | Exp `{analysis.volatility.expansion_probability:.0%}`\n"
            f"📉 Stress: `{stress.level.value}` (×{stress.risk_multiplier}) | "
            f"Model: `{gov.status.value}`\n\n"
        )
        if analysis.model_result and analysis.model_result.signals:
            msg += "✅ *Confluences*\n"
            for s in analysis.model_result.signals[:5]:
                msg += f"  • {s}\n"
            msg += "\n"
        msg += (
            f"_Reply /confirm_{setup.id[:8]} to execute_\n"
            f"_Reply /reject_{setup.id[:8]} to skip_\n"
            f"⏳ Expires in {CONFIRM_TIMEOUT // 60} minutes"
        )
        return self.send(msg)


class StatusNotifier:
    COOLDOWN = 30

    def __init__(self, bot: Optional[TelegramBot] = None) -> None:
        self._bot = bot
        self._seen: dict[str, datetime] = {}

    def bind(self, bot: TelegramBot) -> None:
        self._bot = bot

    def _ok(self, key: str) -> bool:
        if key not in self._seen:
            return True
        return (datetime.now() - self._seen[key]).total_seconds() > self.COOLDOWN * 60

    def _send(self, key: str, text: str) -> None:
        if not self._bot or not self._ok(key):
            return
        if self._bot.send(text):
            self._seen[key] = datetime.now()

    def engine_started(self) -> None:
        self._send(
            "start",
            (
                "⚡ *JeaFX v5 — ONLINE*\n"
                f"Pairs: {', '.join(PAIRS)}\n"
                f"Risk per trade: {RISK_PERCENT}% | Daily cap: {DAILY_RISK_CAP}%\n"
                f"Open cap: {MAX_OPEN_TRADES} | Scan: {SCAN_INTERVAL}s\n\n"
                "_Waiting for kill zone… I'll message you when London opens._"
            ),
        )

    def going_to_sleep(self, wake_time: str, duration: str) -> None:
        self._send(
            "sleep",
            (
                f"😴 *Off-Session — Sleeping*\n\n"
                f"⏰ Next session: *{wake_time} UTC*\n"
                f"🕐 Resuming in: *{duration}*\n\n"
                f"_I'll message you when London opens._"
            ),
        )

    def session_opening(self, session: str) -> None:
        from datetime import datetime, timezone
        now = datetime.now(tz=timezone.utc).strftime("%H:%M UTC")
        self._send(
            f"sess_{session}",
            (
                f"🌅 *{session} — Scanner Active*\n\n"
                f"⏰ {now}\n"
                f"🔍 Scanning {', '.join(PAIRS)} every {SCAN_INTERVAL}s\n\n"
                "_High-confidence setups will require your confirmation._"
            ),
        )

    def stress_update(self, level: str, expectancy: float, winrate: float,
                      drawdown: float, multiplier: float, triggers: list) -> None:
        em = {"NONE": "✅", "MILD": "🟡", "MODERATE": "🟠", "SEVERE": "🔴"}.get(level, "⚪")
        text = (
            f"{em} *Stress Level: {level}*\n\n"
            f"Rolling expectancy: `{expectancy:+.2f}R`\n"
            f"Win rate: `{winrate:.0%}`\n"
            f"Drawdown: `{drawdown:.1%}`\n"
        )
        if level != "NONE":
            text += f"Risk scaled to `{multiplier:.0%}`\n"
        if triggers:
            text += "\n⚠️ " + " · ".join(triggers)
        self._send(f"stress_{level}", text)

    def governance_update(self, status: str, reason: str) -> None:
        em = {"ACTIVE": "✅", "DISABLED": "🚫", "SHADOW": "👻"}.get(status, "⚪")
        self._send(f"gov_{status}", f"{em} *Model Status: {status}*\n\n{reason}")

    def blackout_active(self, reason: str) -> None:
        self._send(
            f"bo_{reason[:30]}",
            f"🚫 *News Blackout*\n\n{reason}\n\n_Scanner paused._"
        )

    def blackout_clear(self) -> None:
        self._send("bo_clear", "✅ *Blackout Lifted* — Scanning resumed.")

    def trade_executed(self, pair: str, direction: str, entry: float,
                       sl: float, tp: float, lot: float, rr: float,
                       trade_id: str, is_shadow: bool) -> None:
        dp = {"XAUUSD": 2, "EURUSD": 5, "GBPUSD": 5}.get(pair, 5)
        shadow = "\n👻 _SHADOW_" if is_shadow else ""
        self._send(
            f"exec_{trade_id}",
            (
                f"✅ *Trade Executed*{shadow}\n\n"
                f"`{pair}` `{direction}` @ `{entry:.{dp}f}`\n"
                f"SL: `{sl:.{dp}f}` | TP: `{tp:.{dp}f}`\n"
                f"Lot: `{lot}` | R:R `1:{rr}`"
            ),
        )

    def trade_closed(self, pair: str, direction: str, entry: float,
                     close_price: float, result_r: float, trade_id: str,
                     is_shadow: bool) -> None:
        em = "✅" if result_r > 0 else "❌"
        dp = {"XAUUSD": 2, "EURUSD": 5, "GBPUSD": 5}.get(pair, 5)
        shadow = " [SHADOW]" if is_shadow else ""
        self._send(
            f"close_{trade_id}",
            (
                f"{em} *Trade Closed — {pair}*{shadow}\n\n"
                f"Result: *{result_r:+.2f}R*\n"
                f"Entry: `{entry:.{dp}f}` → Exit: `{close_price:.{dp}f}`"
            ),
        )


class CommandListener:
    def __init__(self, bot: TelegramBot) -> None:
        self._bot = bot
        self._offset = 0
        self._pending: dict[str, TradeSetup] = {}
        self._callbacks: dict[str, Callable[[bool], None]] = {}
        self._processed: set[str] = set()
        # Injected by main.py after build so commands can query live state
        self._db: Any = None
        self._stress_engine: Any = None
        self._governance_engine: Any = None
        self._mt5: Any = None

    def bind_state(self, db: Any, stress: Any, governance: Any, mt5: Any) -> None:
        self._db = db
        self._stress_engine = stress
        self._governance_engine = governance
        self._mt5 = mt5

    def register(self, trade: TradeSetup, callback: Callable[[bool], None]) -> None:
        short_id = trade.id[:8]
        self._pending[short_id] = trade
        self._callbacks[short_id] = callback

    def unregister(self, trade_id: str) -> None:
        short_id = trade_id[:8]
        self._pending.pop(short_id, None)
        self._callbacks.pop(short_id, None)

    def poll(self) -> None:
        updates = self._bot.get_updates(self._offset)
        for upd in updates:
            update_id = upd.get("update_id")
            if not isinstance(update_id, int):
                continue
            self._offset = update_id + 1
            message = upd.get("message")
            if not isinstance(message, dict):
                continue
            msg: dict[str, Any] = message
            raw_chat = msg.get("chat")
            chat: dict[str, Any] = raw_chat if isinstance(raw_chat, dict) else {}
            sender_chat_id = str(chat.get("id", ""))
            configured_chat_id = str(self._bot.chat_id or "")
            if configured_chat_id and sender_chat_id and sender_chat_id != configured_chat_id:
                continue
            text = str(msg.get("text", "")).strip()

            if text.startswith("/confirm_"):
                short = text.split("_", 1)[1][:8]
                if short in self._processed:
                    continue
                self._processed.add(short)
                callback = self._callbacks.pop(short, None)
                self._pending.pop(short, None)
                if callback:
                    callback(True)
                    self._bot.send(f"✅ Trade `{short}` confirmed — executing now…")

            elif text.startswith("/reject_"):
                short = text.split("_", 1)[1][:8]
                if short in self._processed:
                    continue
                self._processed.add(short)
                callback = self._callbacks.pop(short, None)
                self._pending.pop(short, None)
                if callback:
                    callback(False)
                    self._bot.send(f"❌ Trade `{short}` rejected.")

            elif text in ("/status", "/s"):
                self._cmd_status()

            elif text in ("/trades", "/t"):
                self._cmd_trades()

            elif text in ("/help", "/h", "/start"):
                self._cmd_help()

    def _cmd_status(self) -> None:
        if not self._db or not self._stress_engine or not self._mt5:
            self._bot.send("⚠️ Status not available yet — engine still starting.")
            return
        try:
            from datetime import datetime, timezone
            equity = self._mt5.get_equity()
            stress = self._stress_engine.evaluate(equity)
            gov    = self._governance_engine.evaluate(stress)
            sl_em  = {"NONE": "✅", "MILD": "🟡", "MODERATE": "🟠", "SEVERE": "🔴"}.get(stress.level.value, "⚪")
            gv_em  = {"ACTIVE": "✅", "DISABLED": "🚫", "SHADOW": "👻"}.get(gov.status.value, "⚪")
            now    = datetime.now(tz=timezone.utc).strftime("%H:%M UTC")
            meta = MetaLearningEngine()
            meta_status = meta.status()
            weights_raw = meta_status.get("model_weights", {}) if isinstance(meta_status, dict) else {}
            samples_raw = meta_status.get("samples_per_model", {}) if isinstance(meta_status, dict) else {}
            weights: dict[str, object] = weights_raw if isinstance(weights_raw, dict) else {}
            samples: dict[str, object] = samples_raw if isinstance(samples_raw, dict) else {}
            last_update = str(meta_status.get("last_update", "")) if isinstance(meta_status, dict) else ""
            meta_state = str(meta_status.get("meta_state", "warming_up")) if isinstance(meta_status, dict) else "warming_up"

            def _to_int(value: object, default: int = 0) -> int:
                try:
                    return int(float(str(value)))
                except (TypeError, ValueError):
                    return default

            def _to_float(value: object, default: float = 0.0) -> float:
                try:
                    return float(str(value))
                except (TypeError, ValueError):
                    return default

            total_samples = sum(_to_int(v, 0) for v in samples.values())
            reversal_weight = _to_float(weights.get("reversal_model", 1.0), 1.0)
            continuation_weight = _to_float(weights.get("continuation_model", 1.0), 1.0)
            raid_weight = _to_float(weights.get("raid_model", 1.0), 1.0)
            reversal_samples = _to_int(samples.get("reversal_model", 0), 0)
            continuation_samples = _to_int(samples.get("continuation_model", 0), 0)
            raid_samples = _to_int(samples.get("raid_model", 0), 0)

            self._bot.send(
                f"📊 *JeaFX Status* — {now}\n\n"
                f"Model:    {gv_em} `{gov.status.value}`\n"
                f"Stress:   {sl_em} `{stress.level.value}` (×{stress.risk_multiplier})\n"
                f"Expect:   `{stress.rolling_expectancy:+.2f}R`\n"
                f"Win rate: `{stress.rolling_winrate:.0%}`\n"
                f"DD:       `{stress.drawdown:.1%}`\n\n"
                f"Equity:      `${equity:,.0f}`\n"
                f"Risk today:  `{self._db.get_today_risk():.1f}% / {DAILY_RISK_CAP}%`\n"
                f"Open trades: `{self._db.get_open_trade_count()} / {MAX_OPEN_TRADES}`\n"
                + (f"\n⚠️ {gov.reason}" if gov.reason else "")
                + "\n\n*META LEARNING*\n"
                + "━━━━━━━━━━━━━━━━━━\n"
                + f"State: `{meta_state}`\n"
                + f"Last Update: `{last_update or 'N/A'}`\n"
                + f"Samples: `{total_samples} trades`\n\n"
                + "Model Weights\n"
                + f"Reversal: `{reversal_weight:.2f}` ({reversal_samples})\n"
                + f"Continuation: `{continuation_weight:.2f}` ({continuation_samples})\n"
                + f"Raid: `{raid_weight:.2f}` ({raid_samples})"
            )
        except Exception as exc:
            self._bot.send(f"⚠️ Status error: {exc}")

    def _cmd_trades(self) -> None:
        if not self._db:
            self._bot.send("⚠️ Database not available yet."); return
        try:
            trades = self._db.get_recent_trades(5)
            if not trades:
                self._bot.send("📋 No trades recorded yet."); return
            lines = ["📋 *Last 5 Trades*\n"]
            for t in trades:
                r = t.get("result_r")
                em = "✅" if r and float(r) > 0 else "❌" if r and float(r) < 0 else "⏳"
                state = t.get("trade_state", "?")
                result = f"`{float(r):+.2f}R`" if r is not None else f"`{state}`"
                shadow = " 👻" if t.get("is_shadow") else ""
                lines.append(f"{em} {t.get('pair')} {t.get('direction')} {result}{shadow}")
            self._bot.send("\n".join(lines))
        except Exception as exc:
            self._bot.send(f"⚠️ Trades error: {exc}")

    def _cmd_help(self) -> None:
        self._bot.send(
            "🤖 *JeaFX Commands*\n\n"
            "/status — engine health, stress, risk\n"
            "/trades — last 5 trades\n\n"
            "When a setup is found:\n"
            "`/confirm_XXXXXXXX` — execute the trade\n"
            "`/reject_XXXXXXXX` — skip the trade\n\n"
            "_Session: London 07-12 · NY 12-17 UTC_"
        )

    def run(self, interval: int = 3) -> None:
        while True:
            try:
                self.poll()
            except Exception as exc:
                log.debug("cmd_poll_error %s", exc)
            time.sleep(interval)

    async def run_async(self, interval: int = 3) -> None:
        while True:
            try:
                self.poll()
            except Exception as exc:
                log.debug("cmd_poll_error %s", exc)
            await asyncio.sleep(interval)
