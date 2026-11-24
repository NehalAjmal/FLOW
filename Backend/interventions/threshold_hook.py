# interventions/threshold_hook.py
# The one place prompt code talks to Mridul's adaptive threshold (his Task 4).
#
# Agreed interface for Mridul to implement in engine/threshold.py:
#     def update_threshold(db, user_id: str, response: str) -> float
# response is one of: accepted | dismissed | snoozed | overridden | reported
# It returns the user's new threshold, kept between 0.50 and 0.80.
#
# Until that file exists this does nothing, so prompt responses still work.

from typing import Optional

try:
    from engine.threshold import update_threshold as _update
except ImportError:
    _update = None


def on_response(db, user_id: str, response: str) -> Optional[float]:
    if _update is None:
        return None
    try:
        return _update(db, user_id, response)
    except Exception as e:          # a threshold bug must never break answering a prompt
        print("threshold update failed:", e)
        return None
