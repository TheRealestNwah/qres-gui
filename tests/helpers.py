"""Small shared test helpers."""

import threading


def no_guard(*_args) -> threading.Thread:
    """Stand-in for launcher._spawn_guard: starts nothing, returns an already-finished thread."""
    done = threading.Thread(target=lambda: None)
    done.start()
    return done
