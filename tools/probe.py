#!/usr/bin/env python3
"""VEIKK S640 USB Protocol Probe Tool

Interrogates USB device 2feb:0001 (VEIKK S640 / T10).
Dumps USB descriptors, string descriptors (including vendor binary blobs at 0x14, 0x16, 0x17),
locates endpoints on Interface 2, sends probe initialization packets,
and captures/decodes raw interrupt IN reports.
"""

import sys
import time
import argparse
import usb.core
import usb.util
from datetime import datetime

VENDOR_ID = 0x2FEB
PRODUCT_ID = 0x0001
INTERFACE_NUM = 2
LANG_ID_EN_US = 0x0409

# String descriptor indices observed in disassembly
STRING_INDICES = [1, 2, 3, 0x14, 0x16, 0x17]

# Candidate init sequences from static analysis
CANDIDATE_INIT_PACKETS = [
    bytes([0x09, 0x01]),
    bytes([0x09, 0x03, 0x02]),
    bytes([0x09, 0x02, 0x02]),
]


def format_hex(data: bytes | list[int]) -> str:
    return " ".join(f"{b:02x}" for b in data)


def get_raw_string_descriptor(dev: usb.core.Device, index: int, langid: int = LANG_ID_EN_US) -> bytes | None:
    """Read raw USB string descriptor via standard control transfer."""
    try:
        # bmRequestType: 0x80 (Device-to-host, Standard, Device)
        # bRequest: 0x06 (GET_DESCRIPTOR)
        # wValue: (DESCRIPTOR_TYPE_STRING << 8) | index = (0x03 << 8) | index
        # wIndex: langid
        # wLength: 255
        raw = dev.ctrl_transfer(
            bmRequestType=0x80,
            bRequest=0x06,
            wValue=(0x03 << 8) | index,
            wIndex=langid,
            data_or_wLength=255,
            timeout=1000
        )
        return bytes(raw)
    except Exception as e:
        return None


def decode_string_desc(raw: bytes) -> tuple[str, str]:
    """Parse raw string descriptor: byte 0 is bLength, byte 1 is bDescriptorType (0x03)."""
    if not raw or len(raw) < 2:
        return "", ""
    length = raw[0]
    payload = raw[2:length]
    # Attempt UTF-16LE decode (standard USB string)
    try:
        decoded_text = payload.decode('utf-16le', errors='replace')
    except Exception:
        decoded_text = ""
    hex_repr = format_hex(raw)
    return hex_repr, decoded_text


def dump_descriptors(dev: usb.core.Device):
    print("=" * 70)
    print("USB DEVICE DESCRIPTORS (VID:PID = 2feb:0001)")
    print("=" * 70)
    print(f"Device: Bus {dev.bus:03d} Device {dev.address:03d}")
    print(f"  bLength:             {dev.bLength}")
    print(f"  bDescriptorType:     {dev.bDescriptorType}")
    print(f"  bcdUSB:              0x{dev.bcdUSB:04x}")
    print(f"  bDeviceClass:        0x{dev.bDeviceClass:02x}")
    print(f"  bDeviceSubClass:     0x{dev.bDeviceSubClass:02x}")
    print(f"  bDeviceProtocol:     0x{dev.bDeviceProtocol:02x}")
    print(f"  bMaxPacketSize0:     {dev.bMaxPacketSize0}")
    print(f"  idVendor:            0x{dev.idVendor:04x}")
    print(f"  idProduct:           0x{dev.idProduct:04x}")
    print(f"  bcdDevice:           0x{dev.bcdDevice:04x}")
    print(f"  iManufacturer:       {dev.iManufacturer}")
    print(f"  iProduct:            {dev.iProduct}")
    print(f"  iSerialNumber:       {dev.iSerialNumber}")
    print(f"  bNumConfigurations:  {dev.bNumConfigurations}")
    print()

    print("STRING DESCRIPTORS (langid=0x0409):")
    for idx in STRING_INDICES:
        raw = get_raw_string_descriptor(dev, idx)
        if raw is not None:
            hex_str, text_str = decode_string_desc(raw)
            clean_text = "".join(c if c.isprintable() else f"\\x{ord(c):02x}" for c in text_str)
            print(f"  Index 0x{idx:02x} ({idx:2d}): len={len(raw)}")
            print(f"    Raw Hex: {hex_str}")
            print(f"    Text:    '{clean_text}'")
        else:
            print(f"  Index 0x{idx:02x} ({idx:2d}): [NOT PRESENT OR ERROR]")
    print()

    print("INTERFACES & ENDPOINTS:")
    cfg = dev.get_active_configuration()
    for intf in cfg:
        print(f"  Interface {intf.bInterfaceNumber} (Alt {intf.bAlternateSetting}):")
        print(f"    Class: 0x{intf.bInterfaceClass:02x}, SubClass: 0x{intf.bInterfaceSubClass:02x}, Protocol: 0x{intf.bInterfaceProtocol:02x}")
        for ep in intf:
            ep_type = usb.util.endpoint_type(ep.bmAttributes)
            ep_dir = "IN" if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN else "OUT"
            type_str = {
                usb.util.ENDPOINT_TYPE_CTRL: "CTRL",
                usb.util.ENDPOINT_TYPE_ISO: "ISO",
                usb.util.ENDPOINT_TYPE_BULK: "BULK",
                usb.util.ENDPOINT_TYPE_INTR: "INTR"
            }.get(ep_type, "UNKNOWN")
            print(f"    Endpoint 0x{ep.bEndpointAddress:02x}: Dir={ep_dir}, Type={type_str}, MaxPacketSize={ep.wMaxPacketSize}, Interval={ep.bInterval}")
    print("=" * 70)


