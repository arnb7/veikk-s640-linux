"""Libadwaita / GTK4 GUI Configuration Application for VEIKK S640 tablet."""

import os
import sys
import math
import subprocess
from typing import List, Tuple

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, Pango

from .config import TabletConfig, load_config, save_config
from .remapper import (
    BUTTON_ACTIONS,
    WORKFLOW_PRESETS,
    action_key_to_index,
    index_to_action_key,
    apply_remapper_preset,
    is_service_active,
)


class DrawingPad(Gtk.DrawingArea):
    """Interactive drawing pad to test tablet smoothness and pressure response."""

    def __init__(self, on_pressure_callback=None):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(False)
        self.set_content_height(220)
        self.on_pressure_callback = on_pressure_callback

        # Stroke data: list of lists of (x, y, pressure, width)
        self.strokes: List[List[Tuple[float, float, float, float]]] = []
        self._current_stroke: List[Tuple[float, float, float, float]] = []
        self._is_drawing = False
        self._last_event_was_stylus = False

        self.set_draw_func(self._on_draw)

        # 1. Primary Stylus Gesture with pressure axis extraction
        self.stylus = Gtk.GestureStylus()
        self.stylus.connect("down", self._on_stylus_down)
        self.stylus.connect("motion", self._on_stylus_motion)
        self.stylus.connect("up", self._on_stylus_up)
        self.stylus.connect("proximity", self._on_stylus_proximity)
        self.add_controller(self.stylus)

        # 2. Mouse/Touch fallback
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
        # Dynamic stroke width from 1.5px (feather touch) to 22.0px (firm press)
        return max(1.5, 1.5 + pressure * 20.5)

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
        # Background
        cr.set_source_rgb(0.12, 0.13, 0.15)
        cr.paint()

        # Grid lines
        cr.set_source_rgba(0.25, 0.28, 0.32, 0.4)
        cr.set_line_width(1.0)
        step = 40
        x = step
        while x < width:
            cr.move_to(x, 0)
            cr.line_to(x, height)
            x += step
        y = step
        while y < height:
            cr.move_to(0, y)
            cr.line_to(width, y)
            y += step
        cr.stroke()

        # Hint text if empty
        if not self.strokes or (len(self.strokes) == 1 and not self.strokes[0]):
            cr.set_source_rgba(0.6, 0.65, 0.7, 0.6)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(14)
            cr.move_to(width / 2.0 - 140, height / 2.0 + 5)
            cr.show_text("Touch tablet with pen to test live pressure sensitivity")
            return

        # Render strokes with round caps
        cr.set_line_cap(1)  # CAIRO_LINE_CAP_ROUND
        cr.set_line_join(1) # CAIRO_LINE_JOIN_ROUND

        for stroke in self.strokes:
            if len(stroke) < 2:
                if stroke:
                    sx, sy, sp, sw = stroke[0]
                    cr.set_source_rgba(0.2 + 0.3 * sp, 0.6 + 0.3 * sp, 1.0, 0.95)
                    cr.arc(sx, sy, sw / 2.0, 0, 2 * math.pi)
                    cr.fill()
                continue

            for i in range(1, len(stroke)):
                x0, y0, p0, w0 = stroke[i - 1]
                x1, y1, p1, w1 = stroke[i]
                cr.set_source_rgba(0.2 + 0.3 * p1, 0.6 + 0.3 * p1, 1.0, 0.95)
                cr.set_line_width((w0 + w1) / 2.0)
                cr.move_to(x0, y0)
                cr.line_to(x1, y1)
                cr.stroke()


class VeikkConfigApp(Adw.Application):
    """Main Libadwaita Application for VEIKK Tablet settings."""

    def __init__(self):
        super().__init__(
            application_id="com.veikk.s640.config",
            flags=0
        )
        self.config: TabletConfig = load_config()
        self.window = None

    def do_activate(self):
        if not self.window:
            self.window = VeikkConfigWindow(self, self.config)
        self.window.present()


