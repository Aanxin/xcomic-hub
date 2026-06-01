import json
import uuid as _uuid
from app import db
from datetime import datetime


class Device(db.Model):
    __tablename__ = 'devices'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(128), unique=True, nullable=False, index=True)
    device_name = db.Column(db.String(256), default='')
    device_type = db.Column(db.String(64), default='')
    ip_address = db.Column(db.String(64), default='')
    user_agent = db.Column(db.String(512), default='')
    status = db.Column(db.String(20), default='approved')
    last_ip = db.Column(db.String(64), default='')
    last_ua = db.Column(db.String(512), default='')
    connect_count = db.Column(db.Integer, default=0)
    last_active_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'device_name': self.device_name,
            'device_type': self.device_type,
            'ip_address': self.ip_address,
            'status': self.status,
            'last_ip': self.last_ip,
            'connect_count': self.connect_count,
            'last_active_at': self.last_active_at.isoformat() if self.last_active_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Comic(db.Model):
    __tablename__ = 'comics'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(256), nullable=False, default='未命名')
    title_jp = db.Column(db.String(512), default='')
    author = db.Column(db.String(128), default='')
    genre = db.Column(db.String(256), default='')
    category = db.Column(db.String(64), default='')
    date = db.Column(db.String(32), default='')
    plot = db.Column(db.Text, default='')
    rating = db.Column(db.Float, default=0.0)
    rating_count = db.Column(db.Integer, default=0)
    tags = db.Column(db.String(256), default='')
    status = db.Column(db.String(32), default='')
    publisher = db.Column(db.String(128), default='')
    language = db.Column(db.String(64), default='')
    is_translated = db.Column(db.Boolean, default=False)
    uploader = db.Column(db.String(128), default='')
    page_count = db.Column(db.Integer, default=0)
    favorited = db.Column(db.Integer, default=0)
    source_url = db.Column(db.String(512), default='')
    torrent_urls = db.Column(db.Text, default='')
    cover = db.Column(db.String(512), default='')
    filename = db.Column(db.String(512), default='')
    nfo_file = db.Column(db.String(512), default='')
    file_size = db.Column(db.BigInteger, default=0)
    collection_id = db.Column(db.Integer, db.ForeignKey('collections.id'), nullable=True)
    volume = db.Column(db.String(64), default='')
    is_favorite = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    reading_history = db.relationship('ReadingHistory', backref='comic', uselist=False, cascade='all, delete-orphan')

    def to_dict(self):
        from app.utils.tag_utils import map_tag
        raw_tags = self.tags or ''
        mapped_list = []
        if raw_tags:
            for t in raw_tags.split(','):
                t = t.strip()
                if t:
                    mapped_list.append(map_tag(t))
        return {
            'id': self.id,
            'title': self.title,
            'title_jp': self.title_jp,
            'author': self.author,
            'genre': self.genre,
            'category': self.category,
            'date': self.date,
            'plot': self.plot,
            'rating': self.rating,
            'rating_count': self.rating_count,
            'tags': ','.join(mapped_list),
            'raw_tags': raw_tags,
            'status': self.status,
            'publisher': self.publisher,
            'language': self.language,
            'is_translated': self.is_translated,
            'uploader': self.uploader,
            'page_count': self.page_count,
            'favorited': self.favorited,
            'source_url': self.source_url,
            'torrent_urls': self.torrent_urls,
            'cover': self.cover,
            'filename': self.filename,
            'nfo_file': self.nfo_file,
            'file_size': self.file_size,
            'collection_id': self.collection_id,
            'volume': self.volume,
            'is_favorite': self.is_favorite,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class Collection(db.Model):
    __tablename__ = 'collections'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), nullable=False, unique=True)
    cover = db.Column(db.String(512), default='')
    description = db.Column(db.Text, default='')
    nfo_file = db.Column(db.String(512), default='')
    is_favorite = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    comics = db.relationship('Comic', backref='collection', lazy='dynamic',
                             order_by='Comic.volume.asc(), Comic.id.asc()')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'cover': self.cover,
            'description': self.description,
            'nfo_file': self.nfo_file,
            'is_favorite': self.is_favorite,
            'comic_count': self.comics.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Setting(db.Model):
    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    value = db.Column(db.String(512), default='')

    @staticmethod
    def get(key, default=''):
        s = Setting.query.filter_by(key=key).first()
        return s.value if s else default

    @staticmethod
    def set(key, value):
        s = Setting.query.filter_by(key=key).first()
        if s:
            s.value = str(value)
        else:
            s = Setting(key=key, value=str(value))
            db.session.add(s)
        db.session.commit()