def find_interface_endpoints(intf: usb.core.Interface) -> tuple[usb.core.Endpoint | None, usb.core.Endpoint | None]:
    ep_in = None
    ep_out = None
    for ep in intf:
        if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
            if ep_in is None:
                ep_in = ep
        else:
            if ep_out is None:
                ep_out = ep
    return ep_in, ep_out


def decode_packet(pkt: bytes, coord_width: int = 3) -> str:
    """Tentative decoding based on disassembly findings."""
    if len(pkt) < 3:
        return f"[Short packet len={len(pkt)}: {format_hex(pkt)}]"

    report_id = pkt[0]
    report_type = pkt[1]

    if report_id != 0x09:
        return f"[Non-0x09 report ID 0x{report_id:02x}: {format_hex(pkt)}]"

    if report_type == 0x41:  # Pen
        status = pkt[2]
        # Proximity: 0xA0 hover, 0xA1 tip down, others out-of-range
        hover = (status & 0xF0) == 0xA0
        tip_down = status == 0xA1 or (status & 0x01) == 0x01
        btn1 = bool(status & 0x02)
        btn2 = bool(status & 0x04)
        flag8 = bool(status & 0x08)

        # X, Y parsing with coordinate width n (default 2)
        offset_x = 3
        offset_y = 3 + coord_width
        offset_p = 3 + 2 * coord_width

        x = int.from_bytes(pkt[offset_x:offset_y], byteorder='little') if len(pkt) >= offset_y else None
        y = int.from_bytes(pkt[offset_y:offset_p], byteorder='little') if len(pkt) >= offset_p else None
        p = int.from_bytes(pkt[offset_p:offset_p + 2], byteorder='little') if len(pkt) >= offset_p + 2 else None

        tilt_str = ""
        if len(pkt) >= 13:
            tilt_x = pkt[11]
            tilt_y = pkt[12]
            tilt_str = f" tilt=({tilt_x},{tilt_y})"

        return (
            f"PEN (0x41) status=0x{status:02x} "
            f"[hover={hover} tip={tip_down} b1={btn1} b2={btn2} b3={flag8}] "
            f"X={x} Y={y} P={p}{tilt_str} | raw: {format_hex(pkt)}"
        )

    elif report_type == 0x42:
        return f"KEYS (0x42) | raw: {format_hex(pkt)}"
    elif report_type == 0x43:
        return f"DIAL (0x43) | raw: {format_hex(pkt)}"
    else:
        return f"TYPE (0x{report_type:02x}) | raw: {format_hex(pkt)}"


