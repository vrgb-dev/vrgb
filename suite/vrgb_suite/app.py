"""VRGB Suite: app."""

import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from PyQt6.QtCore import (
    pyqtClassInfo,
    Qt,
    QTimer,
    QObject,
    QSocketNotifier,
    QFileSystemWatcher,
    pyqtSlot,
)
from PyQt6.QtDBus import QDBusConnection, QDBusInterface
from PyQt6.QtGui import QColor, QAction, QActionGroup, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QDoubleSpinBox,
    QPushButton,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QGroupBox,
    QInputDialog,
    QMessageBox,
    QSystemTrayIcon,
    QMenu,
    QFrame,
    QColorDialog,
)

from . import sun
from .core import load_core
from .idle import make_idle_backend
from .system import Autostart, KbdBacklight
from .widgets import PRESETS, ColorWheel, make_logo_icon, swatch_icon
from .worker import DeviceWorker


# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, worker: DeviceWorker, mod, session_start=False):
        super().__init__()
        self.worker = worker
        self.mod = mod
        self.kbd = KbdBacklight()
        self._suppress = False           # block feedback loops while we set widgets
        self._interacting = False        # user dragging a control
        self._devinfo = None
        self._preset_btns = []
        self._dev_widgets = []

        # Unified-brightness state
        self._brightness_b = 100         # slider value (unified 0..100)
        self._percent = 100              # HID intensity % sent to vrgb
        self._expected_fw = self.kbd.level() if self.kbd.available else None
        self._fw_ignore_until = 0.0      # monotonic deadline to ignore self-induced fw changes

        self.setWindowTitle("Keyboard RGB")
        self.setWindowIcon(make_logo_icon())

        cfg = mod.load_config()
        self._color = QColor("#" + cfg.get("color", "aa00ff"))

        # Automation: idle dimming + daytime off
        self._auto = {}                  # last applied automation settings
        self._dimmed = False
        self._day_state = None           # None = not evaluated yet
        self._suggested = sun.guess_location()
        self.idle_mon = make_idle_backend(self)
        self.idle_mon.idle.connect(self._on_user_idle)
        self.idle_mon.active.connect(self._on_user_active)

        self._build_ui()
        self._wire_worker()

        self._preview = QTimer(self)
        self._preview.setSingleShot(True)
        self._preview.setInterval(45)
        self._preview.timeout.connect(self._emit_preview)
        self._pending = None             # (hex, hid_percent)

        # Started for the session (--tray): restore the lighting, or keep it off
        # if it is daytime and daytime-off is on. Queued before the day check.
        if session_start:
            worker.submit("login")

        # Wall-clock check once a minute (QTimer is monotonic and pauses in suspend,
        # so a single long timer to sunrise/sunset would fire late after resume).
        self._day_timer = QTimer(self)
        self._day_timer.setInterval(60_000)
        self._day_timer.timeout.connect(self._check_day)
        self._day_timer.start()

        self._load_from_cfg(cfg)
        self._load_autostart_state()

        # Follow FN+F4/F3. The kernel signals key-driven changes through
        # brightness_hw_changed (sysfs_notify -> POLLPRI), so in the tray we sleep
        # until it fires; the 300 ms poll only runs while the window is visible.
        self._fw_timer = QTimer(self)
        self._fw_timer.setInterval(300)
        self._fw_timer.timeout.connect(self._poll_firmware)
        self._hw_notifier = None
        self._hw_fd = None
        if self.kbd.available:
            self._watch_hw_changed()
            if self._hw_notifier is None:
                self._fw_timer.start()   # no notification support: keep polling

        # Pick up config changes made outside this process (the CLI, an
        # editor). The directory is watched because saves replace the file atomically.
        self._cfg_mtime = self._config_mtime()
        self._cfg_watch = QFileSystemWatcher(self)
        self._cfg_reload = QTimer(self)
        self._cfg_reload.setSingleShot(True)
        self._cfg_reload.setInterval(200)
        self._cfg_reload.timeout.connect(self._reload_external_cfg)
        cfg_dir = Path(getattr(mod, "CONFIG_DIR", ""))
        if cfg_dir.is_dir():
            self._cfg_watch.addPath(str(cfg_dir))
            self._cfg_watch.directoryChanged.connect(lambda _p: self._cfg_reload.start())

        self.worker.submit("detect")

        # Ctrl+Q: quit the app entirely (not just hide to tray)
        quit_sc = QShortcut(QKeySequence("Ctrl+Q"), self)
        quit_sc.activated.connect(self.quit_app)

    # ---- unified brightness math ----
    def _levels_for(self, b):
        """Unified brightness B (0..100) -> (firmware_level | None, hid_percent)."""
        b = max(0, min(100, int(round(b))))
        if not self.kbd.available:
            return None, b                       # pure HID
        if b <= 0:
            return 0, 0
        maxf = self.kbd.max
        f = max(1, math.ceil(b / 100.0 * maxf))  # smallest fw step that can reach b
        i = min(100, int(round(b * maxf / f)))   # HID fills the gap: (f/maxf)*(i/100)=b/100
        return f, i

    def _b_from(self, fw_level, hid_percent):
        if not self.kbd.available or fw_level is None:
            return int(round(hid_percent))
        return int(round(fw_level * hid_percent / self.kbd.max))

    def _set_firmware(self, level):
        if level == self._expected_fw:
            return                       # each change spawns busctl; skip no-ops
        self._expected_fw = level
        self._fw_ignore_until = time.monotonic() + 0.6
        self.worker.submit("fwlevel", level)

    # -- UI construction --
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        self.status_lbl = QLabel("Detecting keyboard…")
        self.status_lbl.setStyleSheet("color:#999;")
        root.addWidget(self.status_lbl)

        color_box = QGroupBox("Color")
        cgrid = QGridLayout(color_box)

        self.wheel = ColorWheel()
        cgrid.addWidget(self.wheel, 0, 0, 4, 1)

        self.value_slider = QSlider(Qt.Orientation.Vertical)
        self.value_slider.setRange(0, 100)
        self.value_slider.setValue(100)
        self.value_slider.setToolTip("Value (color lightness)")
        cgrid.addWidget(self.value_slider, 0, 1, 4, 1)

        self.swatch = QFrame()
        self.swatch.setMinimumSize(64, 64)
        self.swatch.setFrameShape(QFrame.Shape.StyledPanel)
        cgrid.addWidget(self.swatch, 0, 2)

        cgrid.addWidget(QLabel("Hex"), 1, 2)
        self.hex_edit = QLineEdit()
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setPlaceholderText("#rrggbb")
        cgrid.addWidget(self.hex_edit, 2, 2)

        preset_row = QHBoxLayout()
        for name, hexc in PRESETS:
            b = QPushButton()
            b.setFixedSize(24, 24)
            b.setToolTip(name)
            b.setStyleSheet(f"background:#{hexc}; border:1px solid #444; border-radius:4px;")
            b.clicked.connect(lambda _=False, h=hexc: self._apply_hex("#" + h, commit=True))
            preset_row.addWidget(b)
            self._preset_btns.append(b)
        preset_row.addStretch(1)
        cgrid.addLayout(preset_row, 4, 0, 1, 3)

        root.addWidget(color_box)

        bbox = QGroupBox("Brightness & power")
        bl = QGridLayout(bbox)
        self.power_btn = QPushButton("Power")
        self.power_btn.setCheckable(True)
        self.power_btn.setMinimumWidth(90)
        bl.addWidget(self.power_btn, 0, 0, 2, 1)

        bl.addWidget(QLabel("Brightness"), 0, 1)
        self.bright_slider = QSlider(Qt.Orientation.Horizontal)
        self.bright_slider.setRange(0, 100)
        self.bright_slider.setValue(self._brightness_b)
        if self.kbd.available:
            self.bright_slider.setToolTip("Unified brightness — also moves with FN+F4 / FN+F3")
        bl.addWidget(self.bright_slider, 0, 2)
        self.bright_lbl = QLabel(f"{self._brightness_b}%")
        self.bright_lbl.setMinimumWidth(40)
        bl.addWidget(self.bright_lbl, 0, 3)

        self.auto_chk = QCheckBox("Firmware / autonomous mode")
        self.auto_chk.setToolTip("Hand control back to the keyboard firmware")
        bl.addWidget(self.auto_chk, 1, 1, 1, 2)

        self.cycle_chk = QCheckBox("Rainbow")
        self.cycle_chk.setToolTip(
            "Cycle through the color spectrum (vrgb rainbow). Keeps running after the "
            "window closes and comes back after logout/reboot; idle dimming is paused.")
        bl.addWidget(self.cycle_chk, 2, 1, 1, 2)

        root.addWidget(bbox)

        pbox = QGroupBox("Profiles")
        pl = QGridLayout(pbox)
        self.profile_list = QListWidget()
        self.profile_list.setMaximumHeight(110)
        pl.addWidget(self.profile_list, 0, 0, 4, 1)
        self.btn_load = QPushButton("Load")
        self.btn_save = QPushButton("Save current…")
        self.btn_delete = QPushButton("Delete")
        pl.addWidget(self.btn_save, 0, 1)
        pl.addWidget(self.btn_load, 1, 1)
        pl.addWidget(self.btn_delete, 2, 1)
        root.addWidget(pbox)

        sbox = QGroupBox("Start at login")
        sgl = QVBoxLayout(sbox)
        self.auto_tray_chk = QCheckBox("Start VRGB in the tray at login")
        self.auto_tray_chk.setToolTip(
            "Restores your lighting at login (or keeps it off by day if daytime-off is on) "
            "and runs the automatic off")
        self.auto_restore_chk = QCheckBox("Only restore my lighting at login (no tray)")
        self.auto_restore_chk.setToolTip(
            "Runs `vrgb restore` on login (color can reset on a full power cycle); "
            "not needed when the tray starts at login")
        sgl.addWidget(self.auto_tray_chk)
        sgl.addWidget(self.auto_restore_chk)
        root.addWidget(sbox)

        # Automation: idle dimming + daytime off
        tbox = QGroupBox("Automatic off")
        tgl = QGridLayout(tbox)
        self.idle_enable_chk = QCheckBox("Turn off after inactivity")
        self.idle_enable_chk.setToolTip(
            "Switch the backlight off when no keys/mouse are used; it comes back on the next input")
        tgl.addWidget(self.idle_enable_chk, 0, 0, 1, 2)
        self.idle_spin = QSpinBox()
        self.idle_spin.setRange(1, 600)
        self.idle_spin.setValue(12)
        self.idle_spin.setSuffix(" s")
        self.idle_spin.setToolTip("Seconds of inactivity before the backlight goes off")
        tgl.addWidget(self.idle_spin, 0, 2, 1, 2)

        self.day_chk = QCheckBox("Keep off during daytime (sunrise → sunset)")
        self.day_chk.setToolTip(
            "While the sun is up at the location below the backlight stays off; "
            "it comes back at sunset if it was on")
        tgl.addWidget(self.day_chk, 1, 0, 1, 4)

        tgl.addWidget(QLabel("Location"), 2, 0)
        self.lat_spin = QDoubleSpinBox()
        self.lat_spin.setRange(-90.0, 90.0)
        self.lat_spin.setDecimals(4)
        self.lat_spin.setPrefix("lat ")
        self.lat_spin.setSuffix("°")
        self.lon_spin = QDoubleSpinBox()
        self.lon_spin.setRange(-180.0, 180.0)
        self.lon_spin.setDecimals(4)
        self.lon_spin.setPrefix("lon ")
        self.lon_spin.setSuffix("°")
        for sp in (self.lat_spin, self.lon_spin):
            sp.setKeyboardTracking(False)   # valueChanged only once editing is done
        tgl.addWidget(self.lat_spin, 2, 1)
        tgl.addWidget(self.lon_spin, 2, 2)
        self.suggest_btn = QPushButton("Suggest")
        self.suggest_btn.setToolTip("Use the reference city of the system timezone (offline)")
        self.suggest_btn.setEnabled(self._suggested_location() is not None)
        tgl.addWidget(self.suggest_btn, 2, 3)

        self.sun_lbl = QLabel("")
        self.sun_lbl.setStyleSheet("color:#999;")
        self.sun_lbl.setWordWrap(True)
        tgl.addWidget(self.sun_lbl, 3, 0, 1, 4)
        if self.idle_mon.available:
            self.idle_enable_chk.setToolTip(
                self.idle_enable_chk.toolTip() + f"\nIdle detection: {self.idle_mon.name}")
        else:
            self.idle_enable_chk.setToolTip(
                "No idle detection for this session (needs GNOME, a Wayland compositor "
                "with ext-idle-notify-v1, or X11 with the XScreenSaver extension)")
        root.addWidget(tbox)

        self.setCentralWidget(central)

        self._dev_widgets = [
            self.wheel, self.value_slider, self.hex_edit,
            self.bright_slider, self.power_btn, self.auto_chk, self.cycle_chk,
        ] + self._preset_btns

        # Signal wiring
        self.wheel.hs_changed.connect(self._on_wheel)
        self.wheel.released.connect(self._commit_color)
        self.value_slider.valueChanged.connect(self._on_value)
        self.value_slider.sliderReleased.connect(self._commit_color)
        self.hex_edit.editingFinished.connect(lambda: self._apply_hex(self.hex_edit.text(), commit=True))
        self.bright_slider.valueChanged.connect(self._on_brightness)
        self.bright_slider.sliderReleased.connect(self._commit_color)
        self.power_btn.clicked.connect(self._on_power)
        self.auto_chk.toggled.connect(self._on_auto)
        self.cycle_chk.toggled.connect(self._on_cycle)
        self.btn_save.clicked.connect(self._profile_save)
        self.btn_load.clicked.connect(self._profile_load)
        self.btn_delete.clicked.connect(self._profile_delete)
        self.profile_list.itemDoubleClicked.connect(lambda _i: self._profile_load())
        self.auto_restore_chk.toggled.connect(lambda on: self._toggle_autostart("restore", on))
        self.auto_tray_chk.toggled.connect(lambda on: self._toggle_autostart("tray", on))
        self.idle_enable_chk.toggled.connect(self._on_automation_changed)
        self.idle_spin.valueChanged.connect(self._on_automation_changed)
        self.day_chk.toggled.connect(self._on_automation_changed)
        self.lat_spin.valueChanged.connect(self._on_automation_changed)
        self.lon_spin.valueChanged.connect(self._on_automation_changed)
        self.suggest_btn.clicked.connect(self._suggest_location)

    def _wire_worker(self):
        self.worker.op_done.connect(self._on_op_done)
        self.worker.device_status.connect(self._on_device_status)
        self.worker.config_updated.connect(self._on_config_updated)

    # -- config <-> widgets --
    def _load_from_cfg(self, cfg):
        self._suppress = True
        self._color = QColor("#" + cfg.get("color", "aa00ff"))
        self._percent = int(cfg.get("percent", 100))   # HID intensity %

        fw = self.kbd.level() if self.kbd.available else None
        if self.kbd.available and fw is None:
            fw = self.kbd.max
        if fw is not None:
            self._expected_fw = fw
        self._brightness_b = self._b_from(fw, self._percent)

        h, s, v, _ = self._color.getHsvF()
        h = max(h, 0.0)              # gray -> hue is -1; clamp
        self.wheel.set_hsv(h, s, v)
        self.value_slider.setValue(int(v * 100))
        self.hex_edit.setText(self._color.name())
        self._update_swatch()
        self.bright_slider.setValue(self._brightness_b)
        self.bright_lbl.setText(f"{self._brightness_b}%")
        self.power_btn.setChecked(self._brightness_b > 0)
        self.power_btn.setText("On" if self._brightness_b > 0 else "Off")
        self.auto_chk.setChecked(bool(cfg.get("autonomous", False)))
        self.cycle_chk.setChecked(isinstance(cfg.get("cycle"), dict))
        self._reload_profiles(cfg)
        st = sun.settings(cfg)
        self.idle_enable_chk.setChecked(st["idle_enabled"])
        self.idle_spin.setValue(st["idle_timeout_seconds"])
        self.day_chk.setChecked(st["day_off_enabled"])
        lat, lon = st["latitude"], st["longitude"]
        if lat is None and self._suggested_location() is not None:
            lat, lon, _label = self._suggested_location()
        if lat is not None:
            self.lat_spin.setValue(lat)
            self.lon_spin.setValue(lon)
        self._suppress = False
        self._apply_automation(cfg)

    def _reload_profiles(self, cfg):
        self.profile_list.clear()
        for name in sorted(cfg.get("profiles", {})):
            self.profile_list.addItem(QListWidgetItem(name))

    def _update_swatch(self):
        self.swatch.setStyleSheet(
            f"background:{self._color.name()}; border:1px solid #333; border-radius:6px;"
        )

    def _current_hex(self):
        return self._color.name().lstrip("#")

    # -- interaction handlers --
    def _on_wheel(self, h, s):
        if self._suppress:
            return
        v = self.value_slider.value() / 100.0
        self._color = QColor.fromHsvF(h, s, v)
        self._sync_color_widgets(update_wheel=False)
        self._queue_preview()

    def _on_value(self, val):
        if self._suppress:
            return
        h, s, _v, _a = self._color.getHsvF()
        self._color = QColor.fromHsvF(max(h, 0.0), s, val / 100.0)
        self.wheel.set_value(val / 100.0)
        self._sync_color_widgets(update_wheel=False)
        self._queue_preview()

    def _apply_hex(self, text, commit=False):
        text = text.strip()
        if not text.startswith("#"):
            text = "#" + text
        col = QColor(text)
        if not col.isValid():
            return
        self._color = col
        self._sync_color_widgets(update_wheel=True)
        if commit:
            self._commit_color()

    def _sync_color_widgets(self, update_wheel):
        self._suppress = True
        if update_wheel:
            h, s, v, _ = self._color.getHsvF()
            self.wheel.set_hsv(max(h, 0.0), s, v)
            self.value_slider.setValue(int(v * 100))
        self.hex_edit.setText(self._color.name())
        self._update_swatch()
        self._suppress = False

    def _queue_preview(self):
        self._interacting = True
        self._pending = (self._current_hex(), self._percent)
        if not self._preview.isActive():
            self._preview.start()

    def _emit_preview(self):
        if not self._pending:
            return
        hexc, pct = self._pending
        self.worker.submit("color", hexc, pct, False)
        self._pending = None

    def _commit_color(self):
        self._preview.stop()
        self._pending = None
        self._interacting = False
        self.worker.submit("color", self._current_hex(), self._percent, True)

    def _on_brightness(self, val):
        if self._suppress:
            return
        # val is the unified brightness B; decompose into firmware step + HID intensity.
        self._brightness_b = val
        fw, hid = self._levels_for(val)
        self._percent = hid
        self.bright_lbl.setText(f"{val}%")
        self.power_btn.setChecked(val > 0)
        self.power_btn.setText("On" if val > 0 else "Off")
        if fw is not None:
            self._set_firmware(fw)
        self._queue_preview()

    def set_brightness_external(self, b):
        """Set unified brightness from the tray (or anywhere) and persist it."""
        b = max(0, min(100, int(b)))
        if self.bright_slider.value() == b:
            # value unchanged -> valueChanged won't fire; apply directly
            self._on_brightness(b)
        else:
            self.bright_slider.setValue(b)   # fires _on_brightness
        self._commit_color()

    def _on_power(self, checked):
        if self._suppress:
            return
        self.power_btn.setText("On" if checked else "Off")
        self.worker.submit("power", bool(checked))

    def _on_auto(self, checked):
        if self._suppress:
            return
        self.worker.submit("auto", bool(checked))

    def _on_cycle(self, checked):
        if self._suppress:
            return
        self.worker.submit("cycle", bool(checked))

    def _config_mtime(self):
        try:
            return self.mod.CONFIG_FILE.stat().st_mtime_ns
        except (OSError, AttributeError):
            return None

    def _reload_external_cfg(self):
        mtime = self._config_mtime()
        if mtime is None or mtime == self._cfg_mtime:
            return
        self._cfg_mtime = mtime
        self.worker.config_updated.emit(self.mod.load_config())

    # -- automation (idle dimming + daytime off) --
    def _suggested_location(self):
        return self._suggested

    def _suggest_location(self):
        sug = self._suggested_location()
        if sug is None:
            return
        self._suppress = True
        self.lat_spin.setValue(sug[0])
        self.lon_spin.setValue(sug[1])
        self._suppress = False
        self._on_automation_changed()

    def _on_automation_changed(self):
        if self._suppress:
            return
        values = {
            "idle_enabled": self.idle_enable_chk.isChecked(),
            "idle_timeout_seconds": self.idle_spin.value(),
            "day_off_enabled": self.day_chk.isChecked(),
            "latitude": round(self.lat_spin.value(), 4),
            "longitude": round(self.lon_spin.value(), 4),
        }
        self.idle_spin.setEnabled(values["idle_enabled"])
        self.worker.submit("settings", values)   # echoes back via config_updated

    def _apply_automation(self, cfg):
        """Push config into the idle watch and the daytime check."""
        cfg = sun.settings(cfg)
        idle_ms = cfg["idle_timeout_seconds"] * 1000 if cfg["idle_enabled"] else 0
        self.idle_spin.setEnabled(cfg["idle_enabled"])
        self.idle_mon.set_timeout(idle_ms)
        if idle_ms == 0 and self._dimmed:
            self._on_user_active()

        auto = {k: cfg.get(k) for k in ("day_off_enabled", "latitude", "longitude")}
        if auto != self._auto:
            self._auto = auto
            self._day_state = None       # settings changed -> re-evaluate now
        self._check_day()

    def _on_user_idle(self):
        self._dimmed = True
        self.worker.submit("idle_dim")
        self.idle_mon.watch_active()

    def _on_user_active(self):
        if self._dimmed:
            self._dimmed = False
            self.worker.submit("idle_restore")

    def _check_day(self):
        cfg = self._auto
        lat, lon = cfg.get("latitude"), cfg.get("longitude")
        if lat is None:
            sug = self._suggested_location()
            if sug is None:
                self.sun_lbl.setText("Set a location to use daytime off.")
                return
            lat, lon = sug[0], sug[1]
        is_day = bool(cfg.get("day_off_enabled")) and sun.is_daytime(lat, lon)

        times = sun.sun_times(lat, lon)
        if times is True:
            txt = "Today: the sun does not set (polar day)."
        elif times is False:
            txt = "Today: the sun does not rise (polar night)."
        else:
            txt = f"Today: sunrise {times[0]:%H:%M} · sunset {times[1]:%H:%M}"
        if cfg.get("latitude") is None and self._suggested is not None:
            txt += f" — suggested from timezone {self._suggested[2]}"
        self.sun_lbl.setText(txt)

        if is_day == self._day_state:
            return                       # act on transitions only: manual "on" by day sticks
        self._day_state = is_day
        self.worker.submit("day_off" if is_day else "day_on")

    # -- autostart --
    def _load_autostart_state(self):
        self._suppress = True
        tray = Autostart.is_enabled("tray")
        self.auto_tray_chk.setChecked(tray)
        self.auto_restore_chk.setChecked(Autostart.is_enabled("restore") and not tray)
        self.auto_restore_chk.setEnabled(not tray)   # the tray restores by itself
        self._suppress = False

    def _toggle_autostart(self, key, on):
        if self._suppress:
            return
        try:
            Autostart.set_enabled(key, on)
            if key == "tray" and on:
                Autostart.set_enabled("restore", False)   # avoid a double restore
            ok = True
        except OSError as exc:
            ok = False
            err = str(exc)
        label = "login restore" if key == "restore" else "tray autostart"
        self.status_lbl.setStyleSheet("color:#5c5;" if ok else "color:#d55;")
        self.status_lbl.setText(
            (f"{'Enabled' if on else 'Disabled'} {label}") if ok
            else f"✗ autostart: {err}"
        )
        self._load_autostart_state()

    # -- firmware (FN+F4/F3) polling --
    def _watch_hw_changed(self):
        path = self.kbd.PATH / "brightness_hw_changed"
        try:
            self._hw_fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        self._rearm_hw()
        self._hw_notifier = QSocketNotifier(self._hw_fd, QSocketNotifier.Type.Exception, self)
        self._hw_notifier.activated.connect(self._on_hw_changed)

    def _rearm_hw(self):
        # sysfs_notify only wakes a poller that has read the attribute; the read
        # fails with ENODATA until the first FN key press, which still arms it.
        try:
            os.lseek(self._hw_fd, 0, os.SEEK_SET)
            os.read(self._hw_fd, 16)
        except OSError:
            pass

    def _on_hw_changed(self, *_args):
        self._rearm_hw()
        self._poll_firmware()

    def showEvent(self, e):
        super().showEvent(e)
        if self.kbd.available:
            self._poll_firmware()
            self._fw_timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        if self._hw_notifier is not None:
            self._fw_timer.stop()        # notifier covers FN keys while hidden

    def _poll_firmware(self):
        if not self.kbd.available or self._interacting:
            return
        if time.monotonic() < self._fw_ignore_until:
            return
        cur = self.kbd.level()
        if cur is None or cur == self._expected_fw:
            return
        # FN key changed the firmware level -> mirror it into the slider + HID.
        self._expected_fw = cur
        b = int(round(cur * 100 / self.kbd.max))
        self._suppress = True
        self._brightness_b = b
        self._percent = 100              # FN snaps the HID sub-step to full
        self.bright_slider.setValue(b)
        self.bright_lbl.setText(f"{b}%")
        self.power_btn.setChecked(b > 0)
        self.power_btn.setText("On" if b > 0 else "Off")
        self._suppress = False
        # Persist the matching color/intensity (keeps the current color).
        self.worker.submit("color", self._current_hex(), self._percent, True)

    # -- profiles --
    def _profile_save(self):
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:")
        if ok and name.strip():
            self._commit_color()         # persist on-screen state first
            self.worker.submit("profile_save", name.strip())

    def _profile_load(self):
        item = self.profile_list.currentItem()
        if item:
            self.worker.submit("profile_load", item.text())

    def _profile_delete(self):
        item = self.profile_list.currentItem()
        if not item:
            return
        if QMessageBox.question(self, "Delete profile", f"Delete '{item.text()}'?") \
                == QMessageBox.StandardButton.Yes:
            self.worker.submit("profile_delete", item.text())

    # -- worker callbacks --
    def _on_op_done(self, op, ok, msg):
        self.status_lbl.setStyleSheet("color:#5c5;" if ok else "color:#d55;")
        self.status_lbl.setText(("✓ " if ok else "✗ ") + msg)

    def _on_device_status(self, devinfo, err):
        self._devinfo = devinfo
        present = devinfo is not None
        for w in self._dev_widgets:
            w.setEnabled(present)
        if present:
            self.status_lbl.setStyleSheet("color:#5c5;")
            self.status_lbl.setText(
                f"● {devinfo.get('model', 'keyboard')}  ·  {devinfo.get('path', '')}"
            )
        else:
            self.status_lbl.setStyleSheet("color:#d55;")
            self.status_lbl.setText("✗ " + (err or "Keyboard not found"))

    def _on_config_updated(self, cfg):
        if self._interacting:
            self._reload_profiles(cfg)
            return
        self._load_from_cfg(cfg)

    def quit_app(self):
        self._quitting = True
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray._quit()
        else:
            QApplication.instance().quit()


