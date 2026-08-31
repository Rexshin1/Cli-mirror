# 📱 cli-mirror

> **Mirror your iPhone screen to Linux in one command.** No jailbreak. No app on your iPhone. Just plug & play via AirPlay + Bluetooth mouse control.

![Platform](https://img.shields.io/badge/platform-Linux-blue)
![Language](https://img.shields.io/badge/language-C%2B%2B%20%2F%20Python-informational)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Features

- 📡 **AirPlay Mirroring** — Works with iOS built-in Screen Mirroring. No app needed on iPhone.
- 🖱️ **Bluetooth Mouse Control** — Use your Ubuntu mouse to tap/click/scroll on the iPhone screen (like Samsung DeX!).
- 🔍 **Auto-detect iPhone** — Scans and pairs your iPhone automatically via Bluetooth.
- 📟 **Wi-Fi QR Code** — Generates a QR code in the terminal so your iPhone can join the same Wi-Fi instantly.
- ⚡ **Low Latency** — Hardware-accelerated H.264 decoding via GStreamer.
- 🪶 **Lightweight** — Single Python script + compiled C++ engine. No Docker, no bloat.

---

## 📋 Requirements

- Ubuntu 22.04+ / Debian-based Linux
- Bluetooth adapter (built-in or USB dongle)
- iPhone and Ubuntu on the **same Wi-Fi network**
- `sudo` access for Bluetooth HID emulation

---

## 🚀 Quick Start (2 steps!)

### Step 1 — Install (one-time)
```bash
git clone https://github.com/yourusername/cli-mirror
cd cli-mirror
sudo bash install.sh
```

### Step 2 — Run
```bash
sudo python3 cli_mirror.py
```

**That's it!** The program will:
1. Start the AirPlay receiver (detectable in iOS Screen Mirroring).
2. Automatically scan for your iPhone via Bluetooth and pair.
3. Enable mouse control: your Ubuntu mouse controls the iPhone.

Then on your iPhone:
1. Swipe down → **Control Center**
2. Tap **Screen Mirroring** → select **`cli-mirror`**
3. 🎉 Your iPhone screen appears on Ubuntu!

---

## ⚙️ Usage & Options

```bash
sudo python3 cli_mirror.py [options]

Options:
  -n, --name NAME       Receiver name in iOS Screen Mirroring (default: cli-mirror)
  -p, --port PORT       AirPlay RTSP port (default: 7000)
  --ssid SSID           Wi-Fi name for QR code generation
  --pass PASSWORD       Wi-Fi password for QR code
  --no-bt               Disable Bluetooth mouse (mirror-only mode)
  -h, --help            Show help

Examples:
  sudo python3 cli_mirror.py --name "MyMirror"
  sudo python3 cli_mirror.py --ssid "HomeWiFi" --pass "secret123"
  sudo python3 cli_mirror.py --no-bt   # Mirror only, no mouse
```

---

## 🖱️ Mouse Controls

| Action on Ubuntu       | Action on iPhone    |
|------------------------|---------------------|
| Move mouse             | Move cursor         |
| Left click             | Tap                 |
| Right click            | Tap & hold          |
| Scroll wheel up/down   | Scroll page         |

> **Note:** A small circular cursor (AssistiveTouch) will appear on your iPhone screen when Bluetooth mouse is connected.

---

## 🔧 How It Works

```
iPhone (AirPlay Sender)
    │
    ├─── Wi-Fi (AirPlay / RTSP) ──► Ubuntu: UxPlay C++ Engine ──► GStreamer Window
    │                                        (H.264 decode + render)
    │
    └─── Bluetooth (HID Mouse) ◄─── Ubuntu: bt_mouse.py (L2CAP HID)
         (Sends tap/click/scroll)            (Captures mouse events)
```

---

## 🐛 Troubleshooting

**iPhone not appearing in Screen Mirroring list?**
- Make sure iPhone and Ubuntu are on the **same Wi-Fi network**.
- Check your firewall: `sudo ufw allow 7000/tcp && sudo ufw allow 7000/udp`.
- Verify Avahi/mDNS is running: `systemctl status avahi-daemon`.

**Bluetooth not found?**
- Run `sudo rfkill unblock bluetooth` then `sudo systemctl restart bluetooth`.

**Mouse not working?**
- Make sure `DisablePlugins = input` is set in `/etc/bluetooth/main.conf`.
- On iPhone: **Settings → Accessibility → AssistiveTouch → Enable**.

**Screen goes black when iPhone locks?**
- Set iPhone Auto-Lock to **Never**: Settings → Display & Brightness → Auto-Lock → Never.

---

## 📦 Project Structure

```
cli-mirror/
├── cli_mirror.py      # Main entry point (AirPlay + Bluetooth orchestrator)
├── bt_mouse.py        # Bluetooth HID Mouse Emulator module
├── install.sh         # One-time dependency installer & builder
├── uxplay/            # C++ AirPlay core engine (auto-cloned by install.sh)
└── src/core/          # Custom mDNS discovery module (C)
    ├── mdns.c
    ├── mdns.h
    └── main.c
```

---

## 🙏 Credits

- [UxPlay](https://github.com/FDH2/UxPlay) — Open-source AirPlay mirroring server (C++)
- [GStreamer](https://gstreamer.freedesktop.org/) — Multimedia framework for H.264 decoding

---

## 📄 License

MIT License — feel free to use, modify, and distribute.
