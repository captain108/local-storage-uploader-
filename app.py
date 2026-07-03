import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, login_required, current_user
from werkzeug.utils import secure_filename
from models import db, User
from auth import auth_bp, oauth
from config import Config
import shutil
import requests

app = Flask(__name__)
app.config.from_object(Config)

# Database
db.init_app(app)

# Login manager
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Register auth blueprint
app.register_blueprint(auth_bp)

# OAuth init
oauth.init_app(app)

# Create tables and user folders
with app.app_context():
    db.create_all()
    # Ensure uploads folder exists
    os.makedirs('uploads', exist_ok=True)

# ---------- HELPERS ----------
def get_user_folder(username):
    path = os.path.join('uploads', username)
    os.makedirs(path, exist_ok=True)
    return path

def get_total_storage_used(username):
    folder = get_user_folder(username)
    total = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total += os.path.getsize(fp)
    return total

def send_to_telegram(file_path, bot_token, chat_id):
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    try:
        with open(file_path, 'rb') as f:
            r = requests.post(url, files={'document': f}, data={'chat_id': chat_id}, timeout=60)
            return r.status_code == 200
    except:
        return False

# ---------- ROUTES ----------
@app.route('/')
def index():
    return redirect(url_for('auth.login'))

@app.route('/dashboard')
@login_required
def dashboard():
    used = get_total_storage_used(current_user.username)
    limit = Config.MAX_TOTAL_STORAGE_PER_USER
    percent = min(100, (used / limit) * 100) if limit else 0
    return render_template('dashboard.html', used=used, limit=limit, percent=percent)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        current_user.bot_token = request.form.get('bot_token', '').strip()
        current_user.chat_id = request.form.get('chat_id', '').strip()
        db.session.commit()
        flash('Telegram settings updated!')
        return redirect(url_for('settings'))
    return render_template('settings.html', user=current_user)

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Check storage limit
    used = get_total_storage_used(current_user.username)
    remaining = Config.MAX_TOTAL_STORAGE_PER_USER - used
    if remaining <= 0:
        return jsonify({'error': 'Storage quota exceeded'}), 413

    # Check file size against remaining
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > remaining:
        return jsonify({'error': f'File exceeds remaining storage ({remaining//(1024**2)} MB)'}), 413

    filename = secure_filename(file.filename)
    user_folder = get_user_folder(current_user.username)
    save_path = os.path.join(user_folder, filename)

    # Stream write
    file.save(save_path)

    # Update storage used in DB (optional)
    current_user.storage_used = get_total_storage_used(current_user.username)
    db.session.commit()

    # Telegram forwarding if configured
    tg_success = False
    if current_user.bot_token and current_user.chat_id:
        tg_success = send_to_telegram(save_path, current_user.bot_token, current_user.chat_id)

    return jsonify({
        'message': 'Upload successful',
        'filename': filename,
        'telegram': tg_success
    }), 200

@app.route('/delete/<filename>', methods=['POST'])
@login_required
def delete_file(filename):
    user_folder = get_user_folder(current_user.username)
    path = os.path.join(user_folder, secure_filename(filename))
    if os.path.exists(path):
        os.remove(path)
        current_user.storage_used = get_total_storage_used(current_user.username)
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'error': 'File not found'}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
