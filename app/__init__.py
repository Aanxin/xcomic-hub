from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine
import os
from config import COMICS_DIR, COVERS_DIR, DATA_DIR, NFO_DIR, PAGES_DIR, IMAGE_CACHE_DIR

CHUNKS_DIR = os.path.join(DATA_DIR, 'chunks')

db = SQLAlchemy()


@event.listens_for(Engine, 'connect')
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """SQLite 连接级调优：WAL 读写不互斥、NORMAL 同步、写锁等待 5s。

    多 gunicorn 进程 + 后台线程并发写同一库文件，默认回滚日志模式
    极易 database is locked。非 SQLite 连接（如测试内存库）自动跳过。
    """
    if type(dbapi_connection).__module__.startswith('sqlite'):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA busy_timeout=5000')
        cursor.close()


_scheduler_service = None


def create_app():
    global _scheduler_service
    app = Flask(__name__)
    app.config.from_object('config')

    os.makedirs(COMICS_DIR, exist_ok=True)
    os.makedirs(COVERS_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(NFO_DIR, exist_ok=True)
    os.makedirs(PAGES_DIR, exist_ok=True)
    os.makedirs(CHUNKS_DIR, exist_ok=True)
    os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)

    db.init_app(app)

    from app.routes import bp
    app.register_blueprint(bp)

    from app.api import register_api_blueprints
    register_api_blueprints(app)

    @app.context_processor
    def inject_settings():
        from app.models import Setting
        return {'site_name': Setting.get('site_name', 'xcomic')}

    @app.template_filter('map_tag')
    def map_tag_filter(tag):
        from app.utils.tag_utils import map_tag
        return map_tag(tag)

    @app.before_request
    def apply_max_content_length():
        from app.models import Setting
        from flask import request
        if request.path.startswith('/api/chunked-upload/chunk') or request.path.startswith('/api/v1/uploads/chunk'):
            app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024
        else:
            max_mb = int(Setting.get('max_content_length', '2048'))
            app.config['MAX_CONTENT_LENGTH'] = max_mb * 1024 * 1024

    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, PATCH'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
        return response

    with app.app_context():
        import sqlalchemy.exc
        try:
            db.create_all()
        except sqlalchemy.exc.OperationalError:
            pass
        _migrate_db(db)

        # 中断任务恢复已移至 SchedulerService.start()：抓取任务只在持有
        # 调度锁的 leader 进程运行，仅 leader 恢复——非 leader worker
        # 重启时误把存活 leader 正在跑的任务标记失败，队列会被假死阻塞
        if _scheduler_service is None:
            from app.services.scheduler_service import SchedulerService
            _scheduler_service = SchedulerService()
            _scheduler_service.start()

    return app


def _migrate_db(db):
    from app.models import Comic
    try:
        inspector = db.inspect(db.engine)
        existing = [c['name'] for c in inspector.get_columns('comics')]
        new_cols = {
            'title_jp': 'ALTER TABLE comics ADD COLUMN title_jp VARCHAR(512) DEFAULT ""',
            'category': 'ALTER TABLE comics ADD COLUMN category VARCHAR(64) DEFAULT ""',
            'language': 'ALTER TABLE comics ADD COLUMN language VARCHAR(64) DEFAULT ""',
            'uploader': 'ALTER TABLE comics ADD COLUMN uploader VARCHAR(128) DEFAULT ""',
            'page_count': 'ALTER TABLE comics ADD COLUMN page_count INTEGER DEFAULT 0',
            'favorited': 'ALTER TABLE comics ADD COLUMN favorited INTEGER DEFAULT 0',
            'source_url': 'ALTER TABLE comics ADD COLUMN source_url VARCHAR(512) DEFAULT ""',
            'date': 'ALTER TABLE comics ADD COLUMN date VARCHAR(32) DEFAULT ""',
            'is_translated': 'ALTER TABLE comics ADD COLUMN is_translated BOOLEAN DEFAULT 0',
            'rating_count': 'ALTER TABLE comics ADD COLUMN rating_count INTEGER DEFAULT 0',
            'torrent_urls': 'ALTER TABLE comics ADD COLUMN torrent_urls TEXT DEFAULT ""',
        }
        for col, sql in new_cols.items():
            if col not in existing:
                db.session.execute(db.text(sql))
        if 'year' in existing and 'date' not in existing:
            db.session.execute(db.text('UPDATE comics SET date = year WHERE date = "" OR date IS NULL'))
        if 'year' in existing:
            try:
                db.session.execute(db.text('ALTER TABLE comics DROP COLUMN year'))
            except Exception as e:
                print(f'[数据库] 删除旧列year失败: {e}')
        db.session.commit()
    except Exception as e:
        print(f'[数据库] comics表迁移失败: {e}')
        db.session.rollback()

    # 高频查询/排序列补索引（命名与 SQLAlchemy index=True 默认一致）
    _create_missing_indexes(db, 'comics', [
        'ix_comics_source_url', 'ix_comics_collection_id', 'ix_comics_rating',
        'ix_comics_file_size', 'ix_comics_created_at', 'ix_comics_updated_at',
    ])

    try:
        inspector = db.inspect(db.engine)
        if inspector.has_table('download_tasks'):
            existing = [c['name'] for c in inspector.get_columns('download_tasks')]
            new_cols = {
                'torrent_file': 'ALTER TABLE download_tasks ADD COLUMN torrent_file VARCHAR(512) DEFAULT ""',
                'queue': 'ALTER TABLE download_tasks ADD COLUMN queue VARCHAR(20) DEFAULT "waiting"',
                'queue_position': 'ALTER TABLE download_tasks ADD COLUMN queue_position INTEGER DEFAULT 0',
                'nfo_data': 'ALTER TABLE download_tasks ADD COLUMN nfo_data TEXT DEFAULT ""',
            }
            for col, sql in new_cols.items():
                if col not in existing:
                    db.session.execute(db.text(sql))
            db.session.commit()
    except Exception as e:
        print(f'[数据库] download_tasks表迁移失败: {e}')
        db.session.rollback()


def _create_missing_indexes(db, table, index_names):
    """为旧库补建缺失索引（幂等，IF NOT EXISTS）。"""
    try:
        inspector = db.inspect(db.engine)
        existing = {i['name'] for i in inspector.get_indexes(table)}
        for name in index_names:
            if name in existing:
                continue
            column = name[len(f'ix_{table}_'):]
            db.session.execute(db.text(
                f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})'))
        db.session.commit()
    except Exception as e:
        print(f'[数据库] {table} 索引迁移失败: {e}')
        db.session.rollback()
