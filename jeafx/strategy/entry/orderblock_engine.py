from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
log = logging.getLogger("jeafx.ob")
EXP_MULT=1.5

@dataclass
class OrderBlock:
    high:float; low:float; direction:str; quality:float; candle_idx:int; description:str
    @property
    def midpoint(self): return round((self.high+self.low)/2,2)

class OrderBlockEngine:
    def find_order_blocks(self,candles,direction) -> list[OrderBlock]:
        if len(candles)<20: return []
        atr=sum(c.high-c.low for c in candles[-14:])/14
        blocks=self._demand(candles,atr) if direction=="BUY" else self._supply(candles,atr)
        blocks.sort(key=lambda b:(b.quality,b.candle_idx),reverse=True)
        return blocks[:3]
    def price_in_block(self,price,block): return block.low<=price<=block.high
    def _demand(self,c,atr):
        bs=[]
        for i in range(len(c)-10,len(c)-2):
            if c[i].close>=c[i].open: continue
            exp=max(c[i+1:i+4],key=lambda x:x.close-x.open,default=None)
            if not exp or (exp.close-exp.open)<atr*EXP_MULT: continue
            if not(c[i].low<=c[-1].close<=c[i].high): continue
            q=min((exp.close-exp.open)/(atr*2),1.0)
            bs.append(OrderBlock(round(c[i].high,2),round(c[i].low,2),"BUY",round(q,2),i,f"Demand OB {c[i].low:.2f}-{c[i].high:.2f}"))
        return bs
    def _supply(self,c,atr):
        bs=[]
        for i in range(len(c)-10,len(c)-2):
            if c[i].close<=c[i].open: continue
            exp=min(c[i+1:i+4],key=lambda x:x.open-x.close,default=None)
            if not exp or (exp.open-exp.close)<atr*EXP_MULT: continue
            if not(c[i].low<=c[-1].close<=c[i].high): continue
            q=min((exp.open-exp.close)/(atr*2),1.0)
            bs.append(OrderBlock(round(c[i].high,2),round(c[i].low,2),"SELL",round(q,2),i,f"Supply OB {c[i].low:.2f}-{c[i].high:.2f}"))
        return bs