# ----------------------------------------------------------------------------
# Tray
# ----------------------------------------------------------------------------

class Tray(QSystemTrayIcon):
    def __init__(self, window: MainWindow, worker: DeviceWorker, app: QApplication):
        super().__init__(make_logo_icon())
        self.window = window
        self.worker = worker
        self.app = app
        self._tray_suppress = False
        self.setToolTip("VRGB — keyboard RGB")

        menu = QMenu()
        self.act_show = QAction("Show / hide window", self)
        self.act_show.triggered.connect(self._toggle_window)
        menu.addAction(self.act_show)
        menu.addSeparator()

        self.act_on = QAction("Turn on", self)
        self.act_on.triggered.connect(lambda: self.worker.submit("power", True))
        self.act_off = QAction("Turn off", self)
        self.act_off.triggered.connect(lambda: self.worker.submit("power", False))
        menu.addAction(self.act_on)
        menu.addAction(self.act_off)
        self.act_rainbow = QAction("Rainbow", self)
        self.act_rainbow.setCheckable(True)
        self.act_rainbow.triggered.connect(lambda on: self.worker.submit("cycle", on))
        menu.addAction(self.act_rainbow)

        # Brightness as a submenu of discrete steps. KDE's tray menu is rendered over
        # DBusMenu, which cannot host an embedded QSlider widget — only plain items.
        self.bright_menu = menu.addMenu("Brightness")
        self._bright_group = QActionGroup(self)
        self._bright_group.setExclusive(True)
        self._bright_actions = []
        for pct in (10, 25, 50, 75, 100):
            a = QAction(f"{pct}%", self)
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, p=pct: self.window.set_brightness_external(p))
            self._bright_group.addAction(a)
            self.bright_menu.addAction(a)
            self._bright_actions.append((pct, a))

        # Color as a submenu of preset swatches (colored icons) + the full dialog.
        self.color_menu = menu.addMenu("Color")
        for name, hexc in PRESETS:
            a = QAction(swatch_icon(hexc), name, self)
            a.triggered.connect(lambda _=False, h=hexc: self.window._apply_hex("#" + h, commit=True))
            self.color_menu.addAction(a)
        self.color_menu.addSeparator()
        self.act_more = QAction("More colors…", self)
        self.act_more.triggered.connect(self._pick_color)
        self.color_menu.addAction(self.act_more)

        menu.addSeparator()
        self.profiles_menu = menu.addMenu("Profiles")
        self._rebuild_profiles(window.mod.load_config())
        worker.config_updated.connect(self._rebuild_profiles)

        menu.addSeparator()
        self.act_quit = QAction("Quit", self)
        self.act_quit.triggered.connect(self._quit)
        menu.addAction(self.act_quit)

        menu.aboutToShow.connect(self._sync_controls)
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _sync_controls(self):
        # Tick the brightness step nearest the current unified brightness.
        b = self.window._brightness_b
        nearest = min(self._bright_actions, key=lambda pa: abs(pa[0] - b))[1]
        for _pct, a in self._bright_actions:
            a.setChecked(a is nearest)
        self.act_rainbow.setChecked(self.window.cycle_chk.isChecked())

    def _pick_color(self):
        col = QColorDialog.getColor(self.window._color, self.window, "Pick keyboard color")
        if col.isValid():
            self.window._apply_hex(col.name(), commit=True)

    def _rebuild_profiles(self, cfg):
        self.profiles_menu.clear()
        names = sorted(cfg.get("profiles", {}))
        if not names:
            a = QAction("(none saved)", self)
            a.setEnabled(False)
            self.profiles_menu.addAction(a)
            return
        for name in names:
            a = QAction(name, self)
            a.triggered.connect(lambda _=False, n=name: self.worker.submit("profile_load", n))
            self.profiles_menu.addAction(a)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window()

    def _toggle_window(self):
        if self.window.isVisible() and not self.window.isMinimized():
            self.window.hide()
        else:
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()

    def _quit(self):
        self.worker.stop()
        if not self.worker.wait(3000):
            self.worker.terminate()
            self.worker.wait(1000)
        self.app.quit()


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

