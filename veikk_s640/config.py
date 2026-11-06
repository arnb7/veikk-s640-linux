"""Configuration management for veikk-s640d."""

import os
import tomllib
from dataclasses import dataclass, field
from typing import Literal

CONFIG_DEFAULT_PATHS = [
    os.path.expanduser("~/.config/veikk-s640/config.toml"),
    "/etc/veikk-s640/config.toml",
    "./config/config.toml",
]


@dataclass
class TabletConfig:
    button_mode: Literal["native", "remapper"] = "remapper"
    orientation: int = 0  # 0, 90, 180, 270
    coord_width: int = 3
    max_x: int = 30480
    max_y: int = 20320
    max_pressure: int = 8191
    input_prop: Literal["none", "direct"] = "none"

    # Smoothing & Anti-Jitter configuration
    smoothing_enable: bool = True
    smoothing_factor: float = 0.35   # 0.0 (raw) to 1.0 (heavy smoothing; 0.35 = snappy handwriting)
    smoothing_deadzone: int = 3      # raw units (suppresses micro-tremors during hover only)
    pressure_smoothing: float = 0.3  # 0.0 (raw) to 1.0 (smooth stroke dynamics)

    # Physical dimensions in mm (Veikk S640 is 6x4 inches ~ 152.4 x 101.6 mm)
    physical_width_mm: float = 152.4
    physical_height_mm: float = 101.6

    # Active area crop ratios (0.0 to 1.0)
    area_min_x: float = 0.0
    area_max_x: float = 1.0
    area_min_y: float = 0.0
    area_max_y: float = 1.0

    # Motion & Hover distance scaling
    hover_scale: float = 1.0         # 0.10 to 2.00 (default 1.0 = 1:1 screen mapping)
    contact_scale: float = 1.0       # 0.10 to 2.00 (1.0 = true 1:1 inking mapping)
    lock_motion_scales: bool = False # Independent contact scale ensures true 1:1 handwriting precision

    # Stylus button mapping (integrated input-remapper presets)
    button1_action: str = "mouse:btn_right"
    button2_action: str = "pan_scroll"
    button1_custom: str = ""
    button2_custom: str = ""
    button_autoload: bool = True

    # Pan / Scroll configuration (holding barrel button and moving pen)
    scroll_sensitivity: float = 1.0  # 0.1 to 3.0 (default 1.0)
    scroll_natural: bool = False      # False = standard PC down-scroll, True = natural touch-style
    scroll_require_touch: bool = True # True = require touching pen tip to scroll (disables hover scrolling)

    # Pressure configuration
    pressure_curve: Literal["linear", "gamma"] = "linear"
    pressure_gamma: float = 1.0
    pressure_threshold: int = 0

    @property
    def resolution_x(self) -> int:
        """Units per millimeter on X axis."""
        return int(self.max_x / self.physical_width_mm)

    @property
    def resolution_y(self) -> int:
        """Units per millimeter on Y axis."""
        return int(self.max_y / self.physical_height_mm)

    @property
    def is_portrait(self) -> bool:
        """True when tablet is in 90° or 270° portrait/vertical orientation."""
        return self.orientation in (90, 270)

    @property
    def output_max_x(self) -> int:
        """Virtual uinput coordinate maximum for X axis (swapped to 20320 in portrait)."""
        return self.max_y if self.is_portrait else self.max_x

    @property
    def output_max_y(self) -> int:
        """Virtual uinput coordinate maximum for Y axis (swapped to 30480 in portrait)."""
        return self.max_x if self.is_portrait else self.max_y

    @property
    def output_res_x(self) -> int:
        """Virtual uinput resolution for X axis in units/mm."""
        return self.resolution_y if self.is_portrait else self.resolution_x

    @property
    def output_res_y(self) -> int:
        """Virtual uinput resolution for Y axis in units/mm."""
        return self.resolution_x if self.is_portrait else self.resolution_y

    def apply_pressure_curve(self, raw_p: int) -> int:
        """Apply configured threshold, clamping, and gamma response."""
        if raw_p <= self.pressure_threshold:
            return 0
        clamped = min(raw_p, self.max_pressure)
        if self.pressure_curve == "gamma" and self.pressure_gamma > 0 and self.pressure_gamma != 1.0:
            eff_max = max(1, self.max_pressure - self.pressure_threshold)
            norm = (clamped - self.pressure_threshold) / eff_max
            norm = max(0.0, min(1.0, norm))
            transformed = norm ** self.pressure_gamma
            return int(transformed * self.max_pressure)
        return clamped

    def transform_coordinates(self, raw_x: int, raw_y: int) -> tuple[int, int]:
        """Apply active area cropping and rotation with true isotropic proportions."""
        # 1. Active area normalization & clamping
        x_span = max(self.area_max_x - self.area_min_x, 0.01)
        y_span = max(self.area_max_y - self.area_min_y, 0.01)

        norm_x = (raw_x / self.max_x - self.area_min_x) / x_span
        norm_y = (raw_y / self.max_y - self.area_min_y) / y_span

        norm_x = max(0.0, min(1.0, norm_x))
        norm_y = max(0.0, min(1.0, norm_y))

        # 2. Orientation rotation
        if self.orientation == 90:
            rx, ry = 1.0 - norm_y, norm_x
        elif self.orientation == 180:
            rx, ry = 1.0 - norm_x, 1.0 - norm_y
        elif self.orientation == 270:
            rx, ry = norm_y, 1.0 - norm_x
        else:  # 0
            rx, ry = norm_x, norm_y

        out_x = int(rx * self.output_max_x)
        out_y = int(ry * self.output_max_y)
        return out_x, out_y


