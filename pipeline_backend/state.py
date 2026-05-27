# state.py
# Manajemen State Ephemeral (RAM-ONLY) dan Utility pendukungnya.
# Seluruh keadaan aplikasi disimpan sebagai variabel Global (Dictionary) di RAM Python.

import os
import uuid
import random
import string
import threading
import time

# Impor konfigurasi dari config.py
from config import COUNTER_FILE, RANDOM_LENGTH, MAX_LOG_ENTRIES

# =============================================================================
# STATE MEMORY (RAM-ONLY, EPHEMERAL)
# Seluruh keadaan disimpan di sini. Urutan selalu terbaru di Index 0.
# =============================================================================

STATE_MEMORY = []       # List of dicts, file terbaru selalu di index 0

# Lock utama untuk melindungi STATE_MEMORY agar tidak corrupt saat
# Thread menulis log dan Flask membaca data secara bersamaan.
# Menggunakan RLock (Re-entrant Lock) agar aman untuk nested calls.
state_lock = threading.RLock()

# Lock khusus untuk counter file (penulisan ke COUNTER_FILE)
counter_lock = threading.Lock()


# =============================================================================
# UTILITY FUNCTIONS: Penamaan & Ukuran File
# =============================================================================

def generate_random_string(length=RANDOM_LENGTH):
    """Hasilkan string acak alfanumerik (huruf kecil + angka)."""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=length))


def get_next_index():
    """
    Baca counter dari file, tingkatkan, tulis ulang.
    Kembalikan indeks 3 digit (misal '001', '002').
    Thread-safe dengan counter_lock.
    """
    with counter_lock:
        if os.path.exists(COUNTER_FILE):
            with open(COUNTER_FILE, "r") as f:
                try:
                    last_index = int(f.read().strip())
                except ValueError:
                    last_index = 0
        else:
            last_index = 0

        next_index = last_index + 1

        with open(COUNTER_FILE, "w") as f:
            f.write(str(next_index))

    return f"{next_index:03d}"


def get_file_size_mb(path):
    """Dapatkan ukuran file dalam MB, 0 jika tidak ada."""
    if os.path.exists(path):
        return os.path.getsize(path) / (1024 * 1024)
    return 0.0


# =============================================================================
# STATE MANIPULATION FUNCTIONS (THREAD-SAFE)
# =============================================================================

def create_file_entry(name, path, size_mb=0.0, status="ready", cdn_link=None):
    """Buat entri file baru di STATE_MEMORY (selalu di index 0)."""
    entry = {
        "file_id": uuid.uuid4().hex[:8],
        "name": name,
        "path": path,
        "size_mb": round(size_mb, 2),
        "status": status,
        "log": [],
        "cdn_link": cdn_link,
    }
    with state_lock:
        STATE_MEMORY.insert(0, entry)
    return entry


def update_file_entry(file_id, **kwargs):
    """Update field pada entri file tertentu (thread-safe)."""
    with state_lock:
        entry = _get_file_entry_unsafe(file_id)
        if entry:
            entry.update(kwargs)
            return dict(entry) # Kembalikan copy
    return None


def get_file_entry(file_id):
    """Ambil entri file berdasarkan ID (thread-safe, mengembalikan copy)."""
    with state_lock:
        entry = _get_file_entry_unsafe(file_id)
        if entry:
            return dict(entry)
    return None


def _get_file_entry_unsafe(file_id):
    """
    Ambil referensi langsung ke entry di STATE_MEMORY.
    HANYA dipakai di dalam blok state_lock (internal function).
    """
    for entry in STATE_MEMORY:
        if entry["file_id"] == file_id:
            return entry
    return None


def move_to_top(file_id):
    """Pindahkan entri file ke index 0 (paling atas)."""
    with state_lock:
        for i, entry in enumerate(STATE_MEMORY):
            if entry["file_id"] == file_id:
                if i > 0:
                    STATE_MEMORY.insert(0, STATE_MEMORY.pop(i))
                return dict(entry)
    return None


def append_log(file_id, text, log_type="info"):
    """
    Tambah baris log ke entri file (thread-safe, bounded).
    log_type: "info", "success", "warning", "error", "accent", "dim"
    """
    with state_lock:
        entry = _get_file_entry_unsafe(file_id)
        if entry:
            entry["log"].append({
                "text": text,
                "type": log_type,
                "ts": time.time()
            })
            # Batasi jumlah log per file untuk mencegah memory leak
            if len(entry["log"]) > MAX_LOG_ENTRIES:
                entry["log"] = entry["log"][-MAX_LOG_ENTRIES:]
            return
    # Fallback jika file_id tidak ditemukan di STATE
    print(f"[ORPHAN LOG][{file_id}] {text}")


def get_new_logs(file_id, since_index=0):
    """Ambil log baru sejak indeks tertentu (thread-safe)."""
    with state_lock:
        entry = _get_file_entry_unsafe(file_id)
        if entry:
            logs = entry["log"][since_index:]
            return list(logs), len(entry["log"])
    return [], since_index


def get_all_files():
    """Ambil seluruh STATE_MEMORY tanpa log (untuk API response, hemat bandwidth)."""
    with state_lock:
        return [
            {
                "file_id": e["file_id"],
                "name": e["name"],
                "path": e["path"],
                "size_mb": e["size_mb"],
                "status": e["status"],
                "cdn_link": e["cdn_link"],
                "log_count": len(e["log"]),
            }
            for e in STATE_MEMORY
        ]