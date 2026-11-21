import numpy as np
from collections import defaultdict
from datetime import datetime


# The activity agent sends a tick every 30s — used when timestamps are missing.
TICK_MINUTES = 0.5

# Cap accumulated history arrays to prevent unbounded JSON growth.
MAX_HISTORY = 50
MAX_HOURLY_SAMPLES = 100


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


class PatternLearner:
    """
    Stateless learner.  Each call to update() takes the user's existing
    pattern_model (from DB) plus the new session's signal log and returns
    the updated model.  No instance state, no cross-user leakage.
    """

    # ─────────────────────────────────────────────
    # MAIN UPDATE FUNCTION
    # ─────────────────────────────────────────────

    def update(self, previous_model: dict, session_data: list) -> dict:
        """
        previous_model : the user's current pattern_model from DB (or {})
        session_data   : the signal log from the just-ended session,
                         already converted by _prepare_learning_data()
        Returns        : the updated pattern_model dict to store in DB
        """
        if not session_data:
            return previous_model or self._empty_model()

        prev_params = (previous_model or {}).get("parameters", {})

        # ── Recover accumulated history from previous model ──────────
        session_lengths   = list(prev_params.get("_session_lengths", []))
        trough_history    = list(prev_params.get("_trough_history", []))
        keystroke_history = list(prev_params.get("_keystroke_history", []))
        switch_history    = list(prev_params.get("_switch_history", []))
        hourly_fatigue    = {
            int(k): list(v)
            for k, v in (prev_params.get("_hourly_fatigue") or {}).items()
        }

        # ── Process the new session ──────────────────────────────────
        timestamps   = []
        fatigue_vals = []
        keystrokes   = []
        switches     = []

        for point in session_data:
            timestamps.append(_parse_ts(point.get("timestamp")))
            fatigue_vals.append(
                point.get("output", {}).get("fatigue", 0.0)
            )
            inp = point.get("input", {})
            keystrokes.append(inp.get("keystroke_count", 0))
            switches.append(inp.get("window_switches", 0))

        # Session length (real minutes)
        session_lengths.append(self._session_duration_minutes(timestamps))

        # Hourly fatigue profile
        for t, f in zip(timestamps, fatigue_vals):
            hour = t.hour if t else datetime.utcnow().hour
            hourly_fatigue.setdefault(hour, []).append(f)

        # Baselines
        avg_kpm    = float(np.mean(keystrokes)) if keystrokes else 0
        avg_switch = float(np.mean(switches))   if switches   else 0
        keystroke_history.append(avg_kpm)
        switch_history.append(avg_switch)

        # Trough
        trough = self._compute_trough_minute(session_data, timestamps)
        trough_history.append(trough)

        return self._export_model(
            hourly_fatigue, session_lengths,
            keystroke_history, switch_history, trough_history,
        )

    # ─────────────────────────────────────────────
    # SESSION DURATION
    # ─────────────────────────────────────────────

    def _session_duration_minutes(self, parsed_timestamps) -> float:
        valid = [t for t in parsed_timestamps if t is not None]
        if len(valid) >= 2:
            span = (max(valid) - min(valid)).total_seconds() / 60.0
            if span > 0:
                return round(span + TICK_MINUTES, 1)
        return round(len(parsed_timestamps) * TICK_MINUTES, 1)

    # ─────────────────────────────────────────────
    # EXPORT MODEL
    # ─────────────────────────────────────────────

    def _export_model(self, hourly_fatigue, session_lengths,
                      keystroke_history, switch_history, trough_history):

        # fatigue profile
        avg = {
            h: np.mean(v)
            for h, v in hourly_fatigue.items()
            if len(v) >= 3
        }

        if avg:
            mn, mx = min(avg.values()), max(avg.values())
            fatigue_profile = {
                str(h): round(1 - (v - mn) / (mx - mn + 1e-8), 3)
                for h, v in avg.items()
            }
        else:
            fatigue_profile = {}

        # ultradian cycle — median session length in MINUTES
        if len(session_lengths) >= 3:
            cycle = max(25, int(np.median(session_lengths)))
        else:
            cycle = 90

        # baselines
        baseline_kpm    = float(np.mean(keystroke_history)) if keystroke_history else 0
        baseline_switch = float(np.mean(switch_history))    if switch_history    else 0

        # trough (learned over sessions)
        trough_minute = int(np.median(trough_history)) if trough_history else 45

        return {
            "schema_version": "learning_v3",
            "parameters": {
                "fatigue_focus_profile":       fatigue_profile,
                "ultradian_cycle_minutes":     cycle,
                "baseline_keystrokes_per_min": round(baseline_kpm, 2),
                "baseline_window_switches":    round(baseline_switch, 2),
                "trough_minute":               trough_minute,
                # Private accumulated history (survives restarts).
                # Prefixed with _ so they are clearly internal.
                # The frontend ignores unknown fields (CONTRACT_NOTES rule).
                "_session_lengths":   session_lengths[-MAX_HISTORY:],
                "_trough_history":    trough_history[-MAX_HISTORY:],
                "_keystroke_history": keystroke_history[-MAX_HISTORY:],
                "_switch_history":    switch_history[-MAX_HISTORY:],
                "_hourly_fatigue": {
                    str(h): v[-MAX_HOURLY_SAMPLES:]
                    for h, v in hourly_fatigue.items()
                },
            }
        }

    # ─────────────────────────────────────────────
    # TROUGH CALCULATION
    # ─────────────────────────────────────────────

    def _compute_trough_minute(self, log, parsed_timestamps=None):

        if not log:
            return 45

        scores = []

        for i, point in enumerate(log):
            inp = point.get("input", {})

            score = (
                inp.get("keystroke_count", 0)
                - inp.get("window_switches", 0) * 2
                - inp.get("idle_seconds", 0) * 0.5
            )

            scores.append((i, score))

        trough_idx = min(scores, key=lambda x: x[1])[0]

        # Convert the entry index to minutes using real tick spacing
        if parsed_timestamps:
            valid = [t for t in parsed_timestamps if t is not None]
            if len(valid) >= 2 and trough_idx < len(parsed_timestamps):
                ticks = parsed_timestamps[: trough_idx + 1]
                valid_ticks = [t for t in ticks if t is not None]
                if len(valid_ticks) >= 2:
                    return int(round((valid_ticks[-1] - valid_ticks[0]).total_seconds() / 60.0))

        return int(round(trough_idx * TICK_MINUTES))

    # ─────────────────────────────────────────────
    # EMPTY MODEL
    # ─────────────────────────────────────────────

    def _empty_model(self):
        return {
            "schema_version": "empty",
            "parameters": {}
        }
