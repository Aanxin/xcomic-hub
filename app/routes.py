import os
import uuid
import threading
import shutil
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, Response
from app import db
from app.models import Comic, Setting, ReadingHistory, UploadTask, ChunkedUpload, Collection, DownloadTask
from app.nfo_parser import parse_nfo, generate_nfo
from app.reader import get_comic_pages, get_page_dir, is_readable, cleanup_pages
from config import COMICS_DIR, COVERS_DIR, NFO_DIR, PAGES_DIR, DATA_DIR, ALLOWED_EXTENSIONS, IMAGE_EXTENSIONS, DOWNLOAD_DIR

from app.utils.file_utils import safe_filename, resolve_conflict, allowed_file, get_storage_subdir, group_tags
from app.utils.proxy_utils import get_proxy_handler, urlopen_with_proxy, parse_proxy_url
from app.scrapers.scraper_factory import ScraperFactory
from app.clients.http_client import urlopen_native
from app.clients.qbittorrent_client import QbittorrentClient
from app.services.nfo_service import NfoService
from app.services.comic_service import ComicService
from app.services.collection_service import CollectionService
from app.services.download_service import DownloadService, get_next_queue_position
from app.services.upload_service import UploadService, CHUNKS_DIR

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = int(Setting.get('per_page', '12'))
    search = request.args.get('search', '').strip()
    view_filter = request.args.get('filter', '')
    sort = request.args.get('sort', 'updated')

    collections = Collection.query
    standalone = Comic.query.filter(Comic.collection_id.is_(None))

    if search:
        from app.utils.tag_utils import reverse_map_tag

        def _tag_search(query, val):
            originals = reverse_map_tag(val)
            conditions = [Comic.tags.contains(v) for v in originals]
            return query.filter(db.or_(*conditions))

        def _field_search(query, field, val):
            originals = reverse_map_tag(val)
            conditions = [getattr(Comic, field).contains(v) for v in originals]
            return query.filter(db.or_(*conditions))

        if search.startswith('author:'):
            author_val = search[7:].strip()
            collections = collections.filter(False)
            standalone = _field_search(standalone, 'author', author_val)
        elif search.startswith('genre:'):
            genre_val = search[6:].strip()
            collections = collections.filter(False)
            standalone = _field_search(standalone, 'genre', genre_val)
        elif search.startswith('category:'):
            category_val = search[9:].strip()
            collections = collections.filter(False)
            standalone = _field_search(standalone, 'category', category_val)
        elif search.startswith('publisher:'):
            publisher_val = search[10:].strip()
            collections = collections.filter(False)
            standalone = _field_search(standalone, 'publisher', publisher_val)
        elif search.startswith('language:'):
            language_val = search[9:].strip()
            collections = collections.filter(False)
            standalone = _field_search(standalone, 'language', language_val)
        elif search.startswith('uploader:'):
            uploader_val = search[9:].strip()
            collections = collections.filter(False)
            standalone = _field_search(standalone, 'uploader', uploader_val)
        elif search.startswith('tag:'):
            tag_val = search[4:].strip()
            collections = collections.filter(False)
            standalone = _tag_search(standalone, tag_val)
        elif ':' in search:
            cat, val = search.split(':', 1)
            cat = cat.strip().lower()
            val = val.strip()
            collections = collections.filter(False)
            originals = reverse_map_tag(val)
            conditions = [Comic.tags.contains(f'{cat}:{v}') for v in originals] + [Comic.tags.contains(search)]
            standalone = standalone.filter(db.or_(*conditions))
        else:
            originals = reverse_map_tag(search)
            tag_conditions = [Comic.tags.contains(v) for v in originals]
            collections = collections.filter(
                db.or_(Collection.name.contains(search),)
            )
            standalone = standalone.filter(
                db.or_(
                    Comic.title.contains(search),
                    Comic.author.contains(search),
                    *tag_conditions,
                    Comic.genre.contains(search),
                )
            )

    if view_filter == 'favorite':
        collections = collections.filter(Collection.is_favorite == True)
        standalone = standalone.filter(Comic.is_favorite == True)
    elif view_filter == 'comic':
        collections = Collection.query.filter(False)
    elif view_filter == 'collection':
        standalone = Comic.query.filter(False)

    sort_map = {
        'updated': (Collection.updated_at.desc(), Comic.updated_at.desc()),
        'created': (Collection.created_at.desc(), Comic.created_at.desc()),
        'title': (Collection.name.asc(), Comic.title.asc()),
        'size': (Collection.id.asc(), Comic.file_size.desc()),
    }
    col_sort, comic_sort = sort_map.get(sort, sort_map['updated'])

    if view_filter == 'random':
        collections = collections.order_by(db.func.random()).limit(per_page).all()
        standalone_items = standalone.order_by(db.func.random()).limit(per_page).all()
        class FakePagination:
            def __init__(self, items, per_page):
                self.items = items
                self.page = 1
                self.pages = 1
                self.has_prev = False
                self.has_next = False
                self.per_page = per_page
        standalone_pag = FakePagination(standalone_items, per_page)
    else:
        collections = collections.order_by(col_sort).all()
        standalone_pag = standalone.order_by(comic_sort).paginate(page=page, per_page=per_page, error_out=False)

    comic_ids = [c.id for c in standalone_pag.items]
    histories = ReadingHistory.query.filter(ReadingHistory.comic_id.in_(comic_ids)).all() if comic_ids else []
    history_map = {h.comic_id: h for h in histories}

    collection_ids = [col.id for col in collections]
    col_histories = {}
    if collection_ids:
        col_comics = Comic.query.filter(Comic.collection_id.in_(collection_ids)).all()
        col_comic_ids = [c.id for c in col_comics]
        if col_comic_ids:
            all_h = ReadingHistory.query.filter(ReadingHistory.comic_id.in_(col_comic_ids)).all()
            for h in all_h:
                col_histories[h.comic_id] = h

    return render_template('index.html', collections=collections, comics=standalone_pag.items,
                           pagination=standalone_pag, search=search, history_map=history_map,
                           col_histories=col_histories, view_filter=view_filter, sort=sort)


