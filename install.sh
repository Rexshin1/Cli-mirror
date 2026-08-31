#!/bin/bash
# install.sh - One-time setup for cli-mirror
# Installs all dependencies, builds C++ engine, and configures Bluetooth

set -e

BLUE='\033[94m'
GREEN='\033[92m'
YELLOW='\033[93m'
RED='\033[91m'
BOLD='\033[1m'
RESET='\033[0m'

print_header() {
    echo ""
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════${RESET}"
    echo -e "${BOLD}${BLUE}   cli-mirror - Installer                 ${RESET}"
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════${RESET}"
    echo ""
}

print_step() {
    echo -e "\n${BOLD}${BLUE}▶ $1${RESET}"
}

print_ok() {
    echo -e "${GREEN}✓ $1${RESET}"
}

print_warn() {
    echo -e "${YELLOW}⚠ $1${RESET}"
}

print_err() {
    echo -e "${RED}✗ $1${RESET}"
}

# ── Check root ──────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    print_err "Please run as root: sudo bash install.sh"
    exit 1
fi

print_header

# ── 1. System Dependencies ──────────────────────────────────────────────────
print_step "Installing system dependencies..."
apt-get update -qq
apt-get install -y \
    libavahi-client-dev \
    libavahi-common-dev \
    libssl-dev \
    libplist-dev \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-libav \
    gstreamer1.0-tools \
    qrencode \
    bluez \
    python3-dbus \
    python3-gi \
    git \
    cmake \
    build-essential \
    > /dev/null 2>&1
print_ok "System packages installed."

# ── 2. Python Dependencies ───────────────────────────────────────────────────
print_step "Installing Python packages..."
pip3 install python-xlib evdev --break-system-packages -q 2>/dev/null || \
    pip3 install python-xlib evdev -q 2>/dev/null || true
print_ok "Python packages installed."

# ── 3. Build C++ AirPlay Engine ──────────────────────────────────────────────
print_step "Building C++ AirPlay core engine..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "uxplay" ]; then
    echo "  Cloning UxPlay engine..."
    git clone https://github.com/FDH2/UxPlay.git uxplay -q
    print_ok "UxPlay cloned."
fi

mkdir -p uxplay/build
cd uxplay/build
cmake .. -DCMAKE_BUILD_TYPE=Release > /dev/null 2>&1
make -j$(nproc) > /dev/null 2>&1
cd "$SCRIPT_DIR"
print_ok "C++ engine built: uxplay/build/uxplay"

# ── 4. Configure Bluetooth HID ───────────────────────────────────────────────
print_step "Configuring Bluetooth for HID emulation..."

MAIN_CONF="/etc/bluetooth/main.conf"

if ! grep -q "DisablePlugins" "$MAIN_CONF" 2>/dev/null; then
    echo "" >> "$MAIN_CONF"
    echo "# Added by cli-mirror installer" >> "$MAIN_CONF"
    echo "[Policy]" >> "$MAIN_CONF"
    echo "DisablePlugins = input" >> "$MAIN_CONF"
    print_ok "Bluetooth input plugin disabled (for HID emulation)."
else
    # Ensure it's set
    sed -i 's/^#\?DisablePlugins.*/DisablePlugins = input/' "$MAIN_CONF"
    print_ok "Bluetooth config updated."
fi

systemctl restart bluetooth > /dev/null 2>&1
print_ok "Bluetooth service restarted."

# ── 5. Unblock Bluetooth ──────────────────────────────────────────────────────
print_step "Ensuring Bluetooth is unblocked..."
rfkill unblock bluetooth 2>/dev/null || true
print_ok "Bluetooth unblocked."

# ── 6. Set Permissions ────────────────────────────────────────────────────────
print_step "Setting file permissions..."
cd "$SCRIPT_DIR"
chmod +x cli_mirror.py
chmod +x bt_mouse.py
print_ok "Permissions set."

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  Installation complete! 🎉               ${RESET}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════${RESET}"
echo ""
echo -e "Run the app with:"
echo -e "  ${BOLD}sudo python3 cli_mirror.py${RESET}"
echo ""
echo -e "Or with custom name:"
echo -e "  ${BOLD}sudo python3 cli_mirror.py --name \"MyMirror\"${RESET}"
echo ""
