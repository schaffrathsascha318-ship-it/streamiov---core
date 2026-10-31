"""Provider contract for local, replaceable model inference."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class ModelReply:
    content: str
    provider: str
    model: str

class ModelProvider(Protocol):
    def generate(self, *, system: str, messages: list[dict[str, str]]) -> ModelReply: ...
