# services/uploader.py
# Logika bisnis untuk Pre-processing (Moov Atom/FFmpeg) dan Upload ke CDN.

import os
import uuid
import mimetypes
import subprocess
from urllib.parse import parse_qs, urlparse
import requests as std_requests

# Impor konfigurasi
from config import SERVER_CONFIG, FALLBACK_SERVER, DEFAULT_EXPIRY_QUAX, MOOV_CONFIG

# Impor state management
from state import append_log, get_file_size_mb

# Impor tracking proses dari manager (akan dibuat selanjutnya)
from workers.manager import register_process, unregister_process


# =============================================================================
# HELPER FUNCTIONS: PARSING RESPONS CDN
# =============================================================================

def parse_aceimg_cdn(download_link):
    """Ekstrak CDN link dari format URL AceImg."""
    try:
        parsed_url = urlparse(download_link)
        file_id = parse_qs(parsed_url.query)['f'][0]
        return f"https://cdn.aceimg.com/{file_id}"
    except (KeyError, IndexError):
        raise ValueError("Gagal mengekstrak File ID dari respons AceImg.")


def process_server_response(server_name, data):
    """Parsing respons JSON dari server CDN menjadi link CDN."""
    if server_name == "Videy":
        video_id = data.get('id')
        if not video_id:
            raise ValueError("Respons Videy tidak mengandung 'id'")
        return f"https://cdn.videy.co/{video_id}.mp4"

    elif server_name == "AceImg":
        if not data.get('status') or not data.get('link'):
            raise ValueError(data.get('message', 'Respons AceImg tidak valid'))
        return parse_aceimg_cdn(data['link'])

    elif server_name == "Qu.ax":
        if not data.get('success') or not data.get('files'):
            raise ValueError(data.get('description', 'Respons Qu.ax tidak valid'))
        return data['files'][0]['url']

    raise ValueError("Server tidak dikenali.")


# =============================================================================
# PRE-PROCESSING PIPELINE: MOOV ATOM ANALYZER & REMUXER
# =============================================================================

