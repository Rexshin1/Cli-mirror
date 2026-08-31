#!/usr/bin/env python3
"""
cli-mirror - iOS Screen Mirroring for Linux
Mirrors your iPhone screen to Ubuntu via AirPlay (Wi-Fi)
and enables mouse control via Bluetooth HID emulation.

GitHub: https://github.com/yourusername/cli-mirror
Usage:  sudo python3 cli_mirror.py [--name NAME] [--ssid SSID --pass PASS]
"""

import sys
import os
import socket
import struct
import subprocess
import threading
import time
import signal
import argparse

# ─── Enforce root ─────────────────────────────────────────────────────────────
if os.geteuid() != 0:
    print("\033[91mError: Run with sudo → sudo python3 cli_mirror.py\033[0m")
    sys.exit(1)

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

# ─── ANSI Colors ──────────────────────────────────────────────────────────────
BLUE   = "\033[94m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"
CLEAR  = "\033[H\033[2J"

# ─── Bluetooth HID Ports ──────────────────────────────────────────────────────
HID_CTRL = 17
HID_INTR = 19

# ─── HID Mouse Descriptor ─────────────────────────────────────────────────────
HID_DESCRIPTOR = bytes([
    0x05,0x01, 0x09,0x02, 0xA1,0x01, 0x09,0x01,
    0xA1,0x00, 0x05,0x09, 0x19,0x01, 0x29,0x03,
    0x15,0x00, 0x25,0x01, 0x75,0x01, 0x95,0x03,
    0x81,0x02, 0x75,0x05, 0x95,0x01, 0x81,0x03,
    0x05,0x01, 0x09,0x30, 0x09,0x31, 0x09,0x38,
    0x15,0x81, 0x25,0x7F, 0x75,0x08, 0x95,0x03,
    0x81,0x06, 0xC0, 0xC0,
])

SDP_RECORD = """<?xml version="1.0" encoding="UTF-8" ?>
<record>
  <attribute id="0x0001"><sequence><uuid value="0x1124"/></sequence></attribute>
  <attribute id="0x0004">
    <sequence>
      <sequence><uuid value="0x0100"/><uint16 value="0x0011"/></sequence>
      <sequence><uuid value="0x0011"/></sequence>
    </sequence>
  </attribute>
  <attribute id="0x000d">
    <sequence><sequence>
      <sequence><uuid value="0x0100"/><uint16 value="0x0013"/></sequence>
      <sequence><uuid value="0x0011"/></sequence>
    </sequence></sequence>
  </attribute>
  <attribute id="0x0005"><sequence><uuid value="0x1002"/></sequence></attribute>
  <attribute id="0x0100"><text value="cli-mirror Mouse"/></attribute>
  <attribute id="0x0101"><text value="iOS Bluetooth Mouse"/></attribute>
  <attribute id="0x0200"><uint16 value="0x0100"/></attribute>
  <attribute id="0x0201"><uint16 value="0x0111"/></attribute>
  <attribute id="0x0202"><uint8 value="0xC0"/></attribute>
  <attribute id="0x0203"><uint8 value="0x00"/></attribute>
  <attribute id="0x0204"><boolean value="false"/></attribute>
  <attribute id="0x0205"><boolean value="false"/></attribute>
  <attribute id="0x0206">
    <sequence><sequence>
      <uint8 value="0x22"/>
      <text encoding="hex" value="{}"/>
    </sequence></sequence>
  </attribute>
  <attribute id="0x020b"><uint16 value="0x0100"/></attribute>
  <attribute id="0x020d"><boolean value="false"/></attribute>
  <attribute id="0x020e"><boolean value="false"/></attribute>
</record>""".format(HID_DESCRIPTOR.hex())


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 1: Network Utilities
# ════════════════════════════════════════════════════════════════════════════════

def get_local_ip():
    """Auto-detects local IP and active interface name."""
    try:
        import fcntl
        with open("/proc/net/route") as f:
            for line in f:
                fields = line.strip().split()
                if len(fields) > 1 and fields[1] == '00000000':
                    iface = fields[0]
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    ip = socket.inet_ntoa(fcntl.ioctl(
                        s.fileno(), 0x8915,
                        struct.pack('256s', iface[:15].encode())
                    )[20:24])
                    s.close()
                    return ip, iface
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip, "default"
    except Exception:
        return "127.0.0.1", "lo"

