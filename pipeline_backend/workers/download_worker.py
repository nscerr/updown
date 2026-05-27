# workers/download_worker.py
# Orkestrator Thread untuk pipeline download video.

import os
from config import COOKIE_FILE
from state import append_log, update_file_entry, get_file_size_mb
from services import downloader


def worker_download(file_id, url):
    """
    Fungsi target untuk thread download.
    Mengorkestrasi: State update -> Ekstraksi -> Download -> Finalisasi State
    """
    try:
        # 1. Tandai status menjadi downloading di STATE_MEMORY
        update_file_entry(file_id, status="downloading")

        # 2. Logging awal
        append_log(file_id, "Memulai pipeline download...", "accent")
        append_log(file_id, f"URL: {url}", "info")

        # 3. Ekstrak header & cookie menggunakan service
        headers, cookies = downloader.extract_headers_and_cookies(url, file_id)

        if not headers:
            append_log(file_id, "Tidak ada header yang diekstrak. Proses mungkin gagal.", "warning")

        # 4. Simpan cookie ke file
        cookie_count = downloader.save_cookies_to_file(cookies)
        append_log(file_id, f"Cookie disimpan ({cookie_count} entri)", "success")

        # 5. Jalankan yt-dlp menggunakan service
        result_path = downloader.run_ytdlp(url, headers, COOKIE_FILE, file_id)

        # 6. Finalisasi berdasarkan hasil download
        if result_path:
            size_mb = get_file_size_mb(result_path)
            update_file_entry(
                file_id,
                name=os.path.basename(result_path),
                path=result_path,
                size_mb=round(size_mb, 2),
                status="ready"
            )
            append_log(file_id, f"Pipeline download selesai! File: {os.path.basename(result_path)} ({size_mb:.1f} MB)", "accent")
        else:
            update_file_entry(file_id, status="error")
            append_log(file_id, "Pipeline download gagal.", "error")

    except Exception as e:
        # Tangkap error fatal yang mungkin tidak tertangkap di dalam service
        update_file_entry(file_id, status="error")
        append_log(file_id, f"Error fatal di worker download: {e}", "error")