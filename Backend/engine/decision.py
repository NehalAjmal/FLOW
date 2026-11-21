import math


class DecisionEngine:
    WEIGHTS = {
        "deviation": 0.40,
        "fatigue": 0.30,
        "ultradian": 0.20,
        "biometric": 0.10,
    }

    @staticmethod
    def _normalize(value, name):
        """
        None means unavailable.
        Valid numeric values are clamped to [0, 1].
        """
        if value is None:
            return None

        if isinstance(value, bool):
            raise ValueError(
                f"{name} must be numeric"
            )

        value = float(value)

        if not math.isfinite(value):
            raise ValueError(
                f"{name} must be finite"
            )

        return min(1.0, max(0.0, value))

    def compute(
        self,
        fatigue=None,
        deviation=None,
        ultradian=None,
        biometric=None,
        trough_pressure=0.0,
    ):
        """
        Returns a normalized focus score and state.

        fatigue: 0 = low fatigue, 1 = high fatigue
        deviation: 0 = low deviation, 1 = high
        ultradian: 0 = fresh cycle, 1 = full pressure
        biometric: 0 = poor readiness, 1 = good
        """

        raw_signals = {
            "fatigue": self._normalize(
                fatigue, "fatigue"
            ),
            "deviation": self._normalize(
                deviation, "deviation"
            ),
            "ultradian": self._normalize(
                ultradian, "ultradian"
            ),
            "biometric": self._normalize(
                biometric, "biometric"
            ),
        }

        # Convert all signals to focus-friendly values.
        focus_signals = {
            "fatigue": (
                None if raw_signals["fatigue"] is None
                else 1.0 - raw_signals["fatigue"]
            ),
            "deviation": (
                None if raw_signals["deviation"] is None
                else 1.0 - raw_signals["deviation"]
            ),
            "ultradian": (
                None if raw_signals["ultradian"] is None
                else 1.0 - raw_signals["ultradian"]
            ),
            "biometric": raw_signals["biometric"],
        }

        available = {
            name: value
            for name, value in focus_signals.items()
            if value is not None
        }

        if not available:
            return {
                "state": "unknown",
                "focus_score": None,
                "contributions": {},
            }

        # Renormalize only available weights.
        total_weight = sum(
            self.WEIGHTS[name]
            for name in available
        )

        contributions = {
            name: {
                "value": value,
                "weight": (
                    self.WEIGHTS[name] / total_weight
                ),
                "contribution": (
                    value * self.WEIGHTS[name]
                    / total_weight
                ),
            }
            for name, value in available.items()
        }

        score = sum(
            item["contribution"]
            for item in contributions.values()
        )

        # Trough pressure is a separate penalty,
        # not an additional weighted signal.
        trough = self._normalize(
            trough_pressure, "trough_pressure"
        )

        if trough is not None:
            score -= trough * 0.20

        score = max(0.0, min(1.0, score))

        # Prevent severe fatigue being labeled deep work.
        severe_fatigue = (
            raw_signals["fatigue"] is not None
            and raw_signals["fatigue"] >= 0.80
        )

        if severe_fatigue and score > 0.30:
            state = "fatigue"
        elif score >= 0.75:
            state = "deep_work"
        elif score >= 0.50:
            state = "neutral"
        elif score >= 0.30:
            state = "distracted"
        else:
            state = "fatigue"

        return {
            "state": state,
            "focus_score": round(score, 4),
            "contributions": contributions,
        }


def compute_trough_pressure(
    current_minute,
    trough_minute,
):
    if trough_minute <= 0:
        return 0.0

    distance = trough_minute - current_minute

    if distance > 20:
        return 0.0
    elif distance > 10:
        return 0.3
    elif distance > 5:
        return 0.6
    elif distance > 0:
        return 0.9
    else:
        return 1.0
