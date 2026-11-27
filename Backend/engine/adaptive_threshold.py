import math


class AdaptiveThresholdEngine:
    """
    Adaptive intervention threshold for individual users.

    Lower focus scores indicate poorer focus.
    An intervention becomes eligible when the focus
    score falls below the current threshold.
    """

    MIN_THRESHOLD = 0.50
    MAX_THRESHOLD = 0.80
    DEFAULT_THRESHOLD = 0.65
    ADJUSTMENT_STEP = 0.02

    def __init__(self, threshold=None):
        if threshold is None:
            threshold = self.DEFAULT_THRESHOLD

        self.threshold = self._clamp(threshold)

    @classmethod
    def _clamp(cls, value):
        if isinstance(value, bool):
            raise ValueError("Threshold must be numeric")

        value = float(value)

        if not math.isfinite(value):
            raise ValueError("Threshold must be finite")

        return round(
            max(
                cls.MIN_THRESHOLD,
                min(cls.MAX_THRESHOLD, value)
            ),
            4
        )

    def get_threshold(self) -> float:
        return self.threshold

    def update(self, response: str) -> float:
        """
        Accepted:
            Increase sensitivity to future focus drops.

        Dismissed:
            Reduce sensitivity to future focus drops.

        Ignored:
            Keep the threshold unchanged.
        """

        if not isinstance(response, str):
            raise ValueError("Response must be a string")

        response = response.strip().lower()

        if response == "accepted":
            self.threshold = self._clamp(
                self.threshold + self.ADJUSTMENT_STEP
            )

        elif response == "dismissed":
            self.threshold = self._clamp(
                self.threshold - self.ADJUSTMENT_STEP
            )

        elif response == "ignored":
            pass

        else:
            raise ValueError(
                f"Invalid intervention response: {response}"
            )

        return self.threshold

    def should_intervene(self, focus_score) -> bool:
        """
        Expects a normalized focus score between 0 and 1.
        Missing scores do not trigger interventions.
        """

        if focus_score is None:
            return False

        if isinstance(focus_score, bool):
            raise ValueError("Focus score must be numeric")

        focus_score = float(focus_score)

        if not math.isfinite(focus_score):
            raise ValueError("Focus score must be finite")

        if not 0.0 <= focus_score <= 1.0:
            raise ValueError(
                "Focus score must be between 0 and 1"
            )

        return focus_score < self.threshold

    def reset(self) -> float:
        self.threshold = self.DEFAULT_THRESHOLD
        return self.threshold
