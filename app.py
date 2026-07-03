import os
import time
import requests
from flask import Flask, request, render_template, jsonify
from werkzeug.utils import secure_filename

# ---------- CONFIG ----------
UPLOAD_FOLDER = os.path.expanduser("~/uploads")
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'mp4', 'zip', 'apk', 'mp3'}
MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200 MB total limit

# 🔹 TELEGRAM SETTINGS (set to None/empty to disable)
BOT_TOKEN = "YOUR_BOT_TOKEN"   # ← replace with your token
CHAT_ID = "YOUR_CHAT_ID"       # ← replace with your chat ID

# -----------------------------
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def send_to_telegram(file_path):
    """Forward a file to Telegram (returns True if success)"""
    if not BOT_TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(file_path, 'rb') as f:
        files = {'document': f}
        data = {'chat_id': CHAT_ID}
        try:
            r = requests.post(url, files=files, data=data, timeout=15)
            return r.status_code == 200
        except Exception as e:
            print(f"Telegram error: {e}")
            return False

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    # 1. Get all uploaded files
    uploaded_files = request.files.getlist('file')
    if not uploaded_files or uploaded_files[0].filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # 2. Read multi-options from the form
    opt_telegram = request.form.get('opt-telegram') == 'on'
    opt_save = request.form.get('opt-save') == 'on'
    opt_notify = request.form.get('opt-notify') == 'on'  # placeholder for future use

    saved_paths = []
    tg_success = []

    for file in uploaded_files:
        if file.filename == '':
            continue
        if not allowed_file(file.filename):
            return jsonify({'error': f'File type not allowed: {file.filename}'}), 400

        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # 3. Save locally (if checkbox is ON)
        if opt_save:
            file.save(save_path)
            saved_paths.append(save_path)
        else:
            # If not saving, we need to store temporarily to send via Telegram
            # Let's save anyway, but delete later if not needed
            file.save(save_path)
            saved_paths.append(save_path)  # we'll clean up if needed

        # 4. Send to Telegram (if checkbox is ON)
        if opt_telegram and BOT_TOKEN and CHAT_ID:
            if send_to_telegram(save_path):
                tg_success.append(filename)

        # 5. Clean up if local save was OFF (we only saved it for Telegram)
        if not opt_save:
            try:
                os.remove(save_path)
            except:
                pass

    # Return summary
    return jsonify({
        'message': 'Upload processed',
        'saved': saved_paths if opt_save else [],
        'sent_to_telegram': tg_success,
        'notify': opt_notify
    }), 200

if __name__ == '__main__':
    # Run on all interfaces so other devices can connect
    app.run(host='0.0.0.0', port=5000, debug=False)