@bp.route('/comic/<int:comic_id>')
def detail(comic_id):
    data = ComicService.get_detail(comic_id)
    return render_template('detail.html', **data)


@bp.route('/collection/<int:collection_id>')
def collection_detail(collection_id):
    col = Collection.query.get_or_404(collection_id)
    comics = col.comics.all()
    comic_ids = [c.id for c in comics]
    history_map = {}
    if comic_ids:
        histories = ReadingHistory.query.filter(ReadingHistory.comic_id.in_(comic_ids)).all()
        history_map = {h.comic_id: h for h in histories}
    return render_template('collection.html', collection=col, comics=comics, history_map=history_map)


@bp.route('/collection/<int:collection_id>/edit', methods=['GET', 'POST'])
def edit_collection(collection_id):
    col = Collection.query.get_or_404(collection_id)
    if request.method == 'POST':
        cover_file = request.files.get('cover_file')
        col, error = CollectionService.update_collection(collection_id, request.form, cover_file)
        if error:
            flash(error, 'error')
        else:
            flash('合集信息已更新', 'success')
            return redirect(url_for('main.collection_detail', collection_id=col.id))

    return render_template('edit_collection.html', collection=col)


@bp.route('/upload')
def upload():
    upload_interval = Setting.get('upload_interval', '1')
    return render_template('upload.html', upload_interval=upload_interval)


@bp.route('/api/chunked-upload/init', methods=['POST'])
def chunked_upload_init():
    data = request.get_json()
    if not data or not data.get('filename') or data.get('file_size') is None:
        return jsonify({'error': '缺少文件名或文件大小'}), 400

    filename = data['filename']
    file_size = int(data['file_size'])

    if not allowed_file(filename):
        return jsonify({'error': f'不支持的文件格式：{filename}'}), 400

    safe_name = safe_filename(filename)
    if not safe_name:
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'zip'
        safe_name = f"{uuid.uuid4().hex}.{ext}"

    collection_name = data.get('collection_name', '').strip()
    volume = data.get('volume', '').strip()

    storage_subdir = get_storage_subdir(filename, collection_name or None)
    target_dir = os.path.join(COMICS_DIR, storage_subdir)

    rel_path = os.path.join(storage_subdir, safe_name).replace('\\', '/')

    existing_comic = Comic.query.filter_by(filename=rel_path).first()
    if existing_comic:
        return jsonify({'error': f'文件已存在：{filename}', 'duplicate': True}), 409

    if os.path.exists(os.path.join(target_dir, safe_name)):
        return jsonify({'error': f'文件已存在：{filename}', 'duplicate': True}), 409

    default_chunk_size = int(Setting.get('chunk_size', '5')) * 1024 * 1024
    chunk_size = int(data.get('chunk_size', default_chunk_size))
    total_chunks = (file_size + chunk_size - 1) // chunk_size if file_size > 0 else 1

    upload_id = uuid.uuid4().hex

    existing = ChunkedUpload.query.filter_by(
        original_filename=filename, file_size=file_size, status='paused'
    ).first()
    if existing:
        return jsonify(existing.to_dict())

    cu = ChunkedUpload(
        id=upload_id,
        original_filename=filename,
        file_size=file_size,
        chunk_size=chunk_size,
        total_chunks=total_chunks,
        status='pending',
        nfo_filename=data.get('nfo_filename', ''),
        cover_filename=data.get('cover_filename', ''),
        manual_title=data.get('manual_title', ''),
        manual_author=data.get('manual_author', ''),
        collection_name=collection_name,
        volume=volume,
    )
    db.session.add(cu)
    db.session.commit()

    os.makedirs(os.path.join(CHUNKS_DIR, upload_id), exist_ok=True)

    return jsonify(cu.to_dict())


@bp.route('/api/chunked-upload/chunk', methods=['POST'])
def chunked_upload_chunk():
    upload_id = request.form.get('upload_id', '')
    chunk_index = request.form.get('chunk_index', '')

    if not upload_id or chunk_index == '':
        return jsonify({'error': '缺少参数'}), 400

    chunk_index = int(chunk_index)
    cu = ChunkedUpload.query.get(upload_id)
    if not cu:
        return jsonify({'error': '上传任务不存在'}), 404

    if cu.status == 'cancelled':
        return jsonify({'error': '上传已取消'}), 400

    if cu.status == 'paused':
        cu.status = 'uploading'
        db.session.commit()

    chunk_file = request.files.get('chunk')
    if not chunk_file:
        return jsonify({'error': '缺少分片数据'}), 400

    chunk_dir = os.path.join(CHUNKS_DIR, upload_id)
    os.makedirs(chunk_dir, exist_ok=True)
    chunk_path = os.path.join(chunk_dir, str(chunk_index))
    chunk_file.save(chunk_path)

    uploaded = cu.uploaded_chunks
    if chunk_index not in uploaded:
        uploaded.append(chunk_index)
    cu.uploaded_chunks = uploaded
    cu.status = 'uploading'
    cu.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify(cu.to_dict())


