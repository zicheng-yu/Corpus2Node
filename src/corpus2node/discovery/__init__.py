"""Cross-session knowledge discovery."""

from corpus2node.discovery.engine import (
    DiscoveryInputError,
    deepen_proposal,
    make_deepener_or_none,
    run_discovery,
)

__all__ = ["DiscoveryInputError", "deepen_proposal", "make_deepener_or_none", "run_discovery"]
