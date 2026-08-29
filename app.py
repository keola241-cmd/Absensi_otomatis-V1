from datetime import datetime, timedelta, timezone
import os
import threading
import time
from flask import Flask, jsonify, render_template, request
import requests

app = Flask(__name__)

# --- PEMERIKSA STATUS VERCEL / LOKAL ---
@app.before_request
def check_status():
    if os.environ.get('WEB_ACTIVE', 'TRUE').upper() != 'TRUE':
        return (
            """
            <div style="text-align:center; padding:50px; font-family:sans-serif;">
                <h1 style="color:red;">Akses Ditangguhkan ⚠️</h1>
                <p>Masa aktif aplikasi telah berakhir / menunggu konfirmasi pembayaran.</p>
                <p>Silakan hubungi Admin/Developer untuk mengaktifkan kembali.</p>
            </div>
            """,
            403,
        )

# Ganti dengan URL deployment Web App Apps Script kamu yang terbaru
GOOGLE_SHEET_URL = 'https://script.google.com/macros/s/AKfycbxkImh_DpnBxKKn_TWRoSKArVnx9ZDorhO2WXrh7GA8ghsdfGXqLz94rKlPuojrz1dznw/exec'

# Storage RAM: Key -> timestamp_terakhir_scan
sudah_absen = {}
lock = threading.Lock()

WIB = timezone(timedelta(hours=7))

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_riwayat', methods=['GET'])
def get_riwayat():
    try:
        response = requests.get(GOOGLE_SHEET_URL, timeout=10)
        return jsonify(response.json())
    except Exception:
        return jsonify([])

@app.route('/proses_absen', methods=['POST'])
@app.route('/proses_absen', methods=['POST'])
def proses_absen():
    sekarang = datetime.now(WIB)
    tanggal = sekarang.strftime('%Y-%m-%d')
    waktu = sekarang.strftime('%H:%M')

    BATAS_JAM_MASUK = "10:00"
    
    if waktu > BATAS_JAM_MASUK:
        status_kehadiran = "telat"
    else:
        status_kehadiran = "tepat"

    data = request.json.get('qr_data', '')
    data_split = data.split('|')

    if len(data_split) == 4:
        id_user, nama, kelas, role = data_split
        kunci_absen_hari_ini = f'{tanggal}|{id_user}'
        waktu_sekarang = time.time()

        with lock:
            if kunci_absen_hari_ini in sudah_absen:
                waktu_scan_terakhir = sudah_absen[kunci_absen_hari_ini]
                selisih_detik = waktu_sekarang - waktu_scan_terakhir

                if selisih_detik < 15:
                    return jsonify({
                        'status': 'warning',
                        'message': f'⚠️ {nama} sudah absen!',
                    })

            sudah_absen[kunci_absen_hari_ini] = waktu_sekarang

        payload = {
            'id': id_user,
            'nama': nama,
            'kelas': kelas,
            'role': role,
            'tanggal': tanggal,
            'waktu': waktu,
            'status_kehadiran': status_kehadiran
        }

        try:
            # Kirim data dan baca respon dari Google Sheets
            res = requests.post(
                GOOGLE_SHEET_URL, json=payload, allow_redirects=True, timeout=12
            )
            res_data = res.json()

            # Jika Google Sheets mengembalikan status error
            if res_data.get('status') == 'error':
                with lock:
                    if kunci_absen_hari_ini in sudah_absen:
                        del sudah_absen[kunci_absen_hari_ini]
                return jsonify({
                    'status': 'error',
                    'message': f"⚠️ Sheet Error: {res_data.get('message')}"
                })

            pesan_tampil = f'⚠️ {nama} Terlambat!' if status_kehadiran == "telat" else f'✅ {nama} Tepat Waktu!'

            return jsonify({
                'status': 'success',
                'message': pesan_tampil,
                'siswa': payload,
            })
        except Exception as e:
            with lock:
                if kunci_absen_hari_ini in sudah_absen:
                    del sudah_absen[kunci_absen_hari_ini]
            return jsonify({
                'status': 'error',
                'message': '⚠️ Koneksi lambat, silakan coba scan lagi.',
            })
    else:
        return jsonify({'status': 'error', 'message': '⚠️ Format QR Code salah!'})
        
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