@bp.route('/api/chunked-upload/complete', methods=['POST'])
def chunked_upload_complete():
    data = request.get_json()
    upload_id = data.get('upload_id', '') if data else ''
    cu = ChunkedUpload.query.get(upload_id)
    if not cu:
        return jsonify({'error': '上传任务不存在'}), 404

    uploaded = cu.uploaded_chunks
    if len(uploaded) < cu.total_chunks:
        return jsonify({'error': f'分片不完整：{len(uploaded)}/{cu.total_chunks}'}), 400

    cu.status = 'assembling'
    db.session.commit()

    thread = threading.Thread(
        target=UploadService.assemble_chunked_upload,
        args=(upload_id,),
        daemon=True,
    )
    thread.start()

    return jsonify(cu.to_dict())


@bp.route('/api/chunked-upload/cancel', methods=['POST'])
def chunked_upload_cancel():
    data = request.get_json()
    upload_id = data.get('upload_id', '') if data else ''
    cu = ChunkedUpload.query.get(upload_id)
    if not cu:
        return jsonify({'error': '上传任务不存在'}), 404

    cu.status = 'cancelled'
    db.session.commit()

    chunk_dir = os.path.join(CHUNKS_DIR, upload_id)
    if os.path.exists(chunk_dir):
        shutil.rmtree(chunk_dir, ignore_errors=True)

    return jsonify({'message': '已取消'})


@bp.route('/api/chunked-upload/pause', methods=['POST'])
def chunked_upload_pause():
    data = request.get_json()
    upload_id = data.get('upload_id', '') if data else ''
    cu = ChunkedUpload.query.get(upload_id)
    if not cu:
        return jsonify({'error': '上传任务不存在'}), 404

    cu.status = 'paused'
    db.session.commit()
    return jsonify(cu.to_dict())


@bp.route('/api/chunked-upload/status/<upload_id>')
def chunked_upload_status(upload_id):
    cu = ChunkedUpload.query.get(upload_id)
    if not cu:
        return jsonify({'error': '上传任务不存在'}), 404
    return jsonify(cu.to_dict())


@bp.route('/api/chunked-upload/nfo-files', methods=['POST'])
def chunked_upload_nfo():
    nfo_file = request.files.get('nfo_file')
    if not nfo_file or nfo_file.filename == '':
        return jsonify({'error': '缺少NFO文件'}), 400

    safe = safe_filename(nfo_file.filename) or f'{uuid.uuid4().hex}.nfo'
    nfo_temp_dir = os.path.join(CHUNKS_DIR, '_nfo_temp')
    os.makedirs(nfo_temp_dir, exist_ok=True)
    nfo_id = uuid.uuid4().hex
    nfo_sub_dir = os.path.join(nfo_temp_dir, nfo_id)
    os.makedirs(nfo_sub_dir, exist_ok=True)
    nfo_path = os.path.join(nfo_sub_dir, safe)
    nfo_file.save(nfo_path)

    return jsonify({'nfo_id': nfo_id, 'nfo_filename': safe, 'original_name': nfo_file.filename})


@bp.route('/api/chunked-upload/cover-files', methods=['POST'])
def chunked_upload_cover():
    cover_file = request.files.get('cover_file')
    if not cover_file or cover_file.filename == '':
        return jsonify({'error': '缺少封面文件'}), 400

    safe = safe_filename(cover_file.filename) or f'{uuid.uuid4().hex}.jpg'
    cover_temp_dir = os.path.join(CHUNKS_DIR, '_cover_temp')
    os.makedirs(cover_temp_dir, exist_ok=True)
    cover_id = uuid.uuid4().hex
    cover_sub_dir = os.path.join(cover_temp_dir, cover_id)
    os.makedirs(cover_sub_dir, exist_ok=True)
    cover_path = os.path.join(cover_sub_dir, safe)
    cover_file.save(cover_path)

    return jsonify({'cover_id': cover_id, 'cover_filename': safe, 'original_name': cover_file.filename})


@bp.route('/comic/<int:comic_id>/edit', methods=['GET', 'POST'])
def edit(comic_id):
    comic = Comic.query.get_or_404(comic_id)
    if request.method == 'POST':
        nfo_file = request.files.get('nfo_file')
        cover_file = request.files.get('cover_file')
        ComicService.update_comic(comic_id, request.form, nfo_file, cover_file)
        flash('漫画信息已更新', 'success')
        return redirect(url_for('main.detail', comic_id=comic_id))

    collection_name = comic.collection.name if comic.collection else ''
    return render_template('edit.html', comic=comic, collection_name=collection_name)


