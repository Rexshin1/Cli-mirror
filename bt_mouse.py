#!/usr/bin/env python3
"""
bt_mouse.py - Bluetooth HID Mouse Emulator for iOS Control
Emulates a Bluetooth mouse device using BlueZ D-Bus API + L2CAP HID sockets.
Pairs with iPhone and sends movement/click HID reports.

Usage:
    sudo python3 bt_mouse.py --pair <iphone_bt_mac>   # One-time pairing
    sudo python3 bt_mouse.py                           # Start emulator
"""

import os
import sys
import socket
import struct
import threading
import time
import signal
import argparse
import subprocess
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

# ─── ANSI Colors ────────────────────────────────────────────────────────────
BLUE   = "\033[94m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# ─── Bluetooth HID L2CAP Ports ───────────────────────────────────────────────
HID_CONTROL_PORT   = 17
HID_INTERRUPT_PORT = 19

# ─── HID Report Descriptor (Mouse: 3 buttons + X/Y relative movement) ────────
HID_DESCRIPTOR = bytes([
    0x05, 0x01,  # Usage Page (Generic Desktop)
    0x09, 0x02,  # Usage (Mouse)
    0xA1, 0x01,  # Collection (Application)
    0x09, 0x01,  #   Usage (Pointer)
    0xA1, 0x00,  #   Collection (Physical)
    0x05, 0x09,  #     Usage Page (Buttons)
    0x19, 0x01,  #     Usage Minimum (Button 1 = Left)
    0x29, 0x03,  #     Usage Maximum (Button 3 = Right)
    0x15, 0x00,  #     Logical Minimum (0)
    0x25, 0x01,  #     Logical Maximum (1)
    0x75, 0x01,  #     Report Size (1)
    0x95, 0x03,  #     Report Count (3)
    0x81, 0x02,  #     Input (Data, Variable, Absolute) - Button states
    0x75, 0x05,  #     Report Size (5)
    0x95, 0x01,  #     Report Count (1)
    0x81, 0x03,  #     Input (Constant) - Padding
    0x05, 0x01,  #     Usage Page (Generic Desktop)
    0x09, 0x30,  #     Usage (X)
    0x09, 0x31,  #     Usage (Y)
    0x09, 0x38,  #     Usage (Wheel)
    0x15, 0x81,  #     Logical Minimum (-127)
    0x25, 0x7F,  #     Logical Maximum (127)
    0x75, 0x08,  #     Report Size (8)
    0x95, 0x03,  #     Report Count (3: X, Y, Wheel)
    0x81, 0x06,  #     Input (Data, Variable, Relative)
    0xC0,        #   End Collection
    0xC0,        # End Collection
])