DBUS_NAME = "io.github.vrgb_dev.vrgb"


@pyqtClassInfo("D-Bus Interface", DBUS_NAME)
class SingleInstance(QObject):
    """Session-bus name so only one copy runs the automation; a second launch of
    `vrgb-gui` just asks the running one to show its window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window = None

    @pyqtSlot()
    def Quit(self):
        tray = getattr(self.window, "tray", None) if self.window else None
        if tray is not None:
            tray._quit()
        else:
            QApplication.instance().quit()

    @pyqtSlot()
    def Show(self):
        if self.window is not None:
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()


def claim_single_instance(background):
    """Return the SingleInstance object, or None if another copy owns the name
    (in which case it has been asked to show its window unless `background`)."""
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return SingleInstance()          # no session bus: nothing to coordinate
    if not bus.registerService(DBUS_NAME):
        if not background:
            QDBusInterface(DBUS_NAME, "/", DBUS_NAME, bus).call("Show")
        return None
    inst = SingleInstance()
    bus.registerObject("/", inst, QDBusConnection.RegisterOption.ExportAllSlots)
    return inst


def detach_from_terminal():
    """Started from a terminal: relaunch in the background and give the shell back.

    Desktop launchers and systemd start the GUI without a terminal and are left
    alone (a detached child would make the systemd unit exit). `--foreground`
    keeps it attached, for debugging.
    """
    if "--foreground" in sys.argv or "--quit" in sys.argv or not sys.stdin.isatty():
        return False
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    subprocess.Popen(
        [sys.executable, "-m", "vrgb_suite", "--foreground", *sys.argv[1:]],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, env=env,
    )
    return True


def main():
    if detach_from_terminal():
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("vrgb-gui")
    app.setApplicationDisplayName("VRGB")
    # Matches vrgb-gui.desktop, so the shell shows our icon/name for the window
    # (Wayland app_id; otherwise Qt would report the interpreter, "python3").
    app.setDesktopFileName("vrgb-gui")
    app.setWindowIcon(make_logo_icon())
    background = "--tray" in sys.argv

    if "--quit" in sys.argv:
        bus = QDBusConnection.sessionBus()
        QDBusInterface(DBUS_NAME, "/", DBUS_NAME, bus).call("Quit")
        return 0

    instance = claim_single_instance(background)
    if instance is None:
        return 0                         # already running

    try:
        mod, _core_path = load_core()
    except FileNotFoundError as exc:
        QMessageBox.critical(None, "VRGB GUI", str(exc))
        return 1

    Autostart.migrate()

    worker = DeviceWorker(mod)
    worker.start()

    window = MainWindow(worker, mod, session_start=background)
    instance.window = window

    tray = Tray(window, worker, app) if QSystemTrayIcon.isSystemTrayAvailable() else None
    window.tray = tray
    if tray:
        tray.show()
    # Started for the session (--tray): keep the automation alive when the window
    # is closed, even without a tray (e.g. sway without a bar) — run `vrgb-gui`
    # again to bring the window back.
    if tray or background:
        app.setQuitOnLastWindowClosed(False)

        def close_event(e):
            e.ignore()
            window.hide()
            if tray and not getattr(window, "_quitting", False):
                tray.showMessage("VRGB", "Still running in the tray.",
                                 QSystemTrayIcon.MessageIcon.Information, 2000)
        window.closeEvent = close_event

    if not background:
        window.show()

    # Ctrl+C / SIGTERM quit cleanly. Python only runs signal handlers between
    # bytecodes, which never happens while Qt's event loop blocks in C++, so a
    # short timer hands control back to the interpreter.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: app.quit())
    wake = QTimer()
    wake.timeout.connect(lambda: None)
    wake.start(250)

    rc = app.exec()
    worker.stop()
    if not worker.wait(3000):
        worker.terminate()
        worker.wait(1000)
    return rc


