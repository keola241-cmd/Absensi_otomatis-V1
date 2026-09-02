from datetime import datetime, timedelta, timezone
import os
import threading
import time
from flask import Flask, jsonify, render_template, request
import requests

app = Flask(__name__)

# ==============================================================================
# 🔗 TEMPAT MENYAMBUNGKAN GOOGLE SHEETS APPS SCRIPT
# Ganti URL di bawah ini dengan URL Web App Deployment Apps Script kamu!
# ==============================================================================
GOOGLE_SHEET_URL = 'https://script.google.com/macros/s/AKfycbz656v_emKK4DMdp20z8Z7L7pHzIfa3qcs3-b-46v00cOe54BnpA9mS3DGMFCwuafE7_A/exec'
# ==============================================================================


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

sudah_absen = {}
lock = threading.Lock()

WIB = timezone(timedelta(hours=7))

@app.route('/')
def home():
    return render_template('index.html')

# --- ROUTE 1: GET RIWAYAT ABSEN HARI INI ---
@app.route('/get_riwayat', methods=['GET'])
def get_riwayat():
    try:
        response = requests.get(GOOGLE_SHEET_URL, timeout=10)
        return jsonify(response.json())
    except Exception:
        return jsonify([])

# --- ROUTE 2: AMBIL DAFTAR TAB DARI GOOGLE SHEETS ---
@app.route('/get_tabs', methods=['GET'])
def get_tabs():
    try:
        payload = {'action': 'get_tabs'}
        res = requests.post(GOOGLE_SHEET_URL, json=payload, timeout=10)
        return jsonify(res.json())
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Gagal mengambil daftar tab: {str(e)}', 'tabs': []})

# --- ROUTE 3: AMBIL DATA REKAP KHUSUS UNTUK TAB/KELAS CERTAIN ---
@app.route('/get_rekap', methods=['POST', 'GET'])
def get_rekap():
    try:
        if request.method == 'POST':
            nama_tab = request.json.get('nama_tab', '').strip()
        else:
            nama_tab = request.args.get('nama_tab', '').strip()

        if not nama_tab:
            return jsonify({'status': 'error', 'message': 'Nama Tab/Kelas wajib diisi!'})

        payload = {
            'action': 'get_rekap',
            'nama_tab': nama_tab
        }
        res = requests.post(GOOGLE_SHEET_URL, json=payload, timeout=12)
        return jsonify(res.json())
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Gagal memuat rekap: {str(e)}', 'data': []})

# --- ROUTE 4: BUAT TAB KELAS BARU DARI WEB ---
@app.route('/buat_tab', methods=['POST'])
def buat_tab():
    try:
        nama_tab = request.json.get('nama_tab', '').strip()
        if not nama_tab:
            return jsonify({'status': 'error', 'message': 'Nama Tab/Kelas tidak boleh kosong!'})
        
        payload = {
            'action': 'create_tab',
            'kelas': nama_tab
        }
        res = requests.post(GOOGLE_SHEET_URL, json=payload, timeout=12)
        return jsonify(res.json())
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Gagal membuat tab: {str(e)}'})

# --- ROUTE 5: PROSES ABSEN DARI QR SCANNER ---
@app.route('/proses_absen', methods=['POST'])
def proses_absen():
    sekarang = datetime.now(WIB)
    tanggal = sekarang.strftime('%Y-%m-%d')
    waktu = sekarang.strftime('%H:%M')
    waktu_titik = waktu.replace(':', '.')

    data = request.json.get('qr_data', '')
    data_split = data.split('|')

    if len(data_split) == 4:
        id_user, nama, kelas, role = [item.strip() for item in data_split]
        kunci_cooldown = f'{tanggal}|{id_user}'
        waktu_sekarang = time.time()

        # JEDA COOLDOWN (60 Detik)
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

        # PENENTUAN STATUS PEGAWAI VS SISWA
        role_clean = role.lower()
        daftar_pegawai = ['guru', 'karyawan', 'anak magang', 'magang', 'pekerja kantoran']

        if role_clean in daftar_pegawai:
            status_kehadiran = "pegawai"
            teks_waktu = waktu_titik
        else:
            BATAS_SISWA = "07:00"
            if waktu <= BATAS_SISWA:
                status_kehadiran = "tepat"
            else:
                status_kehadiran = "telat"
            teks_waktu = waktu

        payload = {
            'id': id_user,
            'nama': nama,
            'kelas': kelas,
            'role': role,
            'tanggal': tanggal,
            'waktu': teks_waktu,
            'status_kehadiran': status_kehadiran
        }

        try:
            res = requests.post(
                GOOGLE_SHEET_URL, json=payload, allow_redirects=True, timeout=12
            )
            res_data = res.json()

            if res_data.get('status') == 'error':
                with lock:
                    if kunci_cooldown in sudah_absen:
                        del sudah_absen[kunci_cooldown]
                return jsonify({
                    'status': 'error',
                    'message': f"⚠️ Sheet Error: {res_data.get('message')}"
                })

            pesan_dari_script = res_data.get('message')
            
            if not pesan_dari_script:
                if status_kehadiran == "telat":
                    pesan_dari_script = f'⚠️ {nama} Terlambat ({teks_waktu})!'
                else:
                    pesan_dari_script = f'✅ {nama} Presensi Berhasil ({teks_waktu})!'

            return jsonify({
                'status': res_data.get('status', 'success'),
                'message': pesan_dari_script,
                'siswa': payload,
            })

        except Exception:
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