def generate_wifi_qr(ssid, password, security="WPA"):
    wifi_string = f"WIFI:S:{ssid};T:{security};P:{password};;"
    print(f"\n{BOLD}{CYAN}┌─ Wi-Fi QR Code ──────────────────────────┐{RESET}")
    print(f"{CYAN}│{RESET}  Scan to join {BOLD}{ssid}{RESET} automatically")
    print(f"{CYAN}└──────────────────────────────────────────┘{RESET}\n")
    try:
        subprocess.run(["qrencode", "-t", "ansiutf8", wifi_string], check=True)
    except FileNotFoundError:
        print(f"{YELLOW}  qrencode not found. Install: sudo apt install qrencode{RESET}")


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 2: Bluetooth Discovery & Pairing
# ════════════════════════════════════════════════════════════════════════════════

def scan_for_iphone(timeout=15):
    """
    Scans for nearby Bluetooth devices and returns the first iPhone found.
    Returns (name, mac) or (None, None).
    """
    print(f"\n{BOLD}{BLUE}▶ Scanning for iPhone/iPad...{RESET} ({timeout}s)")
    found = {}
    stop_event = threading.Event()

    def _scan():
        proc = subprocess.Popen(
            ["bluetoothctl", "scan", "on"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        for line in proc.stdout:
            if stop_event.is_set():
                break
            if "Device" in line and "NEW" in line:
                parts = line.strip().split()
                try:
                    idx = parts.index("Device") + 1
                    mac  = parts[idx]
                    name = " ".join(parts[idx+1:])
                    found[mac] = name
                    if any(k in name.lower() for k in ["iphone", "ipad", "apple"]):
                        print(f"  {GREEN}Found:{RESET} {BOLD}{name}{RESET}  [{mac}]")
                except (ValueError, IndexError):
                    pass
        proc.terminate()

    t = threading.Thread(target=_scan, daemon=True)
    t.start()
    time.sleep(timeout)
    stop_event.set()

    # Return first Apple device found
    for mac, name in found.items():
        if any(k in name.lower() for k in ["iphone", "ipad", "apple"]):
            return name, mac

    # Let user pick manually if no Apple device detected automatically
    if found:
        print(f"\n{YELLOW}No iPhone auto-detected. Nearby devices:{RESET}")
        items = list(found.items())
        for i, (mac, name) in enumerate(items):
            print(f"  [{i+1}] {name}  ({mac})")
        try:
            choice = int(input(f"\n  Pick device number (0 to skip Bluetooth): ")) - 1
            if 0 <= choice < len(items):
                return items[choice][1], items[choice][0]
        except (ValueError, KeyboardInterrupt):
            pass

    return None, None

def pair_device(mac):
    """Pairs and trusts a Bluetooth device."""
    print(f"\n{BOLD}{BLUE}▶ Pairing with {mac}...{RESET}")
    print(f"  {YELLOW}→ Accept the pairing request on your iPhone!{RESET}")
    cmds = f"power on\nagent on\ndefault-agent\npairable on\npair {mac}\ntrust {mac}\nquit\n"
    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True
    )
    stdout, _ = proc.communicate(input=cmds, timeout=30)
    if "Pairing successful" in stdout or "AlreadyExists" in stdout:
        print(f"  {GREEN}✓ Paired and trusted.{RESET}")
        return True
    print(f"  {YELLOW}Pairing output: {stdout.strip()[-200:]}{RESET}")
    return True  # continue anyway if already paired


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 3: Bluetooth HID Agent & Emulator
# ════════════════════════════════════════════════════════════════════════════════

class BtAgent(dbus.service.Object):
    AGENT_PATH = "/cli_mirror/agent"
    def __init__(self, bus):
        super().__init__(bus, self.AGENT_PATH)

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self): pass

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid): pass

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device): return dbus.UInt32(0)

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device): return "0000"

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        print(f"  {YELLOW}Passkey: {passkey:06d}{RESET}")

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print(f"  {GREEN}Auto-confirming passkey {passkey:06d}{RESET}")

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device): pass

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self): pass