@bp.route('/comic/<int:comic_id>/regenerate-cover', methods=['POST'])
def regenerate_cover(comic_id):
    from app.reader import regenerate_comic_cover
    comic = Comic.query.get_or_404(comic_id)
    try:
        result = regenerate_comic_cover(comic)
        if result:
            return jsonify({'success': True, 'cover_url': url_for('main.cover', filename=result)})
        return jsonify({'success': False, 'error': '封面生成失败，请确认漫画文件存在且格式支持'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/comic/<int:comic_id>/delete', methods=['POST'])
def delete(comic_id):
    ComicService.delete_comic(comic_id)
    flash('漫画已删除', 'success')
    return redirect(url_for('main.index'))


@bp.route('/comic/<int:comic_id>/download')
def download(comic_id):
    comic = Comic.query.get_or_404(comic_id)
    if not comic.filename:
        return jsonify({'error': '文件不存在'}), 404
    file_path = os.path.join(COMICS_DIR, comic.filename)
    if not os.path.exists(file_path):
        return jsonify({'error': '文件不存在'}), 404
    download_name = comic.title + os.path.splitext(comic.filename)[1]
    return send_from_directory(os.path.dirname(file_path), os.path.basename(file_path),
                               as_attachment=True, download_name=download_name)


@bp.route('/comic/<int:comic_id>/nfo')
def export_nfo(comic_id):
    comic = Comic.query.get_or_404(comic_id)
    NfoService.save_comic_nfo(comic)
    db.session.commit()
    if comic.nfo_file:
        nfo_path = os.path.join(NFO_DIR, comic.nfo_file)
        if os.path.exists(nfo_path):
            nfo_dir = os.path.dirname(nfo_path)
            nfo_base = os.path.basename(nfo_path)
            return send_from_directory(nfo_dir, nfo_base, as_attachment=True, download_name=f"{comic.title}.nfo")
    nfo_content = generate_nfo(comic.to_dict())
    return Response(nfo_content, mimetype='application/xml', headers={'Content-Disposition': f'attachment; filename={comic.title}.nfo'})


@bp.route('/collection/<int:collection_id>/nfo')
def export_collection_nfo(collection_id):
    col = Collection.query.get_or_404(collection_id)
    NfoService.save_collection_nfo(col)
    db.session.commit()
    if col.nfo_file:
        nfo_path = os.path.join(NFO_DIR, col.nfo_file)
        if os.path.exists(nfo_path):
            nfo_dir = os.path.dirname(nfo_path)
            nfo_base = os.path.basename(nfo_path)
            return send_from_directory(nfo_dir, nfo_base, as_attachment=True, download_name=f"{col.name}.nfo")
    nfo_content = generate_nfo(col.to_dict())
    return Response(nfo_content, mimetype='application/xml', headers={'Content-Disposition': f'attachment; filename={col.name}.nfo'})


@bp.route('/covers/<path:filename>')
def cover(filename):
    cover_path = os.path.join(COVERS_DIR, filename)
    cover_dir = os.path.dirname(cover_path)
    cover_base = os.path.basename(cover_path)
    if os.path.exists(cover_path):
        return send_from_directory(cover_dir, cover_base)
    return '', 404


@bp.route('/comic/<int:comic_id>/read')
def reader(comic_id):
    comic = Comic.query.get_or_404(comic_id)
    pages = get_comic_pages(comic_id, comic.filename)
    if not pages:
        flash('无法读取此漫画文件', 'error')
        return redirect(url_for('main.detail', comic_id=comic_id))
    history = ReadingHistory.query.filter_by(comic_id=comic_id).first()
    last_page = history.last_page if history else 1
    start_param = request.args.get('start', type=int)
    if start_param == 1:
        start_page = 1
    else:
        start_page = last_page
    is_new_read = history is None
    if is_new_read:
        history = ReadingHistory(comic_id=comic_id, total_pages=len(pages), read_count=1)
        db.session.add(history)
        db.session.commit()
    else:
        history.read_count += 1
        history.total_pages = len(pages)
        history.last_read_at = datetime.utcnow()
        db.session.commit()

    if comic.page_count != len(pages):
        comic.page_count = len(pages)
        db.session.commit()

    next_comic_id = None
    next_comic_title = None
    if comic.collection_id:
        siblings = Comic.query.filter_by(collection_id=comic.collection_id)\
            .order_by(Comic.volume.asc(), Comic.id.asc()).all()
        for i, c in enumerate(siblings):
            if c.id == comic.id and i + 1 < len(siblings):
                next_comic_id = siblings[i + 1].id
                next_comic_title = siblings[i + 1].volume or siblings[i + 1].title
                break

    return render_template('reader.html', comic=comic, pages=pages, total=len(pages),
                           start_page=start_page, next_comic_id=next_comic_id,
                           next_comic_title=next_comic_title)


@bp.route('/comic/<int:comic_id>/page/<page_filename>')
def serve_page(comic_id, page_filename):
    page_dir = get_page_dir(comic_id, page_filename)
    if page_dir is None:
        return jsonify({'error': '页面不存在'}), 404
    response = send_from_directory(page_dir, page_filename)
    response.headers['Cache-Control'] = 'public, max-age=86400'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@bp.route('/api/comics/<int:comic_id>/progress', methods=['GET', 'POST'])
def api_progress(comic_id):
    comic = Comic.query.get_or_404(comic_id)
    if request.method == 'GET':
        history = ReadingHistory.query.filter_by(comic_id=comic_id).first()
        if not history:
            return jsonify({'last_page': 1, 'total_pages': 0, 'read_count': 0})
        return jsonify(history.to_dict())

    data = request.get_json(silent=True)
    if not data:
        data = request.form.to_dict()

    last_page = data.get('last_page')
    total_pages = data.get('total_pages')

    history = ReadingHistory.query.filter_by(comic_id=comic_id).first()
    if not history:
        history = ReadingHistory(comic_id=comic_id)
        db.session.add(history)

    if last_page is not None:
        history.last_page = max(1, int(last_page))
    if total_pages is not None:
        history.total_pages = max(0, int(total_pages))
    history.last_read_at = datetime.utcnow()
    db.session.commit()
    return jsonify(history.to_dict())


@bp.route('/api/scrape-info', methods=['POST'])
def scrape_info():
    html_content = None
    source_url = ''

    if request.content_type and 'application/json' in request.content_type:
        data = request.get_json(silent=True) or {}
        url = data.get('url', '').strip()
        source_url = url
        if not url:
            return jsonify({'error': '请输入网址'}), 400
        if not url.startswith(('http://', 'https://')):
            return jsonify({'error': '网址必须以 http:// 或 https:// 开头'}), 400
        try:
            html_content = urlopen_with_proxy(url)
        except Exception as e:
            return jsonify({'error': f'无法获取网页: {str(e)}'}), 400
    else:
        html_file = request.files.get('html_file')
        if not html_file:
            return jsonify({'error': '请上传 HTML 文件或输入网址'}), 400
        try:
            html_content = html_file.read().decode('utf-8', errors='ignore')
        except Exception as _e:
            print(f'[采集] 读取上传文件失败: {_e}')
            return jsonify({'error': '无法读取文件'}), 400

    scraper = ScraperFactory.create_scraper(source_url, html_content)
    result = scraper.scrape(html_content, source_url)
    return jsonify(result)


@bp.route('/api/test-proxy', methods=['POST'])
def test_proxy():
    data = request.get_json(silent=True) or {}
    enabled = data.get('proxy_enabled', '0')
    if enabled != '1':
        return jsonify({'success': False, 'message': '代理未启用'})

    proxy_type = data.get('proxy_type', 'http')
    host = data.get('proxy_host', '').strip()
    port = data.get('proxy_port', '').strip()
    user = data.get('proxy_user', '').strip()
    pwd = data.get('proxy_pass', '').strip()

    if not host:
        return jsonify({'success': False, 'message': '代理地址不能为空'})

    auth = f"{user}:{pwd}@" if user else ""
    if proxy_type == 'socks5':
        proxy_url = f"socks5://{auth}{host}"
        if port:
            proxy_url += f":{port}"
    elif proxy_type == 'https':
        proxy_url = f"https://{auth}{host}"
        if port:
            proxy_url += f":{port}"
    else:
        proxy_url = f"http://{auth}{host}"
        if port:
            proxy_url += f":{port}"

    proxy_dict = {'http': proxy_url, 'https': proxy_url}

    test_url = 'https://e-hentai.org/'
    import time
    start = time.time()

    try:
        from urllib.request import urlopen, Request, build_opener, ProxyHandler
        req = Request(test_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

        if proxy_type == 'socks5':
            try:
                import socks
                import socket
                old_socket = socket.socket
                parsed = parse_proxy_url(proxy_url)
                if parsed['user']:
                    socks.set_default_proxy(socks.SOCKS5, parsed['host'], parsed['port'], True, parsed['user'], parsed['pwd'])
                else:
                    socks.set_default_proxy(socks.SOCKS5, parsed['host'], parsed['port'])
                socket.socket = socks.socksocket
                try:
                    resp = urlopen(req, timeout=15)
                    resp.read()
                finally:
                    socket.socket = old_socket
            except ImportError:
                return jsonify({'success': False, 'message': 'SOCKS5 需要 PySocks 库，请执行 pip install PySocks'})
        else:
            handler = ProxyHandler(proxy_dict)
            opener = build_opener(handler)
            resp = opener.open(req, timeout=15)
            resp.read()

        elapsed = round((time.time() - start) * 1000)
        return jsonify({'success': True, 'message': f'连接成功（耗时 {elapsed}ms）'})
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        return jsonify({'success': False, 'message': f'连接失败: {str(e)}（耗时 {elapsed}ms）'})


@bp.route('/api/backup-settings', methods=['GET'])
def backup_settings():
    import json
    settings = Setting.query.all()
    data = {s.key: s.value for s in settings}
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content,
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=manhua_settings.json'}
    )


@bp.route('/api/import-settings', methods=['POST'])
def import_settings():
    import json
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '未选择文件'})
    f = request.files['file']
    if not f.filename:
        return jsonify({'success': False, 'message': '未选择文件'})
    try:
        content = f.read().decode('utf-8')
        data = json.loads(content)
        if not isinstance(data, dict):
            return jsonify({'success': False, 'message': '文件格式错误：需要JSON对象'})
        count = 0
        for key, value in data.items():
            if isinstance(value, str):
                Setting.set(key, value)
                count += 1
        db.session.commit()
        return jsonify({'success': True, 'message': f'导入成功，已更新 {count} 项设置'})
    except json.JSONDecodeError:
        return jsonify({'success': False, 'message': '文件格式错误：无效的JSON'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'导入失败: {str(e)}'})