# ─── BlueZ D-Bus SDP Record for HID Mouse ────────────────────────────────────
SDP_RECORD_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<record>
  <attribute id="0x0001">
    <sequence>
      <uuid value="0x1124"/>
    </sequence>
  </attribute>
  <attribute id="0x0004">
    <sequence>
      <sequence><uuid value="0x0100"/><uint16 value="0x0011"/></sequence>
      <sequence><uuid value="0x0011"/></sequence>
    </sequence>
  </attribute>
  <attribute id="0x000d">
    <sequence>
      <sequence>
        <sequence><uuid value="0x0100"/><uint16 value="0x0013"/></sequence>
        <sequence><uuid value="0x0011"/></sequence>
      </sequence>
    </sequence>
  </attribute>
  <attribute id="0x0005">
    <sequence><uuid value="0x1002"/></sequence>
  </attribute>
  <attribute id="0x0006">
    <sequence>
      <uint16 value="0x656e"/>
      <uint16 value="0x006a"/>
      <uint16 value="0x0100"/>
    </sequence>
  </attribute>
  <attribute id="0x0009">
    <sequence>
      <sequence><uuid value="0x1124"/><uint16 value="0x0100"/></sequence>
    </sequence>
  </attribute>
  <attribute id="0x0100">
    <text value="iOS Mouse Emulator"/>
  </attribute>
  <attribute id="0x0101">
    <text value="Bluetooth HID Mouse"/>
  </attribute>
  <attribute id="0x0102">
    <text value="rexshin-cli-mirror"/>
  </attribute>
  <attribute id="0x0200">
    <uint16 value="0x0100"/>
  </attribute>
  <attribute id="0x0201">
    <uint16 value="0x0111"/>
  </attribute>
  <attribute id="0x0202">
    <uint8 value="0xC0"/>
  </attribute>
  <attribute id="0x0203">
    <uint8 value="0x00"/>
  </attribute>
  <attribute id="0x0204">
    <boolean value="false"/>
  </attribute>
  <attribute id="0x0205">
    <boolean value="false"/>
  </attribute>
  <attribute id="0x0206">
    <sequence>
      <sequence>
        <uint8 value="0x22"/>
        <text encoding="hex" value="{}"/>
      </sequence>
    </sequence>
  </attribute>
  <attribute id="0x0207">
    <sequence>
      <sequence>
        <uint16 value="0x0409"/>
        <uint16 value="0x0100"/>
      </sequence>
    </sequence>
  </attribute>
  <attribute id="0x020b">
    <uint16 value="0x0100"/>
  </attribute>
  <attribute id="0x020c">
    <uint16 value="0x0C80"/>
  </attribute>
  <attribute id="0x020d">
    <boolean value="false"/>
  </attribute>
  <attribute id="0x020e">
    <boolean value="false"/>
  </attribute>
  <attribute id="0x020f">
    <uint16 value="0x0640"/>
  </attribute>
  <attribute id="0x0210">
    <uint16 value="0x0320"/>
  </attribute>
