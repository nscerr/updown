# workers/compress_worker.py
# Orkestrator Thread untuk pipeline kompresi video.

import os
from state import append_log, update_file_entry, get_file_entry, get_file_size_mb, move_to_top
from services import compressor


def worker_compress(file_id, server, target_mb):
    """
    Fungsi target untuk thread kompresi.
    Mengorkestrasi: State update -> Kompresi -> Hapus file lama -> Update file baru -> Pindah ke atas
    """
    try:
        # 1. Ambil data file saat ini
        entry = get_file_entry(file_id)
        if not entry:
            return

        original_path = entry["path"]
        original_name = entry["name"]

        # 2. Tandai status menjadi compressing di STATE_MEMORY
        update_file_entry(file_id, status="compressing")

        # 3. Logging awal
        append_log(file_id, "Memulai pipeline kompresi...", "accent")
        append_log(file_id, f"Server: {server} | Target: {target_mb} MB | Asli: {entry['size_mb']:.1f} MB", "info")

        # 4. Panggil service kompresi sesuai pilihan server
        if server == "freeconvert":
            result_path = compressor.compress_freeconvert(original_path, target_mb, file_id)
        elif server == "compress2go":
            result_path = compressor.compress_compress2go(original_path, target_mb, file_id)
        else:
            append_log(file_id, f"Server kompresi tidak dikenali: {server}", "error")
            update_file_entry(file_id, status="error")
            return

        # 5. Finalisasi berdasarkan hasil kompresi
        if result_path:
            # Hapus file lama dari disk Colab (hemat penyimpanan)
            if result_path != original_path and os.path.exists(original_path):
                os.remove(original_path)
                append_log(file_id, f"File lama dihapus: {original_name}", "dim")

            # Update state dengan metadata file baru
            new_size = get_file_size_mb(result_path)
            update_file_entry(
                file_id,
                name=os.path.basename(result_path),
                path=result_path,
                size_mb=round(new_size, 2),
                status="ready"
            )

            # Pindahkan entri file ke urutan paling atas sesuai PRD
            move_to_top(file_id)
            append_log(file_id, f"Pipeline kompresi selesai! File baru: {os.path.basename(result_path)} ({new_size:.1f} MB)", "accent")
        else:
            update_file_entry(file_id, status="error")
            append_log(file_id, "Pipeline kompresi gagal.", "error")

    except Exception as e:
        # Tangkap error fatal yang mungkin tidak tertangkap di dalam service
        update_file_entry(file_id, status="error")
        append_log(file_id, f"Error fatal di worker kompresi: {e}", "error")