class BtHidMouse:
    def __init__(self):
        self.ctrl_sock = self.intr_sock = None
        self.ctrl_conn = self.intr_conn = None
        self.connected = False
        self._lock = threading.Lock()

    def setup_adapter(self):
        for cmd in [
            ["hciconfig", "hci0", "class", "0x002580"],
            ["hciconfig", "hci0", "piscan"],
            ["hciconfig", "hci0", "name", "cli-mirror"],
        ]:
            try:
                subprocess.run(cmd, check=True, capture_output=True)
            except Exception:
                pass

    def register_sdp(self):
        try:
            bus = dbus.SystemBus()
            mgr = dbus.Interface(
                bus.get_object("org.bluez", "/org/bluez"),
                "org.bluez.ProfileManager1"
            )
            mgr.RegisterProfile(
                "/cli_mirror/hid",
                "00001124-0000-1000-8000-00805f9b34fb",
                {"ServiceRecord": SDP_RECORD,
                 "Role": "server",
                 "RequireAuthentication": dbus.Boolean(False),
                 "RequireAuthorization": dbus.Boolean(False)}
            )
        except dbus.DBusException:
            pass  # Already registered or not critical

    def listen(self):
        self.ctrl_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        self.intr_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        for s in [self.ctrl_sock, self.intr_sock]:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ctrl_sock.bind(("", HID_CTRL))
        self.intr_sock.bind(("", HID_INTR))
        self.ctrl_sock.listen(1)
        self.intr_sock.listen(1)
        self.ctrl_conn, addr = self.ctrl_sock.accept()
        self.intr_conn, _ = self.intr_sock.accept()
        self.connected = True
        return addr[0]

    def send(self, buttons=0, dx=0, dy=0, wheel=0):
        if not self.connected:
            return
        report = bytes([0xA1, 0x01, buttons & 0x07,
                        dx & 0xFF, dy & 0xFF]) + struct.pack("b", max(-127, min(127, wheel)))
        try:
            with self._lock:
                self.intr_conn.send(report)
        except OSError:
            self.connected = False

    def move(self, dx, dy):
        while abs(dx) > 0 or abs(dy) > 0:
            sx, sy = max(-127, min(127, dx)), max(-127, min(127, dy))
            self.send(dx=sx, dy=sy)
            dx -= sx; dy -= sy
            if dx or dy:
                time.sleep(0.004)

    def click(self, btn=1):
        self.send(buttons=btn); time.sleep(0.05); self.send(buttons=0)

    def scroll(self, delta):
        self.send(wheel=delta)

    def cleanup(self):
        self.connected = False
        for s in [self.ctrl_conn, self.intr_conn, self.ctrl_sock, self.intr_sock]:
            try:
                if s: s.close()
            except Exception:
                pass


class MouseCapture:
    def __init__(self, bt: BtHidMouse):
        self.bt = bt
        self.running = False

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _loop(self):
        try:
            from Xlib import display, X
            d = display.Display()
            root = d.screen().root
            root.change_attributes(event_mask=(
                X.PointerMotionMask | X.ButtonPressMask | X.ButtonReleaseMask
            ))
            px, py = 0, 0
            while self.running:
                if d.pending_events():
                    ev = d.next_event()
                    if ev.type == X.MotionNotify:
                        dx, dy = ev.root_x - px, ev.root_y - py
                        if dx or dy:
                            self.bt.move(dx, dy)
                        px, py = ev.root_x, ev.root_y
                    elif ev.type == X.ButtonPress:
                        if ev.detail == 1: self.bt.send(buttons=1)
                        elif ev.detail == 3: self.bt.send(buttons=2)
                        elif ev.detail == 4: self.bt.scroll(-15)
                        elif ev.detail == 5: self.bt.scroll(15)
                    elif ev.type == X.ButtonRelease:
                        self.bt.send(buttons=0)
                else:
                    time.sleep(0.002)
        except ImportError:
            self._fallback_loop()

    def _fallback_loop(self):
        try:
            with open("/dev/input/mice", "rb") as f:
                while self.running:
                    data = f.read(3)
                    if len(data) == 3:
                        b, dx, dy = struct.unpack("3b", data)
                        self.bt.send(
                            buttons=((b&1)|(((b>>1)&1)<<1)|(((b>>2)&1)<<2)),
                            dx=dx, dy=-dy
                        )
        except Exception as e:
            print(f"  {RED}Mouse capture error: {e}{RESET}")


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 4: AirPlay Engine Process Manager
# ════════════════════════════════════════════════════════════════════════════════

