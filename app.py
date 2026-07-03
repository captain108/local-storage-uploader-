import os
import shutil
import gc
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from authlib.integrations.flask_client import OAuth
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'auth.login'

oauth = OAuth(app)
oauth.register(
    name='google',
    client_id=Config.GOOGLE_CLIENT_ID,
    client_secret=Config.GOOGLE_CLIENT_SECRET,
    server_metadata_url=Config.GOOGLE_DISCOVERY_URL,
    client_kwargs={'scope': 'openid email profile'}
)

# ---------- User Model ----------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200))
    bot_token = db.Column(db.String(200), default='')
    chat_id = db.Column(db.String(200), default='')
    storage_used = db.Column(db.BigInteger, default=0)
    google_id = db.Column(db.String(200), unique=True, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------- Helpers ----------
def get_user_folder(username):
    path = os.path.join('uploads', username)
    os.makedirs(path, exist_ok=True)
    return path

def get_total_storage_used(username):
    folder = get_user_folder(username)
    total = 0
    for dirpath, _, filenames in os.walk(folder):
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

# ---------- Routes ----------
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Username already taken')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('register'))
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        os.makedirs(f'uploads/{username}', exist_ok=True)
        flash('Registration successful! Please log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/google-login')
def google_login():
    redirect_uri = url_for('google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route('/google-callback')
def google_callback():
    token = oauth.google.authorize_access_token()
    user_info = oauth.google.parse_id_token(token)
    email = user_info['email']
    name = user_info.get('name', email.split('@')[0])
    google_id = user_info['sub']

    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()
        if user:
            user.google_id = google_id
        else:
            username = name.replace(' ', '_').lower() + str(User.query.count())
            while User.query.filter_by(username=username).first():
                username += str(User.query.count())
            user = User(username=username, email=email, google_id=google_id)
            db.session.add(user)
            db.session.commit()
            os.makedirs(f'uploads/{username}', exist_ok=True)
    login_user(user)
    return redirect(url_for('dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    used = get_total_storage_used(current_user.username)
    limit = Config.MAX_TOTAL_STORAGE_PER_USER
    percent = min(100, (used / limit) * 100) if limit else 0
    # List files in user folder
    folder = get_user_folder(current_user.username)
    files = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    return render_template('dashboard.html', used=used, limit=limit, percent=percent, files=files)

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

    # Check storage quota
    used = get_total_storage_used(current_user.username)
    remaining = Config.MAX_TOTAL_STORAGE_PER_USER - used
    if remaining <= 0:
        return jsonify({'error': 'Storage quota exceeded'}), 413

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > remaining:
        return jsonify({'error': f'File exceeds remaining storage ({remaining//(1024**2)} MB)'}), 413

    filename = secure_filename(file.filename)
    user_folder = get_user_folder(current_user.username)
    save_path = os.path.join(user_folder, filename)

    # STREAM WRITE – chunk by chunk to avoid memory issues
    with open(save_path, 'wb') as out_file:
        chunk_size = 8192  # 8 KB
        while True:
            chunk = file.stream.read(chunk_size)
            if not chunk:
                break
            out_file.write(chunk)

    # Update storage used
    current_user.storage_used = get_total_storage_used(current_user.username)
    db.session.commit()

    # Telegram forwarding (if configured)
    tg_success = False
    if current_user.bot_token and current_user.chat_id:
        tg_success = send_to_telegram(save_path, current_user.bot_token, current_user.chat_id)

    # Optional garbage collection
    gc.collect()

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
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=False)
