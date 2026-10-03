"""Simple per-session rate limit that protects the SerpApi and Groq quotas."""
import time


def check_rate_limit(history: list[float], limit: int, window_seconds: float,
                     now: float | None = None) -> tuple[bool, int, list[float]]:
    """Decide if one more trip plan is allowed.

    history is the list of times (Unix seconds) of earlier plans in this session.
    Returns (allowed, seconds to wait, plans still inside the window)."""
    now = time.time() if now is None else now
    recent = [moment for moment in history if now - moment < window_seconds]
    if len(recent) >= limit:
        wait_seconds = int(window_seconds - (now - min(recent))) + 1
        return False, wait_seconds, recent
    return True, 0, recent