def launch_airplay(name, port):
    engine = "./uxplay/build/uxplay"
    if not os.path.exists(engine):
        print(f"  {RED}Engine not found. Run: sudo bash install.sh{RESET}")
        return None
    cmd = [engine, "-n", name, "-p", str(port), "-s", "1920x1080", "-fps", "60", "-nc"]
    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )

def airplay_log_reader(proc):
    keywords = {
        "RTSP connection": (GREEN,  "iPhone connected!"),
        "mirror_start":   (GREEN,  "Screen Mirroring ACTIVE ▶"),
        "Mirroring start":(GREEN,  "Screen Mirroring ACTIVE ▶"),
        "mirror_stop":    (YELLOW, "Mirroring paused."),
        "Connection close":(YELLOW,"Device disconnected."),
        "ERROR":          (RED,    None),
        "error":          (RED,    None),
    }
    for line in proc.stdout:
        line = line.strip()
        for key, (color, msg) in keywords.items():
            if key in line:
                label = msg if msg else line
                print(f"  [{color}AirPlay{RESET}] {label}")
                break


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 5: Main Orchestrator
# ════════════════════════════════════════════════════════════════════════════════

def print_banner(name, local_ip, iface, bt_mac):
    print(CLEAR)
    print(f"{BOLD}{BLUE}╔══════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{BLUE}║     cli-mirror — iOS Screen Mirroring    ║{RESET}")
    print(f"{BOLD}{BLUE}╚══════════════════════════════════════════╝{RESET}")
    print(f"\n  {DIM}Network{RESET}   {GREEN}{local_ip}{RESET}  ({iface})")
    print(f"  {DIM}Receiver{RESET}  {BOLD}{YELLOW}{name}{RESET}  (search in iOS Screen Mirroring)")
    print(f"  {DIM}Bluetooth{RESET} {GREEN}{bt_mac}{RESET}")
    print(f"\n{DIM}{'─'*44}{RESET}")

