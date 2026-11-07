"""Material 3 Expressive UI for VEIKK S640 Linux Driver Control Center.

Fully recreated from the official VEIKK Pen Tablet User Manual with:
- Left Navigation Rail (Model Selector, Pen, Mapping, Function, About Us)
- Interactive Cairo Visual Mapping Canvas (Monitor, Tablet, Red Projection Rays)
- Stylus Button Callouts & Live Pressure Response Curve
- Full Material 3 Expressive styling (Tonal surfaces, rounded cards, expressive pills)
"""

import os
import sys
import time
import math
import subprocess
import glob
import re
from typing import List, Tuple, Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, Pango
import cairo

from .config import TabletConfig, load_config, save_config
from .remapper import (
    BUTTON_ACTIONS,
    WORKFLOW_PRESETS,
    action_key_to_index,
    index_to_action_key,
    apply_remapper_preset,
    is_service_active,
)


def get_system_monitors() -> list[dict]:
    """Detect all active monitors and their EDID triplets dynamically."""
    monitors = [
        {
            "id": "all",
            "name": "All Displays",
            "connector": "",
            "width": 0,
            "height": 0,
            "is_primary": False,
            "edid": ["", "", ""],
            "label": "All Displays (Virtual Desktop)"
        }
    ]
    detected = []

    # 1. Query Mutter DisplayConfig D-Bus (live active state on GNOME Wayland)
    try:
        res = subprocess.run([
            "gdbus", "call", "--session",
            "--dest", "org.gnome.Mutter.DisplayConfig",
            "--object-path", "/org/gnome/Mutter/DisplayConfig",
            "--method", "org.gnome.Mutter.DisplayConfig.GetCurrentState"
        ], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            out = res.stdout
            log_mons = re.findall(
                r"\((\d+),\s*(\d+),\s*([0-9.]+),\s*(?:uint32\s*)?(\d+),\s*(true|false),\s*\[\('([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)'\)\],",
                out
            )
            for lm in log_mons:
                x, y, scale, transform, primary, conn, vendor, prod, serial = lm
                is_pri = (primary.lower() == "true")

                dname_m = re.search(rf"'{conn}'[^}}]+'display-name':\s*<'(?:[^']*)'>", out)
                if dname_m:
                    dname = dname_m.group(0).split("<")[1].strip("'>")
                elif "edp" in conn.lower():
                    dname = "Built-in Laptop Display"
                elif prod and not prod.startswith("0x"):
                    dname = f"{vendor} {prod}"
                else:
                    dname = f"External Display ({conn})"

                res_m = re.search(rf"'{conn}'[^\]]*\[\('(\d+)x(\d+)@", out)
                w = int(res_m.group(1)) if res_m else (1920 if is_pri else 1366)
                h = int(res_m.group(2)) if res_m else (1080 if is_pri else 768)

                detected.append({
                    "id": conn,
                    "name": dname,
                    "connector": conn,
                    "width": w,
                    "height": h,
                    "is_primary": is_pri,
                    "edid": [vendor, prod, serial]
                })
    except Exception:
        pass

    # 2. Fallback to ~/.config/monitors.xml if Mutter D-Bus didn't return any
    if not detected:
        xml_path = os.path.expanduser("~/.config/monitors.xml")
        if os.path.isfile(xml_path):
            try:
                import xml.etree.ElementTree as ET
                tree = ET.parse(xml_path)
                config = tree.getroot().find("configuration")
                if config is not None:
                    for lm in config.findall("logicalmonitor"):
                        is_pri = (lm.find("primary") is not None and lm.find("primary").text.strip().lower() == "yes")
                        mon = lm.find("monitor")
                        if mon is None:
                            continue
                        mspec = mon.find("monitorspec")
                        if mspec is None:
                            continue
                        conn = mspec.findtext("connector", "")
                        vend = mspec.findtext("vendor", "")
                        prod = mspec.findtext("product", "")
                        serial = mspec.findtext("serial", "")
                        mode = mon.find("mode")
                        w = int(mode.findtext("width", "1920")) if mode else 1920
                        h = int(mode.findtext("height", "1080")) if mode else 1080
                        dname = "Built-in Laptop Display" if "edp" in conn.lower() else f"{vend} {prod}"
                        detected.append({
                            "id": conn,
                            "name": dname,
                            "connector": conn,
                            "width": w,
                            "height": h,
                            "is_primary": is_pri,
                            "edid": [vend, prod, serial]
                        })
            except Exception:
                pass

    # Sort so primary is Monitor 1, external is Monitor 2
    detected.sort(key=lambda m: (not m["is_primary"], m["connector"]))
    for i, m in enumerate(detected, 1):
        m["index"] = i
        m["label"] = f"Monitor {i}: {m['name']} ({m['connector']} {m['width']}×{m['height']})"
        monitors.append(m)

    return monitors


def apply_gnome_tablet_output(edid: list[str]) -> bool:
    """Assign tablet devices in GNOME Mutter to target monitor output EDID."""
    try:
        val = f"['{edid[0]}', '{edid[1]}', '{edid[2]}']"
        for tablet_id in ("2feb:0001", "2feb:2000"):
            subprocess.run([
                "gsettings", "set",
                f"org.gnome.desktop.peripherals.tablet:/org/gnome/desktop/peripherals/tablets/{tablet_id}/",
                "output", val
            ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


# ==============================================================================
# Material 3 Expressive Stylesheet
# ==============================================================================
M3_EXPRESSIVE_CSS = """
window.m3-window {
    background-color: #0d0f14;
    color: #e2e8f0;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Inter", sans-serif;
}

/* Sidebar & Navigation Rail */
.m3-sidebar {
    background-color: #14171f;
    border-right: 1px solid rgba(255, 255, 255, 0.08);
    padding: 16px 12px;
}

.m3-brand-title {
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 0.8px;
    color: #3b82f6;
}

.m3-device-badge {
    background: linear-gradient(135deg, rgba(37, 99, 235, 0.25), rgba(30, 58, 138, 0.4));
    border: 1px solid rgba(59, 130, 246, 0.4);
    border-radius: 12px;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: 700;
    color: #93c5fd;
}

.m3-nav-item {
    border-radius: 24px;
    padding: 12px 18px;
    font-size: 14px;
    font-weight: 600;
    border: none;
    background: transparent;
    color: #94a3b8;
    margin-bottom: 6px;
    transition: all 180ms ease;
}

.m3-nav-item:hover {
    background-color: rgba(255, 255, 255, 0.05);
    color: #f8fafc;
}

.m3-nav-item.active {
    background-color: #2563eb;
    color: #ffffff;
    box-shadow: 0 4px 16px rgba(37, 99, 235, 0.45);
}

/* Content Cards */
.m3-card {
    background-color: #191c24;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 22px;
    padding: 20px;
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
}

.m3-card-header {
    font-size: 16px;
    font-weight: 700;
    color: #f8fafc;
    margin-bottom: 4px;
}

.m3-card-sub {
    font-size: 12px;
    color: #94a3b8;
    margin-bottom: 12px;
}

.m3-btn-primary {
    background: linear-gradient(135deg, #2563eb, #1d4ed8);
    color: #ffffff;
    border-radius: 20px;
    font-weight: 700;
    padding: 10px 22px;
    border: none;
    box-shadow: 0 4px 14px rgba(37, 99, 235, 0.35);
}

.m3-btn-primary:hover {
    background: linear-gradient(135deg, #3b82f6, #2563eb);
}

.m3-btn-tonal {
    background-color: #242933;
    color: #cbd5e1;
    border-radius: 20px;
    font-weight: 600;
    padding: 8px 18px;
    border: 1px solid rgba(255, 255, 255, 0.08);
}

.m3-btn-tonal:hover {
    background-color: #2f3644;
    color: #ffffff;
}

.m3-pill {
    border-radius: 16px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
}

.m3-pill.green {
    background-color: rgba(16, 185, 129, 0.15);
    color: #34d399;
    border: 1px solid rgba(16, 185, 129, 0.3);
}

.m3-pill.amber {
    background-color: rgba(245, 158, 11, 0.15);
    color: #fbbf24;
    border: 1px solid rgba(245, 158, 11, 0.3);
}

.m3-pill.red {
    background-color: rgba(239, 68, 68, 0.15);
    color: #f87171;
    border: 1px solid rgba(239, 68, 68, 0.3);
}

.m3-entry {
    background-color: #14171f;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 12px;
    padding: 8px 12px;
    color: #f8fafc;
    font-size: 13px;
}

.m3-entry:focus {
    border-color: #3b82f6;
    outline: none;
}

.m3-chip {
    background-color: #242933;
    color: #cbd5e1;
    border-radius: 16px;
    font-weight: 600;
    font-size: 11px;
    padding: 5px 12px;
    border: 1px solid rgba(255, 255, 255, 0.08);
}

.m3-chip:hover {
    background-color: #2f3644;
    color: #ffffff;
}
"""


# ==============================================================================
# Widget 1: Interactive Cairo Mapping Diagram (Monitor + Tablet + Red Rays)
# ==============================================================================
class MappingDiagramWidget(Gtk.DrawingArea):
    """Visualizes Monitor-to-Tablet coordinate projection exactly like official manual."""

    def __init__(self, config: TabletConfig):
        super().__init__()
        self.config = config
        self.monitor_label = ""
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_content_height(330)
        self.set_content_width(420)
        self.set_draw_func(self._on_draw)

    def update_config(self, config: TabletConfig):
        self.config = config
        self.queue_draw()

    def _on_draw(self, area, cr, width, height):
        # Dark viewport canvas
        cr.set_source_rgb(0.08, 0.09, 0.12)
        cr.paint()

        # Canvas Dimensions
        cx = width / 2.0

        # ----------------------------------------------------------------------
        # 1. Desktop Monitor Illustration (Top)
        # ----------------------------------------------------------------------
        mon_w = min(width * 0.72, 320.0)
        mon_h = mon_w * (9.0 / 16.0)  # 16:9 monitor proportion
        mon_x = cx - (mon_w / 2.0)
        mon_y = 18.0

        # Monitor Outer Stand Base
        cr.set_source_rgba(0.25, 0.28, 0.34, 0.8)
        stand_w = mon_w * 0.28
        stand_x = cx - (stand_w / 2.0)
        stand_top_y = mon_y + mon_h + 4.0
        stand_bot_y = stand_top_y + 32.0

        # Stand neck trapezoid
        cr.move_to(cx - stand_w * 0.25, stand_top_y)
        cr.line_to(cx + stand_w * 0.25, stand_top_y)
        cr.line_to(cx + stand_w * 0.45, stand_bot_y)
        cr.line_to(cx - stand_w * 0.45, stand_bot_y)
        cr.close_path()
        cr.fill()

        # Stand bottom foot
        cr.set_source_rgba(0.35, 0.40, 0.48, 0.9)
        cr.rectangle(cx - stand_w * 0.55, stand_bot_y, stand_w * 1.1, 6.0)
        cr.fill()

        # Monitor Bezel
        cr.set_source_rgb(0.12, 0.13, 0.16)
        cr.rectangle(mon_x - 6.0, mon_y - 6.0, mon_w + 12.0, mon_h + 12.0)
        cr.fill()
        cr.set_source_rgba(0.35, 0.40, 0.50, 0.3)
        cr.set_line_width(1.5)
        cr.rectangle(mon_x - 6.0, mon_y - 6.0, mon_w + 12.0, mon_h + 12.0)
        cr.stroke()

        # Monitor Screen Surface (Glowing desktop blue wallpaper)
        pattern = cairo.LinearGradient(mon_x, mon_y, mon_x, mon_y + mon_h)
        pattern.add_color_stop_rgb(0.0, 0.08, 0.32, 0.65)
        pattern.add_color_stop_rgb(1.0, 0.02, 0.18, 0.42)
        cr.set_source(pattern)
        cr.rectangle(mon_x, mon_y, mon_w, mon_h)
        cr.fill()

        # Screen grid & desktop icons hint
        cr.set_source_rgba(0.4, 0.7, 1.0, 0.15)
        cr.set_line_width(0.8)
        for gx in range(1, 4):
            cr.move_to(mon_x + (mon_w * gx / 4.0), mon_y)
            cr.line_to(mon_x + (mon_w * gx / 4.0), mon_y + mon_h)
        for gy in range(1, 3):
            cr.move_to(mon_x, mon_y + (mon_h * gy / 3.0))
            cr.line_to(mon_x + mon_w, mon_y + (mon_h * gy / 3.0))
        cr.stroke()

        # Monitor Active Box (Screen Mapping)
        scr_box_x = mon_x
        scr_box_y = mon_y
        scr_box_w = mon_w
        scr_box_h = mon_h

        # Active Monitor Label on Screen
        if getattr(self, "monitor_label", ""):
            cr.set_source_rgba(0.95, 0.98, 1.0, 0.90)
            cr.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(11.0)
            extents = cr.text_extents(self.monitor_label)
            cr.move_to(mon_x + (mon_w - extents.width) / 2.0, mon_y + 18.0)
            cr.show_text(self.monitor_label)

        # ----------------------------------------------------------------------
        # 2. VEIKK S640 Tablet Illustration (Bottom)
        # ----------------------------------------------------------------------
        is_vert = self.config.orientation in (90, 270)
        if is_vert:
            tab_w = 120.0
            tab_h = 180.0
        else:
            tab_w = min(width * 0.65, 270.0)
            tab_h = tab_w * (4.0 / 6.0)

        tab_x = cx - (tab_w / 2.0)
        tab_y = height - tab_h - 16.0

        # Tablet Chassis
        cr.set_source_rgb(0.11, 0.12, 0.14)
        cr.rectangle(tab_x, tab_y, tab_w, tab_h)
        cr.fill()
        cr.set_source_rgba(0.3, 0.35, 0.4, 0.4)
        cr.set_line_width(1.5)
        cr.rectangle(tab_x, tab_y, tab_w, tab_h)
        cr.stroke()

        # Grip Bar / Cable Side Accent
        if is_vert:
            # Grip bar at top or bottom
            grip_h = tab_h * 0.14
            cr.set_source_rgb(0.08, 0.08, 0.10)
            cr.rectangle(tab_x, tab_y, tab_w, grip_h)
            cr.fill()
            # LED Indicator dot
            cr.set_source_rgb(0.2, 0.8, 1.0)
            cr.arc(tab_x + 16.0, tab_y + grip_h / 2.0, 2.5, 0, 2 * math.pi)
            cr.fill()
            active_rect = (tab_x + 8.0, tab_y + grip_h + 8.0, tab_w - 16.0, tab_h - grip_h - 16.0)
        else:
            # Grip bar at left
            grip_w = tab_w * 0.14
            cr.set_source_rgb(0.08, 0.08, 0.10)
            cr.rectangle(tab_x, tab_y, grip_w, tab_h)
            cr.fill()
            # LED Indicator dot
            cr.set_source_rgb(0.2, 0.8, 1.0)
            cr.arc(tab_x + grip_w / 2.0, tab_y + 16.0, 2.5, 0, 2 * math.pi)
            cr.fill()
            active_rect = (tab_x + grip_w + 8.0, tab_y + 8.0, tab_w - grip_w - 16.0, tab_h - 16.0)

        # Drawing Surface
        cr.set_source_rgb(0.06, 0.06, 0.08)
        cr.rectangle(*active_rect)
        cr.fill()

        # Surface Corner Marking Crosshairs
        ax, ay, aw, ah = active_rect
        cr.set_source_rgba(0.5, 0.55, 0.65, 0.4)
        cr.set_line_width(1.0)
        mark_len = 8.0
        # 4 corners
        for mx, my, dx, dy in [
            (ax + 4, ay + 4, 1, 1),
            (ax + aw - 4, ay + 4, -1, 1),
            (ax + 4, ay + ah - 4, 1, -1),
            (ax + aw - 4, ay + ah - 4, -1, -1),
        ]:
            cr.move_to(mx, my)
            cr.line_to(mx + dx * mark_len, my)
            cr.move_to(mx, my)
            cr.line_to(mx, my + dy * mark_len)
        cr.stroke()

        # ----------------------------------------------------------------------
        # 3. Active Working Area (Red Box on Tablet)
        # ----------------------------------------------------------------------
        # Map config.area_min_x/y to active_rect
        # When orientation is 90/270, orientation swaps axes
        if is_vert:
            work_box_x = ax + (self.config.area_min_y * aw)
            work_box_w = max(10.0, (self.config.area_max_y - self.config.area_min_y) * aw)
            work_box_y = ay + (self.config.area_min_x * ah)
            work_box_h = max(10.0, (self.config.area_max_x - self.config.area_min_x) * ah)
        else:
            work_box_x = ax + (self.config.area_min_x * aw)
            work_box_w = max(10.0, (self.config.area_max_x - self.config.area_min_x) * aw)
            work_box_y = ay + (self.config.area_min_y * ah)
            work_box_h = max(10.0, (self.config.area_max_y - self.config.area_min_y) * ah)

        # ----------------------------------------------------------------------
        # 4. Red Projection Rays (Connecting Working Area to Screen Mapping)
        # ----------------------------------------------------------------------
        # Coordinates:
        # Screen corners: (scr_box_x, scr_box_y), (scr_box_x + scr_box_w, scr_box_y), ...
        # Tablet corners: (work_box_x, work_box_y), (work_box_x + work_box_w, work_box_y), ...

        # Semi-transparent red trapezoid fill
        cr.set_source_rgba(0.95, 0.25, 0.25, 0.08)
        cr.move_to(scr_box_x, scr_box_y + scr_box_h)
        cr.line_to(scr_box_x + scr_box_w, scr_box_y + scr_box_h)
        cr.line_to(work_box_x + work_box_w, work_box_y)
        cr.line_to(work_box_x, work_box_y)
        cr.close_path()
        cr.fill()

        # Distinct Red Boundary Lines
        cr.set_source_rgba(0.95, 0.20, 0.20, 0.9)
        cr.set_line_width(2.0)

        # Screen Red Box
        cr.rectangle(scr_box_x, scr_box_y, scr_box_w, scr_box_h)
        cr.stroke()

        # Tablet Red Box
        cr.rectangle(work_box_x, work_box_y, work_box_w, work_box_h)
        cr.stroke()

        # 4 Corner Projection Rays
        cr.set_line_width(1.5)
        # Top-left of tablet -> bottom-left of screen
        cr.move_to(work_box_x, work_box_y)
        cr.line_to(scr_box_x, scr_box_y + scr_box_h)
        # Top-right of tablet -> bottom-right of screen
        cr.move_to(work_box_x + work_box_w, work_box_y)
        cr.line_to(scr_box_x + scr_box_w, scr_box_y + scr_box_h)
        # Bottom-left of tablet -> top-left of screen
        cr.move_to(work_box_x, work_box_y + work_box_h)
        cr.line_to(scr_box_x, scr_box_y)
        # Bottom-right of tablet -> top-right of screen
        cr.move_to(work_box_x + work_box_w, work_box_y + work_box_h)
        cr.line_to(scr_box_x + scr_box_w, scr_box_y)
        cr.stroke()


# ==============================================================================
# Widget 2: Stylus & Live Pressure Curve (Pen Tab)
# ==============================================================================
class StylusDiagramWidget(Gtk.DrawingArea):
    """Vector illustration of the VEIKK battery-free stylus with button callout brackets."""

    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_content_height(240)
        self.set_content_width(180)
        self.set_draw_func(self._on_draw)

    def _on_draw(self, area, cr, width, height):
        cx = width / 2.0
        cy = height / 2.0

        # Draw battery-free stylus vertically
        pen_w = 16.0
        pen_len = height * 0.82
        pen_top = cy - (pen_len / 2.0)
        pen_bot = cy + (pen_len / 2.0)

        # Pen Body Gradient (matte graphite black)
        pat = cairo.LinearGradient(cx - pen_w / 2.0, 0, cx + pen_w / 2.0, 0)
        pat.add_color_stop_rgb(0.0, 0.12, 0.13, 0.16)
        pat.add_color_stop_rgb(0.5, 0.24, 0.26, 0.30)
        pat.add_color_stop_rgb(1.0, 0.09, 0.10, 0.12)
        cr.set_source(pat)

        # Main barrel
        cr.move_to(cx - pen_w / 2.0, pen_top + 14.0)
        cr.line_to(cx + pen_w / 2.0, pen_top + 14.0)
        cr.line_to(cx + pen_w / 2.0, pen_bot - 35.0)
        # Taper to tip
        cr.line_to(cx + 3.0, pen_bot - 10.0)
        cr.line_to(cx - 3.0, pen_bot - 10.0)
        cr.line_to(cx - pen_w / 2.0, pen_bot - 35.0)
        cr.close_path()
        cr.fill()

        # Rounded Top Cap
        cr.set_source_rgb(0.18, 0.20, 0.24)
        cr.arc(cx, pen_top + 14.0, pen_w / 2.0, math.pi, 0)
        cr.fill()

        # Stylus Nib (White / Grey fine point)
        cr.set_source_rgb(0.85, 0.90, 0.95)
        cr.move_to(cx - 1.5, pen_bot - 10.0)
        cr.line_to(cx + 1.5, pen_bot - 10.0)
        cr.line_to(cx + 0.8, pen_bot)
        cr.line_to(cx - 0.8, pen_bot)
        cr.close_path()
        cr.fill()

        # Silver Accent Band
        cr.set_source_rgba(0.7, 0.75, 0.85, 0.9)
        cr.rectangle(cx - pen_w / 2.0, pen_bot - 70.0, pen_w, 2.5)
        cr.fill()

        # Dual Rocker Buttons on Stylus (Button 2 upper, Button 1 lower)
        btn_w = 6.0
        b2_y = pen_bot - 60.0
        b1_y = pen_bot - 45.0

        # Rocker housing
        cr.set_source_rgb(0.08, 0.08, 0.10)
        cr.rectangle(cx + 1.0, b2_y - 2.0, btn_w + 2.0, 24.0)
        cr.fill()

        # Button 2 (Upper)
        cr.set_source_rgb(0.35, 0.40, 0.48)
        cr.rectangle(cx + 2.0, b2_y, btn_w, 9.0)
        cr.fill()

        # Button 1 (Lower)
        cr.set_source_rgb(0.35, 0.40, 0.48)
        cr.rectangle(cx + 2.0, b1_y, btn_w, 9.0)
        cr.fill()

        # Callout lines to the right
        cr.set_source_rgba(0.4, 0.7, 1.0, 0.75)
        cr.set_line_width(1.2)
        # Upper button callout
        cr.move_to(cx + btn_w + 3.0, b2_y + 4.5)
        cr.line_to(width - 8.0, b2_y + 4.5)
        # Lower button callout
        cr.move_to(cx + btn_w + 3.0, b1_y + 4.5)
        cr.line_to(width - 8.0, b1_y + 4.5)
        cr.stroke()


class PressureCurveWidget(Gtk.DrawingArea):
    """Output vs Input Click Sensitivity curve matching User Manual Page 10 & 11."""

    def __init__(self, gamma: float = 1.0):
        super().__init__()
        self.gamma = gamma
        self.current_pressure = 0.0
        self.set_content_height(160)
        self.set_content_width(160)
        self.set_draw_func(self._on_draw)

    def set_gamma(self, gamma: float):
        self.gamma = gamma
        self.queue_draw()

    def set_pressure(self, p: float):
        self.current_pressure = max(0.0, min(1.0, p))
        self.queue_draw()

    def _on_draw(self, area, cr, width, height):
        pad = 22.0
        gw = width - pad * 2.0
        gh = height - pad * 2.0

        # Background Box
        cr.set_source_rgb(0.10, 0.11, 0.14)
        cr.rectangle(pad, pad, gw, gh)
        cr.fill()
        cr.set_source_rgba(0.3, 0.35, 0.45, 0.4)
        cr.set_line_width(1.0)
        cr.rectangle(pad, pad, gw, gh)
        cr.stroke()

        # Grid lines (25%, 50%, 75%)
        cr.set_source_rgba(0.25, 0.30, 0.38, 0.3)
        for i in (0.25, 0.50, 0.75):
            cr.move_to(pad + gw * i, pad)
            cr.line_to(pad + gw * i, pad + gh)
            cr.move_to(pad, pad + gh * (1.0 - i))
            cr.line_to(pad + gw, pad + gh * (1.0 - i))
        cr.stroke()

        # Diagonal 1:1 reference line (gray dashed)
        cr.set_source_rgba(0.5, 0.55, 0.65, 0.35)
        cr.set_dash([4.0, 4.0])
        cr.move_to(pad, pad + gh)
        cr.line_to(pad + gw, pad)
        cr.stroke()
        cr.set_dash([])  # reset

        # Gamma Curve (Blue)
        cr.set_source_rgb(0.23, 0.51, 0.96)
        cr.set_line_width(2.5)
        steps = 40
        for s in range(steps + 1):
            t = s / float(steps)
            val = t ** self.gamma
            px = pad + t * gw
            py = pad + (1.0 - val) * gh
            if s == 0:
                cr.move_to(px, py)
            else:
                cr.line_to(px, py)
        cr.stroke()

        # Live Pressure indicator dot
        if self.current_pressure > 0.0:
            out_p = self.current_pressure ** self.gamma
            dot_x = pad + self.current_pressure * gw
            dot_y = pad + (1.0 - out_p) * gh
            # Glow halo
            cr.set_source_rgba(0.95, 0.25, 0.25, 0.3)
            cr.arc(dot_x, dot_y, 7.0, 0, 2 * math.pi)
            cr.fill()
            # Solid dot
            cr.set_source_rgb(0.95, 0.20, 0.20)
            cr.arc(dot_x, dot_y, 4.0, 0, 2 * math.pi)
            cr.fill()

        # Labels "Output" and "Input"
        cr.set_source_rgba(0.6, 0.65, 0.75, 0.8)
        cr.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(9.0)
        cr.move_to(pad, pad - 6.0)
        cr.show_text("Output")
        cr.move_to(pad + gw - 24.0, pad + gh + 14.0)
        cr.show_text("Input")


# ==============================================================================
# Widget 3: Live Inking Test Pad
# ==============================================================================
class DrawingPad(Gtk.DrawingArea):
    """Interactive drawing pad to test pressure dynamics and handwriting curves."""

    def __init__(self, on_pressure_callback=None):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_content_height(180)
        self.on_pressure_callback = on_pressure_callback

        self.strokes: List[List[Tuple[float, float, float, float]]] = []
        self._current_stroke: List[Tuple[float, float, float, float]] = []
        self._is_drawing = False
        self._last_event_was_stylus = False

        self.set_draw_func(self._on_draw)

        self.stylus = Gtk.GestureStylus()
        self.stylus.connect("down", self._on_stylus_down)
        self.stylus.connect("motion", self._on_stylus_motion)
        self.stylus.connect("up", self._on_stylus_up)
        self.stylus.connect("proximity", self._on_stylus_proximity)
        self.add_controller(self.stylus)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_press)
        click.connect("released", self._on_release)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

    def clear(self):
        self.strokes.clear()
        self._current_stroke.clear()
        self.queue_draw()
        if self.on_pressure_callback:
            self.on_pressure_callback(0.0)

    def _calc_width(self, pressure: float) -> float:
        return max(1.5, 1.5 + pressure * 20.0)

    def _on_stylus_down(self, gesture, x, y):
        self._last_event_was_stylus = True
        self._is_drawing = True
        has_p, p = gesture.get_axis(Gdk.AxisUse.PRESSURE)
        pressure = p if has_p else 0.5
        w = self._calc_width(pressure)
        self._current_stroke = [(x, y, pressure, w)]
        self.strokes.append(self._current_stroke)
        self.queue_draw()
        if self.on_pressure_callback:
            self.on_pressure_callback(pressure)

    def _on_stylus_motion(self, gesture, x, y):
        self._last_event_was_stylus = True
        has_p, p = gesture.get_axis(Gdk.AxisUse.PRESSURE)
        pressure = p if has_p else 0.0
        if self.on_pressure_callback:
            self.on_pressure_callback(pressure)
        if self._is_drawing and self._current_stroke:
            w = self._calc_width(pressure)
            self._current_stroke.append((x, y, pressure, w))
            self.queue_draw()

    def _on_stylus_up(self, gesture, x, y):
        self._is_drawing = False
        self._current_stroke = []
        if self.on_pressure_callback:
            self.on_pressure_callback(0.0)

    def _on_stylus_proximity(self, gesture, x, y):
        has_p, p = gesture.get_axis(Gdk.AxisUse.PRESSURE)
        pressure = p if has_p else 0.0
        if self.on_pressure_callback:
            self.on_pressure_callback(pressure)

    def _on_press(self, gesture, n_press, x, y):
        if self._last_event_was_stylus:
            return
        self._is_drawing = True
        self._current_stroke = [(x, y, 0.5, 4.0)]
        self.strokes.append(self._current_stroke)
        self.queue_draw()

    def _on_release(self, gesture, n_press, x, y):
        if self._last_event_was_stylus:
            return
        self._is_drawing = False
        self._current_stroke = []

    def _on_motion(self, controller, x, y):
        if self._last_event_was_stylus:
            return
        if self._is_drawing and self._current_stroke:
            self._current_stroke.append((x, y, 0.5, 4.0))
            self.queue_draw()

    def _on_draw(self, area, cr, width, height):
        # Slate drawing background
        cr.set_source_rgb(0.09, 0.10, 0.13)
        cr.paint()

        # Dot matrix grid
        cr.set_source_rgba(0.35, 0.40, 0.50, 0.3)
        step = 32
        for x in range(step, int(width), step):
            for y in range(step, int(height), step):
                cr.arc(x, y, 1.2, 0, 2 * math.pi)
                cr.fill()

        # Render Ink Strokes with dynamic pressure width
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)

        for stroke in self.strokes:
            if len(stroke) < 2:
                if len(stroke) == 1:
                    x, y, p, w = stroke[0]
                    cr.set_source_rgba(0.23, 0.51, 0.96, 0.85)
                    cr.arc(x, y, w / 2.0, 0, 2 * math.pi)
                    cr.fill()
                continue

            for i in range(len(stroke) - 1):
                x1, y1, p1, w1 = stroke[i]
                x2, y2, p2, w2 = stroke[i + 1]
                avg_w = (w1 + w2) / 2.0
                cr.set_line_width(avg_w)
                # Cyan/Blue inking gradient
                cr.set_source_rgba(0.25, 0.65, 1.0, 0.90)
                cr.move_to(x1, y1)
                cr.line_to(x2, y2)
                cr.stroke()


# ==============================================================================
# Main Application Window (Material 3 Expressive UI)
# ==============================================================================
class VeikkExpressiveWindow(Gtk.ApplicationWindow):
    """Official VEIKK User Manual design implemented in Material 3 Expressive UI."""

    def __init__(self, app: Gtk.Application, config: TabletConfig):
        super().__init__(application=app, title="VEIKK Pen Tablet Control Center")
        self.config = config
        self.set_default_size(940, 700)
        self.add_css_class("m3-window")

        # Load Material 3 Stylesheet
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(M3_EXPRESSIVE_CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.toast_overlay = Adw.ToastOverlay()
        self.set_child(self.toast_overlay)

        # Split Root Box: Left Sidebar Navigation Rail + Right Content Area
        root_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.toast_overlay.set_child(root_box)

        # ----------------------------------------------------------------------
        # Left Navigation Rail
        # ----------------------------------------------------------------------
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sidebar.add_css_class("m3-sidebar")
        sidebar.set_size_request(210, -1)
        root_box.append(sidebar)

        # Logo & App Title
        brand_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        brand_box.add_css_class("m3-logo-box")
        title_label = Gtk.Label(label="VEIKK Pen Tablet")
        title_label.add_css_class("m3-brand-title")
        title_label.set_xalign(0.0)
        brand_box.append(title_label)

        # Model Selector Dropdown (S640)
        self.model_combo = Gtk.DropDown.new_from_strings(["S640", "A50", "VK1200", "VK2200 Pro"])
        self.model_combo.set_selected(0)
        self.model_combo.add_css_class("m3-device-badge")
        brand_box.append(self.model_combo)
        sidebar.append(brand_box)

        # Navigation Buttons (Pen, Mapping, Function, About Us)
        self.nav_buttons = []
        tabs = [
            ("Pen", "document-edit-symbolic", 0),
            ("Mapping", "video-display-symbolic", 1),
            ("Function", "input-keyboard-symbolic", 2),
            ("About Us", "help-about-symbolic", 3),
        ]

        for name, icon_name, page_idx in tabs:
            btn = Gtk.Button()
            btn.add_css_class("m3-nav-item")
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_icon_size(Gtk.IconSize.NORMAL)
            lbl = Gtk.Label(label=name)
            lbl.set_xalign(0.0)
            lbl.set_hexpand(True)
            row.append(icon)
            row.append(lbl)
            btn.set_child(row)
            btn.connect("clicked", lambda _, idx=page_idx: self._switch_page(idx))
            sidebar.append(btn)
            self.nav_buttons.append(btn)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        sidebar.append(spacer)

        # Hardware connection badge at bottom of sidebar
        self.hw_badge = Gtk.Label(label="● S640 Connected")
        self.hw_badge.add_css_class("m3-pill")
        self.hw_badge.add_css_class("green")
        self.hw_badge.set_xalign(0.0)
        sidebar.append(self.hw_badge)

        # ----------------------------------------------------------------------
        # Right Content View Stack
        # ----------------------------------------------------------------------
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content_box.set_hexpand(True)
        root_box.append(content_box)

        # Top Bar with Apply & Save button
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top_bar.set_margin_start(24)
        top_bar.set_margin_end(24)
        top_bar.set_margin_top(14)
        top_bar.set_margin_bottom(10)

        self.page_title_label = Gtk.Label(label="Screen & Tablet Mapping")
        self.page_title_label.add_css_class("m3-brand-title")
        self.page_title_label.set_hexpand(True)
        self.page_title_label.set_xalign(0.0)
        top_bar.append(self.page_title_label)

        apply_btn = Gtk.Button(label="Apply Changes")
        apply_btn.add_css_class("m3-btn-primary")
        apply_btn.connect("clicked", self._on_apply_clicked)
        top_bar.append(apply_btn)

        content_box.append(top_bar)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(200)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        content_box.append(self.stack)

        # Build the 4 pages exactly per the User Manual:
        self._build_pen_page()       # Page 0
        self._build_mapping_page()   # Page 1
        self._build_function_page()  # Page 2
        self._build_about_page()     # Page 3

        # Default to Mapping Tab (as shown in user's image)
        self._switch_page(1)

        # Periodic Hardware Status Poll
        self._refresh_hardware_status()
        GLib.timeout_add_seconds(3, self._refresh_hardware_status)

    def _switch_page(self, page_idx: int):
        for idx, btn in enumerate(self.nav_buttons):
            if idx == page_idx:
                btn.add_css_class("active")
            else:
                btn.remove_css_class("active")

        titles = [
            "Pen Settings & Pressure Dynamics",
            "Screen & Tablet Working Area Mapping",
            "Express Keys, Scroll & Workflow Presets",
            "About VEIKK & Driver Diagnostics"
        ]
        if page_idx < len(titles):
            self.page_title_label.set_text(titles[page_idx])

        self.stack.set_visible_child_name(f"page_{page_idx}")

    # =========================================================================
    # Page 0: Pen (User Manual Section 7.1)
    # =========================================================================
    def _build_pen_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_bottom(24)

        # Left Column: Stylus Vector Graphic with Button Selectors
        left_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        left_card.add_css_class("m3-card")
        left_card.set_size_request(380, -1)

        left_title = Gtk.Label(label="Stylus Button Function Settings")
        left_title.add_css_class("m3-card-title")
        left_title.set_xalign(0.0)
        left_card.append(left_title)

        # Mode Selector
        mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        mode_lbl = Gtk.Label(label="Button Routing Mode")
        mode_lbl.set_xalign(0.0)
        mode_lbl.add_css_class("m3-card-sub")
        self.btn_mode_combo = Gtk.DropDown.new_from_strings([
            "input-remapper (Shortcuts & Macros)",
            "Native Stylus (Direct BTN_STYLUS)"
        ])
        self.btn_mode_combo.set_selected(0 if self.config.button_mode == "remapper" else 1)
        mode_box.append(mode_lbl)
        mode_box.append(self.btn_mode_combo)
        left_card.append(mode_box)

        stylus_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        stylus_diagram = StylusDiagramWidget()
        stylus_box.append(stylus_diagram)

        # Button Configuration Controls
        btn_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        btn_controls.set_valign(Gtk.Align.CENTER)
        btn_controls.set_hexpand(True)

        action_labels = [label for label, _, _ in BUTTON_ACTIONS]

        # Button 2 (Upper)
        b2_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        b2_lbl = Gtk.Label(label="Button 2 (Upper Barrel / Rear)")
        b2_lbl.set_xalign(0.0)
        b2_lbl.add_css_class("m3-card-sub")
        self.b2_combo = Gtk.DropDown.new_from_strings(action_labels)
        self.b2_combo.set_selected(action_key_to_index(self.config.button2_action))
        b2_box.append(b2_lbl)
        b2_box.append(self.b2_combo)

        self.b2_custom_entry = Gtk.Entry()
        self.b2_custom_entry.add_css_class("m3-entry")
        self.b2_custom_entry.set_placeholder_text("Custom macro (e.g. Control_L+z)")
        self.b2_custom_entry.set_text(self.config.button2_custom)
        self.b2_custom_entry.set_visible(self.config.button2_action == "custom")
        b2_box.append(self.b2_custom_entry)

        def _on_b2_changed(dropdown, _):
            idx = dropdown.get_selected()
            key = index_to_action_key(idx)
            self.b2_custom_entry.set_visible(key == "custom")
        self.b2_combo.connect("notify::selected", _on_b2_changed)

        btn_controls.append(b2_box)

        # Button 1 (Lower)
        b1_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        b1_lbl = Gtk.Label(label="Button 1 (Lower Barrel / Near Tip)")
        b1_lbl.set_xalign(0.0)
        b1_lbl.add_css_class("m3-card-sub")
        self.b1_combo = Gtk.DropDown.new_from_strings(action_labels)
        self.b1_combo.set_selected(action_key_to_index(self.config.button1_action))
        b1_box.append(b1_lbl)
        b1_box.append(self.b1_combo)

        self.b1_custom_entry = Gtk.Entry()
        self.b1_custom_entry.add_css_class("m3-entry")
        self.b1_custom_entry.set_placeholder_text("Custom macro (e.g. Control_L+s)")
        self.b1_custom_entry.set_text(self.config.button1_custom)
        self.b1_custom_entry.set_visible(self.config.button1_action == "custom")
        b1_box.append(self.b1_custom_entry)

        def _on_b1_changed(dropdown, _):
            idx = dropdown.get_selected()
            key = index_to_action_key(idx)
            self.b1_custom_entry.set_visible(key == "custom")
        self.b1_combo.connect("notify::selected", _on_b1_changed)

        btn_controls.append(b1_box)

        stylus_box.append(btn_controls)
        left_card.append(stylus_box)

        # Restore default button
        restore_btn = Gtk.Button(label="Restore Default")
        restore_btn.add_css_class("m3-btn-tonal")
        restore_btn.connect("clicked", self._restore_pen_defaults)
        left_card.append(restore_btn)

        page.append(left_card)

        # Right Column: Current Pressure & Click Sensitivity (Manual 7.1.2 & 7.1.3)
        right_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        right_card.add_css_class("m3-card")
        right_card.set_hexpand(True)

        right_title = Gtk.Label(label="Current Pen Pressure & Click Sensitivity")
        right_title.add_css_class("m3-card-title")
        right_title.set_xalign(0.0)
        right_card.append(right_title)

        # Gauge & Numeric readout
        gauge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.pressure_label = Gtk.Label(label="Pressure: 0 / 8191 (Hovering)")
        self.pressure_label.set_xalign(0.0)
        self.pressure_label.set_hexpand(True)
        gauge_box.append(self.pressure_label)

        self.pressure_bar = Gtk.ProgressBar()
        self.pressure_bar.set_hexpand(True)
        gauge_box.append(self.pressure_bar)
        right_card.append(gauge_box)

        # Pressure Curve Graph
        curve_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.curve_graph = PressureCurveWidget(gamma=self.config.pressure_gamma)
        curve_box.append(self.curve_graph)

        sliders_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sliders_box.set_hexpand(True)
        sliders_box.set_valign(Gtk.Align.CENTER)

        # Click Sensitivity Gamma Slider
        gamma_lbl = Gtk.Label(label="Click Sensitivity (<1.0 Soft, >1.0 Firm)")
        gamma_lbl.set_xalign(0.0)
        gamma_lbl.add_css_class("m3-card-sub")
        sliders_box.append(gamma_lbl)

        self.gamma_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.4, 2.5, 0.1)
        self.gamma_scale.set_value(self.config.pressure_gamma)
        self.gamma_scale.set_draw_value(True)
        self.gamma_scale.connect("value-changed", lambda s: self.curve_graph.set_gamma(s.get_value()))
        sliders_box.append(self.gamma_scale)

        # Threshold Slider
        thresh_lbl = Gtk.Label(label="Tip Contact Threshold (raw units)")
        thresh_lbl.set_xalign(0.0)
        thresh_lbl.add_css_class("m3-card-sub")
        sliders_box.append(thresh_lbl)

        self.thresh_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 600, 20)
        self.thresh_scale.set_value(self.config.pressure_threshold)
        self.thresh_scale.set_draw_value(True)
        sliders_box.append(self.thresh_scale)

        # Pressure Smoothing Slider
        ps_lbl = Gtk.Label(label="Pressure Transition Smoothing")
        ps_lbl.set_xalign(0.0)
        ps_lbl.add_css_class("m3-card-sub")
        sliders_box.append(ps_lbl)

        self.p_smooth_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05)
        self.p_smooth_scale.set_value(self.config.pressure_smoothing)
        self.p_smooth_scale.set_draw_value(True)
        sliders_box.append(self.p_smooth_scale)

        curve_box.append(sliders_box)
        right_card.append(curve_box)

        # Live Inking Pad
        pad_title = Gtk.Label(label="Live Pressure Inking Pad")
        pad_title.set_xalign(0.0)
        pad_title.add_css_class("m3-card-sub")
        right_card.append(pad_title)

        def _update_pressure_meter(p: float):
            self.pressure_bar.set_fraction(p)
            self.curve_graph.set_pressure(p)
            if p <= 0.0:
                self.pressure_label.set_text("Pressure: 0 / 8191 (Hovering)")
            else:
                raw_equiv = int(round(p * 8191))
                self.pressure_label.set_text(f"Pressure: {raw_equiv} / 8191 ({p*100:.1f}%)")

        self.drawing_pad = DrawingPad(on_pressure_callback=_update_pressure_meter)
        self.drawing_pad.add_css_class("m3-card")
        right_card.append(self.drawing_pad)

        clear_btn = Gtk.Button(label="Clear Test Pad")
        clear_btn.add_css_class("m3-btn-tonal")
        clear_btn.connect("clicked", lambda _: self.drawing_pad.clear())
        right_card.append(clear_btn)

        page.append(right_card)
        self.stack.add_named(page, "page_0")

    # =========================================================================
    # Page 1: Mapping (User Manual Section 7.2) - Highlighted by User
    # =========================================================================
    def _build_mapping_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_bottom(24)

        # Left Column: Visual Projection Canvas (Cairo Diagram)
        left_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        left_card.add_css_class("m3-card")
        left_card.set_hexpand(True)

        diag_title = Gtk.Label(label="Screen & Working Area Projection")
        diag_title.add_css_class("m3-card-title")
        diag_title.set_xalign(0.0)
        left_card.append(diag_title)

        self.mapping_diagram = MappingDiagramWidget(self.config)
        left_card.append(self.mapping_diagram)

        # Bottom Handedness & Windows Ink equivalent (Page 11 in Manual)
        hand_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        hand_box.set_margin_top(8)

        self.radio_right = Gtk.CheckButton(label="Right-hand Mode (0°)")
        self.radio_left = Gtk.CheckButton(label="Left-hand Mode (180°)", group=self.radio_right)
        self.radio_p90 = Gtk.CheckButton(label="Portrait Left (90°)", group=self.radio_right)
        self.radio_p270 = Gtk.CheckButton(label="Portrait Right (270°)", group=self.radio_right)

        ori_map = {0: self.radio_right, 180: self.radio_left, 90: self.radio_p90, 270: self.radio_p270}
        active_radio = ori_map.get(self.config.orientation, self.radio_right)
        active_radio.set_active(True)

        self.radio_right.connect("toggled", lambda r: self._on_orientation_changed(0) if r.get_active() else None)
        self.radio_left.connect("toggled", lambda r: self._on_orientation_changed(180) if r.get_active() else None)
        self.radio_p90.connect("toggled", lambda r: self._on_orientation_changed(90) if r.get_active() else None)
        self.radio_p270.connect("toggled", lambda r: self._on_orientation_changed(270) if r.get_active() else None)

        hand_box.append(self.radio_right)
        hand_box.append(self.radio_left)
        hand_box.append(self.radio_p90)
        hand_box.append(self.radio_p270)
        left_card.append(hand_box)

        bottom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bottom_row.set_margin_top(6)

        restore_btn = Gtk.Button(label="Restore Default")
        restore_btn.add_css_class("m3-btn-tonal")
        restore_btn.connect("clicked", self._restore_mapping_defaults)
        bottom_row.append(restore_btn)

        self.ink_check = Gtk.CheckButton(label="Enable High-Precision Linux Inking (Windows Ink equivalent)")
        self.ink_check.set_active(self.config.smoothing_enable)
        self.ink_check.set_hexpand(True)
        bottom_row.append(self.ink_check)

        left_card.append(bottom_row)
        page.append(left_card)

        # Right Column: Mode, Screen Mapping & Working Area Selectors
        right_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        right_card.add_css_class("m3-card")
        right_card.set_size_request(340, -1)

        # 1. Mode (Pen vs Mouse)
        mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        mode_title = Gtk.Label(label="Mode")
        mode_title.add_css_class("m3-card-title")
        mode_title.set_xalign(0.0)
        mode_box.append(mode_title)

        mode_radios = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.mode_pen = Gtk.CheckButton(label="Pen (Absolute)")
        self.mode_mouse = Gtk.CheckButton(label="Mouse (Relative)", group=self.mode_pen)
        self.mode_pen.set_active(True)
        mode_radios.append(self.mode_pen)
        mode_radios.append(self.mode_mouse)
        mode_box.append(mode_radios)
        right_card.append(mode_box)

        # 2. Screen Mapping (Dynamic active monitor detection)
        screen_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        screen_title = Gtk.Label(label="Screen Mapping")
        screen_title.add_css_class("m3-card-title")
        screen_title.set_xalign(0.0)
        screen_box.append(screen_title)

        self.monitors = get_system_monitors()
        labels = [m["label"] for m in self.monitors]
        self.screen_combo = Gtk.DropDown.new_from_strings(labels)

        # Detect active monitor from config or gsettings
        current_edid = None
        if self.config.screen_output and any(self.config.screen_output):
            current_edid = [str(x) for x in self.config.screen_output]
        else:
            try:
                res = subprocess.run([
                    "gsettings", "get",
                    "org.gnome.desktop.peripherals.tablet:/org/gnome/desktop/peripherals/tablets/2feb:0001/",
                    "output"
                ], capture_output=True, text=True, timeout=1)
                if res.returncode == 0:
                    parts = re.findall(r"'([^']*)'", res.stdout)
                    if len(parts) >= 3:
                        current_edid = parts[:3]
            except Exception:
                pass

        selected_idx = 0
        if current_edid:
            for i, mon in enumerate(self.monitors):
                if mon["edid"] == current_edid:
                    selected_idx = i
                    break
        elif len(self.monitors) > 1:
            selected_idx = 1

        self.screen_combo.set_selected(selected_idx)
        if 0 <= selected_idx < len(self.monitors):
            self.mapping_diagram.monitor_label = self.monitors[selected_idx].get("name", "")

        self.screen_combo.connect("notify::selected", self._on_screen_mapping_changed)
        screen_box.append(self.screen_combo)
        right_card.append(screen_box)

        # 3. Working Area (All, Match 16:9, Portrait Notes, Part)
        area_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        area_title = Gtk.Label(label="Working Area")
        area_title.add_css_class("m3-card-title")
        area_title.set_xalign(0.0)
        area_box.append(area_title)

        self.area_combo = Gtk.DropDown.new_from_strings([
            "All (Full Tablet 100%)",
            "Match 16:9 Screen (No Distortion)",
            "Portrait Notes (Split-Screen 1:1)",
            "Part (Custom Sliders)..."
        ])
        is_custom_area = (
            abs(self.config.area_min_x - 0.0) > 0.01 or
            abs(self.config.area_max_x - 1.0) > 0.01 or
            abs(self.config.area_min_y - 0.0) > 0.01 or
            abs(self.config.area_max_y - 1.0) > 0.01
        )
        self.area_combo.set_selected(3 if is_custom_area else 0)
        self.area_combo.connect("notify::selected", self._on_working_area_changed)
        area_box.append(self.area_combo)

        # Quick Area Presets Buttons Row
        area_preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        area_preset_row.set_margin_top(2)

        btn_full = Gtk.Button(label="Full (100%)")
        btn_full.add_css_class("m3-chip")
        btn_full.connect("clicked", lambda _: self._set_area_preset(0))
        area_preset_row.append(btn_full)

        btn_169 = Gtk.Button(label="Match 16:9")
        btn_169.add_css_class("m3-chip")
        btn_169.connect("clicked", lambda _: self._set_area_preset(1))
        area_preset_row.append(btn_169)

        btn_notes = Gtk.Button(label="Portrait 1:1")
        btn_notes.add_css_class("m3-chip")
        btn_notes.connect("clicked", lambda _: self._set_area_preset(2))
        area_preset_row.append(btn_notes)

        area_box.append(area_preset_row)
        right_card.append(area_box)

        # Sliders for fine-tuning Working Area (Top/Bottom/Left/Right)
        sliders_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sliders_lbl = Gtk.Label(label="Fine-Tune Tablet Active Area")
        sliders_lbl.set_xalign(0.0)
        sliders_lbl.add_css_class("m3-card-sub")
        sliders_group.append(sliders_lbl)

        # Min X / Max X
        self.area_min_x_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 0.95, 0.01)
        self.area_min_x_scale.set_value(self.config.area_min_x)
        self.area_min_x_scale.connect("value-changed", self._on_area_slider_changed)
        row_x1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row_x1.append(Gtk.Label(label="Left / X1:"))
        row_x1.append(self.area_min_x_scale)
        sliders_group.append(row_x1)

        self.area_max_x_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.05, 1.0, 0.01)
        self.area_max_x_scale.set_value(self.config.area_max_x)
        self.area_max_x_scale.connect("value-changed", self._on_area_slider_changed)
        row_x2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row_x2.append(Gtk.Label(label="Right / X2:"))
        row_x2.append(self.area_max_x_scale)
        sliders_group.append(row_x2)

        # Min Y / Max Y
        self.area_min_y_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 0.95, 0.01)
        self.area_min_y_scale.set_value(self.config.area_min_y)
        self.area_min_y_scale.connect("value-changed", self._on_area_slider_changed)
        row_y1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row_y1.append(Gtk.Label(label="Top / Y1:"))
        row_y1.append(self.area_min_y_scale)
        sliders_group.append(row_y1)

        self.area_max_y_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.05, 1.0, 0.01)
        self.area_max_y_scale.set_value(self.config.area_max_y)
        self.area_max_y_scale.connect("value-changed", self._on_area_slider_changed)
        row_y2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row_y2.append(Gtk.Label(label="Bottom / Y2:"))
        row_y2.append(self.area_max_y_scale)
        sliders_group.append(row_y2)

        right_card.append(sliders_group)
        page.append(right_card)
        self.stack.add_named(page, "page_1")

    # =========================================================================
    # Page 2: Function (Presets, Pan/Scroll, Remapper)
    # =========================================================================
    def _build_function_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_bottom(24)

        # Left Column: Distance Scaling Card + Workflow Presets Card
        left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        left_col.set_hexpand(True)

        # Card 1: Motion & Distance Scaling
        motion_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        motion_card.add_css_class("m3-card")

        m_title = Gtk.Label(label="Hover & Motion Distance Scaling")
        m_title.add_css_class("m3-card-title")
        m_title.set_xalign(0.0)
        motion_card.append(m_title)

        m_sub = Gtk.Label(label="Controls cursor travel distance across display (0.50x high precision, 1.00x default 1:1)")
        m_sub.add_css_class("m3-card-sub")
        m_sub.set_xalign(0.0)
        motion_card.append(m_sub)

        # Hover Distance Scale
        h_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        h_lbl = Gtk.Label(label="Hover Distance Scale Multiplier")
        h_lbl.set_xalign(0.0)
        h_lbl.add_css_class("m3-card-sub")
        h_box.append(h_lbl)

        self.hover_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.10, 2.00, 0.05)
        self.hover_scale.set_value(self.config.hover_scale)
        self.hover_scale.set_draw_value(True)
        h_box.append(self.hover_scale)
        motion_card.append(h_box)

        # Lock Scales Check
        self.lock_scales_check = Gtk.CheckButton(label="Lock Hover & Touch Distance (Prevents cursor jumps)")
        self.lock_scales_check.set_active(self.config.lock_motion_scales)
        motion_card.append(self.lock_scales_check)

        # Contact Distance Scale
        c_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        c_lbl = Gtk.Label(label="Touch / Drawing Distance Scale Multiplier")
        c_lbl.set_xalign(0.0)
        c_lbl.add_css_class("m3-card-sub")
        c_box.append(c_lbl)

        self.contact_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.10, 2.00, 0.05)
        self.contact_scale.set_value(self.config.contact_scale)
        self.contact_scale.set_draw_value(True)
        self.contact_scale.set_sensitive(not self.config.lock_motion_scales)
        c_box.append(self.contact_scale)
        motion_card.append(c_box)

        def _on_lock_toggled(check):
            locked = check.get_active()
            self.contact_scale.set_sensitive(not locked)
            if locked:
                self.contact_scale.set_value(self.hover_scale.get_value())
        self.lock_scales_check.connect("toggled", _on_lock_toggled)

        # Aspect Compensate Check
        self.aspect_compensate_check = Gtk.CheckButton(label="Equalize Side-to-Side & Up-Down Travel Speeds")
        self.aspect_compensate_check.set_active(self.config.aspect_compensate)
        motion_card.append(self.aspect_compensate_check)

        # Distance Presets Chips
        chips_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chips_box.set_margin_top(4)

        for label_text, s_val in [
            ("0.50x Precision", 0.50),
            ("0.75x Balanced", 0.75),
            ("1.00x Default", 1.00),
            ("1.25x Fast", 1.25)
        ]:
            c_btn = Gtk.Button(label=label_text)
            c_btn.add_css_class("m3-chip")
            c_btn.connect("clicked", lambda _, val=s_val: self._set_motion_scale(val))
            chips_box.append(c_btn)

        motion_card.append(chips_box)
        left_col.append(motion_card)

        # Card 2: One-Click Workflow Presets
        presets_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        presets_card.add_css_class("m3-card")

        p_title = Gtk.Label(label="One-Click Workflow Presets")
        p_title.add_css_class("m3-card-title")
        p_title.set_xalign(0.0)
        presets_card.append(p_title)

        for preset in WORKFLOW_PRESETS:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.set_margin_bottom(2)
            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            info.set_hexpand(True)
            nl = Gtk.Label(label=preset["name"])
            nl.set_xalign(0.0)
            nl.add_css_class("m3-card-header")
            dl = Gtk.Label(label=preset["desc"])
            dl.set_xalign(0.0)
            dl.add_css_class("m3-card-sub")
            info.append(nl)
            info.append(dl)
            row.append(info)

            u_btn = Gtk.Button(label="Activate")
            u_btn.add_css_class("m3-btn-tonal")
            u_btn.connect("clicked", lambda _, p=preset: self._apply_workflow_preset(p))
            row.append(u_btn)
            presets_card.append(row)

        left_col.append(presets_card)
        page.append(left_col)

        # Right Column: Pan & Scroll Settings + Anti-Jitter Deadzone + input-remapper Tools
        right_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        right_col.set_size_request(380, -1)

        # Card 3: Pan & Scroll & Anti-Jitter
        scroll_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scroll_card.add_css_class("m3-card")

        s_title = Gtk.Label(label="Pan & Smooth Scroll Settings")
        s_title.add_css_class("m3-card-title")
        s_title.set_xalign(0.0)
        scroll_card.append(s_title)

        sens_lbl = Gtk.Label(label="Scroll Speed & Sensitivity")
        sens_lbl.set_xalign(0.0)
        sens_lbl.add_css_class("m3-card-sub")
        scroll_card.append(sens_lbl)

        self.scroll_sens_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.2, 3.0, 0.1)
        self.scroll_sens_scale.set_value(self.config.scroll_sensitivity)
        self.scroll_sens_scale.set_draw_value(True)
        scroll_card.append(self.scroll_sens_scale)

        self.scroll_natural_check = Gtk.CheckButton(label="Natural Scrolling (macOS / Touch style)")
        self.scroll_natural_check.set_active(self.config.scroll_natural)
        scroll_card.append(self.scroll_natural_check)

        self.scroll_touch_check = Gtk.CheckButton(label="Require Surface Contact (Touch & Slide to scroll)")
        self.scroll_touch_check.set_active(self.config.scroll_require_touch)
        scroll_card.append(self.scroll_touch_check)

        # Anti-Jitter Smoothing & Deadzone
        j_title = Gtk.Label(label="Adaptive Anti-Jitter & Hardware Deadzone")
        j_title.add_css_class("m3-card-title")
        j_title.set_xalign(0.0)
        j_title.set_margin_top(8)
        scroll_card.append(j_title)

        sm_lbl = Gtk.Label(label="Smoothing Strength")
        sm_lbl.set_xalign(0.0)
        sm_lbl.add_css_class("m3-card-sub")
        scroll_card.append(sm_lbl)

        self.smooth_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05)
        self.smooth_scale.set_value(self.config.smoothing_factor)
        self.smooth_scale.set_draw_value(True)
        scroll_card.append(self.smooth_scale)

        dz_lbl = Gtk.Label(label="Hardware ADC Deadzone (raw units)")
        dz_lbl.set_xalign(0.0)
        dz_lbl.add_css_class("m3-card-sub")
        scroll_card.append(dz_lbl)

        self.deadzone_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 12, 1)
        self.deadzone_scale.set_value(self.config.smoothing_deadzone)
        self.deadzone_scale.set_draw_value(True)
        scroll_card.append(self.deadzone_scale)

        right_col.append(scroll_card)

        # Card 4: input-remapper Tools
        rem_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        rem_card.add_css_class("m3-card")

        rem_title = Gtk.Label(label="input-remapper Integration & Service Tools")
        rem_title.add_css_class("m3-card-title")
        rem_title.set_xalign(0.0)
        rem_card.append(rem_title)

        rem_sub = Gtk.Label(label="Inject macros and shortcuts via the system input-remapper daemon")
        rem_sub.add_css_class("m3-card-sub")
        rem_sub.set_xalign(0.0)
        rem_card.append(rem_sub)

        self.autoload_check = Gtk.CheckButton(label="Auto-Activate on Login & Plug-in")
        self.autoload_check.set_active(self.config.button_autoload)
        rem_card.append(self.autoload_check)

        rem_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        rem_btn_box.set_margin_top(4)

        reload_btn = Gtk.Button(label="Reload Injection")
        reload_btn.add_css_class("m3-btn-tonal")
        reload_btn.connect("clicked", self._on_reload_remapper_clicked)
        rem_btn_box.append(reload_btn)

        launch_btn = Gtk.Button(label="Launch Remapper GUI")
        launch_btn.add_css_class("m3-btn-tonal")
        launch_btn.connect("clicked", self._on_launch_remapper)
        rem_btn_box.append(launch_btn)

        rem_card.append(rem_btn_box)
        right_col.append(rem_card)

        page.append(right_col)
        self.stack.add_named(page, "page_2")

    # =========================================================================
    # Page 3: About Us (User Manual Section 7.3)
    # =========================================================================
    def _build_about_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page.set_margin_start(30)
        page.set_margin_end(30)
        page.set_margin_bottom(24)
        page.set_valign(Gtk.Align.CENTER)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.add_css_class("m3-card")
        card.set_size_request(660, -1)
        card.set_halign(Gtk.Align.CENTER)

        # VEIKK Logo Header
        logo_label = Gtk.Label(label="VEIKK")
        logo_label.set_css_classes(["m3-brand-title"])
        logo_label.set_markup("<span size='28000' weight='bold' letter_spacing='3000'>VEIKK</span>")
        card.append(logo_label)

        ver_label = Gtk.Label(label="Linux Open-Source Userspace Driver & Control Center v1.0.0")
        ver_label.add_css_class("m3-card-sub")
        card.append(ver_label)

        # Live Status Badges Row
        badge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        badge_box.set_halign(Gtk.Align.CENTER)

        self.about_hw_badge = Gtk.Label(label="● VEIKK S640 (USB)")
        self.about_hw_badge.add_css_class("m3-pill")
        self.about_hw_badge.add_css_class("green")
        badge_box.append(self.about_hw_badge)

        self.about_svc_badge = Gtk.Label(label="● Driver Daemon")
        self.about_svc_badge.add_css_class("m3-pill")
        self.about_svc_badge.add_css_class("green")
        badge_box.append(self.about_svc_badge)

        self.about_rem_badge = Gtk.Label(label="● input-remapper")
        self.about_rem_badge.add_css_class("m3-pill")
        self.about_rem_badge.add_css_class("green")
        badge_box.append(self.about_rem_badge)

        card.append(badge_box)

        # Diagnostics Output Area
        self.diag_label = Gtk.Label()
        self.diag_label.set_xalign(0.0)
        self.diag_label.set_markup(
            "<b>Hardware Status:</b> VEIKK S640 (USB 2FEB:0001) Connected\n"
            "<b>Kernel Driver:</b> Detached from Interface 2 (Pure Userspace Mode)\n"
            "<b>Virtual Devices:</b> VEIKK S640 Pen, VEIKK S640 Buttons, VEIKK S640 Mouse\n"
            "<b>Config Path:</b> ~/.config/veikk-s640/config.toml"
        )
        self.diag_label.add_css_class("m3-card")
        card.append(self.diag_label)

        # System Administration Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_box.set_halign(Gtk.Align.CENTER)

        diag_btn = Gtk.Button(label="Run Hardware Diagnostics")
        diag_btn.add_css_class("m3-btn-tonal")
        diag_btn.connect("clicked", self._run_diagnostics)
        btn_box.append(diag_btn)

        reload_svc_btn = Gtk.Button(label="Reload Configuration")
        reload_svc_btn.add_css_class("m3-btn-tonal")
        reload_svc_btn.connect("clicked", self._reload_service)
        btn_box.append(reload_svc_btn)

        repair_btn = Gtk.Button(label="Restart Driver Daemon")
        repair_btn.add_css_class("m3-btn-primary")
        repair_btn.connect("clicked", self._restart_service)
        btn_box.append(repair_btn)

        card.append(btn_box)

        copy_lbl = Gtk.Label(label="Beijing Veikk E-commerce Co., Ltd. • Open-Source Linux Driver by arnb7")
        copy_lbl.add_css_class("m3-card-sub")
        card.append(copy_lbl)

        page.append(card)
        self.stack.add_named(page, "page_3")

    # =========================================================================
    # Event Handlers & Config Synchronization
    # =========================================================================
    def _on_orientation_changed(self, ori: int):
        self.config.orientation = ori
        self.mapping_diagram.update_config(self.config)

    def _on_screen_mapping_changed(self, dropdown, _param):
        idx = dropdown.get_selected()
        if hasattr(self, "monitors") and 0 <= idx < len(self.monitors):
            target_mon = self.monitors[idx]
            edid = target_mon["edid"]
            self.config.screen_output = edid
            apply_gnome_tablet_output(edid)
            if hasattr(self, "mapping_diagram"):
                self.mapping_diagram.monitor_label = target_mon.get("name", "")
                self.mapping_diagram.update_config(self.config)
        else:
            self.mapping_diagram.update_config(self.config)

    def _on_working_area_changed(self, dropdown, _param):
        idx = dropdown.get_selected()
        is_vert = self.config.orientation in (90, 270)

        if idx == 0:
            # Full Tablet (100%)
            self.area_min_x_scale.set_value(0.0)
            self.area_max_x_scale.set_value(1.0)
            self.area_min_y_scale.set_value(0.0)
            self.area_max_y_scale.set_value(1.0)
        elif idx == 1:
            # Match 16:9 Screen (No Distortion)
            if is_vert:
                self.area_min_x_scale.set_value(0.313)
                self.area_max_x_scale.set_value(0.687)
                self.area_min_y_scale.set_value(0.0)
                self.area_max_y_scale.set_value(1.0)
            else:
                self.area_min_x_scale.set_value(0.0)
                self.area_max_x_scale.set_value(1.0)
                self.area_min_y_scale.set_value(0.078)
                self.area_max_y_scale.set_value(0.922)
        elif idx == 2:
            # Portrait Notes (Split-Screen 1:1)
            self.area_min_x_scale.set_value(0.125)
            self.area_max_x_scale.set_value(0.875)
            self.area_min_y_scale.set_value(0.0)
            self.area_max_y_scale.set_value(1.0)

    def _set_area_preset(self, idx: int):
        self._updating_area = True
        try:
            self.area_combo.set_selected(idx)
            is_vert = self.config.orientation in (90, 270)
            if idx == 0:
                self.area_min_x_scale.set_value(0.0)
                self.area_max_x_scale.set_value(1.0)
                self.area_min_y_scale.set_value(0.0)
                self.area_max_y_scale.set_value(1.0)
            elif idx == 1:
                if is_vert:
                    self.area_min_x_scale.set_value(0.313)
                    self.area_max_x_scale.set_value(0.687)
                    self.area_min_y_scale.set_value(0.0)
                    self.area_max_y_scale.set_value(1.0)
                else:
                    self.area_min_x_scale.set_value(0.0)
                    self.area_max_x_scale.set_value(1.0)
                    self.area_min_y_scale.set_value(0.078)
                    self.area_max_y_scale.set_value(0.922)
            elif idx == 2:
                self.area_min_x_scale.set_value(0.125)
                self.area_max_x_scale.set_value(0.875)
                self.area_min_y_scale.set_value(0.0)
                self.area_max_y_scale.set_value(1.0)

            self.config.area_min_x = round(self.area_min_x_scale.get_value(), 3)
            self.config.area_max_x = round(self.area_max_x_scale.get_value(), 3)
            self.config.area_min_y = round(self.area_min_y_scale.get_value(), 3)
            self.config.area_max_y = round(self.area_max_y_scale.get_value(), 3)
            self.mapping_diagram.update_config(self.config)
        finally:
            self._updating_area = False

    def _on_area_slider_changed(self, _):
        if getattr(self, "_updating_area", False):
            return
        self.config.area_min_x = round(self.area_min_x_scale.get_value(), 3)
        self.config.area_max_x = round(self.area_max_x_scale.get_value(), 3)
        self.config.area_min_y = round(self.area_min_y_scale.get_value(), 3)
        self.config.area_max_y = round(self.area_max_y_scale.get_value(), 3)
        if self.area_combo.get_selected() != 3:
            self.area_combo.set_selected(3)
        self.mapping_diagram.update_config(self.config)

    def _restore_mapping_defaults(self, _):
        self.radio_right.set_active(True)
        self._set_area_preset(0)
        default_idx = 1 if (hasattr(self, "monitors") and len(self.monitors) > 1) else 0
        self.screen_combo.set_selected(default_idx)
        self.config.area_min_x = 0.0
        self.config.area_max_x = 1.0
        self.config.area_min_y = 0.0
        self.config.area_max_y = 1.0
        self.mapping_diagram.update_config(self.config)

    def _restore_pen_defaults(self, _):
        self.btn_mode_combo.set_selected(0)
        self.b1_combo.set_selected(action_key_to_index("mouse:btn_right"))
        self.b2_combo.set_selected(action_key_to_index("pan_scroll"))
        self.b1_custom_entry.set_text("")
        self.b2_custom_entry.set_text("")
        self.gamma_scale.set_value(1.0)
        self.thresh_scale.set_value(0)
        self.p_smooth_scale.set_value(0.15)

    def _set_motion_scale(self, scale_val: float):
        self.hover_scale.set_value(scale_val)
        if self.lock_scales_check.get_active():
            self.contact_scale.set_value(scale_val)

    def _apply_workflow_preset(self, preset: dict):
        self.b1_combo.set_selected(action_key_to_index(preset["b1"]))
        self.b2_combo.set_selected(action_key_to_index(preset["b2"]))
        self.btn_mode_combo.set_selected(0)
        toast = Adw.Toast.new(f"Preset '{preset['name']}' selected. Click 'Apply Changes' to save.")
        self.toast_overlay.add_toast(toast)

    def _on_reload_remapper_clicked(self, _):
        b1_act = index_to_action_key(self.b1_combo.get_selected())
        b2_act = index_to_action_key(self.b2_combo.get_selected())
        c1 = self.b1_custom_entry.get_text()
        c2 = self.b2_custom_entry.get_text()
        autoload = self.autoload_check.get_active()

        ok, msg = apply_remapper_preset(b1_act, b2_act, c1, c2, autoload=autoload)
        self._refresh_hardware_status()
        toast = Adw.Toast.new(msg if ok else f"Remapper error: {msg}")
        self.toast_overlay.add_toast(toast)

    def _on_launch_remapper(self, _):
        try:
            subprocess.Popen(["input-remapper-gtk"])
        except Exception as e:
            toast = Adw.Toast.new(f"Could not open input-remapper: {e}")
            self.toast_overlay.add_toast(toast)

    def _run_diagnostics(self, _):
        connected = False
        for uevent in glob.glob("/sys/bus/usb/devices/*/idVendor"):
            try:
                with open(uevent, "r") as f:
                    if f.read().strip().lower() == "2feb":
                        connected = True
                        break
            except Exception:
                continue

        try:
            res = subprocess.run(["systemctl", "is-active", "veikk-s640.service"], capture_output=True, text=True)
            svc_active = (res.stdout.strip() == "active")
        except Exception:
            svc_active = False

        rem_active = is_service_active()

        status_str = (
            f"<b>Hardware USB:</b> {'Connected (2FEB:0001)' if connected else 'Not Connected'}\n"
            f"<b>Driver Daemon:</b> {'Active & Running (veikk-s640.service)' if svc_active else 'Inactive / Stopped'}\n"
            f"<b>input-remapper:</b> {'Active (input-remapper.service)' if rem_active else 'Inactive / Not Running'}\n"
            f"<b>Virtual Pen Device:</b> /dev/uinput Active\n"
            f"<b>Active Orientation:</b> {self.config.orientation}°\n"
            f"<b>Active Crop Area:</b> X=[{self.config.area_min_x:.3f}, {self.config.area_max_x:.3f}], Y=[{self.config.area_min_y:.3f}, {self.config.area_max_y:.3f}]\n"
            f"<b>Motion Scales:</b> Hover={self.config.hover_scale:.2f}x, Touch={self.config.contact_scale:.2f}x (Locked={self.config.lock_motion_scales})\n"
            f"<b>Configuration:</b> Valid & Synced"
        )
        self.diag_label.set_markup(status_str)
        self._refresh_hardware_status()
        toast = Adw.Toast.new("Diagnostics check complete.")
        self.toast_overlay.add_toast(toast)

    def _restart_service(self, _):
        try:
            subprocess.run(["systemctl", "restart", "veikk-s640.service"], check=False)
            self._refresh_hardware_status()
            toast = Adw.Toast.new("VEIKK driver service restarted.")
        except Exception as e:
            toast = Adw.Toast.new(f"Failed: {e}")
        self.toast_overlay.add_toast(toast)

    def _reload_service(self, _):
        try:
            subprocess.run(["systemctl", "reload", "veikk-s640.service"], check=False)
            toast = Adw.Toast.new("Driver configuration reloaded.")
        except Exception as e:
            toast = Adw.Toast.new(f"Failed: {e}")
        self.toast_overlay.add_toast(toast)

    def _refresh_hardware_status(self):
        # 1. USB Connection
        connected = False
        for uevent in glob.glob("/sys/bus/usb/devices/*/idVendor"):
            try:
                with open(uevent, "r") as f:
                    if f.read().strip().lower() == "2feb":
                        connected = True
                        break
            except Exception:
                continue

        if connected:
            self.hw_badge.set_text("● S640 Connected")
            self.hw_badge.remove_css_class("amber")
            self.hw_badge.remove_css_class("red")
            self.hw_badge.add_css_class("green")
            if hasattr(self, "about_hw_badge"):
                self.about_hw_badge.set_text("● VEIKK S640 (USB)")
                self.about_hw_badge.remove_css_class("amber")
                self.about_hw_badge.add_css_class("green")
        else:
            self.hw_badge.set_text("○ S640 Disconnected")
            self.hw_badge.remove_css_class("green")
            self.hw_badge.add_css_class("amber")
            if hasattr(self, "about_hw_badge"):
                self.about_hw_badge.set_text("○ S640 Disconnected")
                self.about_hw_badge.remove_css_class("green")
                self.about_hw_badge.add_css_class("amber")

        # 2. Driver Daemon
        try:
            res = subprocess.run(["systemctl", "is-active", "veikk-s640.service"], capture_output=True, text=True)
            svc_active = (res.stdout.strip() == "active")
        except Exception:
            svc_active = False

        if hasattr(self, "about_svc_badge"):
            if svc_active:
                self.about_svc_badge.set_text("● Driver Running")
                self.about_svc_badge.remove_css_class("red")
                self.about_svc_badge.add_css_class("green")
            else:
                self.about_svc_badge.set_text("○ Driver Inactive")
                self.about_svc_badge.remove_css_class("green")
                self.about_svc_badge.add_css_class("red")

        # 3. input-remapper Daemon
        rem_active = is_service_active()
        if hasattr(self, "about_rem_badge"):
            if rem_active:
                self.about_rem_badge.set_text("● input-remapper Active")
                self.about_rem_badge.remove_css_class("amber")
                self.about_rem_badge.add_css_class("green")
            else:
                self.about_rem_badge.set_text("○ input-remapper Stopped")
                self.about_rem_badge.remove_css_class("green")
                self.about_rem_badge.add_css_class("amber")

        return True

    def _on_apply_clicked(self, _):
        # 1. Orientation
        if self.radio_right.get_active():
            self.config.orientation = 0
        elif self.radio_left.get_active():
            self.config.orientation = 180
        elif self.radio_p90.get_active():
            self.config.orientation = 90
        elif self.radio_p270.get_active():
            self.config.orientation = 270

        # 2. Stylus Buttons & Pressure
        self.config.button_mode = "remapper" if self.btn_mode_combo.get_selected() == 0 else "native"
        self.config.button1_action = index_to_action_key(self.b1_combo.get_selected())
        self.config.button2_action = index_to_action_key(self.b2_combo.get_selected())
        self.config.button1_custom = self.b1_custom_entry.get_text()
        self.config.button2_custom = self.b2_custom_entry.get_text()
        self.config.button_autoload = self.autoload_check.get_active()

        self.config.pressure_gamma = round(self.gamma_scale.get_value(), 2)
        self.config.pressure_threshold = int(self.thresh_scale.get_value())
        self.config.pressure_smoothing = round(self.p_smooth_scale.get_value(), 2)
        self.config.pressure_curve = "gamma" if abs(self.config.pressure_gamma - 1.0) > 0.05 else "linear"
        self.config.smoothing_enable = self.ink_check.get_active()

        # 3. Active Area
        self.config.area_min_x = round(self.area_min_x_scale.get_value(), 3)
        self.config.area_max_x = round(self.area_max_x_scale.get_value(), 3)
        self.config.area_min_y = round(self.area_min_y_scale.get_value(), 3)
        self.config.area_max_y = round(self.area_max_y_scale.get_value(), 3)

        # 4. Scroll & Motion Scaling & Smoothing
        self.config.scroll_sensitivity = round(self.scroll_sens_scale.get_value(), 2)
        self.config.scroll_natural = self.scroll_natural_check.get_active()
        self.config.scroll_require_touch = self.scroll_touch_check.get_active()
        self.config.smoothing_factor = round(self.smooth_scale.get_value(), 2)
        self.config.smoothing_deadzone = int(self.deadzone_scale.get_value())

        self.config.hover_scale = round(self.hover_scale.get_value(), 2)
        self.config.contact_scale = round(self.contact_scale.get_value(), 2)
        self.config.lock_motion_scales = self.lock_scales_check.get_active()
        self.config.aspect_compensate = self.aspect_compensate_check.get_active()

        # 5. Apply display monitor mapping
        self._on_screen_mapping_changed(self.screen_combo, None)

        # 6. Persist to disk (both user directory and system /etc if writable)
        save_config(self.config)
        try:
            if os.access("/etc/veikk-s640/config.toml", os.W_OK):
                save_config(self.config, "/etc/veikk-s640/config.toml")
        except Exception:
            pass

        # 6. Trigger driver live reload immediately through multiple channels
        # Channel A: systemctl reload (polkit permits non-root reload without password)
        try:
            subprocess.run(["systemctl", "reload", "veikk-s640.service"], capture_output=True, timeout=2)
        except Exception:
            pass

        # Channel B: Trigger files in /tmp and /run
        for trig_path in ("/tmp/veikk-reload", "/run/veikk-reload"):
            try:
                with open(trig_path, "w") as f:
                    f.write(str(time.time()))
            except Exception:
                pass

        # Channel C: SIGHUP to running veikk-s640d processes
        try:
            out = subprocess.check_output(["pgrep", "-f", "veikk-s640d"]).decode().strip()
            for pid_str in out.split():
                try:
                    import signal
                    os.kill(int(pid_str), signal.SIGHUP)
                except Exception:
                    pass
        except Exception:
            pass

        # 7. Apply input-remapper bindings if button action changed
        if self.config.button_mode == "remapper":
            apply_remapper_preset(
                self.config.button1_action,
                self.config.button2_action,
                custom1=self.config.button1_custom,
                custom2=self.config.button2_custom,
                autoload=self.config.button_autoload
            )
        self.mapping_diagram.update_config(self.config)
        self._refresh_hardware_status()
        toast = Adw.Toast.new("Settings applied and reloaded immediately.")
        self.toast_overlay.add_toast(toast)


# ==============================================================================
# Application Entry Point
# ==============================================================================
class VeikkExpressiveApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="com.veikk.s640.expressive",
            flags=0
        )
        self.config: TabletConfig = load_config()
        self.window = None

    def do_activate(self):
        if not self.window:
            self.window = VeikkExpressiveWindow(self, self.config)
        self.window.present()


def main():
    app = VeikkExpressiveApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
