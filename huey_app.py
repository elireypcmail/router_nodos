"""Shim: instancia Huey en workers.huey_app (alternativa: huey_tasks.huey para el consumer)."""

from workers.huey_app import huey

__all__ = ["huey"]
