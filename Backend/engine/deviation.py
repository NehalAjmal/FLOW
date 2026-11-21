from collections import deque
import numpy as np


class DeviationEngine:
    # Initial heuristics for 30-second windows.
    # Tune using observed activity data.
    BASELINES = {
        "light": {
            "keystrokes": 5,
            "switches": 3,
            "idle_seconds": 25,
        },
        "moderate": {
            "keystrokes": 20,
            "switches": 5,
            "idle_seconds": 15,
        },
        "heavy": {
            "keystrokes": 35,
            "switches": 8,
            "idle_seconds": 10,
        },
    }

    WEIGHTS = {
        "keystrokes": 0.4,
        "switches": 0.3,
        "idle_seconds": 0.3,
    }

    def __init__(self):
        self.history = deque(maxlen=10)

    def reset(self):
        """Clear history when a new session begins."""
        self.history.clear()

    def compute(
        self,
        keystrokes: int,
        switches: int,
        idle_seconds: int,
        declared_difficulty: str = "moderate",
    ) -> float:
        """
        Compute deviation score:
            0.0 = low behavioral deviation
            1.0 = high behavioral deviation

        Inputs are measured over a 30-second window.
        """

        difficulty = declared_difficulty.lower().strip()

        if difficulty not in self.BASELINES:
            raise ValueError(
                f"Invalid difficulty: {declared_difficulty}"
            )

        if any(
            value < 0
            for value in (
                keystrokes,
                switches,
                idle_seconds,
            )
        ):
            raise ValueError(
                "Activity measurements cannot be negative"
            )

        baseline = self.BASELINES[difficulty]

        # Low keyboard activity contributes to deviation.
        keystroke_score = 1.0 - min(
            keystrokes / baseline["keystrokes"],
            1.0,
        )

        # Excessive switching contributes to deviation.
        switch_score = min(
            switches / baseline["switches"],
            1.0,
        )

        # Excessive inactivity contributes to deviation.
        idle_score = min(
            idle_seconds / baseline["idle_seconds"],
            1.0,
        )

        deviation = (
            self.WEIGHTS["keystrokes"] * keystroke_score
            + self.WEIGHTS["switches"] * switch_score
            + self.WEIGHTS["idle_seconds"] * idle_score
        )

        deviation = float(
            np.clip(deviation, 0.0, 1.0)
        )

        self.history.append(deviation)

        return round(
            float(np.mean(self.history)),
            3,
        )
