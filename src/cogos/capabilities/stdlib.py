"""stdlib capability — exposes Python standard library modules to processes."""

from __future__ import annotations

import random
import time


class StdLib:
    """Access to Python standard library utilities.

    Provides:
        stdlib.time  — Python time module (time(), sleep(), strftime(), etc.)
        stdlib.random — Python random module (random(), randint(), choice(), etc.)
    """

    time = time
    random = random

    def __repr__(self) -> str:
        return "<StdLib time, random>"


stdlib = StdLib()