def main():
    parser = argparse.ArgumentParser(
        description="cli-mirror: iOS Screen Mirroring for Linux"
    )
    parser.add_argument("-n", "--name", default="cli-mirror",
                        help="Receiver name shown in iOS Screen Mirroring (default: cli-mirror)")
    parser.add_argument("-p", "--port", type=int, default=7000,
                        help="AirPlay RTSP port (default: 7000)")
    parser.add_argument("--ssid", default=None,
                        help="Wi-Fi SSID to generate QR code for")
    parser.add_argument("--pass", dest="wifi_pass", default="",
                        help="Wi-Fi password for QR code")
    parser.add_argument("--no-bt", action="store_true",
                        help="Disable Bluetooth mouse emulation (mirror only)")
    args = parser.parse_args()

    local_ip, iface = get_local_ip()

    # ── Get Bluetooth adapter MAC ────────────────────────────────────────────
    bt_mac = "N/A"
    try:
        result = subprocess.run(["bluetoothctl", "show"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if "Controller" in line:
                bt_mac = line.split()[1]
                break
    except Exception:
        pass

    print_banner(args.name, local_ip, iface, bt_mac)

    # ── Wi-Fi QR Code (optional) ─────────────────────────────────────────────
    if args.ssid:
        generate_wifi_qr(args.ssid, args.wifi_pass)

    # ── Launch AirPlay engine ────────────────────────────────────────────────
    print(f"\n{BOLD}{BLUE}▶ Starting AirPlay engine...{RESET}")
    airplay_proc = launch_airplay(args.name, args.port)
    if airplay_proc:
        t = threading.Thread(target=airplay_log_reader, args=(airplay_proc,), daemon=True)
        t.start()
        print(f"  {GREEN}✓ AirPlay engine active on port {args.port}.{RESET}")

    # ── Bluetooth HID Mouse Setup ────────────────────────────────────────────
    bt_mouse = None
    capture  = None

    if not args.no_bt:
        print(f"\n{BOLD}{BLUE}▶ Setting up Bluetooth HID Mouse...{RESET}")

        # D-Bus GLib mainloop for agent in background
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()
        mainloop = GLib.MainLoop()
        threading.Thread(target=mainloop.run, daemon=True).start()

        # Register agent for auto-confirm pairing
        agent = BtAgent(bus)
        try:
            agentmgr = dbus.Interface(
                bus.get_object("org.bluez", "/org/bluez"),
                "org.bluez.AgentManager1"
            )
            agentmgr.RegisterAgent(BtAgent.AGENT_PATH, "NoInputNoOutput")
            agentmgr.RequestDefaultAgent(BtAgent.AGENT_PATH)
        except dbus.DBusException:
            pass

        # Scan and pair iPhone
        iphone_name, iphone_mac = scan_for_iphone(timeout=15)

        if iphone_mac:
            pair_device(iphone_mac)

            # Setup Bluetooth HID server
            bt_mouse = BtHidMouse()
            bt_mouse.setup_adapter()
            bt_mouse.register_sdp()

            print(f"\n  {YELLOW}→ On your iPhone: Settings → Bluetooth → connect to {BOLD}'{args.name}'{RESET}")
            print(f"  {DIM}Waiting for Bluetooth HID connection...{RESET}")

            # Start listener in thread so AirPlay can be used meanwhile
            def _bt_listen_loop():
                while True:
                    try:
                        peer = bt_mouse.listen()
                        print(f"\n  [{GREEN}BT Mouse{RESET}] {BOLD}Connected! Mouse control active.{RESET}")
                        print(f"  Left click=tap  Right click=hold  Scroll=scroll\n")
                        nonlocal capture
                        capture = MouseCapture(bt_mouse)
                        capture.start()
                        # Wait until disconnected
                        while bt_mouse.connected:
                            time.sleep(1)
                        print(f"  [{YELLOW}BT Mouse{RESET}] Disconnected. Waiting for reconnect...")
                        if capture:
                            capture.stop()
                    except Exception as e:
                        time.sleep(3)

            threading.Thread(target=_bt_listen_loop, daemon=True).start()
        else:
            print(f"  {YELLOW}No iPhone found via Bluetooth. Running in mirror-only mode.{RESET}")
            print(f"  {DIM}You can connect later via Settings → Bluetooth → cli-mirror{RESET}")
    else:
        print(f"\n  {DIM}Bluetooth mouse disabled (--no-bt flag set).{RESET}")

    # ── Print usage guide ────────────────────────────────────────────────────
    print(f"\n{DIM}{'─'*44}{RESET}")
    print(f"\n{BOLD}How to mirror your iPhone screen:{RESET}")
    print(f"  1. Make sure iPhone is on the same Wi-Fi as this computer.")
    print(f"  2. Open Control Center on iPhone (swipe down).")
    print(f"  3. Tap {BOLD}Screen Mirroring{RESET} → select {BOLD}{YELLOW}{args.name}{RESET}.")
    print(f"  4. Your iPhone screen will appear in a new window!")
    print(f"\n  {DIM}Press Ctrl+C to stop.{RESET}\n")

    # ── Signal handler ───────────────────────────────────────────────────────
    def _exit(sig, frame):
        print(f"\n{YELLOW}Shutting down cli-mirror...{RESET}")
        if capture:
            capture.stop()
        if bt_mouse:
            bt_mouse.cleanup()
        if airplay_proc:
            airplay_proc.terminate()
            try:
                airplay_proc.wait(timeout=2)
            except Exception:
                airplay_proc.kill()
        print(f"{GREEN}Done. Goodbye!{RESET}\n")
        sys.exit(0)

    signal.signal(signal.SIGINT, _exit)
    signal.signal(signal.SIGTERM, _exit)

    # ── Keep alive ───────────────────────────────────────────────────────────
    while True:
        if airplay_proc and airplay_proc.poll() is not None:
            print(f"  [{YELLOW}AirPlay{RESET}] Engine stopped. Restarting...")
            airplay_proc = launch_airplay(args.name, args.port)
            if airplay_proc:
                threading.Thread(target=airplay_log_reader, args=(airplay_proc,), daemon=True).start()
        time.sleep(2)


if __name__ == "__main__":
    main()