</record>""".format(HID_DESCRIPTOR.hex())


# ─── BlueZ Agent (handles pairing confirmations automatically) ────────────────
class BluetoothAgent(dbus.service.Object):
    AGENT_PATH = "/cli_mirror/agent"

    def __init__(self, bus):
        super().__init__(bus, self.AGENT_PATH)

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):
        pass

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"[{GREEN}BT{RESET}] Service authorized: {uuid}")

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        return dbus.UInt32(0)

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        return "0000"

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        print(f"[{YELLOW}BT{RESET}] Passkey: {passkey:06d}")

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        print(f"[{YELLOW}BT{RESET}] Pin Code: {pincode}")

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print(f"[{GREEN}BT{RESET}] Auto-confirming passkey: {passkey:06d}")

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        print(f"[{GREEN}BT{RESET}] Connection authorized.")

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):
        pass


# ─── Core Bluetooth HID Mouse Emulator ───────────────────────────────────────
class BtMouseEmulator:
    def __init__(self):
        self.ctrl_sock     = None
        self.intr_sock     = None
        self.ctrl_conn     = None
        self.intr_conn     = None
        self.connected     = False
        self.iphone_mac    = None
        self._lock         = threading.Lock()

    def setup_adapter(self):
        """Configure the local Bluetooth adapter as a HID device."""
        try:
            # Set adapter class to HID Mouse (0x2580 = Peripheral/Pointing)
            subprocess.run(["hciconfig", "hci0", "class", "0x002580"], check=True)
            subprocess.run(["hciconfig", "hci0", "piscan"], check=True)
            subprocess.run(["hciconfig", "hci0", "name", "iOS Mouse Emulator"], check=True)
            print(f"[{GREEN}BT{RESET}] Adapter configured as HID Mouse (discoverable + pairable).")
        except subprocess.CalledProcessError as e:
            print(f"[{RED}BT{RESET}] Error configuring adapter: {e}")
            sys.exit(1)

    def register_sdp(self):
        """Register the HID SDP record with BlueZ via D-Bus."""
        try:
            bus = dbus.SystemBus()
            manager = dbus.Interface(
                bus.get_object("org.bluez", "/org/bluez"),
                "org.bluez.ProfileManager1"
            )
            profile_path = "/cli_mirror/hid_profile"
            opts = {
                "ServiceRecord":   SDP_RECORD_XML,
                "Role":            "server",
                "RequireAuthentication": dbus.Boolean(False),
                "RequireAuthorization":  dbus.Boolean(False),
            }
            manager.RegisterProfile(profile_path, "00001124-0000-1000-8000-00805f9b34fb", opts)
            print(f"[{GREEN}BT{RESET}] HID SDP profile registered successfully.")
        except dbus.DBusException as e:
            # Profile may already be registered
            print(f"[{YELLOW}BT{RESET}] SDP register note: {e.get_dbus_message()}")

    def listen(self):
        """Open L2CAP HID sockets and wait for iPhone to connect."""
        self.ctrl_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        self.intr_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)

        self.ctrl_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.intr_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.ctrl_sock.bind(("", HID_CONTROL_PORT))
        self.intr_sock.bind(("", HID_INTERRUPT_PORT))

        self.ctrl_sock.listen(1)
        self.intr_sock.listen(1)

        print(f"[{BLUE}BT{RESET}] Listening on L2CAP ports {HID_CONTROL_PORT} (ctrl) and {HID_INTERRUPT_PORT} (intr)...")
        print(f"[{YELLOW}BT{RESET}] Go to iPhone Settings → Bluetooth and connect to {BOLD}'{self._get_adapter_name()}'{RESET}")

        # Accept connections from iPhone
        self.ctrl_conn, ctrl_addr = self.ctrl_sock.accept()
        print(f"[{GREEN}BT{RESET}] Control channel connected from {ctrl_addr[0]}")
        self.iphone_mac = ctrl_addr[0]

        self.intr_conn, intr_addr = self.intr_sock.accept()
        print(f"[{GREEN}BT✓{RESET}] {BOLD}iPhone Bluetooth HID connected! Ready to receive mouse input.{RESET}")
        self.connected = True

    def _get_adapter_name(self):
        try:
            result = subprocess.run(["hciconfig", "hci0", "name"], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                if "Name:" in line:
                    return line.split("'")[1]
        except Exception:
            pass
        return "iOS Mouse Emulator"

    def send_mouse_report(self, buttons=0, dx=0, dy=0, wheel=0):
        """
        Send a HID mouse report over the interrupt L2CAP channel.
        buttons: bitmask (bit0=left, bit1=right, bit2=middle)
        dx, dy:  relative movement in pixels (-127 to 127)
        wheel:   scroll wheel delta
        """
        if not self.connected or not self.intr_conn:
            return

        # Clamp movement values to signed 8-bit range
        dx    = max(-127, min(127, dx))
        dy    = max(-127, min(127, dy))
        wheel = max(-127, min(127, wheel))

        # HID interrupt report: header(0xA1) + reportID(0x01) + payload
        report = struct.pack("5B",
            0xA1,           # HID data header (INPUT report)
            0x01,           # Report ID
            buttons & 0x07, # Button bitmask (3 bits)
            dx & 0xFF,      # X movement
            dy & 0xFF,      # Y movement
        ) + struct.pack("b", wheel)  # Wheel (signed)

        try:
            with self._lock:
                self.intr_conn.send(report)
        except OSError:
            self.connected = False

    def move(self, dx, dy):
        """Move the mouse cursor by (dx, dy) pixels."""
        # Break large movements into 127-px chunks
        while abs(dx) > 0 or abs(dy) > 0:
            step_x = max(-127, min(127, dx))
            step_y = max(-127, min(127, dy))
            self.send_mouse_report(dx=step_x, dy=step_y)
            dx -= step_x
            dy -= step_y
            if abs(dx) > 0 or abs(dy) > 0:
                time.sleep(0.004)

    def click(self, button=1):
        """Send a mouse click (button down + up)."""
        self.send_mouse_report(buttons=button)
        time.sleep(0.05)
        self.send_mouse_report(buttons=0)

    def scroll(self, delta):
        """Send a scroll wheel event."""
        self.send_mouse_report(wheel=delta)

    def cleanup(self):
        self.connected = False
        for s in [self.ctrl_conn, self.intr_conn, self.ctrl_sock, self.intr_sock]:
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        print(f"[{YELLOW}BT{RESET}] Bluetooth HID sockets closed.")


# ─── X11 Mouse Event Capture (reads mouse from AirPlay window) ───────────────
class X11MouseCapture:
    """
    Captures mouse events from the GStreamer AirPlay window using Xlib.
    Maps screen coordinates to iPhone resolution and forwards to BtMouseEmulator.
    """
    def __init__(self, bt_mouse: BtMouseEmulator, iphone_res=(1170, 2532)):
        self.bt_mouse   = bt_mouse
        self.iphone_res = iphone_res  # iPhone logical resolution
        self.running    = False
        self._thread    = None
        self._last_x    = 0
        self._last_y    = 0

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def _capture_loop(self):
        """Read /dev/input mouse events and forward to Bluetooth."""
        try:
            from Xlib import display, X, Xutil
            import Xlib.ext.xinput as xi
        except ImportError:
            print(f"[{YELLOW}BT{RESET}] python-xlib not found. Install with: pip3 install python-xlib")
            print(f"[{YELLOW}BT{RESET}] Falling back to /dev/input mouse capture.")
            self._capture_dev_input()
            return

        d = display.Display()
        root = d.screen().root
        root.change_attributes(event_mask=X.PointerMotionMask | X.ButtonPressMask | X.ButtonReleaseMask)

        prev_x, prev_y = 0, 0

        while self.running:
            if d.pending_events():
                event = d.next_event()

                if event.type == X.MotionNotify:
                    dx = event.root_x - prev_x
                    dy = event.root_y - prev_y
                    if dx != 0 or dy != 0:
                        self.bt_mouse.move(dx, dy)
                    prev_x, prev_y = event.root_x, event.root_y

                elif event.type == X.ButtonPress:
                    if event.detail == 1:
                        self.bt_mouse.send_mouse_report(buttons=1)  # Left down
                    elif event.detail == 3:
                        self.bt_mouse.send_mouse_report(buttons=2)  # Right down
                    elif event.detail == 4:
                        self.bt_mouse.scroll(-15)  # Scroll up
                    elif event.detail == 5:
                        self.bt_mouse.scroll(15)   # Scroll down

                elif event.type == X.ButtonRelease:
                    self.bt_mouse.send_mouse_report(buttons=0)
            else:
                time.sleep(0.002)

    def _capture_dev_input(self):
        """Fallback: read raw mouse events from /dev/input/mice."""
        try:
            with open("/dev/input/mice", "rb") as f:
                while self.running:
                    data = f.read(3)
                    if len(data) == 3:
                        buttons, dx, dy = struct.unpack("3b", data)
                        left   = bool(buttons & 0x01)
                        right  = bool(buttons & 0x02)
                        middle = bool(buttons & 0x04)
                        btn_mask = (left << 0) | (right << 1) | (middle << 2)
                        self.bt_mouse.send_mouse_report(buttons=btn_mask, dx=dx, dy=-dy)
        except PermissionError:
            print(f"[{RED}BT{RESET}] Permission denied: /dev/input/mice. Run with sudo.")
        except Exception as e:
            print(f"[{RED}BT{RESET}] Input capture error: {e}")


# ─── One-Time Pairing Helper ──────────────────────────────────────────────────
def pair_with_iphone(iphone_mac: str):
    """
    Initiates Bluetooth pairing with the iPhone.
    Run this once before starting the emulator.
    """
    print(f"[{BLUE}BT{RESET}] Initiating pairing with iPhone ({iphone_mac})...")
    print(f"[{YELLOW}BT{RESET}] IMPORTANT: On your iPhone, accept the Bluetooth pairing request.")

    commands = [
        f"power on",
        f"agent on",
        f"default-agent",
        f"discoverable on",
        f"pairable on",
        f"pair {iphone_mac}",
        f"trust {iphone_mac}",
        f"quit",
    ]
    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    for cmd in commands:
        proc.stdin.write(cmd + "\n")
        proc.stdin.flush()
        time.sleep(1.5)
    proc.stdin.close()
    stdout, _ = proc.communicate(timeout=30)
    print(stdout)
    print(f"[{GREEN}BT✓{RESET}] Pairing complete. Now run: sudo python3 bt_mouse.py")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Bluetooth HID Mouse Emulator for iOS")
    parser.add_argument("--pair", metavar="MAC", help="One-time pair with iPhone Bluetooth MAC (e.g. AA:BB:CC:DD:EE:FF)")
    parser.add_argument("--iphone-res", default="1170x2532", help="iPhone screen resolution (default: 1170x2532)")
    args = parser.parse_args()

    if os.geteuid() != 0:
        print(f"{RED}Error: This script requires root privileges. Run with: sudo python3 bt_mouse.py{RESET}")
        sys.exit(1)

    if args.pair:
        pair_with_iphone(args.pair)
        return

    # Parse iPhone resolution
    try:
        iw, ih = map(int, args.iphone_res.split("x"))
    except Exception:
        iw, ih = 1170, 2532

    print(f"{BOLD}{BLUE}════════════════════════════════════════{RESET}")
    print(f"{BOLD}{BLUE}  Bluetooth HID Mouse Emulator Active   {RESET}")
    print(f"{BOLD}{BLUE}════════════════════════════════════════{RESET}")

    # Initialize D-Bus GLib main loop for agent
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    mainloop = GLib.MainLoop()

    # Register auto-confirm pairing agent
    agent = BluetoothAgent(bus)
    agent_mgr = dbus.Interface(
        bus.get_object("org.bluez", "/org/bluez"),
        "org.bluez.AgentManager1"
    )
    agent_mgr.RegisterAgent(BluetoothAgent.AGENT_PATH, "NoInputNoOutput")
    agent_mgr.RequestDefaultAgent(BluetoothAgent.AGENT_PATH)

    # Start D-Bus loop in background thread
    glib_thread = threading.Thread(target=mainloop.run, daemon=True)
    glib_thread.start()

    # Start Bluetooth HID emulator
    bt_mouse = BtMouseEmulator()
    bt_mouse.setup_adapter()
    bt_mouse.register_sdp()

    def signal_handler(sig, frame):
        print(f"\n{YELLOW}Stopping Bluetooth HID emulator...{RESET}")
        capture.stop()
        bt_mouse.cleanup()
        mainloop.quit()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait for iPhone to connect over Bluetooth HID
    bt_mouse.listen()

    # Start capturing mouse events from Ubuntu and forwarding to iPhone
    capture = X11MouseCapture(bt_mouse, iphone_res=(iw, ih))
    capture.start()

    print(f"[{GREEN}✓{RESET}] Touchpad capture active. Move your finger on the touchpad!")
    print(f"    Tap on touchpad   → tap on iPhone")
    print(f"    Right click       → tap and hold")
    print(f"    Scroll wheel      → scroll on iPhone")
    print(f"    Press Ctrl+C to stop.\n")

    # Keep main thread alive
    while True:
        if not bt_mouse.connected:
            print(f"[{YELLOW}BT{RESET}] iPhone disconnected. Waiting for reconnect...")
            try:
                bt_mouse.listen()
                capture.start()
            except Exception as e:
                print(f"[{RED}BT{RESET}] Reconnect failed: {e}")
                time.sleep(3)
        time.sleep(1)


if __name__ == "__main__":
    main()