def get_config_search_paths() -> list[str]:
    """Return prioritized list of configuration file paths."""
    import glob
    paths = [os.path.expanduser("~/.config/veikk-s640/config.toml")]
    for user_home in sorted(glob.glob("/home/*")):
        user_cfg = os.path.join(user_home, ".config/veikk-s640/config.toml")
        if user_cfg not in paths:
            paths.append(user_cfg)
    paths.append("/etc/veikk-s640/config.toml")
    paths.append("./config/config.toml")
    return paths


def load_config(path: str | None = None) -> TabletConfig:
    """Load config from explicit path or default discovery locations."""
    target_path = None
    if path and os.path.isfile(path):
        target_path = path
    else:
        for p in get_config_search_paths():
            if os.path.isfile(p):
                target_path = p
                break

    cfg = TabletConfig()
    if not target_path:
        return cfg

    try:
        with open(target_path, "rb") as f:
            data = tomllib.load(f)

        tablet = data.get("tablet", {})
        if "button_mode" in tablet:
            mode = tablet["button_mode"].lower()
            if mode in ("native", "remapper"):
                cfg.button_mode = mode

        if "orientation" in tablet:
            ori = int(tablet["orientation"])
            if ori in (0, 90, 180, 270):
                cfg.orientation = ori

        if "coord_width" in tablet:
            cw = int(tablet["coord_width"])
            if cw in (1, 2, 3):
                cfg.coord_width = cw

        if "max_x" in tablet:
            cfg.max_x = int(tablet["max_x"])
        if "max_y" in tablet:
            cfg.max_y = int(tablet["max_y"])
        if "max_pressure" in tablet:
            cfg.max_pressure = int(tablet["max_pressure"])

        smoothing = data.get("smoothing", {})
        if "enable" in smoothing:
            cfg.smoothing_enable = bool(smoothing["enable"])
        if "factor" in smoothing:
            cfg.smoothing_factor = max(0.0, min(1.0, float(smoothing["factor"])))
        if "deadzone" in smoothing:
            cfg.smoothing_deadzone = max(0, int(smoothing["deadzone"]))
        if "pressure_smoothing" in smoothing:
            cfg.pressure_smoothing = max(0.0, min(1.0, float(smoothing["pressure_smoothing"])))

        area = data.get("area", {})
        cfg.area_min_x = float(area.get("min_x", 0.0))
        cfg.area_max_x = float(area.get("max_x", 1.0))
        cfg.area_min_y = float(area.get("min_y", 0.0))
        cfg.area_max_y = float(area.get("max_y", 1.0))

        motion = data.get("motion", {})
        if "hover_scale" in motion:
            cfg.hover_scale = max(0.05, min(3.0, float(motion["hover_scale"])))
        if "contact_scale" in motion:
            cfg.contact_scale = max(0.05, min(3.0, float(motion["contact_scale"])))
        if "lock_scales" in motion:
            cfg.lock_motion_scales = bool(motion["lock_scales"])

        btn_sec = data.get("buttons", {})
        if "button1_action" in btn_sec:
            cfg.button1_action = str(btn_sec["button1_action"])
        if "button2_action" in btn_sec:
            cfg.button2_action = str(btn_sec["button2_action"])
        if "button1_custom" in btn_sec:
            cfg.button1_custom = str(btn_sec["button1_custom"])
        if "button2_custom" in btn_sec:
            cfg.button2_custom = str(btn_sec["button2_custom"])
        if "autoload" in btn_sec:
            cfg.button_autoload = bool(btn_sec["autoload"])

        scroll_sec = data.get("scroll", {})
        if "sensitivity" in scroll_sec:
            cfg.scroll_sensitivity = max(0.1, min(5.0, float(scroll_sec["sensitivity"])))
        if "natural" in scroll_sec:
            cfg.scroll_natural = bool(scroll_sec["natural"])
        if "require_touch" in scroll_sec:
            cfg.scroll_require_touch = bool(scroll_sec["require_touch"])

        pressure = data.get("pressure", {})
        p_curve = pressure.get("curve", "linear").lower()
        if p_curve in ("linear", "gamma"):
            cfg.pressure_curve = p_curve
        cfg.pressure_gamma = float(pressure.get("gamma", 1.0))
        cfg.pressure_threshold = int(pressure.get("threshold", 0))

    except Exception as e:
        print(f"[!] Warning: Failed parsing config file {target_path} ({e}), using defaults.")

    return cfg


