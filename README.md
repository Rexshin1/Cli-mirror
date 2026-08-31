# cli-mirror

Aplikasi CLI ringan untuk Linux yang memungkinkan Anda menerima screen mirroring dari perangkat iOS (iPhone/iPad) ke Ubuntu. Tidak perlu install aplikasi apa pun di iPhone, cukup menggunakan fitur Screen Mirroring bawaan iOS melalui protokol AirPlay.

Dilengkapi dengan modul kontrol via touchpad laptop dan keyboard, serta mouse Bluetooth, sehingga Anda bisa menggerakkan dan mengklik layar iPhone langsung dari laptop Anda.

![Platform](https://img.shields.io/badge/platform-Linux-blue)
![Language](https://img.shields.io/badge/language-C%2B%2B%20%2F%20Python-informational)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Fitur

- **AirPlay Mirroring** — Menampilkan layar iPhone di Ubuntu menggunakan protokol AirPlay bawaan iOS. Tidak perlu aplikasi tambahan di sisi iPhone.
- **Kontrol Mouse via Touchpad & Keyboard** — Gunakan touchpad laptop atau tombol keyboard arrow untuk tap, klik, dan scroll di layar iPhone seperti Samsung DeX.
- **Kontrol Mouse via Bluetooth** — Gunakan mouse Bluetooth di Ubuntu untuk tap, klik, dan scroll di layar iPhone seperti Samsung DeX.
- **Auto-detect iPhone** — Memindai dan melakukan pairing dengan iPhone secara otomatis melalui Bluetooth.
- **QR Code Wi-Fi** — Menampilkan QR code di terminal agar iPhone dapat bergabung ke jaringan Wi-Fi yang sama secara otomatis.
- **Latensi Rendah** — Dekoding H.264 hardware-accelerated menggunakan GStreamer.
- **Ringan** — Hanya satu skrip Python sebagai entry point dan satu binary C++ sebagai engine. Tidak ada Docker atau dependensi besar lainnya.

---

## Persyaratan

- Ubuntu 22.04 atau lebih baru (Debian-based)
- Bluetooth adapter (bawaan laptop atau USB dongle eksternal)
- iPhone dan Ubuntu harus terhubung ke **jaringan Wi-Fi yang sama**
- Akses `sudo` untuk emulasi Bluetooth HID

---

## Instalasi

### Langkah 1 — Clone repositori

```bash
git clone --recurse-submodules https://github.com/Rexshin1/Cli-mirror.git
cd Cli-mirror
```

### Langkah 2 — Jalankan installer (sekali saja)

```bash
sudo bash install.sh
```

Script ini akan secara otomatis:
- Menginstal semua dependensi sistem (GStreamer, Bluetooth, dll.)
- Mengompilasi C++ AirPlay engine dari source
- Mengkonfigurasi Bluetooth untuk emulasi HID mouse
- Menyiapkan semua permission yang dibutuhkan

---

## Cara Pakai

```bash
sudo python3 cli_mirror.py
```

Program akan:
1. Menjalankan AirPlay receiver yang bisa dideteksi oleh iPhone.
2. Memindai iPhone terdekat via Bluetooth dan melakukan pairing otomatis.
3. Mengaktifkan kontrol: gerakan touchpad laptop, klik touchpad, atau scroll di Ubuntu dikirim ke iPhone.
   Gunakan `--keyboard` untuk kontrol via tombol arrow keyboard.

Setelah program berjalan, di iPhone:
1. Buka Control Center (geser layar ke bawah).
2. Ketuk **Screen Mirroring**.
3. Pilih **cli-mirror** (atau nama yang Anda tentukan).
4. Layar iPhone akan muncul di jendela baru di Ubuntu.

---

## Opsi

```bash
sudo python3 cli_mirror.py [opsi]

  -n, --name NAMA         Nama receiver yang tampil di menu Screen Mirroring (default: cli-mirror)
  -p, --port PORT         Port AirPlay RTSP (default: 7000)
  --ssid NAMA_WIFI        Nama Wi-Fi untuk ditampilkan sebagai QR code
  --pass PASSWORD         Password Wi-Fi untuk QR code
  --no-bt                 Nonaktifkan kontrol mouse/touchpad Bluetooth (hanya mirroring)
  --keyboard              Aktifkan kontrol via tombol arrow keyboard
  -h, --help              Tampilkan bantuan

Contoh:
  sudo python3 cli_mirror.py --name "LaptopSaya"
  sudo python3 cli_mirror.py --ssid "NamaWifi" --pass "passwordwifi"
  sudo python3 cli_mirror.py --no-bt
  sudo python3 cli_mirror.py --keyboard
```

---

## Kontrol Mouse & Touchpad

| Aksi di Ubuntu/Touchpad   | Efek di iPhone              |
|---------------------------|-----------------------------|
| Gerak touchpad            | Menggerakkan kursor         |
| Tap touchpad              | Tap                         |
| Scroll wheel              | Scroll halaman              |
| Tombol arrow (keyboard)   | Menggerakkan kursor         |
| Enter / Space (keyboard)  | Tap                         |
| Tab (keyboard)            | Tap dan tahan (kanan)       |

**Opsi keyboard:** Jalankan dengan `sudo python3 cli_mirror.py --keyboard` untuk menggunakan tombol arrow keyboard sebagai pengganti touchpad.

Catatan: Saat Bluetooth mouse/touchpad terhubung, akan muncul kursor bulat kecil (AssistiveTouch) di layar iPhone. Ini normal.

---

## Cara Kerja

```
iPhone (AirPlay Sender)
    |
    |--- Wi-Fi (AirPlay / RTSP) ---> Ubuntu: UxPlay C++ Engine ---> Window GStreamer
    |                                         (Decode H.264 + render)
    |
    |--- Bluetooth (HID Mouse/Touchpad) <---- Ubuntu: cli_mirror.py (L2CAP HID via evdev)
         (Kirim tap/klik/scroll)              (Tangkap event touchpad/keyboard)
```

---

## Struktur Proyek

```
cli-mirror/
├── cli_mirror.py      # Entry point utama (orchestrator AirPlay + Bluetooth)
├── bt_mouse.py        # Modul emulasi Bluetooth HID Mouse (standalone, juga support evdev)
├── install.sh         # Installer dependensi dan builder (jalankan sekali)
├── uxplay/            # C++ AirPlay core engine (git submodule dari UxPlay)
└── src/core/          # Modul mDNS discovery kustom (C)
    ├── mdns.c
    ├── mdns.h
    └── main.c
```

---

## Troubleshooting

**iPhone tidak muncul di daftar Screen Mirroring?**
- Pastikan iPhone dan Ubuntu terhubung ke jaringan Wi-Fi yang sama.
- Buka port di firewall: `sudo ufw allow 7000/tcp && sudo ufw allow 7000/udp`
- Cek apakah Avahi berjalan: `systemctl status avahi-daemon`

**Bluetooth tidak terdeteksi?**
- Jalankan: `sudo rfkill unblock bluetooth`
- Lalu restart: `sudo systemctl restart bluetooth`

**Touchpad/Keyboard tidak bisa mengontrol iPhone?**
- Pastikan baris `DisablePlugins = input` ada di `/etc/bluetooth/main.conf`
- Aktifkan AssistiveTouch di iPhone: Pengaturan > Aksesibilitas > AssistiveTouch > Aktifkan
- Pastikan `evdev` terinstall: `sudo pip3 install evdev`
- Jika menggunakan Wayland, evdev adalah cara yang benar untuk menangkap input

**Layar Ubuntu mati saat layar iPhone dikunci?**
- Atur Auto-Lock iPhone ke "Jangan Pernah": Pengaturan > Tampilan & Kecerahan > Kunci Otomatis > Jangan Pernah

---

## Lisensi

MIT License. Bebas digunakan, dimodifikasi, dan didistribusikan.

---

## Kredit

- [UxPlay](https://github.com/FDH2/UxPlay) — Open-source AirPlay mirroring server (C++)
- [GStreamer](https://gstreamer.freedesktop.org/) — Framework multimedia untuk dekoding H.264