@bp.route('/api/test-qbittorrent', methods=['POST'])
def test_qbittorrent():
    data = request.get_json(silent=True) or {}
    host = data.get('qb_host', '').strip()
    port = data.get('qb_port', '').strip()
    user = data.get('qb_user', 'admin').strip()
    pwd = data.get('qb_pass', '').strip()

    if not host:
        return jsonify({'success': False, 'message': '请填写 qBittorrent 地址'})

    import time
    start = time.time()

    try:
        qb = QbittorrentClient(host=host, port=port, username=user, password=pwd)
        qb_info, qb_err = qb.login()
        elapsed = round((time.time() - start) * 1000)

        if qb_err:
            return jsonify({'success': False, 'message': f'{qb_err}（耗时 {elapsed}ms）'})

        version_resp = urlopen_native(
            f"{qb_info['base_url']}/api/v2/app/version",
            headers={'Cookie': qb_info['cookie']},
            timeout=10
        )
        version = version_resp.get('body', '').strip()
        return jsonify({'success': True, 'message': f'连接成功 v{version}（耗时 {elapsed}ms）'})
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        return jsonify({'success': False, 'message': f'连接失败: {str(e)}（耗时 {elapsed}ms）'})


@bp.route('/api/comic/<int:comic_id>/favorite', methods=['POST'])
def toggle_comic_favorite(comic_id):
    favorite = ComicService.toggle_favorite(comic_id)
    return jsonify({'is_favorite': favorite})


