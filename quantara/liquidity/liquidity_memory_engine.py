from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class _CandleLike(Protocol):
	high: float
	low: float


class LiquidityMemoryEngine:
	def __init__(self) -> None:
		self._last_target: dict[str, object] = {
			"target": "NONE",
			"side": "NONE",
			"score": 0.5,
			"price": 0.0,
		}

	def update(self, candles_d1: Sequence[_CandleLike], current_price: float) -> dict[str, object]:
		if candles_d1 and len(candles_d1) >= 2:
			y = candles_d1[-2]
			if current_price > y.high:
				self._last_target = {
					"target": "Yesterday High",
					"side": "BUY",
					"score": 0.95,
					"price": float(y.high),
				}
			elif current_price < y.low:
				self._last_target = {
					"target": "Yesterday Low",
					"side": "SELL",
					"score": 0.95,
					"price": float(y.low),
				}
			else:
				up_dist = abs(float(y.high) - current_price)
				down_dist = abs(current_price - float(y.low))
				if up_dist <= down_dist:
					self._last_target = {
						"target": "Yesterday High",
						"side": "BUY",
						"score": 0.8,
						"price": float(y.high),
					}
				else:
					self._last_target = {
						"target": "Yesterday Low",
						"side": "SELL",
						"score": 0.8,
						"price": float(y.low),
					}
		return self._last_target

	def latest(self) -> dict[str, object]:
		return self._last_target
