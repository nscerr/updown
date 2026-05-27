# services/downloader.py
# Logika bisnis untuk ekstraksi header/cookie dan eksekusi yt-dlp.

import os
import subprocess
from curl_cffi import requests as cffi_requests
from curl_cffi.curl import CurlOpt

# Impor konfigurasi
from config import (
    OUTPUT_FOLDER, 
    COOKIE_FILE, 
    EXCLUDED_HEADERS, 
    YTDLP_BASE_OPTIONS, 
    IMPERSONATE_TARGET
)

# Impor state management
from state import append_log, get_next_index, generate_random_string, get_file_size_mb

# Impor tracking proses dari manager (akan dibuat selanjutnya)
from workers.manager import register_process, unregister_process


# =============================================================================
# CALLBACK EKSTRAKSI HEADER & COOKIE (SRP)
# =============================================================================
class HeaderExtractor:
    """Menangkap request header terakhir dan semua response cookie."""
    def __init__(self):
        self.request_headers = {}
        self.response_cookies = []

    def callback(self, type_, data):
        if type_ == 2:   # REQUEST HEADER
            raw = data.decode("utf-8", errors="ignore").strip()
            headers = {}
            for line in raw.split("\n"):
                if not line or line.startswith("GET ") or line.startswith("POST "):
                    continue
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers[name.strip()] = value.strip()
            # Simpan hanya header yang tidak dikecualikan
            self.request_headers = {
                k: v for k, v in headers.items()
                if k.lower() not in EXCLUDED_HEADERS
            }

        elif type_ == 1: # RESPONSE HEADER
            raw = data.decode("utf-8", errors="ignore")
            for line in raw.split("\n"):
                if line.lower().startswith("set-cookie:"):
                    cookie = line[len("set-cookie:"):].strip()
                    self.response_cookies.append(cookie)


def extract_headers_and_cookies(url, file_id):
    """Lakukan GET menggunakan curl_cffi, dapatkan header dan cookie via callback."""
    append_log(file_id, f"Mengakses {url} untuk ekstraksi header & cookie...", "info")
    extractor = HeaderExtractor()
    try:
        with cffi_requests.Session() as session:
            session.curl.setopt(CurlOpt.VERBOSE, 1)
            session.curl.setopt(CurlOpt.DEBUGFUNCTION, extractor.callback)
            response = session.get(url, impersonate=IMPERSONATE_TARGET)
            append_log(file_id, f"Status respons: {response.status_code}", "success")
    except Exception as e:
        append_log(file_id, f"Gagal mengekstrak header/cookie: {e}", "error")
    
    return extractor.request_headers, extractor.response_cookies


def save_cookies_to_file(cookies, filepath=COOKIE_FILE):
    """Tulis ulang file cookie (format Netscape). Selalu timpa."""
    with open(filepath, "w") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for raw_cookie in cookies:
            f.write(raw_cookie + "\n")
    return len(cookies)


# =============================================================================
# EKSEKUSI YT-DLP (Streaming Output)
# =============================================================================
def run_ytdlp(url, headers, cookie_file, file_id):
    """
    Susun perintah yt-dlp dengan output terstruktur.
    Stream stdout/stderr ke log file_id secara real-time.
    Kembalikan path file hasil download jika sukses, None jika gagal.
    """
    idx = get_next_index()
    rand_str = generate_random_string()
    output_template = os.path.join(OUTPUT_FOLDER, f"{idx}-{rand_str}.%(ext)s")

    cmd = list(YTDLP_BASE_OPTIONS)
    cmd.extend(["--cookies", cookie_file])
    cmd.extend(["-o", output_template])

    for name, value in headers.items():
        if value:
            cmd.extend(["--add-header", f"{name}:{value}"])

    cmd.append(url)

    append_log(file_id, f"Output: {idx}-{rand_str}.<ext>", "dim")
    append_log(file_id, "Menjalankan yt-dlp + aria2c...", "accent")

    proc = None
    try:
        # Gunakan Popen agar bisa stream output baris demi baris
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
        )
        
        # Daftarkan proses agar bisa di-kill jika SSE terputus
        register_process(file_id, proc)

        # Baca output real-time
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue

            # Klasifikasi warna log berdasarkan konten output yt-dlp
            log_type = "info"
            ll = line.lower()
            if "[download]" in ll:
                if "100%" in line:
                    log_type = "success"
                elif "%" in line:
                    log_type = "dim"
            elif "error" in ll or "warning" in ll:
                log_type = "warning"
            elif "merging" in ll or "destination" in ll:
                log_type = "info"

            append_log(file_id, line, log_type)

        proc.wait()
        unregister_process(file_id)

        if proc.returncode != 0:
            append_log(file_id, f"yt-dlp selesai dengan kode error: {proc.returncode}", "error")
            return None

        # Cari file hasil download berdasarkan prefix yang sudah ditentukan
        downloaded_file = None
        prefix = f"{idx}-{rand_str}."
        for f_name in os.listdir(OUTPUT_FOLDER):
            if f_name.startswith(prefix):
                downloaded_file = os.path.join(OUTPUT_FOLDER, f_name)
                break

        if downloaded_file and os.path.exists(downloaded_file):
            size_mb = get_file_size_mb(downloaded_file)
            append_log(file_id, f"File tersimpan: {os.path.basename(downloaded_file)} ({size_mb:.1f} MB)", "success")
            return downloaded_file
        else:
            append_log(file_id, "File hasil download tidak ditemukan di disk.", "error")
            return None

    except Exception as e:
        if proc:
            unregister_process(file_id)
            if proc.poll() is None:
                proc.kill()
        append_log(file_id, f"Error menjalankan yt-dlp: {e}", "error")
        return None