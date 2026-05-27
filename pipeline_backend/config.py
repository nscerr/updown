# config.py
# Konfigurasi global untuk keseluruhan pipeline.
# Semua "magic numbers" dan path dikumpulkan di sini.

import os

# =============================================================================
# LOKASI PENYIMPANAN (PATHS)
# =============================================================================
OUTPUT_FOLDER = "/content/downloads"
COUNTER_FILE = "/content/download_counter.txt"
COOKIE_FILE = "/content/cookies.txt"
TEMP_DIR = "/content/temp_pipeline"

# Pastikan folder ada saat modul ini di-import
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# =============================================================================
# KONFIGURASI YT-DLP & CURL_CFFI
# =============================================================================
IMPERSONATE_TARGET = "chrome131"

EXCLUDED_HEADERS = {
    "host", "accept-encoding", "content-length", "connection",
    "priority", "upgrade-insecure-requests",
}

YTDLP_BASE_OPTIONS = [
    "yt-dlp",
    "--no-check-certificate",
    "--hls-prefer-native",
    "--concurrent-fragments", "5",
    "--external-downloader", "aria2c",
    "--external-downloader-args", "-x 16 -s 16 -k 1M",
    "-f", "bestvideo[ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]/best",
]

# =============================================================================
# KONFIGURASI SERVER CDN & LIMIT UKURAN
# =============================================================================
SERVER_CONFIG = {
    "Videy": {
        "max_size_mb": 100,
        "endpoint": "https://videy.co/api/upload",
        "file_field_name": "file",
        "requires_visitor_id": True,
    },
    "AceImg": {
        "max_size_mb": 100,
        "endpoint": "https://api.aceimg.com/api/upload",
        "file_field_name": "file",
        "requires_visitor_id": False,
    },
    "Qu.ax": {
        "max_size_mb": 256,
        "endpoint": "https://qu.ax/upload.php",
        "file_field_name": "files[]",
        "requires_visitor_id": False,
        "valid_expiry": [1, 7, 30, 360, -1],
    }
}

FALLBACK_SERVER = "Qu.ax"
DEFAULT_EXPIRY_QUAX = -1

# =============================================================================
# KONFIGURASI MOOV ATOM & FFMPEG
# =============================================================================
MOOV_CONFIG = {
    "scan_buffer_bytes": 5 * 1024 * 1024,  # Baca 5MB pertama/terakhir
    "remux_suffix": "_faststart",
    "ffmpeg_loglevel": "error"
}

# =============================================================================
# KONFIGURASI BACKEND (STATE, SSE, THREADS)
# =============================================================================
RANDOM_LENGTH = 5          # Panjang string alfanumerik acak penamaan file
MAX_LOG_ENTRIES = 600      # Batas log per file (mencegah memory leak di RAM)
SSE_PING_INTERVAL = 15     # Detik antar heartbeat SSE
GRACE_KILL_SECONDS = 8     # Tunggu sebelum kill proses setelah SSE putus
SSE_STREAM_INTERVAL = 0.4  # Detik jeda polling log di SSE stream