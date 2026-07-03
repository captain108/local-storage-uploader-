from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200))
    # Telegram settings (per user)
    bot_token = db.Column(db.String(200), default='')
    chat_id = db.Column(db.String(200), default='')
    # Storage used (in bytes) – we can compute from files, but we'll store for quick access
    storage_used = db.Column(db.BigInteger, default=0)
    # Google OAuth id (optional)
    google_id = db.Column(db.String(200), unique=True, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_total_storage(self):
        return self.storage_used
