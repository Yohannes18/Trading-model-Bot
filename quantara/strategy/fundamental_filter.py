from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.request import Request, urlopen

from ..config import BLACKOUT_MINUTES, Impact, PAIRS, Sentiment, log


@dataclass
class EconomicEvent:
    title: str
    currency: str
    impact: Impact
    event_time: datetime
    forecast: str = ""
    previous: str = ""

    @property
    def minutes_away(self) -> float:
        return (self.event_time - datetime.now(tz=timezone.utc)).total_seconds() / 60


@dataclass
class NewsHeadline:
    title: str
    source: str
    sentiment: Sentiment
    published: datetime


@dataclass
class CentralBankBias:
    bank: str
    currency: str
    stance: str
    rate: str
    summary: str


@dataclass
class FundamentalContext:
    events: list[EconomicEvent] = field(default_factory=list)
    imminent_events: list[EconomicEvent] = field(default_factory=list)
    headlines: list[NewsHeadline] = field(default_factory=list)
    cb_biases: list[CentralBankBias] = field(default_factory=list)
    overall_sentiment: dict[str, Sentiment] = field(default_factory=dict)
    blackout_active: bool = False
    blackout_reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def fund_score(self, pair: str, direction: str) -> int:
        score = 0
        sent = self.overall_sentiment.get(pair, Sentiment.NEUTRAL)
        if direction == "BUY" and sent == Sentiment.BULLISH:
            score += 4
        if direction == "SELL" and sent == Sentiment.BEARISH:
            score += 4
        if direction == "BUY" and sent == Sentiment.BEARISH:
            score -= 4
        if direction == "SELL" and sent == Sentiment.BULLISH:
            score -= 4
        for cb in self.cb_biases:
            if cb.currency == "USD":
                if direction == "SELL" and cb.stance == "HAWKISH":
                    score += 2
                if direction == "BUY" and cb.stance == "DOVISH":
                    score += 2
        if not self.imminent_events:
            score += 2
        return max(-10, min(10, score))


class FundamentalFilter:
    CB_STANCES: list[CentralBankBias] = [
        CentralBankBias(
            "Federal Reserve (Fed)",
            "USD",
            "HAWKISH",
            "4.25–4.50%",
            "On hold; data-dependent. 2 cuts priced for 2025.",
        ),
        CentralBankBias(
            "European Central Bank",
            "EUR",
            "DOVISH",
            "3.00%",
            "Cutting cycle underway. EUR bearish medium-term.",
        ),
        CentralBankBias(
            "Bank of England (BOE)",
            "GBP",
            "NEUTRAL",
            "4.75%",
            "Sticky services inflation keeping BOE cautious.",
        ),
    ]

    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, float]] = {}

    def get_context(self) -> FundamentalContext:
        ctx = FundamentalContext(cb_biases=self.CB_STANCES)
        ctx.events = self._ff_events()
        ctx.headlines = self._headlines()
        ctx.overall_sentiment = self._sentiment(ctx.headlines)
        ctx.imminent_events = [
            e for e in ctx.events if e.impact == Impact.HIGH and 0 <= e.minutes_away <= BLACKOUT_MINUTES
        ]
        ctx.blackout_active = bool(ctx.imminent_events)
        if ctx.blackout_active:
            ev = ctx.imminent_events[0]
            ctx.blackout_reason = f"{ev.title} ({ev.currency}) in {ev.minutes_away:.0f}min"
        return ctx

    def _cached_fetch(self, url: str, ttl_min: int) -> Optional[str]:
        now = time.time()
        if url in self._cache:
            data, ts = self._cache[url]
            if now - ts < ttl_min * 60:
                return data
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=12) as response:
                data = response.read().decode("utf-8", errors="ignore")
            self._cache[url] = (data, now)
            return data
        except Exception as exc:
            log.debug("fetch %s: %s", url, exc)
            if url in self._cache:
                return self._cache[url][0]
            return None

    def _ff_events(self) -> list[EconomicEvent]:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        raw = self._cached_fetch(url, 30)
        if not raw:
            return []
        events: list[EconomicEvent] = []
        try:
            for e in json.loads(raw):
                if e.get("impact", "") not in ("High", "Medium"):
                    continue
                try:
                    event_time = datetime.strptime(e["date"], "%Y-%m-%dT%H:%M:%S%z")
                    event_time = event_time.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                events.append(
                    EconomicEvent(
                        title=e.get("title", ""),
                        currency=e.get("country", ""),
                        impact=Impact.HIGH if e.get("impact") == "High" else Impact.MEDIUM,
                        event_time=event_time,
                        forecast=e.get("forecast", ""),
                        previous=e.get("previous", ""),
                    )
                )
        except Exception as exc:
            log.debug("FF parse: %s", exc)
        log.info("ForexFactory events=%s", len(events))
        return events

    def _headlines(self) -> list[NewsHeadline]:
        feeds = [
            ("https://www.forexlive.com/feed/news/", "ForexLive"),
            ("https://feeds.reuters.com/reuters/businessNews", "Reuters"),
        ]
        headlines: list[NewsHeadline] = []
        keywords_bull = ["strong", "beat", "surge", "rise", "hawkish", "hot"]
        keywords_bear = ["weak", "miss", "fall", "decline", "dovish", "soft", "cut"]
        for url, src in feeds:
            raw = self._cached_fetch(url, 15)
            if not raw:
                continue
            try:
                root = ET.fromstring(raw)
                for item in root.findall(".//item")[:10]:
                    title = (item.findtext("title") or "").strip()
                    if not title:
                        continue
                    tl = title.lower()
                    sentiment = Sentiment.NEUTRAL
                    if any(k in tl for k in keywords_bull):
                        sentiment = Sentiment.BULLISH
                    if any(k in tl for k in keywords_bear):
                        sentiment = Sentiment.BEARISH
                    headlines.append(
                        NewsHeadline(
                            title=title,
                            source=src,
                            sentiment=sentiment,
                            published=datetime.now(tz=timezone.utc),
                        )
                    )
            except Exception:
                continue
        log.info("News headlines=%s", len(headlines))
        return headlines

    def _sentiment(self, headlines: list[NewsHeadline]) -> dict[str, Sentiment]:
        counts = {p: {Sentiment.BULLISH: 0, Sentiment.BEARISH: 0} for p in PAIRS}
        pair_kw: dict[str, list[str]] = {
            "XAUUSD": ["gold", "xau"],
            "EURUSD": ["euro", "eur"],
            "GBPUSD": ["pound", "gbp", "sterling"],
        }
        for headline in headlines:
            title_lower = headline.title.lower()
            for pair, kws in pair_kw.items():
                if any(k in title_lower for k in kws):
                    counts[pair][headline.sentiment] = counts[pair].get(headline.sentiment, 0) + 1
        result: dict[str, Sentiment] = {}
        for pair, cnt in counts.items():
            bull = cnt[Sentiment.BULLISH]
            bear = cnt[Sentiment.BEARISH]
            if bull > bear:
                result[pair] = Sentiment.BULLISH
            elif bear > bull:
                result[pair] = Sentiment.BEARISH
            else:
                result[pair] = Sentiment.NEUTRAL
        return result
