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

GOOGLE_SHEET_URL = 'https://script.google.com/macros/s/AKfycbxkImh_DpnBxKKn_TWRoSKArVnx9ZDorhO2WXrh7GA8ghsdfGXqLz94rKlPuojrz1dznw/exec'

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
def proses_absen():
    sekarang = datetime.now(WIB)
    tanggal = sekarang.strftime('%Y-%m-%d')
    waktu = sekarang.strftime('%H:%M')       # Format HH:MM (e.g. "06:50" atau "17:30")
    waktu_titik = waktu.replace(':', '.')    # Format HH.MM (e.g. "06.50" atau "17.30")

    data = request.json.get('qr_data', '')
    data_split = data.split('|')

    if len(data_split) == 4:
        id_user, nama, kelas, role = [item.strip() for item in data_split]
        kunci_cooldown = f'{tanggal}|{id_user}'
        waktu_sekarang = time.time()

        # --- 1. JEDA COOLDOWN (Mencegah Kamera Scan 2x Secara Tidak Sengaja) ---
        # Jeda 60 detik agar pegawai/siswa tidak terscan berulang kali saat berdiri di depan kamera
        COOLDOWN_DETIK = 60 

        with lock:
            if kunci_cooldown in sudah_absen:
                waktu_scan_terakhir = sudah_absen[kunci_cooldown]
                selisih_detik = waktu_sekarang - waktu_scan_terakhir

                if selisih_detik < COOLDOWN_DETIK:
                    sisa_detik = int(COOLDOWN_DETIK - selisih_detik)
                    return jsonify({
                        'status': 'warning',
                        'message': f'⚠️ {nama} baru saja melakukan scan! Tunggu {sisa_detik} detik lagi.',
                    })

            sudah_absen[kunci_cooldown] = waktu_sekarang

        # --- 2. PENENTUAN FORMAT DATA BERDASARKAN ROLE ---
        role_clean = role.lower()
        daftar_pegawai = ['guru', 'karyawan', 'anak magang', 'magang', 'pekerja kantoran']

        if role_clean in daftar_pegawai:
            # Pegawai: Kirim jam murni "06.50" / "17.30", Apps Script akan tentukan ini Masuk/Pulang/Lembur
            status_kehadiran = "pegawai"
            teks_waktu = waktu_titik
        else:
            # Siswa / Pelajar (Kondisi default)
            BATAS_SISWA = "10:00"
            if waktu <= BATAS_SISWA:
                status_kehadiran = "tepat"
            else:
                status_kehadiran = "telat"
            teks_waktu = waktu

        payload = {
            'id': id_user,
            'nama': nama,
            'kelas': kelas,        # Target Tab di Google Sheets (Guru / Karyawan / Magang / Kelas 10A)
            'role': role,
            'tanggal': tanggal,
            'waktu': teks_waktu,
            'status_kehadiran': status_kehadiran
        }

        # --- 3. KIRIM DATA KE GOOGLE APPS SCRIPT ---
        try:
            res = requests.post(
                GOOGLE_SHEET_URL, json=payload, allow_redirects=True, timeout=12
            )
            res_data = res.json()

            # Jika Apps Script mengembalikan status Error
            if res_data.get('status') == 'error':
                with lock:
                    if kunci_cooldown in sudah_absen:
                        del sudah_absen[kunci_cooldown]
                return jsonify({
                    'status': 'error',
                    'message': f"⚠️ Sheet Error: {res_data.get('message')}"
                })

            # Ambil notifikasi langsung dari Google Apps Script (Misal: "ABSEN MASUK", "ABSEN PULANG", "LEMBUR")
            pesan_dari_script = res_data.get('message')
            
            if not pesan_dari_script:
                if status_kehadiran == "telat":
                    pesan_dari_script = f'⚠️ [{role}] {nama} Terlambat ({teks_waktu})!'
                else:
                    pesan_dari_script = f'✅ [{role}] {nama} Presensi Berhasil ({teks_waktu})!'

            return jsonify({
                'status': res_data.get('status', 'success'),
                'message': pesan_dari_script,
                'siswa': payload,
            })

        except Exception:
            # Jika koneksi gagal, hapus cooldown agar bisa scan ulang
            with lock:
                if kunci_cooldown in sudah_absen:
                    del sudah_absen[kunci_cooldown]
            return jsonify({
                'status': 'error',
                'message': '⚠️ Koneksi lambat/terputus, silakan coba scan lagi.',
            })
    else:
        return jsonify({'status': 'error', 'message': '⚠️ Format QR Code salah!'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
