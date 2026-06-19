"""Contexto de la tenant API key reenviada por el hub (headers X-Multishop-Partner-Key-*)."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

HISTORIALP_MODULO_DEFAULT = "Multishop router"
HISTORIALP_USUARIO_FALLBACK = "Usuario Activo: API Multishop"
MAX_HISTORIALP_USUARIO_LEN = 120


@dataclass(frozen=True)
class PartnerRequestContext:
    key_id: str | None = None
    key_label: str | None = None


_partner_ctx: ContextVar[PartnerRequestContext | None] = ContextVar(
    "partner_request_context",
    default=None,
)


def bind_partner_request_context(
    ctx: PartnerRequestContext | None,
) -> Token[PartnerRequestContext | None]:
    return _partner_ctx.set(ctx)


def reset_partner_request_context(token: Token[PartnerRequestContext | None]) -> None:
    _partner_ctx.reset(token)


def get_partner_request_context() -> PartnerRequestContext | None:
    return _partner_ctx.get()


def historialp_usuario_from_context() -> str:
    ctx = get_partner_request_context()
    if not ctx:
        return HISTORIALP_USUARIO_FALLBACK

    label = (ctx.key_label or "").strip()
    key_id = (ctx.key_id or "").strip()
    if label and key_id:
        prefix = "Usuario Activo: "
        suffix = f" ({key_id})"
        max_label = MAX_HISTORIALP_USUARIO_LEN - len(prefix) - len(suffix)
        trimmed_label = label[: max(1, max_label)]
        return f"{prefix}{trimmed_label}{suffix}"
    if label:
        prefix = "Usuario Activo: "
        return f"{prefix}{label[: MAX_HISTORIALP_USUARIO_LEN - len(prefix)]}"
    if key_id:
        return f"Usuario Activo: {key_id[:MAX_HISTORIALP_USUARIO_LEN - len('Usuario Activo: ')]}"
    return HISTORIALP_USUARIO_FALLBACK
