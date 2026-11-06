"""Core userspace driver daemon loop for VEIKK S640."""

import sys
import time
import signal
import logging
import usb.core
import usb.util
from typing import Optional

from .config import TabletConfig, load_config
from .protocol import VeikkProtocolParser
from .uinput_devices import VeikkUinputManager

logger = logging.getLogger("veikk-s640d")

VENDOR_ID = 0x2FEB
PRODUCT_ID = 0x0001
INTERFACE_NUM = 2
LANG_ID_EN_US = 0x0409

# Init packets verified from disassembly
INIT_PACKETS = [
    bytes([0x09, 0x01, 0x04]),
    bytes([0x09, 0x02, 0x02]),
    bytes([0x09, 0x03, 0x02]),
]


class RateLimitedLogger:
    """Prevents log flooding during disconnected states."""
    def __init__(self, interval_sec: float = 10.0):
        self.interval = interval_sec
        self.last_logged = 0.0

    def log(self, message: str, level=logging.INFO):
        now = time.time()
        if now - self.last_logged >= self.interval:
            logger.log(level, message)
            self.last_logged = now


class VeikkDriverDaemon:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self.config: TabletConfig = load_config(config_path)
        self.running = True
        self.rate_limiter = RateLimitedLogger(interval_sec=5.0)

        self.uinput_mgr: Optional[VeikkUinputManager] = None
        self.parser: VeikkProtocolParser = VeikkProtocolParser(
            coord_width=self.config.coord_width,
            max_x=self.config.max_x,
            max_y=self.config.max_y,
            max_pressure=self.config.max_pressure
        )

        self._dev: Optional[usb.core.Device] = None
        self._ep_in: Optional[usb.core.Endpoint] = None
        self._ep_out: Optional[usb.core.Endpoint] = None
        self._detached_interfaces = []

    def setup_signals(self):
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, self._handle_reload)

    def _handle_exit(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def _handle_reload(self, signum, frame):
        logger.info("Received SIGHUP, reloading configuration...")
        try:
            new_cfg = load_config(self.config_path)
            self.config = new_cfg
            if self.uinput_mgr:
                self.uinput_mgr.update_config(new_cfg)
            if self.parser:
                self.parser.coord_width = new_cfg.coord_width
                self.parser.max_x = new_cfg.max_x
                self.parser.max_y = new_cfg.max_y
                self.parser.max_pressure = new_cfg.max_pressure
            logger.info("Configuration successfully reloaded in running daemon.")
        except Exception as e:
            logger.error(f"Failed to reload config: {e}")

    def _query_device_parameters(self, dev: usb.core.Device):
        """Interrogate string descriptor 0x14 to adapt coordinate width and bounds."""
        try:
            # Query string descriptor 0x14 (hardware dimensions & coordinate width)
            # Layout: 3 bytes X (LE), 3 bytes Y (LE), 2 bytes Pressure (LE), 2 bytes Resolution (LE), 1 byte coord_width
            raw_14 = dev.ctrl_transfer(0x80, 0x06, (0x03 << 8) | 0x14, LANG_ID_EN_US, 255, timeout=500)
            if raw_14 and len(raw_14) >= 13:
                payload = raw_14[2:]
                max_x = int.from_bytes(payload[0:3], 'little')
                max_y = int.from_bytes(payload[3:6], 'little')
                max_p = int.from_bytes(payload[6:8], 'little')
                if max_x > 0:
                    self.config.max_x = max_x
                if max_y > 0:
                    self.config.max_y = max_y
                if max_p > 0:
                    self.config.max_pressure = max_p
                # raw_14[12] is the coordinate width in bytes (0x03 on S640/T10)
                if len(raw_14) > 12 and raw_14[12] in (1, 2, 3):
                    self.config.coord_width = raw_14[12]
                    logger.info(f"Auto-detected coordinate width: {self.config.coord_width} bytes from descriptor 0x14")
                logger.info(f"Auto-detected hardware bounds: X={self.config.max_x}, Y={self.config.max_y}, Pressure={self.config.max_pressure}")
        except Exception as e:
            logger.debug(f"String 0x14 query: {e}")

    def _connect_and_claim(self) -> bool:
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev is None:
            self.rate_limiter.log(f"VEIKK tablet ({VENDOR_ID:04x}:{PRODUCT_ID:04x}) not found, waiting...")
            return False

        logger.info(f"Found VEIKK device at Bus {dev.bus:03d} Device {dev.address:03d}")
        self._dev = dev

        # Probe parameters before claiming interface
        self._query_device_parameters(dev)

        cfg = dev.get_active_configuration()
        intf2 = None
        for intf in cfg:
            if intf.bInterfaceNumber == INTERFACE_NUM:
                intf2 = intf
                break

        if intf2 is None:
            logger.error(f"Interface {INTERFACE_NUM} not present on device")
            self._cleanup_usb()
            return False

        self._ep_in = None
        self._ep_out = None
        for ep in intf2:
            if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
                if self._ep_in is None:
                    self._ep_in = ep
            else:
                if self._ep_out is None:
                    self._ep_out = ep

        if self._ep_in is None:
            logger.error(f"No IN endpoint found on Interface {INTERFACE_NUM}")
            self._cleanup_usb()
            return False

        # Detach kernel drivers from all interfaces (0, 1, and 2)
        # Interfaces 0 and 1 host bogus kernel hid-generic pointer/keyboard nodes
        # that send broken relative motions and snap the cursor to the screen edge.
        self._detached_interfaces = []
        for iface_idx in (0, 1, INTERFACE_NUM):
            try:
                if dev.is_kernel_driver_active(iface_idx):
                    logger.info(f"Detaching kernel driver from Interface {iface_idx}")
                    dev.detach_kernel_driver(iface_idx)
                    self._detached_interfaces.append(iface_idx)
            except Exception as e:
                logger.debug(f"Could not detach kernel driver from Interface {iface_idx}: {e}")

        try:
            usb.util.claim_interface(dev, INTERFACE_NUM)
            logger.info(f"Successfully claimed Interface {INTERFACE_NUM}")
        except Exception as e:
            logger.error(f"Failed to claim Interface {INTERFACE_NUM}: {e}")
            self._cleanup_usb()
            return False

        # Send initialization packets to OUT endpoint
        if self._ep_out:
            logger.info("Sending tablet mode initialization reports...")
            for pkt in INIT_PACKETS:
                try:
                    self._ep_out.write(pkt, timeout=500)
                    time.sleep(0.02)
                except Exception as e:
                    logger.warning(f"Init packet {pkt.hex()} write warning: {e}")

        # Initialize uinput manager and protocol parser
        if self.uinput_mgr is None:
            self.uinput_mgr = VeikkUinputManager(self.config, enable_tilt=False)
            self.uinput_mgr.setup()
            logger.info("Initialized uinput devices: 'VEIKK S640 Pen' and 'VEIKK S640 Buttons'")

        self.parser = VeikkProtocolParser(
            coord_width=self.config.coord_width,
            max_x=self.config.max_x,
            max_y=self.config.max_y,
            max_pressure=self.config.max_pressure
        )

        return True

    def _cleanup_usb(self):
        if self._dev is not None:
            try:
                usb.util.release_interface(self._dev, INTERFACE_NUM)
            except Exception:
                pass
            if hasattr(self, "_detached_interfaces"):
                for iface_idx in self._detached_interfaces:
                    try:
                        self._dev.attach_kernel_driver(iface_idx)
                    except Exception:
                        pass
                self._detached_interfaces.clear()
            self._dev = None
            self._ep_in = None
            self._ep_out = None

    def run(self):
        self.setup_signals()
        logger.info(f"Starting veikk-s640d (button_mode='{self.config.button_mode}', orientation={self.config.orientation})")

        while self.running:
            if self._dev is None or self._ep_in is None:
                connected = self._connect_and_claim()
                if not connected:
                    time.sleep(1.0)
                    continue

            # Read interrupt reports
            try:
                data = self._ep_in.read(self._ep_in.wMaxPacketSize or 64, timeout=1000)
                if not data:
                    continue

                raw_bytes = bytes(data)
                report = self.parser.parse_packet(raw_bytes)
                if report is not None:
                    if report.in_proximity:
                        logger.info(f"PACKET: raw={raw_bytes.hex(' ')} -> X={report.x} Y={report.y} P={report.pressure} tip={report.tip_down}")
                    if self.uinput_mgr is not None:
                        self.uinput_mgr.dispatch(report)

            except usb.core.USBTimeoutError:
                # Normal when pen is idle/away
                continue
            except (usb.core.USBError, BrokenPipeError, ConnectionError) as e:
                logger.warning(f"USB connection lost: {e}")
                self._cleanup_usb()
                if self.uinput_mgr:
                    self.uinput_mgr._emit_proximity_out()
                time.sleep(1.0)
            except Exception as e:
                logger.error(f"Unexpected error in driver loop: {e}", exc_info=True)
                time.sleep(0.5)

        logger.info("Driver loop stopped. Cleaning up...")
        if self.uinput_mgr:
            self.uinput_mgr.close()
        self._cleanup_usb()
        logger.info("veikk-s640d stopped cleanly.")