def save_config(cfg: TabletConfig, path: str | None = None) -> str:
    """Save configuration to path or default user config location."""
    target_path = path or os.path.expanduser("~/.config/veikk-s640/config.toml")
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)

    content = f"""# VEIKK S640 Linux Userspace Driver Configuration
# Auto-generated by veikk-config

[tablet]
button_mode = "{cfg.button_mode}"
orientation = {cfg.orientation}
coord_width = {cfg.coord_width}
max_x = {cfg.max_x}
max_y = {cfg.max_y}
max_pressure = {cfg.max_pressure}

[smoothing]
enable = {str(cfg.smoothing_enable).lower()}
factor = {cfg.smoothing_factor:.2f}
deadzone = {cfg.smoothing_deadzone}
pressure_smoothing = {cfg.pressure_smoothing:.2f}

[motion]
hover_scale = {cfg.hover_scale:.2f}
contact_scale = {cfg.contact_scale:.2f}
lock_scales = {str(cfg.lock_motion_scales).lower()}

[buttons]
button1_action = "{cfg.button1_action}"
button2_action = "{cfg.button2_action}"
button1_custom = "{cfg.button1_custom}"
button2_custom = "{cfg.button2_custom}"
autoload = {str(cfg.button_autoload).lower()}

[scroll]
sensitivity = {cfg.scroll_sensitivity:.2f}
natural = {str(cfg.scroll_natural).lower()}
require_touch = {str(cfg.scroll_require_touch).lower()}

[area]
min_x = {cfg.area_min_x:.3f}
max_x = {cfg.area_max_x:.3f}
min_y = {cfg.area_min_y:.3f}
max_y = {cfg.area_max_y:.3f}

[pressure]
curve = "{cfg.pressure_curve}"
gamma = {cfg.pressure_gamma:.2f}
threshold = {cfg.pressure_threshold}
"""
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)

    return target_path
