# workers/manager.py
# Mengelola proses aktif (subprocess), koneksi SSE, dan logika penghentian otomatis (kill).

import threading
import subprocess

# Impor konfigurasi
from config import GRACE_KILL_SECONDS

# Impor state management
from state import append_log, update_file_entry

# =============================================================================
# PROCESS & SSE TRACKING STATE
# =============================================================================

# Dictionary untuk melacak proses Popen yang sedang berjalan
# Format: { file_id: subprocess.Popen }
active_processes = {}

# Dictionary untuk menghitung jumlah klien SSE yang aktif per file
# Format: { file_id: int }
sse_client_counts = {}

# Dictionary untuk menampung timer penjadwalan kill
# Format: { file_id: threading.Timer }
kill_timers = {}

# Lock khusus untuk melindungi dictionary di atas dari race condition
manager_lock = threading.Lock()


# =============================================================================
# PROSES REGISTRATION (Digunakan oleh services/downloader.py & uploader.py)
# =============================================================================

def register_process(file_id, proc):
    """Daftarkan subprocess aktif untuk tracking."""
    with manager_lock:
        active_processes[file_id] = proc
        # Batalkan timer kill jika ada (karena proses baru dimulai/baru terhubung)
        if file_id in kill_timers:
            kill_timers[file_id].cancel()
            del kill_timers[file_id]


def unregister_process(file_id):
    """Hapus subprocess dari tracking (proses selesai secara natural)."""
    with manager_lock:
        active_processes.pop(file_id, None)


# =============================================================================
# SSE CLIENT MANAGEMENT (Digunakan oleh routes/sse.py)
# =============================================================================

def increment_sse_client(file_id):
    """Tandai bahwa ada klien SSE baru yang terhubung untuk file_id ini."""
    with manager_lock:
        sse_client_counts[file_id] = sse_client_counts.get(file_id, 0) + 1
        # Jika ada klien yang terhubung, batalkan jadwal kill proses
        if file_id in kill_timers:
            kill_timers[file_id].cancel()
            del kill_timers[file_id]


def decrement_sse_client(file_id):
    """Tandai bahwa sebuah klien SSE terputus dari file_id ini."""
    with manager_lock:
        sse_client_counts[file_id] = max(0, sse_client_counts.get(file_id, 0) - 1)
        # Jika sudah tidak ada klien SSE lagi, jadwalkan penghentian proses
        if sse_client_counts[file_id] <= 0:
            schedule_process_kill(file_id)


# =============================================================================
# KILL LOGIC (Penghentian Proses Otomatis)
# =============================================================================

def kill_active_process(file_id):
    """Kirim SIGTERM (dan SIGKILL jika perlu) ke subprocess yang sedang berjalan."""
    proc = None
    with manager_lock:
        proc = active_processes.pop(file_id, None)
        kill_timers.pop(file_id, None)

    if proc and proc.poll() is None:
        try:
            proc.terminate()  # Kirim SIGTERM
            try:
                proc.wait(timeout=3)  # Tunggu proses mati dengan baik
            except subprocess.TimeoutExpired:
                proc.kill()  # Jika bandel, paksa mati dengan SIGKILL
                
            append_log(file_id, "Proses dihentikan secara paksa (SSE terputus & grace period habis).", "error")
            update_file_entry(file_id, status="error")
        except Exception as e:
            append_log(file_id, f"Gagal menghentikan proses: {e}", "error")


def schedule_process_kill(file_id):
    """
    Jadwalkan kill proses setelah grace period (GRACE_KILL_SECONDS).
    Dipanggil saat klien SSE terputus. Jika klien baru terhubung kembali 
    sebelum grace period habis, timer akan dibatalkan.
    """
    def _execute_scheduled_kill():
        with manager_lock:
            count = sse_client_counts.get(file_id, 0)
            # Hanya eksekusi kill jika masih 0 klien
            if count <= 0:
                # Keluarkan file_id dari kill_timers dulu sebelum eksekusi
                kill_timers.pop(file_id, None)
                # Lepaskan lock sebelum memanggil kill_active_process 
                # untuk menghindari nested locking yang berpotensi deadlock
                pass 
            else:
                # Ada klien baru muncul sebelum timer selesai, batalkan
                kill_timers.pop(file_id, None)
                return

        # Eksekusi di luar lock
        kill_active_process(file_id)

    timer = threading.Timer(GRACE_KILL_SECONDS, _execute_scheduled_kill)
    with manager_lock:
        # Timpa timer lama jika ada (untuk menghindari duplikasi timer)
        if file_id in kill_timers:
            kill_timers[file_id].cancel()
        kill_timers[file_id] = timer
    
    timer.daemon = True  # Agar thread tidak menghalangi shutdown aplikasi
    timer.start()