def probe_device(args):
    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        print(f"[-] VEIKK S640 device ({VENDOR_ID:04x}:{PRODUCT_ID:04x}) NOT FOUND.")
        print("    Ensure the tablet is plugged in and accessible.")
        print("    (You may need to run as root or ensure udev rules are loaded).")
        sys.exit(1)

    print(f"[+] Found VEIKK device at Bus {dev.bus:03d} Device {dev.address:03d}")

    dump_descriptors(dev)

    cfg = dev.get_active_configuration()
    # Find Interface 2
    intf2 = None
    for intf in cfg:
        if intf.bInterfaceNumber == INTERFACE_NUM:
            intf2 = intf
            break

    if intf2 is None:
        print(f"[-] Interface {INTERFACE_NUM} not found on device!")
        sys.exit(1)

    ep_in, ep_out = find_interface_endpoints(intf2)
    print(f"[+] Interface {INTERFACE_NUM} Endpoints:")
    print(f"    EP IN:  0x{ep_in.bEndpointAddress:02x} (max: {ep_in.wMaxPacketSize})" if ep_in else "    EP IN: None")
    print(f"    EP OUT: 0x{ep_out.bEndpointAddress:02x} (max: {ep_out.wMaxPacketSize})" if ep_out else "    EP OUT: None")

    if not ep_in:
        print("[-] Missing IN endpoint on Interface 2!")
        sys.exit(1)

    # Detach kernel driver if active
    reattach = False
    if dev.is_kernel_driver_active(INTERFACE_NUM):
        print(f"[*] Kernel driver active on Interface {INTERFACE_NUM}. Detaching...")
        try:
            dev.detach_kernel_driver(INTERFACE_NUM)
            reattach = True
            print("[+] Kernel driver detached.")
        except Exception as e:
            print(f"[-] Failed to detach kernel driver: {e}")
            sys.exit(1)

    try:
        usb.util.claim_interface(dev, INTERFACE_NUM)
        print(f"[+] Claimed Interface {INTERFACE_NUM}.")

        # Send init reports if EP OUT exists
        if ep_out and not args.no_init:
            print("\n[*] Sending candidate init packets to EP OUT...")
            for pkt in CANDIDATE_INIT_PACKETS:
                print(f"  -> OUT 0x{ep_out.bEndpointAddress:02x}: {format_hex(pkt)}")
                try:
                    ep_out.write(pkt, timeout=1000)
                    time.sleep(0.05)
                except Exception as e:
                    print(f"     [!] Write failed: {e}")

        # Capture loop
        print(f"\n[*] Listening for IN reports on 0x{ep_in.bEndpointAddress:02x} (Ctrl+C to stop)...")
        if args.log:
            log_file = open(args.log, "a")
            print(f"[*] Logging raw captures to {args.log}")
        else:
            log_file = None

        count = 0
        t0 = time.time()
        while True:
            try:
                data = ep_in.read(ep_in.wMaxPacketSize or 64, timeout=1000)
                pkt = bytes(data)
                now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                decoded = decode_packet(pkt, coord_width=args.coord_width)
                print(f"[{now}] ({len(pkt):2d}B) {decoded}")

                if log_file:
                    log_file.write(f"{now}\t{format_hex(pkt)}\n")
                    log_file.flush()

                count += 1
                if args.count and count >= args.count:
                    break
            except usb.core.USBTimeoutError:
                continue
            except KeyboardInterrupt:
                print("\n[*] Interrupted by user.")
                break

        elapsed = time.time() - t0
        if elapsed > 0 and count > 0:
            print(f"\n[*] Captured {count} packets in {elapsed:.2f}s ({count/elapsed:.1f} pkt/s)")

    finally:
        print("[*] Releasing interface...")
        usb.util.release_interface(dev, INTERFACE_NUM)
        if reattach:
            try:
                print("[*] Re-attaching kernel driver...")
                dev.attach_kernel_driver(INTERFACE_NUM)
            except Exception as e:
                print(f"[-] Could not re-attach kernel driver: {e}")
        if log_file:
            log_file.close()
        print("[+] Done.")


def main():
    parser = argparse.ArgumentParser(description="VEIKK S640 USB Protocol Probe Tool")
    parser.add_argument("--coord-width", type=int, default=3, choices=[1, 2, 3],
                        help="Coordinate width n in bytes (1, 2, or 3; default: 3)")
    parser.add_argument("--count", type=int, default=0,
                        help="Number of packets to capture (0 = infinite)")
    parser.add_argument("--log", type=str, default=None,
                        help="File to log raw hex packets to")
    parser.add_argument("--no-init", action="store_true",
                        help="Skip sending init packets to EP OUT")
    args = parser.parse_args()
    probe_device(args)


if __name__ == "__main__":
    main()
