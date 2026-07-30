"""Per-node wall-clock timing into HelpdeskState.node_timings."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Generator, MutableMapping


@contextmanager
def timed(
    timings: MutableMapping[str, float],
    node_name: str,
) -> Generator[None, None, None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings[node_name] = round(elapsed_ms, 2)


def ensure_timings(state: Dict) -> Dict[str, float]:
    timings = state.get("node_timings")
    if timings is None:
        timings = {}
        state["node_timings"] = timings
    return timings
