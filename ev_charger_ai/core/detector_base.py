"""Base class + common contract for all five competitors.

Rules of the competition:
  - one instance per session (fresh state via reset(), cross-session memory
    is allowed through the object the factory returns — that is a paradigm
    feature, e.g. Agentic AI keeps station baselines)
  - observe() is called once per event, in stream order, with the shared
    FeatureState; returning a non-empty list raises alert(s)
  - the FIRST alert of a session is what gets scored
  - no lookahead, no ground-truth access at inference time
"""
from core.schema import Alert


class Detector:
    name = "base"

    def reset(self, station: str, connector: str) -> None:
        """Called at the start of every session."""
        raise NotImplementedError

    def observe(self, ev, fs) -> list:
        """ev: Event, fs: FeatureState. Return [] or [Alert, ...]."""
        raise NotImplementedError

    def end_session(self, station: str, connector: str) -> None:
        """Called after the last event (for online adaptation, optional)."""

    def alert(self, t, conf, reason, guess=""):
        return Alert(t=t, detector=self.name, confidence=conf,
                     reason=reason, fault_guess=guess)