class ReadingHistory(db.Model):
    __tablename__ = 'reading_history'

    id = db.Column(db.Integer, primary_key=True)
    comic_id = db.Column(db.Integer, db.ForeignKey('comics.id'), unique=True, nullable=False)
    last_page = db.Column(db.Integer, default=1)
    total_pages = db.Column(db.Integer, default=0)
    read_count = db.Column(db.Integer, default=0)
    last_read_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'comic_id': self.comic_id,
            'last_page': self.last_page,
            'total_pages': self.total_pages,
            'read_count': self.read_count,
            'last_read_at': self.last_read_at.isoformat() if self.last_read_at else None,
        }

    @property
    def progress_percent(self):
        if self.total_pages <= 0:
            return 0
        return min(100, round((self.last_page / self.total_pages) * 100))

    @property
    def is_finished(self):
        return self.total_pages > 0 and self.last_page >= self.total_pages


class UploadTask(db.Model):
    __tablename__ = 'upload_tasks'

    id = db.Column(db.String(36), primary_key=True)
    status = db.Column(db.String(20), default='pending')
    total = db.Column(db.Integer, default=0)
    processed = db.Column(db.Integer, default=0)
    succeeded = db.Column(db.Integer, default=0)
    failed = db.Column(db.Integer, default=0)
    current_file = db.Column(db.String(512), default='')
    errors = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'status': self.status,
            'total': self.total,
            'processed': self.processed,
            'succeeded': self.succeeded,
            'failed': self.failed,
            'current_file': self.current_file,
            'errors': self.errors,
            'progress': round((self.processed / self.total) * 100) if self.total > 0 else 0,
        }


class ChunkedUpload(db.Model):
    __tablename__ = 'chunked_uploads'

    id = db.Column(db.String(36), primary_key=True)
    original_filename = db.Column(db.String(512), nullable=False)
    file_size = db.Column(db.BigInteger, default=0)
    chunk_size = db.Column(db.Integer, default=5242880)
    total_chunks = db.Column(db.Integer, default=0)
    uploaded_chunks_json = db.Column(db.Text, default='[]')
    status = db.Column(db.String(20), default='pending')
    comic_id = db.Column(db.Integer, nullable=True)
    error = db.Column(db.Text, default='')
    nfo_filename = db.Column(db.String(512), default='')
    cover_filename = db.Column(db.String(512), default='')
    manual_title = db.Column(db.String(256), default='')
    manual_author = db.Column(db.String(128), default='')
    collection_name = db.Column(db.String(256), default='')
    volume = db.Column(db.String(64), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def uploaded_chunks(self):
        if self.uploaded_chunks_json:
            return json.loads(self.uploaded_chunks_json)
        return []

    @uploaded_chunks.setter
    def uploaded_chunks(self, val):
        self.uploaded_chunks_json = json.dumps(sorted(val))

    def to_dict(self):
        uploaded = self.uploaded_chunks
        return {
            'id': self.id,
            'original_filename': self.original_filename,
            'file_size': self.file_size,
            'chunk_size': self.chunk_size,
            'total_chunks': self.total_chunks,
            'uploaded_chunks': uploaded,
            'uploaded_count': len(uploaded),
            'status': self.status,
            'comic_id': self.comic_id,
            'error': self.error,
            'progress': round((len(uploaded) / self.total_chunks) * 100) if self.total_chunks > 0 else 0,
        }


class DownloadTask(db.Model):
    __tablename__ = 'download_tasks'

    id = db.Column(db.String(36), primary_key=True)
    url = db.Column(db.String(1024), default='')
    title = db.Column(db.String(512), default='')
    status = db.Column(db.String(20), default='pending')
    message = db.Column(db.String(512), default='')
    torrent_urls = db.Column(db.Text, default='')
    torrent_file = db.Column(db.String(512), default='')
    nfo_path = db.Column(db.String(512), default='')
    nfo_data = db.Column(db.Text, default='')
    qb_progress = db.Column(db.Float, default=0.0)
    qb_state = db.Column(db.String(32), default='')
    qb_info_hash = db.Column(db.String(64), default='')
    comic_id = db.Column(db.Integer, nullable=True)
    queue = db.Column(db.String(20), default='waiting')
    queue_position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'url': self.url,
            'title': self.title,
            'status': self.status,
            'message': self.message,
            'torrent_urls': self.torrent_urls.split(',') if self.torrent_urls else [],
            'torrent_file': self.torrent_file,
            'nfo_path': self.nfo_path,
            'qb_progress': self.qb_progress,
            'qb_state': self.qb_state,
            'comic_id': self.comic_id,
            'queue': self.queue,
            'time': self.created_at.strftime('%H:%M:%S') if self.created_at else '',
        }
