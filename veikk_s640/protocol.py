"""Protocol parser for VEIKK S640 / T10 USB tablets.

Decodes raw USB interrupt IN packets based on reverse-engineered
vktablet 3.5.10-9 binary analysis and empirical hardware specs.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PenReport:
    """Decoded state from a pen packet (Report ID 0x09, Type 0x41)."""
    in_proximity: bool
    tip_down: bool
    button1: bool        # Lower barrel button (default right-click, bit 0x04)
    button2: bool        # Upper barrel button (default eraser/toggle, bit 0x02)
    eraser: bool         # Tail eraser / button 3 (bit 0x08)
    x: int
    y: int
    pressure: int
    tilt_x: Optional[int] = None
    tilt_y: Optional[int] = None
    raw_status: int = 0


class VeikkProtocolParser:
    """Parses binary packets received from Interface 2 EP IN."""

    REPORT_ID = 0x09
    TYPE_PEN = 0x41
    TYPE_KEYS = 0x42
    TYPE_DIAL = 0x43

    # Status byte masks & values
    # In disassembly:
    # 0xA0 indicates hover, 0xA1 indicates tip down.
    # Bits 0x02, 0x04, 0x08 represent button states.
    PROXIMITY_MASK = 0xA0
    STATUS_OUT_OF_PROXIMITY = 0xC0

    def __init__(self, coord_width: int = 3, max_x: int = 30480, max_y: int = 20320, max_pressure: int = 8191):
        if coord_width not in (1, 2, 3):
            raise ValueError(f"Invalid coordinate width: {coord_width}. Must be 1, 2, or 3.")
        self.coord_width = coord_width
        self.max_x = max_x
        self.max_y = max_y
        self.max_pressure = max_pressure

    def parse_packet(self, data: bytes | bytearray) -> Optional[PenReport]:
        """Parse raw USB packet into a PenReport.

        Returns None if packet is not a pen report or is malformed.
        """
        if not data or len(data) < 3:
            return None

        report_id = data[0]
        report_type = data[1]

        if report_id != self.REPORT_ID:
            return None

        if report_type != self.TYPE_PEN:
            # Physical keys (0x42) and dial (0x43) are not present on S640
            return None

        status = data[2]
        min_required_len = 3 + 2 * self.coord_width + 2
        if len(data) < min_required_len:
            return None

        # Check proximity
        in_proximity = (status & self.PROXIMITY_MASK) == self.PROXIMITY_MASK

        button2 = in_proximity and bool(status & 0x02)  # bit 0x02: upper button
        button1 = in_proximity and bool(status & 0x04)  # bit 0x04: lower button
        eraser = in_proximity and bool(status & 0x08)   # bit 0x08: eraser/button3

        # Coordinates & Pressure parsing: little-endian
        off_x = 3
        off_y = off_x + self.coord_width
        off_p = off_y + self.coord_width

        x = int.from_bytes(data[off_x:off_y], byteorder='little')
        y = int.from_bytes(data[off_y:off_p], byteorder='little')
        pressure = int.from_bytes(data[off_p:off_p + 2], byteorder='little')

        # Tip contact: active if hardware status bit is set OR pressure > 0
        tip_down = in_proximity and ((status & 0x01) == 0x01 or status == 0xA1 or pressure > 0)

        # Tilt: present only if packet length > 12 bytes
        tilt_x = None
        tilt_y = None
        if len(data) > 12:
            # Tilt values are at offsets 11 and 12
            raw_tx = data[11]
            raw_ty = data[12]
            # Convert unsigned byte to signed int (-128 to 127) if tilt is non-zero
            tilt_x = raw_tx if raw_tx < 128 else raw_tx - 256
            tilt_y = raw_ty if raw_ty < 128 else raw_ty - 256

        return PenReport(
            in_proximity=in_proximity,
            tip_down=tip_down,
            button1=button1,
            button2=button2,
            eraser=eraser,
            x=x,
            y=y,
            pressure=pressure,
            tilt_x=tilt_x,
            tilt_y=tilt_y,
            raw_status=status
        )
