# UpDown

Aplikasi web sederhana untuk [tuliskan tujuan aplikasi Anda di sini] yang menggunakan Flask dan Cloudflare Tunnel.

## 🚀 Instalasi

Pastikan Anda berada di sistem berbasis Linux (Ubuntu/Debian).

1. Clone repository ini:
    git clone https://github.com/nscerr/updown.git
    cd updown

2. Berikan izin eksekusi pada skrip setup dan jalankan:
    chmod +x setup.sh
    ./setup.sh

*Skrip ini akan menginstal dependensi sistem (ffmpeg, aria2), library Python, dan binary cloudflared.*

## 💻 Penggunaan

### Menjalankan Aplikasi
Setelah instalasi selesai, ikuti langkah berikut untuk menjalankan aplikasi:

1. Masuk ke folder backend:
    cd pipeline_backend

2. Jalankan server aplikasi (di background):
    python3 app.py > log.txt 2>&1 &

3. Jalankan tunnel untuk akses publik:
    cloudflared tunnel --url http://localhost:5000

## ☁️ Google Colab

Jika Anda menggunakan proyek ini di Google Colab, Anda dapat menjalankan seluruh proses (Setup hingga Tunnel) menggunakan satu sel kode dengan pendekatan Control Panel. 

Gunakan snippet berikut di sel notebook Anda:

# Jalankan sekali untuk setup
import os
if not os.path.exists('updown'):
    !git clone https://github.com/nscerr/updown.git
%cd updown
!chmod +x setup.sh && ./setup.sh

# Gunakan cell ini untuk Start/Stop aplikasi
# (Gunakan UI Form di Colab untuk kemudahan)
action = "Start" #@param ["Start", "Stop"]
if action == "Start":
    !python3 pipeline_backend/app.py > log.txt 2>&1 &
    !cloudflared tunnel --url http://localhost:5000 > tunnel.log 2>&1 &
else:
    !fuser -k 5000/tcp && pkill cloudflared

## 📋 Catatan

- Log: Anda dapat melihat log aplikasi dengan perintah cat pipeline_backend/log.txt.
- Port: Aplikasi berjalan pada port 5000 secara default.
