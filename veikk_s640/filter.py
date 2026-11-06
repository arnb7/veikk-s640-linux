"""Adaptive anti-jitter and smoothing filter for VEIKK tablet input."""

import math
from typing import Optional, Tuple


class AdaptiveSmoothingFilter:
    """Speed-adaptive low-pass filter with deadzone for digitizer coordinates.

    Eliminates high-frequency ADC noise and hand tremor during slow drawing
    or hovering, while dynamically lowering filtering (alpha -> 1.0) during
    rapid pen flicks to ensure zero perceivable latency.
    """

    def __init__(
        self,
        enabled: bool = True,
        smoothing_factor: float = 0.5,
        deadzone: int = 4,
        pressure_smoothing: float = 0.3
    ):
        self.enabled = enabled
        self.smoothing_factor = max(0.0, min(1.0, smoothing_factor))
        self.deadzone = max(0, deadzone)
        self.pressure_smoothing = max(0.0, min(1.0, pressure_smoothing))

        self._last_x: Optional[float] = None
        self._last_y: Optional[float] = None
        self._last_p: float = 0.0

    def reset(self):
        """Reset internal filter state when pen leaves sensing range."""
        self._last_x = None
        self._last_y = None
        self._last_p = 0.0

    def filter_position(self, raw_x: int, raw_y: int) -> Tuple[int, int]:
        """Apply adaptive smoothing to (X, Y) coordinates."""
        if not self.enabled or self.smoothing_factor <= 0.0:
            self._last_x = float(raw_x)
            self._last_y = float(raw_y)
            return raw_x, raw_y

        if self._last_x is None or self._last_y is None:
            self._last_x = float(raw_x)
            self._last_y = float(raw_y)
            return raw_x, raw_y

        dx = float(raw_x) - self._last_x
        dy = float(raw_y) - self._last_y
        dist = math.hypot(dx, dy)

        # Micro-jitter deadzone suppression
        if dist <= self.deadzone:
            return int(round(self._last_x)), int(round(self._last_y))

        # Speed-adaptive alpha:
        # At zero velocity beyond deadzone, alpha = alpha_min (smoothest).
        # At high velocity (flicks), alpha approaches 1.0 (zero latency).
        alpha_min = 1.0 - 0.85 * self.smoothing_factor
        speed_threshold = 40.0 + 200.0 * self.smoothing_factor
        effective_dist = dist - self.deadzone
        ratio = min(1.0, effective_dist / speed_threshold)
        alpha = alpha_min + (1.0 - alpha_min) * ratio

        new_x = self._last_x + alpha * dx
        new_y = self._last_y + alpha * dy

        self._last_x = new_x
        self._last_y = new_y
        return int(round(new_x)), int(round(new_y))

    def filter_pressure(self, raw_p: int) -> int:
        """Apply smoothing to pressure values."""
        if not self.enabled or self.pressure_smoothing <= 0.0:
            self._last_p = float(raw_p)
            return raw_p

        # Zero pressure indicates pen lift: drop immediately without decay lag
        if raw_p <= 0:
            self._last_p = 0.0
            return 0

        if self._last_p <= 0.0:
            self._last_p = float(raw_p)
            return raw_p

        alpha_p = 1.0 - 0.75 * self.pressure_smoothing
        new_p = self._last_p + alpha_p * (float(raw_p) - self._last_p)
        self._last_p = new_p
        return int(round(new_p))
