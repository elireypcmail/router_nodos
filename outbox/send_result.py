from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OutboxSendResult:
    """Resultado de enviar un batch de outbox al hub (ingest transaccional)."""

    sent_ids: list[int] = field(default_factory=list)
    ignored_ids: list[int] = field(default_factory=list)
    failed_ids: list[int] = field(default_factory=list)
    attempted_ids: list[int] = field(default_factory=list)
    hub_failed_messages: dict[int, str] = field(default_factory=dict)

    @property
    def has_failures(self) -> bool:
        return bool(self.failed_ids)
