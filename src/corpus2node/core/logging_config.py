from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Idempotent logging setup: readable stdout logs, verbose for our package.

    Keeps every pipeline step visible in the terminal; the API's exception handler
    additionally logs full tracebacks so errors persist for inspection.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", datefmt="%H:%M:%S")
    )
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(level)
    logging.getLogger("corpus2node").setLevel(logging.DEBUG)
    _CONFIGURED = True
