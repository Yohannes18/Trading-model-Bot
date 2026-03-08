from __future__ import annotations
import logging
from datetime import datetime, timezone
from ..types import SessionBehavior, SessionType
log = logging.getLogger("jeafx.session")

class SessionEngine:
    def get_session(self) -> tuple[SessionType, SessionBehavior]:
        hour = datetime.now(tz=timezone.utc).hour
        if 12 <= hour < 13:   session = SessionType.LONDON_NY_OVERLAP
        elif 7 <= hour < 12:  session = SessionType.LONDON
        elif 12 <= hour < 17: session = SessionType.NEW_YORK
        elif hour < 7 or hour >= 20: session = SessionType.ASIA
        else: session = SessionType.OFF
        behavior_map = {
            SessionType.ASIA: SessionBehavior.LIQUIDITY_BUILD,
            SessionType.LONDON: SessionBehavior.EXPANSION,
            SessionType.LONDON_NY_OVERLAP: SessionBehavior.OVERLAP,
            SessionType.NEW_YORK: SessionBehavior.CONTINUATION,
            SessionType.OFF: SessionBehavior.INACTIVE,
        }
        log.info("session=%s hour=%s", session.value, hour)
        return session, behavior_map[session]
    def is_expansion_allowed(self) -> bool:
        s, _ = self.get_session()
        return s in (SessionType.LONDON, SessionType.LONDON_NY_OVERLAP)
    def is_reversal_allowed(self) -> bool:
        s, _ = self.get_session()
        return s in (SessionType.NEW_YORK, SessionType.LONDON, SessionType.LONDON_NY_OVERLAP)
