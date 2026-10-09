import os
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, Response
from app import db
from app.models import Comic, Setting, ReadingHistory, Collection
from app.nfo_parser import generate_nfo
from app.reader import get_comic_pages, get_page_dir
from config import COMICS_DIR, COVERS_DIR, NFO_DIR, PAGES_DIR

from app.utils.sort_utils import resolve_direction, apply_order
from app.utils.file_utils import safe_filename
from app.services.nfo_service import NfoService
from app.services.comic_service import ComicService
from app.services.collection_service import CollectionService

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

    order = request.args.get('order', '').strip().lower()

    sort_map = {
        'updated': ((Collection.updated_at, 'desc'), (Comic.updated_at, 'desc')),
        'created': ((Collection.created_at, 'desc'), (Comic.created_at, 'desc')),
        'title': ((Collection.name, 'asc'), (Comic.title, 'asc')),
        'size': ((Collection.id, 'asc'), (Comic.file_size, 'desc')),
        'rating': ((Collection.id, 'asc'), (Comic.rating, 'desc')),
    }
    (col_col, col_default), (comic_col, comic_default) = sort_map.get(sort, sort_map['updated'])
    col_dir = resolve_direction(order, col_default)
    comic_dir = resolve_direction(order, comic_default)

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
        collections = collections.order_by(apply_order(col_col, col_dir)).all()
        standalone_pag = standalone.order_by(apply_order(comic_col, comic_dir)).paginate(page=page, per_page=per_page, error_out=False)

    effective_order = comic_dir

    comic_ids = [c.id for c in standalone_pag.items]
    histories = ReadingHistory.query.filter(ReadingHistory.comic_id.in_(comic_ids)).all() if comic_ids else []
    history_map = {h.comic_id: h for h in histories}

    collection_ids = [col.id for col in collections]
    col_histories = {}
    if collection_ids:
        # JOIN 直接取合集内漫画的阅读历史，避免先全量加载 Comic 实体再二次查询
        rows = (ReadingHistory.query
                .join(Comic, ReadingHistory.comic_id == Comic.id)
                .filter(Comic.collection_id.in_(collection_ids))
                .all())
        for h in rows:
            col_histories[h.comic_id] = h

    return render_template('index.html', collections=collections, comics=standalone_pag.items,
                           pagination=standalone_pag, search=search, history_map=history_map,
                           col_histories=col_histories, view_filter=view_filter, sort=sort,
                           order=effective_order)


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


@bp.route('/browse')
def browse():
    return render_template('browse.html')


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
    from app.reader import regenerate_comic_cover_by_id
    from app.utils.threading_utils import run_cpu_bound
    try:
        # PIL 封面生成是 CPU 密集工作，委托真实线程避免阻塞事件循环
        result = run_cpu_bound(regenerate_comic_cover_by_id, comic_id)
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
    # 截断+清理下载名：客户端文件系统对单文件名有限制（ext4 255 字节），
    # 超长原始名会导致浏览器保存失败
    download_name = safe_filename(comic.title + os.path.splitext(comic.filename)[1]) or os.path.basename(file_path)
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

    history = ReadingHistory.query.filter_by(comic_id=comic_id).first()
    last_page = history.last_page if history else 1
    start_param = request.args.get('start', type=int)
    start_page = 1 if start_param == 1 else last_page

    is_new_read = history is None
    if is_new_read:
        history = ReadingHistory(comic_id=comic_id, total_pages=len(pages), read_count=1)
        db.session.add(history)
        db.session.commit()
    else:
        history.read_count += 1
        history.last_read_at = datetime.utcnow()
        db.session.commit()

    if pages and comic.page_count != len(pages):
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
                           next_comic_title=next_comic_title,
                           extraction_api=url_for('api_comics.extraction_status', comic_id=comic_id))


@bp.route('/comic/<int:comic_id>/page/<page_filename>')
def serve_page(comic_id, page_filename):
    page_dir = get_page_dir(comic_id, page_filename)
    if page_dir is None:
        return jsonify({'error': '页面不存在'}), 404
    response = send_from_directory(page_dir, page_filename)
    response.headers['Cache-Control'] = 'public, max-age=86400'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@bp.route('/settings', methods=['GET', 'POST'])
def settings():
    from app.services.settings_service import SettingsService

    if request.method == 'POST':
        data = {key: request.form[key] for key in SettingsService.FIELD_SPECS
                if key in request.form}
        # 表单未提交的字段按声明式默认值补齐
        for key, spec in SettingsService.FIELD_SPECS.items():
            data.setdefault(key, spec[1])
        data['site_name'] = (data.get('site_name') or '').strip() or 'xcomic'

        if data.get('proxy_enabled') == '1' and data.get('proxy_host'):
            try:
                port_val = int(data.get('proxy_port'))
                if port_val < 1 or port_val > 65535:
                    raise ValueError
            except ValueError:
                flash('代理端口必须为1-65535之间的整数', 'error')
                return redirect(request.url)

        error = SettingsService.validate(data)
        if error:
            flash(error, 'error')
            return redirect(request.url)

        SettingsService.save(data)
        flash('设置已保存', 'success')
        return redirect(url_for('main.settings'))

    from app.utils.file_utils import get_dir_size, format_size
    from config import PAGES_DIR, COVERS_DIR
    vals = SettingsService.load_all()
    vals['max_cache_size'] = int(vals.get('max_cache_size') or 0)
    total_comics = Comic.query.count()
    total_size = db.session.query(db.func.sum(Comic.file_size)).scalar() or 0
    pages_cache_size = get_dir_size(PAGES_DIR)
    covers_cache_size = get_dir_size(COVERS_DIR)
    total_cache_size = pages_cache_size + covers_cache_size

    return render_template('settings.html', **vals,
                           total_comics=total_comics, total_size=total_size,
                           pages_cache_size=pages_cache_size,
                           covers_cache_size=covers_cache_size,
                           total_cache_size=total_cache_size,
                           pages_cache_display=format_size(pages_cache_size),
                           covers_cache_display=format_size(covers_cache_size),
                           total_cache_display=format_size(total_cache_size))


@bp.route('/download')
def download_page():
    return render_template('download.html')
