from __future__ import annotations
import logging
from ..types import LiquidityBias, LiquidityLevel
log = logging.getLogger("jeafx.heatmap")

class LiquidityHeatmap:
    def score_levels(self, buy_side, sell_side, current_price):
        buy_total  = sum(l.score for l in buy_side)
        sell_total = sum(l.score for l in sell_side)
        ta = sorted([l for l in sell_side if l.price > current_price], key=lambda x: x.price)
        tb = sorted([l for l in buy_side  if l.price < current_price], key=lambda x: x.price, reverse=True)
        bias = LiquidityBias.NEUTRAL
        if buy_total > sell_total*1.3:   bias = LiquidityBias.BUY_SIDE
        elif sell_total > buy_total*1.3: bias = LiquidityBias.SELL_SIDE
        return {"buy_total_score":buy_total,"sell_total_score":sell_total,"bias":bias,
                "next_buy_target":ta[0] if ta else None,"next_sell_target":tb[0] if tb else None}
    def tp_before_liquidity(self, direction, entry, levels, buffer=3.0):
        if direction=="BUY":
            t=[l for l in levels if l.price>entry]; t.sort(key=lambda x:x.price)
            return round(t[0].price-buffer,2) if t else 0.0
        t=[l for l in levels if l.price<entry]; t.sort(key=lambda x:x.price,reverse=True)
        return round(t[0].price+buffer,2) if t else 0.0
    def format_heatmap(self, buy_side, sell_side, bias):
        lines=["LIQUIDITY HEATMAP","","Sell-Side (above)"]
        for l in sell_side[:5]: lines.append(f"  {l.price:.2f}  ({l.level_type})  Score:{l.score}")
        lines+=["","Buy-Side (below)"]
        for l in buy_side[:5]:  lines.append(f"  {l.price:.2f}  ({l.level_type})  Score:{l.score}")
        lines+=["",f"Bias: {bias.value.replace('_',' ')}"]
        return "\n".join(lines)
