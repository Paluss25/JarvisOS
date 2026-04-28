from __future__ import annotations

from typing import Protocol


class DocumentReader(Protocol):
    def read(self, path: str) -> str: ...


class OCRReader(Protocol):
    def read(self, path: str) -> str: ...


class LeaveCalculator(Protocol):
    def calculate(self, payload: dict) -> dict: ...


class PensionEstimator(Protocol):
    def estimate(self, payload: dict) -> dict: ...
