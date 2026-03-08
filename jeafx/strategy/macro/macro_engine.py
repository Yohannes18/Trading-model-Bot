from __future__ import annotations
import json, logging, time, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional
from urllib.request import Request, urlopen
from ..types import MacroBias
log = logging.getLogger("jeafx.macro")
_cache: dict[str, tuple[str, float]] = {}

def _fetch(url: str, ttl_min: int = 30) -> Optional[str]:
    now = time.time()
    if url in _cache:
        data, ts = _cache[url]
        if now - ts < ttl_min * 60:
            return data
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as r:
            data = r.read().decode("utf-8", errors="ignore")
        _cache[url] = (data, now)
        return data
    except Exception as exc:
        log.debug("macro_fetch error=%s", exc)
        cached = _cache.get(url)
        return cached[0] if cached else None

class MacroEngine:
    HAWKISH = ["hot","beat","strong","hawkish","hike","surged","above","higher","upside"]
    DOVISH  = ["miss","weak","dovish","cut","below","lower","soft","decline","downside"]
    def evaluate(self) -> MacroBias:
        news = self._news_bias()
        cal  = self._calendar_bias()
        bias = cal if cal != MacroBias.NEUTRAL else news
        log.info("macro_bias=%s", bias.value)
        return bias
    def _news_bias(self) -> MacroBias:
        feeds = ["https://feeds.reuters.com/reuters/businessNews","https://www.forexlive.com/feed/news/"]
        bull = 0; bear = 0
        kws = ["gold","xau","dollar","usd","fed","treasury","yields","cpi","nfp"]
        for url in feeds:
            raw = _fetch(url, 20)
            if not raw: continue
            try:
                root = ET.fromstring(raw)
                for item in root.findall(".//item")[:15]:
                    title = (item.findtext("title") or "").lower()
                    if not any(k in title for k in kws): continue
                    for w in self.HAWKISH:
                        if w in title: bear += 1
                    for w in self.DOVISH:
                        if w in title: bull += 1
            except Exception: continue
        if bull > bear+1: return MacroBias.BULLISH_GOLD
        if bear > bull+1: return MacroBias.BEARISH_GOLD
        return MacroBias.NEUTRAL
    def _calendar_bias(self) -> MacroBias:
        raw = _fetch("https://nfs.faireconomy.media/ff_calendar_thisweek.json", 60)
        if not raw: return MacroBias.NEUTRAL
        try: events = json.loads(raw)
        except Exception: return MacroBias.NEUTRAL
        now = datetime.now(tz=timezone.utc); today = now.date()
        hawk = 0; dove = 0
        for e in events:
            if e.get("country","").upper() not in ("USD","US") or e.get("impact","") != "High": continue
            try: t = datetime.strptime(e["date"],"%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
            except Exception: continue
            if t.date() != today: continue
            if abs((now - t.replace(tzinfo=timezone.utc)).total_seconds()) / 3600 > 3: continue
            actual = e.get("actual",""); forecast = e.get("forecast","")
            if actual and forecast:
                try:
                    def _n(s): return float(s.replace("%","").replace("K","e3").replace("M","e6").strip())
                    if _n(actual) > _n(forecast): hawk += 2
                    elif _n(actual) < _n(forecast): dove += 2
                except Exception: pass
        if hawk > dove: return MacroBias.BEARISH_GOLD
        if dove > hawk: return MacroBias.BULLISH_GOLD
        return MacroBias.NEUTRAL