def check_moov_position(file_path, file_id):
    """Deteksi posisi moov atom menggunakan binary scan + ffprobe."""
    append_log(file_id, f"Mengecek posisi Moov Atom: {os.path.basename(file_path)}", "info")

    file_size = os.path.getsize(file_path)
    buffer_size = min(MOOV_CONFIG["scan_buffer_bytes"], file_size // 2)

    moov_at_begin = False
    moov_at_end = False

    try:
        with open(file_path, 'rb') as f:
            beginning = f.read(buffer_size)
            if b'moov' in beginning:
                moov_at_begin = True

            if not moov_at_begin:
                f.seek(-buffer_size, 2)
                ending = f.read()
                if b'moov' in ending:
                    moov_at_end = True

        # Validasi dengan ffprobe
        ffprobe_valid = False
        try:
            probe_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", file_path]
            subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
            ffprobe_valid = True
        except Exception:
            pass

        result = {
            'moov_at_begin': moov_at_begin,
            'moov_at_end': moov_at_end,
            'ffprobe_success': ffprobe_valid,
            'needs_remux': not moov_at_begin
        }

        if result['needs_remux']:
            append_log(file_id, "Moov Atom berada di akhir file. Diperlukan remuxing.", "warning")
        else:
            append_log(file_id, "Moov Atom sudah di awal. Remuxing tidak diperlukan.", "success")

        return result

    except Exception as e:
        append_log(file_id, f"Error analisis moov: {e}. Akan diasumsikan perlu remux.", "warning")
        return {'needs_remux': True, 'ffprobe_success': False}


def execute_ffmpeg_remux(input_path, file_id):
    """Jalankan FFmpeg untuk memindahkan moov atom ke awal file tanpa re-encode."""
    base, ext = os.path.splitext(input_path)
    output_path = f"{base}{MOOV_CONFIG['remux_suffix']}{ext}"

    append_log(file_id, "Menjalankan FFmpeg remux (faststart)...", "info")

    if os.path.exists(output_path):
        os.remove(output_path)

    ffmpeg_cmd = [
        "ffmpeg",
        "-i", input_path,
        "-c", "copy",
        "-movflags", "+faststart",
        "-loglevel", MOOV_CONFIG["ffmpeg_loglevel"],
        output_path
    ]

    proc = None
    try:
        # Gunakan Popen agar bisa stream output dan di-kill
        proc = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        register_process(file_id, proc)

        for line in proc.stdout:
            line = line.rstrip()
            if line:
                append_log(file_id, f"[ffmpeg] {line}", "dim")

        proc.wait()
        unregister_process(file_id)

        if not os.path.exists(output_path):
            append_log(file_id, "FFmpeg selesai tapi file output tidak ditemukan. Menggunakan file asli.", "warning")
            return input_path

        new_size = get_file_size_mb(output_path)
        append_log(file_id, f"Remux berhasil. Ukuran baru: {new_size:.1f} MB", "success")
        return output_path

    except subprocess.CalledProcessError as e:
        unregister_process(file_id)
        append_log(file_id, f"Gagal meremux: {e}. Menggunakan file asli.", "warning")
        return input_path
    except Exception as e:
        if proc:
            unregister_process(file_id)
            if proc.poll() is None:
                proc.kill()
        append_log(file_id, f"Error remux: {e}. Menggunakan file asli.", "warning")
        return input_path


def prepare_video_for_upload(file_path, enable_faststart, file_id):
    """Orkestrator pre-processing: cek moov → remux jika perlu."""
    if not enable_faststart:
        append_log(file_id, "Faststart dilewati (tidak diaktifkan).", "dim")
        return {"path": file_path, "was_remuxed": False}

    file_ext = os.path.splitext(file_path)[1].lower()
    if file_ext not in ['.mp4', '.mov']:
        append_log(file_id, "Faststart dilewati (bukan file MP4/MOV).", "dim")
        return {"path": file_path, "was_remuxed": False}

    analysis = check_moov_position(file_path, file_id)

    if analysis['needs_remux']:
        append_log(file_id, "Memulai proses remuxing...", "warning")
        remuxed_path = execute_ffmpeg_remux(file_path, file_id)
        is_remuxed = (remuxed_path != file_path)
        return {"path": remuxed_path, "was_remuxed": is_remuxed}
    else:
        return {"path": file_path, "was_remuxed": False}


# =============================================================================
# CDN UPLOAD LOGIC
# =============================================================================

def upload_file_to_server(server_name, file_path, file_id):
    """Fungsi inti untuk mengeksekusi HTTP POST ke server CDN yang dipilih."""
    config = SERVER_CONFIG[server_name]
    file_name = os.path.basename(file_path)
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is None:
        mime_type = 'application/octet-stream'

    append_log(file_id, f"Mengunggah ke {server_name}...", "info")

    try:
        with open(file_path, 'rb') as file_buffer:
            files_payload = {config["file_field_name"]: (file_name, file_buffer, mime_type)}
            data_payload = {}
            url = config["endpoint"]

            if config.get("requires_visitor_id"):
                url = f"{url}?visitorId={str(uuid.uuid4())}"

            if server_name == "Qu.ax":
                data_payload = {"expiry": DEFAULT_EXPIRY_QUAX}

            resp = std_requests.post(url, files=files_payload, data=data_payload)
            resp.raise_for_status()
            
            cdn_link = process_server_response(server_name, resp.json())
            append_log(file_id, f"Upload ke {server_name} berhasil!", "success")
            return cdn_link

    except std_requests.exceptions.RequestException as e:
        raise ConnectionError(f"Koneksi ke {server_name} gagal: {e}")
    except Exception as e:
        raise RuntimeError(f"Error saat upload ke {server_name}: {e}")