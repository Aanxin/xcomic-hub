import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

SECRET_KEY = os.environ.get('SECRET_KEY', 'manhua-dev-secret-key-change-in-production')

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(BASE_DIR, 'data'))
COMICS_DIR = os.environ.get('COMICS_DIR', os.path.join(DATA_DIR, 'comics'))
NFO_DIR = os.environ.get('NFO_DIR', os.path.join(DATA_DIR, 'nfo'))
COVERS_DIR = os.path.join(DATA_DIR, 'covers')
PAGES_DIR = os.path.join(DATA_DIR, 'pages')
DOWNLOAD_DIR = os.environ.get('DOWNLOAD_DIR', os.path.join(DATA_DIR, 'download'))
DB_PATH = os.environ.get('DB_PATH', os.path.join(DATA_DIR, 'manhua.db'))

SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', f'sqlite:///{DB_PATH}')
SQLALCHEMY_TRACK_MODIFICATIONS = False

MAX_CONTENT_LENGTH = 20 * 1024 * 1024 * 1024

ALLOWED_EXTENSIONS = {'cbz', 'cbr', 'zip', 'rar', '7z', 'pdf', 'jpg', 'jpeg', 'png', 'webp', 'gif'}

IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'}

ARCHIVE_EXTENSIONS = {'cbz', 'cbr', 'zip', 'rar', '7z'}
