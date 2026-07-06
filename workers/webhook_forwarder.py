"""Reenvía eventos kardex desde sync_outbox_router al router (webhooks por API key).

Preferir Huey (`HUEY_ENABLED=true` + consumer) o el loop asyncio en main.py.
Este módulo queda como entrypoint CLI: `python -m workers.webhook_forwarder`.
"""

from __future__ import annotations

import logging
import time

from core.config import settings
from workers.huey_tasks import run_outbox_flush_once

logger = logging.getLogger(__name__)


def run_loop() -> None:
    poll = max(1.0, float(settings.webhook_forwarder_poll_seconds))
    logger.info("Webhook forwarder CLI activo (poll=%ss)", poll)
    while True:
        try:
            result = run_outbox_flush_once()
            sent = int(result.get("sent") or 0)
            if sent:
                logger.info("Reenviados %s eventos al router", sent)
        except Exception:
            logger.exception("Error en webhook forwarder")
        time.sleep(poll)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_loop()
