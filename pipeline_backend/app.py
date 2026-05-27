# app.py
# Entry point utama aplikasi Flask VideoPipeline Backend.

from flask import Flask

def create_app():
    """Membuat dan mengkonfigurasi instance aplikasi Flask."""
    app = Flask(__name__)

    # Mendaftarkan Blueprint dari routes/api.py
    # Endpoint polling (GET /api/poll) sudah termasuk di dalam api_bp ini
    from routes.api import api_bp
    app.register_blueprint(api_bp)

    # Catatan: Blueprint SSE (routes/sse.py) telah dihapus karena 
    # kita beralih ke metode Short Polling yang lebih stabil di Cloudflared.

    return app


if __name__ == "__main__":
    # Inisialisasi aplikasi
    app = create_app()
    
    print("=" * 50)
    print("  VideoPipeline Backend")
    print("  Running on http://0.0.0.0:5000")
    print("  Menggunakan Short Polling (/api/poll)")
    print("=" * 50)
    
    # Jalankan server Flask
    # - threaded=True: Sangat penting agar Flask bisa menangani banyak 
    #   request polling secara bersamaan tanpa saling tunggu (blocking).
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)