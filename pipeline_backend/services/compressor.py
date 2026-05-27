# services/compressor.py
# Logika bisnis untuk kompresi video via API eksternal (FreeConvert & Compress2Go).

import os
import time
import requests as std_requests

# Impor konfigurasi
from config import OUTPUT_FOLDER

# Impor state management
from state import append_log, get_next_index, generate_random_string, get_file_size_mb, get_file_entry


# =============================================================================
# KOMPRESI — FREECONVERT (Server 1)
# Dimigrasikan dari Source_Original_Colab.py — bagian "KOMPRES VIDEO SERVER 1"
# =============================================================================

def compress_freeconvert(file_path, target_mb, file_id):
    """Kompresi video menggunakan API FreeConvert."""
    file_name = os.path.basename(file_path)
    file_ext = os.path.splitext(file_name)[1].strip('.')
    original_size = get_file_size_mb(file_path)

    append_log(file_id, f"[FreeConvert] Memulai kompresi: {file_name} ({original_size:.1f} MB) → Target: {target_mb} MB", "warning")

    CREATE_JOB_URL = "https://api.freeconvert.com/v1/process/jobs"
    api_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*"
    }

    # 1. Buat job
    append_log(file_id, "[FreeConvert] Membuat job kompresi...", "info")
    payload = {
        "tasks": {
            "import": {"operation": "import/upload"},
            "compress": {
                "operation": "compress",
                "input": "import",
                "input_format": file_ext,
                "output_format": "mp4",
                "options": {
                    "video_codec_compress": "libx264",
                    "compress_video": "by_size",
                    "video_compress_max_filesize": target_mb,
                    "isCompatibleWithOldDevices_compress": False,
                    "subtitle_add": "upload",
                    "subtitle_mode": "hard"
                }
            },
            "export-url": {"operation": "export/url", "input": "compress"}
        }
    }

    try:
        resp = std_requests.post(CREATE_JOB_URL, headers=api_headers, json=payload)
        resp.raise_for_status()
        job_data = resp.json()
        job_id = job_data['id']
        upload_task = next(t for t in job_data['tasks'] if t['name'] == 'import')
        upload_url = upload_task['result']['form']['url']
        signature = upload_task['result']['form']['parameters']['signature']
        append_log(file_id, f"[FreeConvert] Job dibuat: {job_id}", "success")
    except Exception as e:
        append_log(file_id, f"[FreeConvert] Gagal membuat job: {e}", "error")
        return None

    # 2. Upload file ke server FreeConvert
    append_log(file_id, "[FreeConvert] Mengunggah file ke server...", "info")
    try:
        with open(file_path, 'rb') as f:
            files = {'file': (file_name, f)}
            form_data = {'signature': signature}
            resp = std_requests.post(upload_url, data=form_data, files=files)
            resp.raise_for_status()
        append_log(file_id, "[FreeConvert] File berhasil diunggah", "success")
    except Exception as e:
        append_log(file_id, f"[FreeConvert] Gagal mengunggah file: {e}", "error")
        return None

    # 3. Pantau status job
    append_log(file_id, "[FreeConvert] Memantau status kompresi...", "info")
    status_url = f"https://api.freeconvert.com/v1/process/jobs/{job_id}"
    final_url = None

    while True:
        # Cek apakah proses dibatalkan secara manual (status di-set "error" dari luar)
        entry = get_file_entry(file_id)
        if entry and entry["status"] == "error":
            append_log(file_id, "[FreeConvert] Proses dibatalkan secara eksternal.", "error")
            return None

        try:
            resp = std_requests.get(status_url)
            resp.raise_for_status()
            status_data = resp.json()
            job_status = status_data.get('status')
            append_log(file_id, f"[FreeConvert] Status: {job_status}", "dim")

            if job_status == 'completed':
                export_task = next(t for t in status_data['tasks'] if t['name'] == 'export-url')
                final_url = export_task['result']['url']
                append_log(file_id, "[FreeConvert] Kompresi selesai di server!", "success")
                break
            elif job_status == 'failed':
                append_log(file_id, "[FreeConvert] Kompresi gagal di server.", "error")
                return None

            time.sleep(10)
        except Exception as e:
            append_log(file_id, f"[FreeConvert] Error memeriksa status: {e}", "warning")
            time.sleep(10)

    # 4. Download hasil ke OUTPUT_FOLDER dengan nama baru
    if final_url:
        append_log(file_id, "[FreeConvert] Mengunduh hasil kompresi...", "info")
        new_idx = get_next_index()
        new_rand = generate_random_string()
        new_name = f"{new_idx}-{new_rand}.mp4"
        save_path = os.path.join(OUTPUT_FOLDER, new_name)

        try:
            with std_requests.get(final_url, stream=True) as r:
                r.raise_for_status()
                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            compressed_size = get_file_size_mb(save_path)
            append_log(file_id, f"[FreeConvert] Selesai! {new_name} ({compressed_size:.1f} MB)", "success")
            return save_path
        except Exception as e:
            append_log(file_id, f"[FreeConvert] Gagal mengunduh hasil: {e}", "error")
            # Bersihkan file gagal
            if os.path.exists(save_path):
                os.remove(save_path)
            return None

    return None


