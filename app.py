from datetime import datetime, timedelta, timezone
import os
import time
from flask import Flask, jsonify, render_template, request
import requests

app = Flask(__name__)

# --- ANTI-SPAM MEMORY ---
# Menyimpan waktu terakhir sebuah ID melakukan scan untuk mencegah spam request beruntun
recent_scans = {}

# --- PEMERIKSA STATUS SAKELAR VERCEL ---
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
# ---------------------------------------

GOOGLE_SHEET_URL = 'https://script.google.com/macros/s/AKfycbyn88ANfRmR2M5knaX88Fkd_ALbp8jE1w6giz1Vsme8tuiQ8Zm-DtYgVBqU0wWRhKsc/exec'
WIB = timezone(timedelta(hours=7))

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_riwayat', methods=['GET'])
def get_riwayat():
    try:
        response = requests.get(GOOGLE_SHEET_URL, timeout=5)
        return jsonify(response.json())
    except Exception:
        return jsonify([])

@app.route('/proses_absen', methods=['POST'])
def proses_absen():
    sekarang = datetime.now(WIB)
    tanggal = sekarang.strftime('%Y-%m-%d')
    waktu = sekarang.strftime('%H:%M')

    batas_waktu = sekarang.replace(
        hour=23, minute=59, second=59, microsecond=0
    )

    if sekarang > batas_waktu:
        return jsonify({
            'status': 'ditutup',
            'message': f"❌ Absen ditutup! Sekarang jam {waktu}.",
        })

    data = request.json.get('qr_data', '')
    data_split = data.split('|')

    if len(data_split) == 4:
        id_user, nama, kelas, role = data_split

        # --- 1. CEK ANTI-SPAM INTERNAL (COOLDOWN 10 DETIK) ---
        waktu_sekarang_detik = time.time()
        if id_user in recent_scans:
            selisih_waktu = waktu_sekarang_detik - recent_scans[id_user]
            if selisih_waktu < 10:  # Jika kurang dari 10 detik, abaikan request ini
                return jsonify({
                    'status': 'warning',
                    'message': f'⏳ Tunggu sebentar, data {nama} sedang diproses!'
                })
        
        # Catat waktu scan untuk ID ini agar request berikutnya ditahan sementara
        recent_scans[id_user] = waktu_sekarang_detik

        # --- 2. CEK DATA REAL-TIME KE GOOGLE SHEET ---
        try:
            res_sheet = requests.get(GOOGLE_SHEET_URL, timeout=4)
            riwayat = res_sheet.json() if res_sheet.status_code == 200 else []
        except Exception:
            riwayat = []

        # Cek apakah ID sudah ada di sheet untuk TANGGAL HARI INI
        sudah_absen = any(
            str(item.get('id')) == str(id_user)
            and str(item.get('tanggal')) == tanggal
            for item in riwayat
            if isinstance(item, dict)
        )

        if sudah_absen:
            return jsonify({
                'status': 'warning',
                'message': f'⚠️ {nama} sudah absen hari ini!',
            })

        # --- 3. KIRIM PAYLOAD KE GOOGLE SHEET ---
        payload = {
            'id': id_user,
            'nama': nama,
            'kelas': kelas,
            'role': role,
            'tanggal': tanggal,
            'waktu': waktu,
        }

        try:
            res = requests.post(GOOGLE_SHEET_URL, json=payload, allow_redirects=True)
            res_json = res.json() if res.status_code == 200 else {}

            # Jika Apps Script mendeteksi data ganda
            if res_json.get('result') == 'already_exists':
                return jsonify({
                    'status': 'warning',
                    'message': f'⚠️ {nama} sudah absen hari ini!',
                })

            return jsonify({
                'status': 'success',
                'message': f'✅ {nama} Berhasil Absen!',
                'siswa': payload,
            })
        except Exception as e:
            # Jika gagal (misal timeout), hapus dari memori agar bisa di-scan ulang
            if id_user in recent_scans:
                del recent_scans[id_user]
                
            return jsonify(
                {'status': 'error', 'message': f'⚠️ Gagal menyimpan ke Sheet: {str(e)}'}
            )
    else:
        return jsonify({'status': 'error', 'message': '⚠️ Format QR Code salah!'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
