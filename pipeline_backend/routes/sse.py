# routes/sse.py
# Endpoint Server-Sent Events (SSE) untuk streaming log dan status real-time.

import json
import time
from flask import Blueprint, Response

# Impor State Management
from state import get_file_entry, get_new_logs, get_all_files

# Impor Process Manager (untuk tracking klien SSE)
from workers.manager import increment_sse_client, decrement_sse_client

# Impor Konfigurasi
from config import SSE_PING_INTERVAL, SSE_STREAM_INTERVAL

# Inisialisasi Blueprint
sse_bp = Blueprint('sse', __name__)


# =============================================================================
# SSE PER FILE — Streaming Log & Status untuk file_id tertentu
# =============================================================================

@sse_bp.route("/api/stream/<file_id>")
def stream_file(file_id):
    def event_stream():
        increment_sse_client(file_id)
        
        # KRUSIAL: Kirim data awal segera agar Cloudflared/Browser tidak memutus koneksi
        yield ": connected\n\n"

        try:
            last_index = 0
            entry = get_file_entry(file_id)
            
            if entry:
                # Kirim status awal
                status_data = {
                    "status": entry["status"],
                    "size_mb": entry["size_mb"],
                    "name": entry["name"],
                    "cdn_link": entry["cdn_link"],
                }
                yield f"event: status\ndata: {json.dumps(status_data)}\n\n"

                # Kirim log history
                logs = entry.get("log", [])
                for log in logs:
                    yield f"event: log\ndata: {json.dumps(log)}\n\n"
                last_index = len(logs)

            last_heartbeat = time.time()
            while True:
                # Kirim log baru
                logs, new_index = get_new_logs(file_id, last_index)
                if logs:
                    for log in logs:
                        yield f"event: log\ndata: {json.dumps(log)}\n\n"
                    last_index = new_index

                # Kirim status update
                current_entry = get_file_entry(file_id)
                if current_entry:
                    status_data = {
                        "status": current_entry["status"],
                        "size_mb": current_entry["size_mb"],
                        "name": current_entry["name"],
                        "cdn_link": current_entry["cdn_link"],
                    }
                    yield f"event: status\ndata: {json.dumps(status_data)}\n\n"

                    if current_entry["status"] in ("ready", "error"):
                        yield f"event: done\ndata: {json.dumps({'status': current_entry['status']})}\n\n"
                        break

                # Heartbeat
                now = time.time()
                if now - last_heartbeat >= SSE_PING_INTERVAL:
                    yield ": heartbeat\n\n"
                    last_heartbeat = now

                time.sleep(SSE_STREAM_INTERVAL)

        except GeneratorExit:
            pass
        finally:
            decrement_sse_client(file_id)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# =============================================================================
# SSE GLOBAL — Streaming Semua Log & Status (Untuk Terminal Tab 1 & UI Update)
# =============================================================================

@sse_bp.route("/api/stream")
def stream_global():
    def event_stream():
        # KRUSIAL: Kirim data awal segera agar koneksi tidak dianggap timeout
        yield ": connected\n\n"
        
        log_positions = {}
        last_sent_status = {}  # Melacak status terakhir yang dikirim per file
        last_heartbeat = time.time()
        
        while True:
            files = get_all_files()
            
            for f in files:
                fid = f["file_id"]
                
                if fid not in log_positions:
                    log_positions[fid] = 0

                # 1. Kirim log baru jika ada
                logs, new_index = get_new_logs(fid, log_positions[fid])
                if logs:
                    for log in logs:
                        log_with_fid = dict(log)
                        log_with_fid["file_id"] = fid
                        yield f"event: log\ndata: {json.dumps(log_with_fid)}\n\n"
                    log_positions[fid] = new_index

                # 2. Kirim status update hanya jika ada perubahan (menghemat bandwidth & mencegah render berlebihan)
                current_status_key = f"{f['status']}|{f['size_mb']}|{f['name']}|{f['cdn_link']}"
                if last_sent_status.get(fid) != current_status_key:
                    status_data = {
                        "file_id": fid,
                        "status": f["status"],
                        "size_mb": f["size_mb"],
                        "name": f["name"],
                        "cdn_link": f["cdn_link"],
                    }
                    yield f"event: status\ndata: {json.dumps(status_data)}\n\n"
                    last_sent_status[fid] = current_status_key

            # Heartbeat
            now = time.time()
            if now - last_heartbeat >= SSE_PING_INTERVAL:
                yield ": heartbeat\n\n"
                last_heartbeat = now

            time.sleep(SSE_STREAM_INTERVAL)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )