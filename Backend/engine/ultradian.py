
import time


class UltradianEngine:
    def __init__(self, cycle_minutes: int = 90):
        """
        cycle_minutes: personalized focus cycle duration.
        Default: 90 minutes.

        Score:
            0.0 = beginning of focus cycle
            1.0 = personal cycle duration reached
        """

        if cycle_minutes <= 0:
            raise ValueError(
                "cycle_minutes must be positive"
            )

        self.cycle_seconds = cycle_minutes * 60
        self.start_time = None

    # ─────────────────────────────────────────────
    # START SESSION
    # ─────────────────────────────────────────────

    def start(self):
        self.start_time = time.time()

    # ─────────────────────────────────────────────
    # RESET AFTER COMPLETED BREAK
    # ─────────────────────────────────────────────

    def reset_after_break(self):
        self.start()

    # ─────────────────────────────────────────────
    # MAIN COMPUTE FUNCTION
    # ─────────────────────────────────────────────

    def compute(self) -> float:
        """
        Returns normalized ultradian pressure (0–1).

        Pressure increases as time passes since
        the last completed break.
        """

        if self.start_time is None:
            return 0.0

        elapsed = max(
            0.0,
            time.time() - self.start_time
        )

        score = elapsed / self.cycle_seconds

        score = min(1.0, max(0.0, score))

        return round(score, 3)

    # ─────────────────────────────────────────────
    # GET RAW INFO
    # ─────────────────────────────────────────────

    def get_elapsed_minutes(self) -> float:
        if self.start_time is None:
            return 0.0

        return max(
            0.0,
            (time.time() - self.start_time) / 60.0
        )
