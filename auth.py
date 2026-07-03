from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User
from werkzeug.security import generate_password_hash
from authlib.integrations.flask_client import OAuth
from config import Config
import os

auth_bp = Blueprint('auth', __name__)

# Initialize OAuth
oauth = OAuth()
oauth.register(
    name='google',
    client_id=Config.GOOGLE_CLIENT_ID,
    client_secret=Config.GOOGLE_CLIENT_SECRET,
    server_metadata_url=Config.GOOGLE_DISCOVERY_URL,
    client_kwargs={'scope': 'openid email profile'}
)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password')
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        # Check if username or email already exists
        if User.query.filter_by(username=username).first():
            flash('Username already taken')
            return redirect(url_for('auth.register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('auth.register'))
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        # Create user folder
        os.makedirs(f'uploads/{username}', exist_ok=True)
        flash('Registration successful! Please log in.')
        return redirect(url_for('auth.login'))
    return render_template('register.html')

@auth_bp.route('/google-login')
def google_login():
    redirect_uri = url_for('auth.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@auth_bp.route('/google-callback')
def google_callback():
    token = oauth.google.authorize_access_token()
    user_info = oauth.google.parse_id_token(token)
    email = user_info['email']
    name = user_info.get('name', email.split('@')[0])
    google_id = user_info['sub']

    # Check if user exists
    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()
        if user:
            # Update google_id for existing user
            user.google_id = google_id
        else:
            # Create new user
            username = name.replace(' ', '_').lower() + str(User.query.count())
            # Ensure unique username
            while User.query.filter_by(username=username).first():
                username += str(User.query.count())
            user = User(username=username, email=email, google_id=google_id)
            db.session.add(user)
            db.session.commit()
            os.makedirs(f'uploads/{username}', exist_ok=True)
    login_user(user)
    return redirect(url_for('dashboard'))

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