# =============================================================================
# KOMPRESI — COMPRESS2GO (Server 2)
# Dimigrasikan dari Source_Original_Colab.py — bagian "KOMPRES VIDEO SERVER 2"
# =============================================================================

def compress_compress2go(file_path, target_mb, file_id):
    """Kompresi video menggunakan API Compress2Go."""
    file_name = os.path.basename(file_path)
    original_size = get_file_size_mb(file_path)

    append_log(file_id, f"[Compress2Go] Memulai kompresi: {file_name} ({original_size:.1f} MB) → Target: {target_mb} MB", "warning")

    BASE_API_URL = "https://dragon.compress2go.com/api"
    COMMON_HEADERS = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/json",
        "Origin": "https://www.compress2go.com",
        "Referer": "https://www.compress2go.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    }

    try:
        # Langkah 1: Inisiasi sesi
        append_log(file_id, "[Compress2Go] Membuat sesi pekerjaan...", "info")
        init_payload = {
            "operation": "compressvideo",
            "fail_on_conversion_error": False,
            "fail_on_input_error": False
        }
        resp = std_requests.post(f"{BASE_API_URL}/jobs?async=true", headers=COMMON_HEADERS, json=init_payload)
        resp.raise_for_status()
        initial_job_id = resp.json()['sat']['id_job']
        append_log(file_id, f"[Compress2Go] Sesi dibuat: {initial_job_id}", "success")

        # Langkah 2: Dapatkan detail job
        append_log(file_id, "[Compress2Go] Mengambil detail & token unggahan...", "info")
        time.sleep(1)
        resp = std_requests.get(f"{BASE_API_URL}/jobs/{initial_job_id}?async=true", headers=COMMON_HEADERS)
        resp.raise_for_status()
        details = resp.json()
        real_job_id = details['id']
        upload_token = details['token']
        upload_server = details['server']
        append_log(file_id, f"[Compress2Go] Job ID: {real_job_id}", "success")

        # Langkah 3: Upload file
        append_log(file_id, "[Compress2Go] Mengunggah file video...", "info")
        upload_url = f"{upload_server}/upload-file/{real_job_id}"
        upload_headers = {
            "User-Agent": COMMON_HEADERS["User-Agent"],
            "Origin": COMMON_HEADERS["Origin"],
            "Referer": COMMON_HEADERS["Referer"],
            "Accept": "*/*",
            "x-oc-token": upload_token,
        }
        with open(file_path, 'rb') as f:
            files_payload = {'file[]': (file_name, f, 'video/mp4')}
            resp = std_requests.post(upload_url, headers=upload_headers, files=files_payload)
            resp.raise_for_status()

        upload_result = resp.json()
        if upload_result.get('completed'):
            append_log(file_id, "[Compress2Go] File berhasil diunggah", "success")
        else:
            append_log(file_id, "[Compress2Go] Unggahan gagal menurut server.", "error")
            return None

        # Langkah 4: Mulai kompresi
        append_log(file_id, "[Compress2Go] Memulai proses kompresi...", "info")
        conversion_payload = {
            "category": "video",
            "target": "mp4",
            "options": {"allow_multiple_outputs": True, "file_size": target_mb}
        }
        resp = std_requests.post(
            f"{BASE_API_URL}/jobs/{real_job_id}/conversions",
            headers=COMMON_HEADERS,
            json=conversion_payload
        )
        resp.raise_for_status()
        append_log(file_id, "[Compress2Go] Perintah kompresi dikirim", "success")

        # Langkah 5: Pantau status
        append_log(file_id, "[Compress2Go] Memantau status kompresi...", "info")
        status_url = f"{BASE_API_URL}/jobs/{real_job_id}"
        final_url = None

        while True:
            entry = get_file_entry(file_id)
            if entry and entry["status"] == "error":
                append_log(file_id, "[Compress2Go] Proses dibatalkan secara eksternal.", "error")
                return None

            try:
                resp = std_requests.get(status_url, headers=COMMON_HEADERS)
                resp.raise_for_status()
                status_data = resp.json()
                status_code = status_data['status']['code']
                append_log(file_id, f"[Compress2Go] Status: {status_code}", "dim")

                if status_code == 'completed':
                    final_url = status_data['output'][0]['uri']
                    append_log(file_id, "[Compress2Go] Kompresi selesai!", "success")
                    break
                elif status_code in ['failed', 'error']:
                    append_log(file_id, "[Compress2Go] Kompresi gagal di server.", "error")
                    return None

                time.sleep(10)
            except Exception as e:
                append_log(file_id, f"[Compress2Go] Error memeriksa status: {e}", "warning")
                time.sleep(10)

        # Langkah 6: Download hasil
        if final_url:
            append_log(file_id, "[Compress2Go] Mengunduh hasil kompresi...", "info")
            new_idx = get_next_index()
            new_rand = generate_random_string()
            new_name = f"{new_idx}-{new_rand}.mp4"
            save_path = os.path.join(OUTPUT_FOLDER, new_name)

            with std_requests.get(final_url, stream=True) as r:
                r.raise_for_status()
                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            compressed_size = get_file_size_mb(save_path)
            append_log(file_id, f"[Compress2Go] Selesai! {new_name} ({compressed_size:.1f} MB)", "success")
            return save_path

    except Exception as e:
        append_log(file_id, f"[Compress2Go] Error: {e}", "error")
        return None