# workers/upload_worker.py
# Orkestrator Thread untuk pipeline upload ke CDN.

import os
from config import SERVER_CONFIG, FALLBACK_SERVER
from state import append_log, update_file_entry, get_file_entry, get_file_size_mb
from services import uploader


def worker_upload(file_id, cdn_server, enable_faststart):
    """
    Fungsi target untuk thread upload.
    Mengorkestrasi: Pre-process -> Validasi -> Fallback -> Upload -> Cleanup
    """
    temp_file_to_cleanup = None
    
    try:
        # 1. Ambil data file saat ini
        entry = get_file_entry(file_id)
        if not entry:
            return

        file_path = entry["path"]
        
        # 2. Tandai status menjadi uploading di STATE_MEMORY
        update_file_entry(file_id, status="uploading")

        # 3. Logging awal
        append_log(file_id, "Memulai pipeline upload CDN...", "accent")
        append_log(file_id, f"CDN: {cdn_server} | Faststart: {'Ya' if enable_faststart else 'Tidak'} | Ukuran: {entry['size_mb']:.1f} MB", "info")

        # 4. Pre-processing (moov atom check + remux via FFmpeg jika perlu)
        append_log(file_id, "TAHAP 1: Pre-processing...", "info")
        prep_result = uploader.prepare_video_for_upload(file_path, enable_faststart, file_id)
        final_path = prep_result["path"]
        was_remuxed = prep_result["was_remuxed"]

        # Tandai file hasil remux untuk dihapus nanti di blok finally
        if was_remuxed:
            temp_file_to_cleanup = final_path
            append_log(file_id, f"Menggunakan file remux: {os.path.basename(final_path)}", "info")

        # 5. Validasi ukuran file final terhadap batas CDN
        final_size = get_file_size_mb(final_path)
        target_server = cdn_server
        server_limit = SERVER_CONFIG[target_server]["max_size_mb"]

        append_log(file_id, f"TAHAP 2: Validasi — File: {os.path.basename(final_path)} ({final_size:.1f} MB)", "info")

        if final_size > server_limit:
            append_log(file_id, f"Ukuran melebihi batas {target_server} ({server_limit} MB).", "warning")
            fallback_limit = SERVER_CONFIG[FALLBACK_SERVER]["max_size_mb"]

            if final_size > fallback_limit:
                append_log(file_id, f"File terlalu besar bahkan untuk {FALLBACK_SERVER} ({fallback_limit} MB). Upload dibatalkan.", "error")
                update_file_entry(file_id, status="error")
                # Jika file terlalu besar, tetap hapus file remux karena upload tidak akan pernah jadi
                # Biarkan blok finally yang mengurus cleanup
                return

            append_log(file_id, f"Fallback ke {FALLBACK_SERVER}...", "warning")
            target_server = FALLBACK_SERVER

        # 6. Eksekusi upload ke server CDN
        append_log(file_id, f"TAHAP 3: Upload ke {target_server}...", "info")
        cdn_link = uploader.upload_file_to_server(target_server, final_path, file_id)

        # 7. Sukses! Update state dengan CDN Link
        update_file_entry(file_id, cdn_link=cdn_link, status="ready")
        append_log(file_id, f"CDN URL: {cdn_link}", "success")
        append_log(file_id, "Pipeline upload selesai!", "accent")

    except (ConnectionError, RuntimeError, ValueError) as e:
        # Error bisnis (koneksi gagal, respons server tidak valid, dll)
        update_file_entry(file_id, status="error")
        append_log(file_id, f"Pipeline upload gagal: {e}", "error")
        
        # Keputusan Arsitektur: Jika upload gagal, file remux TIDAK dihapus
        # agar pengguna bisa me-retry upload tanpa perlu remux ulang.
        temp_file_to_cleanup = None

    except Exception as e:
        # Error tak terduga
        update_file_entry(file_id, status="error")
        append_log(file_id, f"Error fatal di worker upload: {e}", "error")
        
        # Juga jangan hapus file remux jika ada error tak terduga
        temp_file_to_cleanup = None

    finally:
        # 8. Cleanup: Hapus file remux sementara HANYA jika proses sukses atau file terlalu besar
        # (Variabel temp_file_to_cleanup diset None secara eksplisit di blok except jika upload gagal)
        if temp_file_to_cleanup and os.path.exists(temp_file_to_cleanup):
            try:
                os.remove(temp_file_to_cleanup)
                append_log(file_id, f"File sementara dihapus: {os.path.basename(temp_file_to_cleanup)}", "dim")
            except Exception as e:
                append_log(file_id, f"Gagal menghapus file sementara: {e}", "warning")