class VeikkConfigWindow(Adw.ApplicationWindow):
    """Configuration Window with tabs for Smoothing, Pressure, Area, and Buttons."""

    def __init__(self, app: Adw.Application, config: TabletConfig):
        super().__init__(application=app, title="VEIKK Tablet Settings")
        self.config = config
        self.set_default_size(780, 720)

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(main_box)

        # Header Bar
        header = Adw.HeaderBar()
        self.view_title = Adw.ViewSwitcherTitle()
        self.view_title.set_title("VEIKK S640 Settings")
        self.view_title.set_subtitle("Userspace Linux Driver")
        header.set_title_widget(self.view_title)

        # Apply Button in Header
        apply_btn = Gtk.Button(label="Apply Changes")
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self._on_apply_clicked)
        header.pack_end(apply_btn)

        main_box.append(header)

        # View Stack & Switcher
        self.stack = Adw.ViewStack()
        self.view_title.set_stack(self.stack)

        main_box.append(self.stack)

        # Build Pages
        self._build_motion_page()
        self._build_pressure_page()
        self._build_area_page()
        self._build_buttons_page()

        # Update initial connection status
        self._refresh_hardware_status()

    # =========================================================================
    # Page 1: Motion & Smoothing
    # =========================================================================
    def _build_motion_page(self):
        page = Adw.PreferencesPage()

        # Status Group
        status_group = Adw.PreferencesGroup(title="Device & Service Status")
        page.add(status_group)

        self.hw_status_row = Adw.ActionRow(
            title="VEIKK S640 Tablet (USB 2feb:0001)",
            subtitle="Checking connection..."
        )
        self.hw_status_icon = Gtk.Image.new_from_icon_name("network-idle-symbolic")
        self.hw_status_row.add_prefix(self.hw_status_icon)
        status_group.add(self.hw_status_row)

        self.svc_status_row = Adw.ActionRow(
            title="Driver Daemon (veikk-s640.service)",
            subtitle="Checking service..."
        )
        self.svc_status_icon = Gtk.Image.new_from_icon_name("network-idle-symbolic")
        self.svc_status_row.add_prefix(self.svc_status_icon)
        status_group.add(self.svc_status_row)

        # Smoothing Group
        smooth_group = Adw.PreferencesGroup(
            title="Cursor Smoothness & Anti-Jitter",
            description="Speed-adaptive filter eliminates digitizer micro-jitter and hand tremors while maintaining instantaneous flick response."
        )
        page.add(smooth_group)

        # Enable Smoothing Switch
        self.smooth_switch = Adw.SwitchRow(
            title="Enable Motion Smoothing",
            subtitle="Filters out ADC noise and smoothens slow tracking"
        )
        self.smooth_switch.set_active(self.config.smoothing_enable)
        smooth_group.add(self.smooth_switch)

        # Smoothness Factor Slider
        self.smooth_factor_row = Adw.ActionRow(
            title="Smoothness Strength",
            subtitle="Higher values produce smoother lines; lower values maximize raw flick speed"
        )
        self.smooth_factor_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05
        )
        self.smooth_factor_scale.set_value(self.config.smoothing_factor)
        self.smooth_factor_scale.set_hexpand(True)
        self.smooth_factor_scale.set_draw_value(True)
        self.smooth_factor_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.smooth_factor_row.add_suffix(self.smooth_factor_scale)
        smooth_group.add(self.smooth_factor_row)

        # Deadzone Slider
        self.deadzone_row = Adw.ActionRow(
            title="Anti-Jitter Deadzone (raw units)",
            subtitle="Threshold below which tiny hand tremors are suppressed when hovering still"
        )
        self.deadzone_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 12, 1
        )
        self.deadzone_scale.set_value(self.config.smoothing_deadzone)
        self.deadzone_scale.set_hexpand(True)
        self.deadzone_scale.set_draw_value(True)
        self.deadzone_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.deadzone_row.add_suffix(self.deadzone_scale)
        smooth_group.add(self.deadzone_row)

        # Pressure Smoothing Slider
        self.p_smooth_row = Adw.ActionRow(
            title="Pressure Smoothing",
            subtitle="Smooths transitions between pressure levels for seamless stroke weight"
        )
        self.p_smooth_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05
        )
        self.p_smooth_scale.set_value(self.config.pressure_smoothing)
        self.p_smooth_scale.set_hexpand(True)
        self.p_smooth_scale.set_draw_value(True)
        self.p_smooth_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.p_smooth_row.add_suffix(self.p_smooth_scale)
        smooth_group.add(self.p_smooth_row)

        # Hover & Motion Distance Scaling Group
        motion_group = Adw.PreferencesGroup(
            title="Hover & Motion Distance Scaling",
            description="Controls how far the cursor travels across the display relative to physical pen movement. Lower values reduce cursor travel distance during hover for high-precision control."
        )
        page.add(motion_group)

        # Hover Distance Scale Slider
        self.hover_scale_row = Adw.ActionRow(
            title="Hover Distance Scale",
            subtitle="Multiplier for cursor travel distance while hovering (0.50x = half distance, 1.00x = 1:1 default)"
        )
        self.hover_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.10, 2.00, 0.05
        )
        self.hover_scale.set_value(self.config.hover_scale)
        self.hover_scale.set_hexpand(True)
        self.hover_scale.set_draw_value(True)
        self.hover_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.hover_scale_row.add_suffix(self.hover_scale)
        motion_group.add(self.hover_scale_row)

        # Lock Scales Switch
        self.lock_scales_switch = Adw.SwitchRow(
            title="Lock Hover & Touch Distance",
            subtitle="Keep pen drawing travel distance synchronized with hover travel distance to prevent cursor jumps"
        )
        self.lock_scales_switch.set_active(self.config.lock_motion_scales)
        motion_group.add(self.lock_scales_switch)

        # Contact Distance Scale Slider
        self.contact_scale_row = Adw.ActionRow(
            title="Touch / Drawing Distance Scale",
            subtitle="Multiplier for cursor travel distance when pen tip is touching tablet surface"
        )
        self.contact_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.10, 2.00, 0.05
        )
        self.contact_scale.set_value(self.config.contact_scale)
        self.contact_scale.set_hexpand(True)
        self.contact_scale.set_draw_value(True)
        self.contact_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.contact_scale.set_sensitive(not self.config.lock_motion_scales)
        self.contact_scale_row.add_suffix(self.contact_scale)
        motion_group.add(self.contact_scale_row)

        def _on_lock_toggled(switch, _gparam):
            locked = switch.get_active()
            self.contact_scale.set_sensitive(not locked)
            if locked:
                self.contact_scale.set_value(self.hover_scale.get_value())

        self.lock_scales_switch.connect("notify::active", _on_lock_toggled)

        # Presets Row
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        p_50 = Gtk.Button(label="High Precision (0.50x)")
        p_50.connect("clicked", lambda _: self._set_motion_scale(0.50))
        preset_box.append(p_50)

        p_75 = Gtk.Button(label="Balanced (0.75x)")
        p_75.connect("clicked", lambda _: self._set_motion_scale(0.75))
        preset_box.append(p_75)

        p_100 = Gtk.Button(label="1:1 Default (1.00x)")
        p_100.connect("clicked", lambda _: self._set_motion_scale(1.00))
        preset_box.append(p_100)

        p_125 = Gtk.Button(label="Fast (1.25x)")
        p_125.connect("clicked", lambda _: self._set_motion_scale(1.25))
        preset_box.append(p_125)

        preset_row = Adw.ActionRow(title="Quick Distance Presets")
        preset_row.add_suffix(preset_box)
        motion_group.add(preset_row)

        self.stack.add_titled(page, "motion", "Motion & Speed").set_icon_name("input-tablet-symbolic")

    # =========================================================================
    # Page 2: Pressure & Live Drawing Pad
    # =========================================================================
    def _build_pressure_page(self):
        page = Adw.PreferencesPage()

        curve_group = Adw.PreferencesGroup(title="Pressure Sensitivity Curve")
        page.add(curve_group)

        # Curve selection
        self.curve_row = Adw.ComboRow(title="Response Curve")
        curve_model = Gtk.StringList.new(["Linear (Standard)", "Gamma (Adjustable Softness)"])
        self.curve_row.set_model(curve_model)
        self.curve_row.set_selected(1 if self.config.pressure_curve == "gamma" else 0)
        curve_group.add(self.curve_row)

        # Gamma slider
        self.gamma_row = Adw.ActionRow(
            title="Gamma Softness (< 1.0 = Soft / > 1.0 = Firm)",
            subtitle="Adjusts curve slope: lower requires less hand force to reach maximum pressure"
        )
        self.gamma_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.3, 3.0, 0.1
        )
        self.gamma_scale.set_value(self.config.pressure_gamma)
        self.gamma_scale.set_hexpand(True)
        self.gamma_scale.set_draw_value(True)
        self.gamma_row.add_suffix(self.gamma_scale)
        curve_group.add(self.gamma_row)

        # Threshold slider
        self.threshold_row = Adw.ActionRow(
            title="Contact Threshold (raw units)",
            subtitle="Minimum pen pressure required before registering stroke contact"
        )
        self.threshold_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 800, 20
        )
        self.threshold_scale.set_value(self.config.pressure_threshold)
        self.threshold_scale.set_hexpand(True)
        self.threshold_scale.set_draw_value(True)
        self.threshold_row.add_suffix(self.threshold_scale)
        curve_group.add(self.threshold_row)

        # Live Pad Group
        pad_group = Adw.PreferencesGroup(
            title="Interactive Drawing Test Pad",
            description="Draw directly on this pad with your pen to evaluate real-time pressure dynamics and stroke weight."
        )
        page.add(pad_group)

        pad_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        # Real-time Pressure Meter
        meter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.pressure_label = Gtk.Label(label="Stylus Pressure: 0.0% (Hovering)")
        self.pressure_label.set_hexpand(True)
        self.pressure_label.set_xalign(0.0)
        meter_box.append(self.pressure_label)

        self.pressure_bar = Gtk.ProgressBar()
        self.pressure_bar.set_hexpand(True)
        self.pressure_bar.set_fraction(0.0)
        meter_box.append(self.pressure_bar)
        pad_box.append(meter_box)

        def _update_meter(p: float):
            self.pressure_bar.set_fraction(p)
            if p <= 0.0:
                self.pressure_label.set_text("Stylus Pressure: 0.0% (Hovering)")
            else:
                raw_equiv = int(round(p * 8191))
                self.pressure_label.set_text(f"Stylus Pressure: {p*100:.1f}% ({raw_equiv} / 8191 levels)")

        self.drawing_pad = DrawingPad(on_pressure_callback=_update_meter)
        self.drawing_pad.add_css_class("card")
        pad_box.append(self.drawing_pad)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        clear_btn = Gtk.Button(label="Clear Test Pad")
        clear_btn.set_icon_name("edit-clear-symbolic")
        clear_btn.connect("clicked", lambda _: self.drawing_pad.clear())
        btn_box.append(clear_btn)
        pad_box.append(btn_box)

        pad_row = Adw.ActionRow()
        pad_row.set_child(pad_box)
        pad_group.add(pad_row)

        self.stack.add_titled(page, "pressure", "Pressure").set_icon_name("draw-freehand-symbolic")

    # =========================================================================
    # Page 3: Active Area & Orientation
    # =========================================================================
    def _build_area_page(self):
        page = Adw.PreferencesPage()

        ori_group = Adw.PreferencesGroup(title="Tablet Orientation")
        page.add(ori_group)

        self.ori_row = Adw.ComboRow(title="Orientation")
        ori_model = Gtk.StringList.new([
            "0° - Standard (Cable on Left)",
            "90° - Portrait Left",
            "180° - Inverted / Left-Handed (Cable on Right)",
            "270° - Portrait Right"
        ])
        self.ori_row.set_model(ori_model)
        ori_map = {0: 0, 90: 1, 180: 2, 270: 3}
        self.ori_row.set_selected(ori_map.get(self.config.orientation, 0))
        ori_group.add(self.ori_row)

        area_group = Adw.PreferencesGroup(
            title="Active Area Crop Ratios",
            description="Restrict tablet mapping to a portion of the physical surface (e.g. to match display aspect ratio)."
        )
        page.add(area_group)

        # Preset buttons
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        full_btn = Gtk.Button(label="Full Tablet (100%)")
        full_btn.connect("clicked", self._set_area_full)
        preset_box.append(full_btn)

        widescreen_btn = Gtk.Button(label="Match 16:9 Screen")
        widescreen_btn.connect("clicked", self._set_area_16_9)
        preset_box.append(widescreen_btn)

        preset_row = Adw.ActionRow(title="Quick Presets")
        preset_row.add_suffix(preset_box)
        area_group.add(preset_row)

        self.area_min_x_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 0.9, 0.05)
        self.area_min_x_scale.set_value(self.config.area_min_x)
        row_min_x = Adw.ActionRow(title="Area Min X")
        row_min_x.add_suffix(self.area_min_x_scale)
        area_group.add(row_min_x)

        self.area_max_x_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.1, 1.0, 0.05)
        self.area_max_x_scale.set_value(self.config.area_max_x)
        row_max_x = Adw.ActionRow(title="Area Max X")
        row_max_x.add_suffix(self.area_max_x_scale)
        area_group.add(row_max_x)

        self.area_min_y_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 0.9, 0.05)
        self.area_min_y_scale.set_value(self.config.area_min_y)
        row_min_y = Adw.ActionRow(title="Area Min Y")
        row_min_y.add_suffix(self.area_min_y_scale)
        area_group.add(row_min_y)

        self.area_max_y_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.1, 1.0, 0.05)
        self.area_max_y_scale.set_value(self.config.area_max_y)
        row_max_y = Adw.ActionRow(title="Area Max Y")
        row_max_y.add_suffix(self.area_max_y_scale)
        area_group.add(row_max_y)

        self.stack.add_titled(page, "area", "Active Area").set_icon_name("preferences-desktop-display-symbolic")

    def _set_area_full(self, _):
        self.area_min_x_scale.set_value(0.0)
        self.area_max_x_scale.set_value(1.0)
        self.area_min_y_scale.set_value(0.0)
        self.area_max_y_scale.set_value(1.0)

    def _set_area_16_9(self, _):
        # Physical S640 aspect ratio is 152.4 / 101.6 = 1.50 (3:2)
        # 16:9 ratio is 1.777 -> crop vertical area to match 16:9
        # vertical span needed: 1.50 / 1.7777 = 0.844
        y_margin = (1.0 - 0.844) / 2.0
        self.area_min_x_scale.set_value(0.0)
        self.area_max_x_scale.set_value(1.0)
        self.area_min_y_scale.set_value(round(y_margin, 3))
        self.area_max_y_scale.set_value(round(1.0 - y_margin, 3))

    # =========================================================================
    # Page 4: Buttons & Remapping
    # =========================================================================
    def _build_buttons_page(self):
        page = Adw.PreferencesPage()

        # Group 1: Stylus Hardware Mapping
        btn_group = Adw.PreferencesGroup(
            title="Stylus Barrel Buttons (input-remapper Integration)",
            description="Remap the physical buttons on your VEIKK pen to mouse clicks, keyboard tools, or custom macros. Mappings apply instantly via the system input-remapper daemon."
        )
        page.add(btn_group)

        # Mode row
        self.btn_mode_row = Adw.ComboRow(title="Button Routing Mode")
        mode_model = Gtk.StringList.new([
            "input-remapper Mode (Recommended: in-app key & mouse macro binding)",
            "Native Stylus Mode (Direct BTN_STYLUS / BTN_STYLUS2 passthrough)"
        ])
        self.btn_mode_row.set_model(mode_model)
        self.btn_mode_row.set_selected(0 if self.config.button_mode == "remapper" else 1)
        btn_group.add(self.btn_mode_row)

        action_labels = [label for label, _, _ in BUTTON_ACTIONS]

        # Button 1 (Lower Barrel Button)
        self.b1_row = Adw.ComboRow(
            title="Button 1 (Lower Barrel / Near Tip)",
            subtitle="Choose action for the lower pen button"
        )
        self.b1_row.set_model(Gtk.StringList.new(action_labels))
        b1_idx = action_key_to_index(self.config.button1_action)
        self.b1_row.set_selected(b1_idx)
        self.b1_row.set_subtitle(BUTTON_ACTIONS[b1_idx][2])
        btn_group.add(self.b1_row)

        self.b1_custom_row = Adw.EntryRow(
            title="Button 1 Custom Macro / Key",
            text=self.config.button1_custom
        )
        self.b1_custom_row.set_visible(self.config.button1_action == "custom")
        btn_group.add(self.b1_custom_row)

        def _on_b1_changed(row, _param):
            idx = row.get_selected()
            key = index_to_action_key(idx)
            self.b1_custom_row.set_visible(key == "custom")
            self.b1_row.set_subtitle(BUTTON_ACTIONS[idx][2])

        self.b1_row.connect("notify::selected", _on_b1_changed)

        # Button 2 (Upper Barrel Button)
        self.b2_row = Adw.ComboRow(
            title="Button 2 (Upper Barrel / Rear)",
            subtitle="Choose action for the upper pen button"
        )
        self.b2_row.set_model(Gtk.StringList.new(action_labels))
        b2_idx = action_key_to_index(self.config.button2_action)
        self.b2_row.set_selected(b2_idx)
        self.b2_row.set_subtitle(BUTTON_ACTIONS[b2_idx][2])
        btn_group.add(self.b2_row)

        self.b2_custom_row = Adw.EntryRow(
            title="Button 2 Custom Macro / Key",
            text=self.config.button2_custom
        )
        self.b2_custom_row.set_visible(self.config.button2_action == "custom")
        btn_group.add(self.b2_custom_row)

        def _on_b2_changed(row, _param):
            idx = row.get_selected()
            key = index_to_action_key(idx)
            self.b2_custom_row.set_visible(key == "custom")
            self.b2_row.set_subtitle(BUTTON_ACTIONS[idx][2])

        self.b2_row.connect("notify::selected", _on_b2_changed)

        # Autoload switch
        self.autoload_switch = Adw.SwitchRow(
            title="Auto-Activate on Login & Plug-in",
            subtitle="Automatically inject button bindings when the tablet is connected or system starts"
        )
        self.autoload_switch.set_active(self.config.button_autoload)
        btn_group.add(self.autoload_switch)

        # Group 1b: Pan & Scroll Settings
        scroll_group = Adw.PreferencesGroup(
            title="Pan & Scroll Settings (Hold Pen Button)",
            description="When Button 1 or Button 2 is set to 'Pan / Scroll', hold that button down and glide your pen up or down over the tablet to smoothly scroll web pages, documents, and code editors."
        )
        page.add(scroll_group)

        self.scroll_sens_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.2, 3.0, 0.1)
        self.scroll_sens_scale.set_value(self.config.scroll_sensitivity)
        self.scroll_sens_scale.set_hexpand(True)
        self.scroll_sens_scale.set_draw_value(True)

        scroll_sens_row = Adw.ActionRow(
            title="Scroll Speed & Sensitivity",
            subtitle="Adjust how rapidly pages scroll when gliding the pen (Default: 1.0x)"
        )
        scroll_sens_row.add_suffix(self.scroll_sens_scale)
        scroll_group.add(scroll_sens_row)

        self.scroll_natural_switch = Adw.SwitchRow(
            title="Natural Scrolling Direction",
            subtitle="Inverts scroll direction (touchscreen / macOS style: moving down pushes content down)"
        )
        self.scroll_natural_switch.set_active(self.config.scroll_natural)
        scroll_group.add(self.scroll_natural_switch)

        # Group 2: Quick Workflow Presets
        presets_group = Adw.PreferencesGroup(
            title="Quick Workflow Presets",
            description="One-click configurations tailored for digital art, illustration, and desktop control."
        )
        page.add(presets_group)

        for preset in WORKFLOW_PRESETS:
            row = Adw.ActionRow(
                title=preset["name"],
                subtitle=preset["desc"]
            )
            apply_preset_btn = Gtk.Button(label="Use Preset")
            apply_preset_btn.connect("clicked", lambda _, p=preset: self._apply_workflow_preset(p))
            row.add_suffix(apply_preset_btn)
            presets_group.add(row)

        # Group 3: input-remapper Daemon Status & Tools
        remapper_group = Adw.PreferencesGroup(title="input-remapper Service Status & Tools")
        page.add(remapper_group)

        self.remapper_status_row = Adw.ActionRow(
            title="input-remapper Daemon (systemd)",
            subtitle="Checking daemon status..."
        )
        self.remapper_status_icon = Gtk.Image.new_from_icon_name("network-idle-symbolic")
        self.remapper_status_row.add_prefix(self.remapper_status_icon)

        # Direct Reload Injection Button
        reload_btn = Gtk.Button(label="Reload Injection")
        reload_btn.set_icon_name("view-refresh-symbolic")
        reload_btn.connect("clicked", self._on_reload_remapper_clicked)
        self.remapper_status_row.add_suffix(reload_btn)
        remapper_group.add(self.remapper_status_row)

        adv_row = Adw.ActionRow(
            title="Advanced input-remapper Editor",
            subtitle="Open full input-remapper interface for multi-step delay macros or advanced timing"
        )
        open_adv_btn = Gtk.Button(label="Open Full App")
        open_adv_btn.set_icon_name("applications-system-symbolic")
        open_adv_btn.connect("clicked", self._on_launch_remapper)
        adv_row.add_suffix(open_adv_btn)
        remapper_group.add(adv_row)

        # Group 4: Driver Service Administration
        svc_group = Adw.PreferencesGroup(title="VEIKK Driver Service Administration")
        page.add(svc_group)

        restart_row = Adw.ActionRow(
            title="Restart VEIKK Driver Daemon",
            subtitle="Forces clean re-attachment and USB interface claiming (veikk-s640.service)"
        )
        restart_btn = Gtk.Button(label="Restart Driver")
        restart_btn.add_css_class("destructive-action")
        restart_btn.connect("clicked", self._on_restart_service)
        restart_row.add_suffix(restart_btn)
        svc_group.add(restart_row)

        self.stack.add_titled(page, "buttons", "Button Control").set_icon_name("input-mouse-symbolic")

    # =========================================================================
    # Actions & Handlers
    # =========================================================================
    def _refresh_hardware_status(self):
        # 1. Check USB connection
        import glob
        connected = False
        for uevent in glob.glob("/sys/bus/usb/devices/*/idVendor"):
            try:
                with open(uevent, "r") as f:
                    vid = f.read().strip()
                pid_path = os.path.join(os.path.dirname(uevent), "idProduct")
                if os.path.isfile(pid_path):
                    with open(pid_path, "r") as pf:
                        pid = pf.read().strip()
                    if vid.lower() == "2feb" and pid.lower() == "0001":
                        connected = True
                        break
            except Exception:
                continue

        if connected:
            self.hw_status_row.set_subtitle("Connected & Detected (Bus /dev/bus/usb)")
            self.hw_status_icon.set_from_icon_name("emblem-ok-symbolic")
            self.hw_status_icon.add_css_class("success")
        else:
            self.hw_status_row.set_subtitle("Not connected — plug in VEIKK S640 USB cable")
            self.hw_status_icon.set_from_icon_name("dialog-warning-symbolic")
            self.hw_status_icon.add_css_class("warning")

        # 2. Check systemd service status
        try:
            res = subprocess.run(["systemctl", "is-active", "veikk-s640.service"], capture_output=True, text=True)
            active = res.stdout.strip() == "active"
        except Exception:
            active = False

        if active:
            self.svc_status_row.set_subtitle("Active & Running (PID active in journalctl)")
            self.svc_status_icon.set_from_icon_name("emblem-ok-symbolic")
            self.svc_status_icon.add_css_class("success")
        else:
            self.svc_status_row.set_subtitle("Inactive / Stopped — start with sudo ./install.sh")
            self.svc_status_icon.set_from_icon_name("dialog-error-symbolic")
            self.svc_status_icon.add_css_class("error")

        # 3. Check input-remapper service status
        if is_service_active():
            self.remapper_status_row.set_subtitle("Active & Running (input-remapper.service)")
            self.remapper_status_icon.set_from_icon_name("emblem-ok-symbolic")
            self.remapper_status_icon.add_css_class("success")
        else:
            self.remapper_status_row.set_subtitle("Inactive / Stopped — enable with systemctl start input-remapper")
            self.remapper_status_icon.set_from_icon_name("dialog-warning-symbolic")
            self.remapper_status_icon.add_css_class("warning")

    def _set_motion_scale(self, scale_val: float):
        self.hover_scale.set_value(scale_val)
        if self.lock_scales_switch.get_active():
            self.contact_scale.set_value(scale_val)

    def _apply_workflow_preset(self, preset: dict):
        b1_key = preset["b1"]
        b2_key = preset["b2"]
        self.b1_row.set_selected(action_key_to_index(b1_key))
        self.b2_row.set_selected(action_key_to_index(b2_key))
        self.btn_mode_row.set_selected(0)  # remapper mode
        toast = Adw.Toast.new(f"Preset '{preset['name']}' selected. Click 'Apply & Save' to activate.")
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def _on_reload_remapper_clicked(self, _):
        b1_act = index_to_action_key(self.b1_row.get_selected())
        b2_act = index_to_action_key(self.b2_row.get_selected())
        c1 = self.b1_custom_row.get_text()
        c2 = self.b2_custom_row.get_text()
        autoload = self.autoload_switch.get_active()

        ok, msg = apply_remapper_preset(b1_act, b2_act, c1, c2, autoload=autoload)
        self._refresh_hardware_status()
        toast = Adw.Toast.new(msg if ok else f"Remapper error: {msg}")
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def _on_apply_clicked(self, _):
        # Update config fields from UI widgets
        self.config.smoothing_enable = self.smooth_switch.get_active()
        self.config.smoothing_factor = round(self.smooth_factor_scale.get_value(), 2)
        self.config.smoothing_deadzone = int(self.deadzone_scale.get_value())
        self.config.pressure_smoothing = round(self.p_smooth_scale.get_value(), 2)

        self.config.hover_scale = round(self.hover_scale.get_value(), 2)
        self.config.contact_scale = round(self.contact_scale.get_value(), 2)
        self.config.lock_motion_scales = self.lock_scales_switch.get_active()

        curve_idx = self.curve_row.get_selected()
        self.config.pressure_curve = "gamma" if curve_idx == 1 else "linear"
        self.config.pressure_gamma = round(self.gamma_scale.get_value(), 2)
        self.config.pressure_threshold = int(self.threshold_scale.get_value())

        ori_idx = self.ori_row.get_selected()
        ori_rev = {0: 0, 1: 90, 2: 180, 3: 270}
        self.config.orientation = ori_rev.get(ori_idx, 0)

        self.config.area_min_x = round(self.area_min_x_scale.get_value(), 3)
        self.config.area_max_x = round(self.area_max_x_scale.get_value(), 3)
        self.config.area_min_y = round(self.area_min_y_scale.get_value(), 3)
        self.config.area_max_y = round(self.area_max_y_scale.get_value(), 3)

        btn_idx = self.btn_mode_row.get_selected()
        self.config.button_mode = "remapper" if btn_idx == 0 else "native"

        # Update button mapping fields
        b1_idx = self.b1_row.get_selected()
        b2_idx = self.b2_row.get_selected()
        self.config.button1_action = index_to_action_key(b1_idx)
        self.config.button2_action = index_to_action_key(b2_idx)
        self.config.button1_custom = self.b1_custom_row.get_text()
        self.config.button2_custom = self.b2_custom_row.get_text()
        self.config.button_autoload = self.autoload_switch.get_active()

        self.config.scroll_sensitivity = round(self.scroll_sens_scale.get_value(), 2)
        self.config.scroll_natural = self.scroll_natural_switch.get_active()

        # Save config file
        user_path = save_config(self.config)
        # Also try to update /etc/veikk-s640/config.toml if writable
        if os.access("/etc/veikk-s640/config.toml", os.W_OK):
            try:
                save_config(self.config, "/etc/veikk-s640/config.toml")
            except Exception:
                pass

        # Send SIGHUP to running driver daemon to reload config
        subprocess.run(["pkill", "-HUP", "-f", "veikk-s640d"], capture_output=True)

        # Apply input-remapper preset if in remapper mode
        remapper_msg = ""
        if self.config.button_mode == "remapper":
            ok, rem_status = apply_remapper_preset(
                self.config.button1_action,
                self.config.button2_action,
                self.config.button1_custom,
                self.config.button2_custom,
                autoload=self.config.button_autoload
            )
            remapper_msg = " | Buttons injected" if ok else f" | {rem_status}"

        toast = Adw.Toast.new(f"Settings saved & reloaded!{remapper_msg}")
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def _on_launch_remapper(self, _):
        try:
            subprocess.Popen(["input-remapper-gtk"])
        except Exception as e:
            toast = Adw.Toast.new(f"Could not launch input-remapper: {e}")
            self.toast_overlay.add_toast(toast)

    def _on_restart_service(self, _):
        try:
            subprocess.Popen(["pkexec", "systemctl", "restart", "veikk-s640.service"])
            toast = Adw.Toast.new("Service restart requested via pkexec.")
            self.toast_overlay.add_toast(toast)
            GLib.timeout_add_seconds(2, self._refresh_hardware_status)
        except Exception as e:
            toast = Adw.Toast.new(f"Restart failed: {e}")
            self.toast_overlay.add_toast(toast)


def main():
    app = VeikkConfigApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