@bp.route('/api/collection/<int:collection_id>/favorite', methods=['POST'])
def toggle_collection_favorite(collection_id):
    favorite = CollectionService.toggle_favorite(collection_id)
    return jsonify({'is_favorite': favorite})


@bp.route('/api/clear-cache', methods=['POST'])
def clear_cache():
    from config import PAGES_DIR
    from app.utils.file_utils import get_dir_size, format_size

    cleared = 0
    if os.path.exists(PAGES_DIR):
        size = get_dir_size(PAGES_DIR)
        shutil.rmtree(PAGES_DIR, ignore_errors=True)
        os.makedirs(PAGES_DIR, exist_ok=True)
        cleared += size

    return jsonify({
        'success': True,
        'message': f'页面缓存已清理，释放 {format_size(cleared)} 空间'
    })


@bp.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        site_name = request.form.get('site_name', 'xcomic').strip()
        per_page = request.form.get('per_page', '12').strip()
        max_content_length = request.form.get('max_content_length', '2048').strip()
        chunk_size = request.form.get('chunk_size', '5').strip()
        upload_interval = request.form.get('upload_interval', '1').strip()
        auto_cover = request.form.get('auto_cover', '1').strip()
        cover_width = request.form.get('cover_width', '300').strip()
        cover_quality = request.form.get('cover_quality', '85').strip()

        try:
            per_page_val = int(per_page)
            if per_page_val < 1 or per_page_val > 100:
                raise ValueError
        except ValueError:
            flash('每页显示数量必须为1-100之间的整数', 'error')
            return redirect(request.url)

        try:
            max_cl_val = int(max_content_length)
            if max_cl_val < 100 or max_cl_val > 51200:
                raise ValueError
        except ValueError:
            flash('最大上传大小必须为100-51200之间的整数', 'error')
            return redirect(request.url)

        try:
            chunk_val = int(chunk_size)
            if chunk_val < 1 or chunk_val > 100:
                raise ValueError
        except ValueError:
            flash('分块上传大小必须为1-100之间的整数', 'error')
            return redirect(request.url)

        try:
            interval_val = float(upload_interval)
            if interval_val < 0 or interval_val > 30:
                raise ValueError
        except ValueError:
            flash('文件处理间隔必须为0-30之间的数值', 'error')
            return redirect(request.url)

        try:
            width_val = int(cover_width)
            if width_val < 100 or width_val > 1000:
                raise ValueError
        except ValueError:
            flash('封面宽度必须为100-1000之间的整数', 'error')
            return redirect(request.url)

        try:
            quality_val = int(cover_quality)
            if quality_val < 10 or quality_val > 100:
                raise ValueError
        except ValueError:
            flash('封面图片质量必须为10-100之间的整数', 'error')
            return redirect(request.url)

        Setting.set('site_name', site_name or 'xcomic')
        Setting.set('per_page', str(per_page_val))
        Setting.set('max_content_length', str(max_cl_val))
        Setting.set('chunk_size', str(chunk_val))
        Setting.set('upload_interval', str(interval_val))
        Setting.set('auto_cover', auto_cover)
        Setting.set('cover_width', str(width_val))
        Setting.set('cover_quality', str(quality_val))

        proxy_enabled = request.form.get('proxy_enabled', '0').strip()
        proxy_type = request.form.get('proxy_type', 'http').strip()
        proxy_host = request.form.get('proxy_host', '').strip()
        proxy_port = request.form.get('proxy_port', '').strip()
        proxy_user = request.form.get('proxy_user', '').strip()
        proxy_pass = request.form.get('proxy_pass', '').strip()

        if proxy_enabled == '1' and proxy_host:
            try:
                port_val = int(proxy_port)
                if port_val < 1 or port_val > 65535:
                    raise ValueError
            except ValueError:
                flash('代理端口必须为1-65535之间的整数', 'error')
                return redirect(request.url)

        Setting.set('proxy_enabled', proxy_enabled)
        Setting.set('proxy_type', proxy_type)
        Setting.set('proxy_host', proxy_host)
        Setting.set('proxy_port', proxy_port)
        Setting.set('proxy_user', proxy_user)
        Setting.set('proxy_pass', proxy_pass)

        cookie_ehentai = request.form.get('cookie_ehentai', '').strip()
        cookie_exhentai = request.form.get('cookie_exhentai', '').strip()
        cookie_nhentai = request.form.get('cookie_nhentai', '').strip()
        Setting.set('cookie_ehentai', cookie_ehentai)
        Setting.set('cookie_exhentai', cookie_exhentai)
        Setting.set('cookie_nhentai', cookie_nhentai)

        qb_enabled = request.form.get('qb_enabled', '0').strip()
        qb_host = request.form.get('qb_host', '').strip()
        qb_port = request.form.get('qb_port', '').strip()
        qb_user = request.form.get('qb_user', '').strip()
        qb_pass = request.form.get('qb_pass', '').strip()
        qb_category = request.form.get('qb_category', '').strip()
        qb_download_path = request.form.get('qb_download_path', '').strip()
        Setting.set('qb_enabled', qb_enabled)
        Setting.set('qb_host', qb_host)
        Setting.set('qb_port', qb_port)
        Setting.set('qb_user', qb_user)
        Setting.set('qb_pass', qb_pass)
        Setting.set('qb_category', qb_category)
        Setting.set('qb_download_path', qb_download_path)

        tag_mapping = request.form.get('tag_mapping', '').strip()
        Setting.set('tag_mapping', tag_mapping)

        max_cache_size = request.form.get('max_cache_size', '0').strip()
        try:
            mcs_val = int(max_cache_size)
            if mcs_val < 0:
                raise ValueError
        except ValueError:
            flash('缓存上限必须为非负整数（0 表示不限制）', 'error')
            return redirect(request.url)
        Setting.set('max_cache_size', str(mcs_val))

        flash('设置已保存', 'success')
        return redirect(url_for('main.settings'))

    site_name = Setting.get('site_name', 'xcomic')
    per_page = Setting.get('per_page', '12')
    max_content_length = Setting.get('max_content_length', '2048')
    chunk_size = Setting.get('chunk_size', '5')
    upload_interval = Setting.get('upload_interval', '1')
    auto_cover = Setting.get('auto_cover', '1')
    cover_width = Setting.get('cover_width', '300')
    cover_quality = Setting.get('cover_quality', '85')
    proxy_enabled = Setting.get('proxy_enabled', '0')
    proxy_type = Setting.get('proxy_type', 'http')
    proxy_host = Setting.get('proxy_host', '')
    proxy_port = Setting.get('proxy_port', '')
    proxy_user = Setting.get('proxy_user', '')
    proxy_pass = Setting.get('proxy_pass', '')
    total_comics = Comic.query.count()
    total_size = db.session.query(db.func.sum(Comic.file_size)).scalar() or 0

    from app.utils.file_utils import get_dir_size, format_size
    from config import PAGES_DIR, COVERS_DIR
    pages_cache_size = get_dir_size(PAGES_DIR)
    covers_cache_size = get_dir_size(COVERS_DIR)
    total_cache_size = pages_cache_size + covers_cache_size
    max_cache_size = int(Setting.get('max_cache_size', '0'))

    return render_template('settings.html', site_name=site_name, per_page=per_page,
                           max_content_length=max_content_length,
                           chunk_size=chunk_size,
                           upload_interval=upload_interval, auto_cover=auto_cover,
                           cover_width=cover_width, cover_quality=cover_quality,
                           proxy_enabled=proxy_enabled, proxy_type=proxy_type,
                           proxy_host=proxy_host, proxy_port=proxy_port,
                           proxy_user=proxy_user, proxy_pass=proxy_pass,
                           cookie_ehentai=Setting.get('cookie_ehentai', ''),
                           cookie_exhentai=Setting.get('cookie_exhentai', ''),
                           cookie_nhentai=Setting.get('cookie_nhentai', ''),
                           qb_enabled=Setting.get('qb_enabled', '0'),
                           qb_host=Setting.get('qb_host', ''),
                           qb_port=Setting.get('qb_port', '8080'),
                           qb_user=Setting.get('qb_user', 'admin'),
                           qb_pass=Setting.get('qb_pass', ''),
                           qb_category=Setting.get('qb_category', ''),
                           qb_download_path=Setting.get('qb_download_path', ''),
                           tag_mapping=Setting.get('tag_mapping', ''),
                           total_comics=total_comics, total_size=total_size,
                           pages_cache_size=pages_cache_size,
                           covers_cache_size=covers_cache_size,
                           total_cache_size=total_cache_size,
                           pages_cache_display=format_size(pages_cache_size),
                           covers_cache_display=format_size(covers_cache_size),
                           total_cache_display=format_size(total_cache_size),
                           max_cache_size=max_cache_size)


