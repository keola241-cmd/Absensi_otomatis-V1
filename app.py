import os
from flask import Flask, render_template, request, jsonify
import requests
from datetime import datetime

app = Flask(__name__)


# --- TAMBAHKAN KODE INI ---
IS_ACTIVE = os.environ.get('WEB_ACTIVE', 'TRUE')


@app.before_request
def check_status():
  # Membaca variabel secara langsung setiap ada request masuk
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

# --------------------------


# 🔗 TEMPEL LINK GOOGLE APPS SCRIPT KAMU DI SINI
GOOGLE_SHEET_URL = "https://script.google.com/macros/s/AKfycby5dRkXn31kDWhe_hNcNAjUgyZ8PpiOPo3Gm5OXNwSdSkI_h9EIuOn3RQiNR11H3BbJ/exec"


sudah_absen = set()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_riwayat', methods=['GET'])
def get_riwayat():
    try:
        response = requests.get(GOOGLE_SHEET_URL)
        return jsonify(response.json())
    except Exception as e:
        return jsonify([])

@app.route('/proses_absen', methods=['POST'])
def proses_absen():
    sekarang = datetime.now()
    batas_waktu = sekarang.replace(hour=23, minute=59 , second=59, microsecond=0)
    
    if sekarang > batas_waktu:
        return jsonify({
            "status": "ditutup", 
            "message": f"❌ Absen ditutup! Sekarang jam {sekarang.strftime('%H:%M')}."
        })

    data = request.json.get('qr_data', '')
    data_split = data.split('|')

    if len(data_split) == 4:
        id_user, nama, kelas, role = data_split
        
        if data in sudah_absen:
            return jsonify({"status": "warning", "message": f"⚠️ {nama} sudah absen sebelumnya!"})

        sudah_absen.add(data)
        
        tanggal = sekarang.strftime('%Y-%m-%d')
        waktu = sekarang.strftime('%H:%M:%S')

        payload = {
            "id": id_user,
            "nama": nama,
            "kelas": kelas,
            "role": role,
            "tanggal": tanggal,
            "waktu": waktu
        }

        try:
            requests.post(GOOGLE_SHEET_URL, json=payload)
            return jsonify({
                "status": "success", 
                "message": f"✅ {nama} Berhasil Absen!",
                "siswa": payload
            })
        except Exception as e:
            return jsonify({"status": "error", "message": f"⚠️ Gagal menyimpan ke Sheet: {str(e)}"})
    else:
        return jsonify({"status": "error", "message": "⚠️ Format QR Code salah!"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
