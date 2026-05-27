# routes/api.py
# Endpoint REST API untuk trigger pipeline dan pengambilan data (Polling).

import os
import threading
from flask import Blueprint, request, jsonify, send_file

# Impor State Management
from state import (
    create_file_entry, 
    get_file_entry, 
    get_all_files,
    STATE_MEMORY,
    state_lock,
    get_next_index, 
    generate_random_string
)

# Impor Workers
from workers.download_worker import worker_download
from workers.compress_worker import worker_compress
from workers.upload_worker import worker_upload

# Impor Konfigurasi
from config import OUTPUT_FOLDER, SERVER_CONFIG

# Inisialisasi Blueprint
api_bp = Blueprint('api', __name__)


# =============================================================================
# SERVE FRONTEND
# =============================================================================

@api_bp.route("/")
def index():
    """Serve frontend HTML utama."""
    html_path = "/content/index.html"
    if os.path.exists(html_path):
        return send_file(html_path)
    return "<h1>VideoPipeline Backend</h1><p>Frontend tidak ditemukan di /content/index.html</p>", 200


# =============================================================================
# POLLING ENDPOINT (Pengganti SSE)
# =============================================================================

@api_bp.route("/api/poll", methods=["GET"])
def api_poll():
    """
    Endpoint polling utama.
    Frontend memanggil endpoint ini berkala (misal setiap 1 detik).
    Mengambil parameter 'since' (timestamp) untuk hanya mengirim log baru 
    dan perubahan status sejak polling terakhir.
    """
    # Ambil timestamp terakhir dari frontend, default 0 (ambil semua)
    try:
        since_ts = float(request.args.get("since", 0))
    except ValueError:
        since_ts = 0.0

    files_data = []
    new_logs = []

    # Baca STATE_MEMORY secara langsung dengan lock untuk konsistensi
    with state_lock:
        for entry in STATE_MEMORY:
            # 1. Kompilasi snapshot status file untuk update UI (Tab 2 & 3)
            files_data.append({
                "file_id": entry["file_id"],
                "name": entry["name"],
                "size_mb": entry["size_mb"],
                "status": entry["status"],
                "cdn_link": entry["cdn_link"],
            })

            # 2. Kumpulkan log baru sejak 'since_ts' untuk Terminal (Tab 1)
            for log in entry["log"]:
                if log["ts"] > since_ts:
                    log_copy = dict(log)
                    # Suntikkan file_id agar frontend tahu asal log (jika perlu)
                    log_copy["file_id"] = entry["file_id"]
                    new_logs.append(log_copy)

    # Urutkan log berdasarkan timestamp agar tidak berantakan
    new_logs.sort(key=lambda x: x["ts"])

    return jsonify({
        "files": files_data,
        "logs": new_logs
    })


# =============================================================================
# DATA ENDPOINTS (GET)
# =============================================================================

@api_bp.route("/api/files", methods=["GET"])
def api_get_files():
    """Ambil daftar seluruh file (tanpa log, untuk efisiensi bandwidth)."""
    return jsonify(get_all_files())


@api_bp.route("/api/files/<file_id>", methods=["GET"])
def api_get_file(file_id):
    """Ambil detail satu file termasuk log terbaru."""
    entry = get_file_entry(file_id)
    if not entry:
        return jsonify({"error": "File tidak ditemukan"}), 404

    # Ambil maks 200 log terakhir agar payload tidak terlalu besar
    logs, _ = get_new_logs(file_id, max(0, len(entry.get("log", [])) - 200))
    
    result = {
        "file_id": entry["file_id"],
        "name": entry["name"],
        "path": entry["path"],
        "size_mb": entry["size_mb"],
        "status": entry["status"],
        "cdn_link": entry["cdn_link"],
        "logs": logs,
    }
    return jsonify(result)


# =============================================================================
# ACTION ENDPOINTS (POST - Trigger Background Threads)
# =============================================================================

@api_bp.route("/api/download", methods=["POST"])
def api_download():
    """Mulai proses download video (background thread)."""
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL tidak boleh kosong"}), 400
    if not url.startswith("http"):
        return jsonify({"error": "URL tidak valid, harus dimulai dengan http(s)://"}), 400

    idx = get_next_index()
    rand = generate_random_string()
    placeholder_name = f"{idx}-{rand}.mp4"
    placeholder_path = os.path.join(OUTPUT_FOLDER, placeholder_name)

    entry = create_file_entry(
        name=placeholder_name,
        path=placeholder_path,
        status="downloading"
    )
    file_id = entry["file_id"]

    thread = threading.Thread(
        target=worker_download,
        args=(file_id, url),
        daemon=True
    )
    thread.start()

    return jsonify({"file_id": file_id})


@api_bp.route("/api/compress", methods=["POST"])
def api_compress():
    """Mulai proses kompresi video (background thread)."""
    data = request.get_json(silent=True) or {}
    file_id = data.get("file_id", "").strip()
    server = data.get("server", "freeconvert")
    target_mb = data.get("target_mb", 99)

    if not file_id:
        return jsonify({"error": "file_id tidak boleh kosong"}), 400

    entry = get_file_entry(file_id)
    if not entry:
        return jsonify({"error": "File tidak ditemukan"}), 404
    if entry["status"] != "ready":
        return jsonify({"error": f"File sedang dalam status '{entry['status']}', tidak bisa dikompresi"}), 409
    if server not in ("freeconvert", "compress2go"):
        return jsonify({"error": "Server kompresi tidak valid (pilih: freeconvert, compress2go)"}), 400

    try:
        target_mb = float(target_mb)
        if target_mb <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "target_mb harus berupa angka positif"}), 400

    thread = threading.Thread(
        target=worker_compress,
        args=(file_id, server, target_mb),
        daemon=True
    )
    thread.start()

    return jsonify({"file_id": file_id, "status": "compressing"})


@api_bp.route("/api/upload", methods=["POST"])
def api_upload():
    """Mulai proses upload ke CDN (background thread)."""
    data = request.get_json(silent=True) or {}
    file_id = data.get("file_id", "").strip()
    cdn = data.get("cdn", "Videy")
    faststart = data.get("faststart", True)

    if not file_id:
        return jsonify({"error": "file_id tidak boleh kosong"}), 400

    entry = get_file_entry(file_id)
    if not entry:
        return jsonify({"error": "File tidak ditemukan"}), 404
    if entry["status"] != "ready":
        return jsonify({"error": f"File sedang dalam status '{entry['status']}', tidak bisa diupload"}), 409
    if cdn not in SERVER_CONFIG:
        return jsonify({"error": f"CDN '{cdn}' tidak valid (pilih: {', '.join(SERVER_CONFIG.keys())})"}), 400

    thread = threading.Thread(
        target=worker_upload,
        args=(file_id, cdn, faststart),
        daemon=True
    )
    thread.start()

    return jsonify({"file_id": file_id, "status": "uploading"})