@bp.route('/api/comics', methods=['GET'])
def api_list():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '').strip()
    query = Comic.query
    if search:
        query = query.filter(
            db.or_(
                Comic.title.contains(search),
                Comic.author.contains(search),
                Comic.tags.contains(search),
            )
        )
    pagination = query.order_by(Comic.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'comics': [c.to_dict() for c in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'pages': pagination.pages,
    })


@bp.route('/api/comics/<int:comic_id>', methods=['GET'])
def api_detail(comic_id):
    comic = Comic.query.get_or_404(comic_id)
    return jsonify(comic.to_dict())


@bp.route('/api/comics', methods=['POST'])
def api_create():
    data = request.get_json()
    if not data or not data.get('title'):
        return jsonify({'error': '标题不能为空'}), 400
    comic = Comic(
        title=data.get('title', '未命名'),
        author=data.get('author', ''),
        genre=data.get('genre', ''),
        category=data.get('category', ''),
        date=data.get('date', ''),
        plot=data.get('plot', ''),
        rating=data.get('rating', 0.0),
        tags=data.get('tags', ''),
        status=data.get('status', ''),
        publisher=data.get('publisher', ''),
    )
    db.session.add(comic)
    db.session.commit()
    return jsonify(comic.to_dict()), 201


@bp.route('/api/comics/<int:comic_id>', methods=['PUT'])
def api_update(comic_id):
    comic = Comic.query.get_or_404(comic_id)
    data = request.get_json()
    if not data:
        return jsonify({'error': '无效数据'}), 400
    for key in ['title', 'title_jp', 'author', 'genre', 'category', 'date', 'plot', 'tags', 'status', 'publisher', 'language', 'uploader', 'source_url', 'torrent_urls']:
        if data.get(key):
            setattr(comic, key, data[key])
    if 'is_translated' in data:
        comic.is_translated = bool(data['is_translated'])
    if 'rating' in data:
        try:
            comic.rating = float(data['rating'])
        except (ValueError, TypeError):
            comic.rating = 0.0
    NfoService.save_comic_nfo(comic)
    db.session.commit()
    return jsonify(comic.to_dict())


