#!/usr/bin/env python3
"""
Live feeder (S3b) — cykliczny refresh katalogu pod Studio / CLI.

  - threading.Event stop (graceful)
  - atexit + stop() z join
  - fail budget (domyślnie 3) → auto-stop
  - callback po udanym refresh (np. log)

Nie importuje UI; przyjmuje callable refresh() → dict.
"""
from __future__ import annotations

import atexit
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("cynober.feeder")


RefreshFn = Callable[[], Dict[str, Any]]


@dataclass
class FeederStats:
    started_at: float = 0.0
    stopped_at: float = 0.0
    cycles: int = 0
    successes: int = 0
    failures: int = 0
    last_error: str = ""
    last_ok_at: float = 0.0
    last_version: int = 0
    last_info: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "cycles": self.cycles,
            "successes": self.successes,
            "failures": self.failures,
            "last_error": self.last_error,
            "last_ok_at": self.last_ok_at,
            "last_version": self.last_version,
            "last_info": dict(self.last_info),
            "uptime_s": (
                (self.stopped_at or time.time()) - self.started_at
                if self.started_at
                else 0.0
            ),
        }


class LiveFeeder:
    """Background refresh loop with graceful shutdown."""

    def __init__(
        self,
        refresh_fn: RefreshFn,
        *,
        interval_sec: float = 900.0,
        max_fails: int = 3,
        name: str = "live-feeder",
        refresh_first: bool = False,
    ):
        if interval_sec < 1.0:
            raise ValueError("interval_sec must be >= 1")
        self.refresh_fn = refresh_fn
        self.interval_sec = float(interval_sec)
        self.max_fails = int(max_fails)
        self.name = name
        self.refresh_first = bool(refresh_first)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.stats = FeederStats()
        self._atexit_registered = False

    @property
    def running(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive() and not self._stop.is_set()

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self.stats = FeederStats(started_at=time.time())
            self._thread = threading.Thread(
                target=self._loop,
                name=self.name,
                daemon=False,
            )
            self._thread.start()
            if not self._atexit_registered:
                atexit.register(self.stop)
                self._atexit_registered = True
            log.info(
                "%s started interval=%.1fs max_fails=%d",
                self.name,
                self.interval_sec,
                self.max_fails,
            )

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._stop.set()
            t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=timeout)
        self.stats.stopped_at = time.time()
        log.info("%s stopped cycles=%d ok=%d fail=%d", self.name, self.stats.cycles, self.stats.successes, self.stats.failures)

    def status(self) -> dict:
        return {
            "running": self.running,
            "interval_sec": self.interval_sec,
            "max_fails": self.max_fails,
            "name": self.name,
            "stats": self.stats.as_dict(),
        }

    def _loop(self) -> None:
        fail_streak = 0
        if self.refresh_first:
            if not self._one_cycle():
                fail_streak += 1
            else:
                fail_streak = 0

        while not self._stop.is_set():
            # interruptible sleep
            if self._stop.wait(timeout=self.interval_sec):
                break
            ok = self._one_cycle()
            if ok:
                fail_streak = 0
            else:
                fail_streak += 1
                if fail_streak >= self.max_fails:
                    log.error(
                        "%s giving up after %d consecutive failures",
                        self.name,
                        fail_streak,
                    )
                    self._stop.set()
                    break

    def _one_cycle(self) -> bool:
        self.stats.cycles += 1
        try:
            info = self.refresh_fn() or {}
            self.stats.successes += 1
            self.stats.last_ok_at = time.time()
            self.stats.last_error = ""
            self.stats.last_info = dict(info) if isinstance(info, dict) else {}
            self.stats.last_version = int(
                info.get("version") or self.stats.last_version
            )
            log.info(
                "%s refresh ok version=%s prop_ms=%s",
                self.name,
                info.get("version"),
                info.get("prop_ms"),
            )
            return True
        except Exception as e:
            self.stats.failures += 1
            self.stats.last_error = str(e)[:300]
            log.exception("%s refresh failed: %s", self.name, e)
            return False
