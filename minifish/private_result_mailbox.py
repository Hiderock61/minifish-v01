"""Synthetic-only private result handoff contract.

This is NOT a network endpoint or a ChatGPT connector. The holder of a
separately provisioned owner capability can claim a result once, in process.
No real account, Codespace Vault, GitHub Issue content, or persistent storage.
The eventual authenticated cross-process/channel transport remains unbuilt.
"""
from __future__ import annotations

from hashlib import sha256
from hmac import compare_digest
from threading import Lock
from time import monotonic
import re
from typing import Callable

_JOB = re.compile(r"issue_[1-9][0-9]{0,15}\Z")
_CAPABILITY = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_MAX_TITLES = 20
_MAX_TITLE_LENGTH = 120


class PrivateResultMailbox:
    """Bounded in-memory one-use payload, never a public GitHub response."""

    def __init__(self, *, owner_capability: str, ttl_seconds: int = 60,
                 clock: Callable[[], float] = monotonic) -> None:
        # Capability comes from the trusted owner side, NEVER an Issue.
        if (not isinstance(owner_capability, str)
                or not _CAPABILITY.fullmatch(owner_capability)):
            raise ValueError("PRIVATE_CAPABILITY_INVALID")
        if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 300:
            raise ValueError("PRIVATE_TTL_INVALID")
        self._expected = sha256(owner_capability.encode("ascii")).digest()
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = Lock()
        self._results: dict[str, tuple[float, tuple[str, ...]]] = {}

    @staticmethod
    def _job(job_id: str) -> None:
        if not isinstance(job_id, str) or not _JOB.fullmatch(job_id):
            raise ValueError("PRIVATE_JOB_ID_INVALID")

    @staticmethod
    def _titles(titles: tuple[str, ...]) -> None:
        if (not isinstance(titles, tuple)
                or not 1 <= len(titles) <= _MAX_TITLES):
            raise ValueError("PRIVATE_RESULT_SHAPE_INVALID")
        for title in titles:
            if (not isinstance(title, str)
                    or not 1 <= len(title) <= _MAX_TITLE_LENGTH
                    or not title.strip()
                    or title != title.strip()
                    or any(ord(ch) < 32 or ord(ch) == 127 for ch in title)):
                raise ValueError("PRIVATE_RESULT_SHAPE_INVALID")

    def publish(self, *, job_id: str, titles: tuple[str, ...]) -> None:
        """Producer writes to private RAM only. Duplicate jobs STOP."""
        self._job(job_id)
        self._titles(titles)
        with self._lock:
            if job_id in self._results:
                raise ValueError("PRIVATE_JOB_DUPLICATE")
            if len(self._results) >= 64:
                raise ValueError("PRIVATE_MAILBOX_FULL")
            self._results[job_id] = (self._clock() + self._ttl, titles)

    def claim(self, *, job_id: str, owner_capability: str) -> tuple[str, ...]:
        """Owner's private channel only: one-use claim with a separate secret."""
        self._job(job_id)
        if not isinstance(owner_capability, str):
            raise ValueError("PRIVATE_ACCESS_DENIED")
        try:
            candidate = sha256(owner_capability.encode("ascii")).digest()
        except UnicodeEncodeError:
            raise ValueError("PRIVATE_ACCESS_DENIED") from None
        if not compare_digest(candidate, self._expected):
            raise ValueError("PRIVATE_ACCESS_DENIED")
        with self._lock:
            record = self._results.get(job_id)
            if record is None:
                raise ValueError("PRIVATE_RESULT_UNAVAILABLE")
            expires, titles = record
            if self._clock() >= expires:
                del self._results[job_id]
                raise ValueError("PRIVATE_RESULT_EXPIRED")
            del self._results[job_id]
            return titles

    @staticmethod
    def public_receipt(job_id: str) -> dict[str, object]:
        """Safe for a PUBLIC Issue: neither values, counts nor credentials."""
        PrivateResultMailbox._job(job_id)
        return {
            "mode": "owner_private_delivery_mock",
            "run_id": job_id,
            "status": "PRIVATE_RESULT_READY",
            "private_values_included": False,
            "credentials_included": False,
            "access_capability_included": False,
            "website_writes": 0,
            "real_site_calls": 0,
            "paid_api_calls": 0,
        }