@bp.route('/api/comics/<int:comic_id>', methods=['DELETE'])
def api_delete(comic_id):
    comic = Comic.query.get_or_404(comic_id)
    if comic.filename:
        file_path = os.path.join(COMICS_DIR, comic.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
    if comic.cover:
        cover_path = os.path.join(COVERS_DIR, comic.cover)
        if os.path.exists(cover_path):
            os.remove(cover_path)
    if comic.nfo_file:
        nfo_path = os.path.join(NFO_DIR, comic.nfo_file)
        if os.path.exists(nfo_path):
            os.remove(nfo_path)
    cleanup_pages(comic_id)
    db.session.delete(comic)
    db.session.commit()
    return jsonify({'message': '已删除'}), 200


@bp.route('/download')
def download_page():
    return render_template('download.html')


@bp.route('/api/download/start', methods=['POST'])
def api_download_start():
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': '请输入网址'}), 400
    if not url.startswith(('http://', 'https://')):
        return jsonify({'error': '网址必须以 http:// 或 https:// 开头'}), 400

    task_id = uuid.uuid4().hex[:8]
    task = DownloadTask(
        id=task_id,
        url=url,
        status='pending',
        message='等待队列中...',
        queue='waiting',
        queue_position=get_next_queue_position(),
    )
    db.session.add(task)
    db.session.commit()

    return jsonify({'task': task.to_dict()})


@bp.route('/api/download/upload-torrent', methods=['POST'])
def api_download_upload_torrent():
    torrent_file_obj = request.files.get('torrent_file')
    if not torrent_file_obj or torrent_file_obj.filename == '':
        return jsonify({'error': '请选择种子文件'}), 400

    filename = torrent_file_obj.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext != 'torrent':
        return jsonify({'error': '仅支持 .torrent 文件'}), 400

    safe_name = safe_filename(filename)
    if not safe_name:
        safe_name = f"{uuid.uuid4().hex}.torrent"

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    safe_name = resolve_conflict(DOWNLOAD_DIR, safe_name)
    torrent_path = os.path.join(DOWNLOAD_DIR, safe_name)
    torrent_file_obj.save(torrent_path)

    url = request.form.get('url', '').strip()
    title = request.form.get('title', '').strip()

    task_id = uuid.uuid4().hex[:8]
    task = DownloadTask(
        id=task_id,
        url=url,
        title=title or os.path.splitext(safe_name)[0],
        status='pending',
        message='等待队列中...',
        queue='waiting',
        queue_position=get_next_queue_position(),
        torrent_file=safe_name,
    )
    db.session.add(task)
    db.session.commit()

    return jsonify({'task': task.to_dict()})


@bp.route('/api/download/tasks', methods=['GET'])
def api_download_tasks():
    DownloadService.update_download_progress()
    waiting = DownloadTask.query.filter_by(queue='waiting').order_by(DownloadTask.queue_position.asc(), DownloadTask.created_at.asc()).all()
    downloading = DownloadTask.query.filter(
        DownloadTask.queue == 'downloading',
        DownloadTask.status.notin_(['done', 'error'])
    ).order_by(DownloadTask.created_at.desc()).all()
    done = DownloadTask.query.filter(
        DownloadTask.status.in_(['done', 'error'])
    ).order_by(DownloadTask.updated_at.desc()).limit(30).all()
    return jsonify({
        'waiting': [t.to_dict() for t in waiting],
        'downloading': [t.to_dict() for t in downloading],
        'done': [t.to_dict() for t in done],
    })


@bp.route('/api/download/progress', methods=['GET'])
def api_download_progress():
    DownloadService.update_download_progress()
    tasks = DownloadTask.query.filter(
        DownloadTask.queue == 'downloading',
        DownloadTask.status.in_(['downloading', 'importing', 'matching', 'done', 'error'])
    ).all()
    return jsonify({'tasks': [t.to_dict() for t in tasks]})


@bp.route('/api/download/<task_id>/delete', methods=['POST'])
def api_download_delete(task_id):
    task = DownloadTask.query.get_or_404(task_id)
    DownloadService.delete_task(task)
    return jsonify({'message': '已删除'})
