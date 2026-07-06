"""Shim para huey.bin.huey_consumer huey_tasks.huey"""

from workers.huey_app import huey  # noqa: F401
import workers.huey_tasks  # noqa: F401 — registra outbox_tick
