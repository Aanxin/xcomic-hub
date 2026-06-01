from flask import Blueprint, request, send_from_directory, Response
from app import db
from app.models import Comic, Collection, ReadingHistory, Setting
from app.services.comic_service import ComicService
from app.services.nfo_service import NfoService
from app.reader import get_comic_pages, get_page_dir, is_readable, cleanup_pages
from app.nfo_parser import generate_nfo
from app.utils.file_utils import group_tags
from app.utils.tag_utils import reverse_map_tag
from app.api.utils import success_response, error_response, ErrorCode, paginate_response
from app.api.auth import optional_device
from config import COMICS_DIR, COVERS_DIR, NFO_DIR

bp = Blueprint('api_comics', __name__, url_prefix='/api/v1/comics')


@bp.route('', methods=['GET'])
@optional_device
def list_comics():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '').strip()
    sort = request.args.get('sort', 'updated')
    view_filter = request.args.get('filter', '')
    collection_id = request.args.get('collection_id', None, type=int)

    query = Comic.query

    if collection_id is not None:
        query = query.filter(Comic.collection_id == collection_id)
    elif view_filter == 'standalone':
        query = query.filter(Comic.collection_id.is_(None))

    if search:
        if search.startswith('author:'):
            val = search[7:].strip()
            originals = reverse_map_tag(val)
            conditions = [Comic.author.contains(v) for v in originals]
            query = query.filter(db.or_(*conditions))
        elif search.startswith('genre:'):
            val = search[6:].strip()
            originals = reverse_map_tag(val)
            conditions = [Comic.genre.contains(v) for v in originals]
            query = query.filter(db.or_(*conditions))
        elif search.startswith('tag:'):
            val = search[4:].strip()
            originals = reverse_map_tag(val)
            conditions = [Comic.tags.contains(v) for v in originals]
            query = query.filter(db.or_(*conditions))
        elif search.startswith('category:'):
            val = search[9:].strip()
            query = query.filter(Comic.category.contains(val))
        elif search.startswith('publisher:'):
            val = search[10:].strip()
            query = query.filter(Comic.publisher.contains(val))
        elif search.startswith('language:'):
            val = search[9:].strip()
            query = query.filter(Comic.language.contains(val))
        else:
            originals = reverse_map_tag(search)
            tag_conditions = [Comic.tags.contains(v) for v in originals]
            query = query.filter(
                db.or_(
                    Comic.title.contains(search),
                    Comic.author.contains(search),
                    *tag_conditions,
                    Comic.genre.contains(search),
                )
            )

    if view_filter == 'favorite':
        query = query.filter(Comic.is_favorite == True)

    sort_map = {
        'updated': Comic.updated_at.desc(),
        'created': Comic.created_at.desc(),
        'title': Comic.title.asc(),
        'rating': Comic.rating.desc(),
        'size': Comic.file_size.desc(),
    }
    order = sort_map.get(sort, sort_map['updated'])
    query = query.order_by(order)

    result = paginate_response(query, page, per_page, lambda c: c.to_dict())

    comic_ids = [c.id for c in Comic.query.filter(
        Comic.id.in_([item['id'] for item in result['items']])
    ).all()] if result['items'] else []
    history_map = {}
    if comic_ids:
        histories = ReadingHistory.query.filter(ReadingHistory.comic_id.in_(comic_ids)).all()
        history_map = {h.comic_id: h.to_dict() for h in histories}
    for item in result['items']:
        item['reading_history'] = history_map.get(item['id'])

    return success_response(data=result)


@bp.route('/random', methods=['GET'])
@optional_device
def random_comics():
    count = request.args.get('count', 10, type=int)
    count = min(max(count, 1), 50)
    comics = Comic.query.order_by(db.func.random()).limit(count).all()
    return success_response(data=[c.to_dict() for c in comics])


@bp.route('/<int:comic_id>', methods=['GET'])
@optional_device
def get_comic(comic_id):
    comic = Comic.query.get(comic_id)
    if not comic:
        return error_response(ErrorCode.NOT_FOUND, '漫画不存在')
    data = comic.to_dict()
    data['readable'] = is_readable(comic.filename)
    history = ReadingHistory.query.filter_by(comic_id=comic_id).first()
    data['reading_history'] = history.to_dict() if history else None
    grouped_tags_result, uncat_tags = group_tags(comic.tags)
    data['grouped_tags'] = grouped_tags_result
    data['uncategorized_tags'] = uncat_tags
    if comic.collection_id:
        collection_comics = Comic.query.filter_by(collection_id=comic.collection_id)\
            .order_by(Comic.volume.asc(), Comic.id.asc()).all()
        data['collection_comics'] = [c.to_dict() for c in collection_comics]
    else:
        data['collection_comics'] = []
    return success_response(data=data)


@bp.route('', methods=['POST'])
def create_comic():
    data = request.get_json(silent=True) or {}
    if not data.get('title'):
        return error_response(ErrorCode.BAD_REQUEST, '标题不能为空')
    comic = Comic(
        title=data.get('title', '未命名'),
        title_jp=data.get('title_jp', ''),
        author=data.get('author', ''),
        genre=data.get('genre', ''),
        category=data.get('category', ''),
        date=data.get('date', ''),
        plot=data.get('plot', ''),
        rating=data.get('rating', 0.0),
        tags=data.get('tags', ''),
        status=data.get('status', ''),
        publisher=data.get('publisher', ''),
        language=data.get('language', ''),
        is_translated=data.get('is_translated', False),
        uploader=data.get('uploader', ''),
        source_url=data.get('source_url', ''),
        volume=data.get('volume', ''),
    )
    collection_name = data.get('collection_name', '').strip()
    if collection_name:
        col = Collection.query.filter_by(name=collection_name).first()
        if not col:
            col = Collection(name=collection_name)
            db.session.add(col)
            db.session.flush()
        comic.collection_id = col.id
    db.session.add(comic)
    db.session.commit()
    return success_response(data=comic.to_dict(), message='创建成功', status_code=201)


@bp.route('/<int:comic_id>', methods=['PUT'])
def update_comic(comic_id):
    comic = Comic.query.get(comic_id)
    if not comic:
        return error_response(ErrorCode.NOT_FOUND, '漫画不存在')
    data = request.get_json(silent=True) or {}
    if not data:
        return error_response(ErrorCode.BAD_REQUEST, '无效数据')
    for key in ['title', 'title_jp', 'author', 'genre', 'category', 'date', 'plot',
                'tags', 'status', 'publisher', 'language', 'uploader', 'source_url',
                'torrent_urls', 'volume']:
        if key in data:
            setattr(comic, key, data[key])
    if 'is_translated' in data:
        comic.is_translated = bool(data['is_translated'])
    if 'rating' in data:
        try:
            comic.rating = float(data['rating'])
        except (ValueError, TypeError):
            comic.rating = 0.0
    if 'page_count' in data:
        try:
            comic.page_count = int(data['page_count'])
        except (ValueError, TypeError):
            comic.page_count = 0
    collection_name = data.get('collection_name', '').strip()
    if collection_name:
        col = Collection.query.filter_by(name=collection_name).first()
        if not col:
            col = Collection(name=collection_name)
            db.session.add(col)
            db.session.flush()
        comic.collection_id = col.id
    elif 'collection_name' in data:
        comic.collection_id = None
    try:
        NfoService.save_comic_nfo(comic)
    except Exception:
        pass
    db.session.commit()
    return success_response(data=comic.to_dict(), message='更新成功')


@bp.route('/<int:comic_id>', methods=['DELETE'])
def delete_comic(comic_id):
    comic = Comic.query.get(comic_id)
    if not comic:
        return error_response(ErrorCode.NOT_FOUND, '漫画不存在')
    ComicService.delete_comic(comic_id)
    return success_response(message='删除成功')


@bp.route('/<int:comic_id>/favorite', methods=['POST'])
def toggle_favorite(comic_id):
    comic = Comic.query.get(comic_id)
    if not comic:
        return error_response(ErrorCode.NOT_FOUND, '漫画不存在')
    favorite = ComicService.toggle_favorite(comic_id)
    return success_response(data={'is_favorite': favorite})


@bp.route('/<int:comic_id>/pages', methods=['GET'])
def get_pages(comic_id):
    comic = Comic.query.get(comic_id)
    if not comic:
        return error_response(ErrorCode.NOT_FOUND, '漫画不存在')
    pages = get_comic_pages(comic_id, comic.filename)
    if not pages:
        return error_response(ErrorCode.NOT_FOUND, '无法读取漫画页面')
    history = ReadingHistory.query.filter_by(comic_id=comic_id).first()
    last_page = history.last_page if history else 1
    return success_response(data={
        'comic_id': comic_id,
        'pages': pages,
        'total_pages': len(pages),
        'last_page': last_page,
    })


@bp.route('/<int:comic_id>/page/<page_filename>', methods=['GET'])
def serve_page(comic_id, page_filename):
    page_dir = get_page_dir(comic_id, page_filename)
    if page_dir is None:
        return error_response(ErrorCode.NOT_FOUND, '页面不存在')
    response = send_from_directory(page_dir, page_filename)
    response.headers['Cache-Control'] = 'public, max-age=86400'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@bp.route('/<int:comic_id>/progress', methods=['GET'])
def get_progress(comic_id):
    comic = Comic.query.get(comic_id)
    if not comic:
        return error_response(ErrorCode.NOT_FOUND, '漫画不存在')
    history = ReadingHistory.query.filter_by(comic_id=comic_id).first()
    if not history:
        return success_response(data={
            'comic_id': comic_id,
            'last_page': 1,
            'total_pages': 0,
            'read_count': 0,
            'last_read_at': None,
        })
    return success_response(data=history.to_dict())


@bp.route('/<int:comic_id>/progress', methods=['POST'])
def update_progress(comic_id):
    from datetime import datetime
    comic = Comic.query.get(comic_id)
    if not comic:
        return error_response(ErrorCode.NOT_FOUND, '漫画不存在')
    data = request.get_json(silent=True) or {}
    last_page = data.get('last_page')
    total_pages = data.get('total_pages')
    history = ReadingHistory.query.filter_by(comic_id=comic_id).first()
    if not history:
        history = ReadingHistory(comic_id=comic_id, read_count=1)
        db.session.add(history)
    if last_page is not None:
        history.last_page = max(1, int(last_page))
    if total_pages is not None:
        history.total_pages = max(0, int(total_pages))
    history.last_read_at = datetime.utcnow()
    db.session.commit()
    return success_response(data=history.to_dict())


@bp.route('/<int:comic_id>/download', methods=['GET'])
def download_comic(comic_id):
    import os
    comic = Comic.query.get(comic_id)
    if not comic:
        return error_response(ErrorCode.NOT_FOUND, '漫画不存在')
    if not comic.filename:
        return error_response(ErrorCode.NOT_FOUND, '文件不存在')
    file_path = os.path.join(COMICS_DIR, comic.filename)
    if not os.path.exists(file_path):
        return error_response(ErrorCode.NOT_FOUND, '文件不存在')
    download_name = comic.title + os.path.splitext(comic.filename)[1]
    return send_from_directory(os.path.dirname(file_path), os.path.basename(file_path),
                               as_attachment=True, download_name=download_name)


@bp.route('/<int:comic_id>/nfo', methods=['GET'])
def export_nfo(comic_id):
    import os
    comic = Comic.query.get(comic_id)
    if not comic:
        return error_response(ErrorCode.NOT_FOUND, '漫画不存在')
    NfoService.save_comic_nfo(comic)
    db.session.commit()
    if comic.nfo_file:
        nfo_path = os.path.join(NFO_DIR, comic.nfo_file)
        if os.path.exists(nfo_path):
            nfo_dir = os.path.dirname(nfo_path)
            nfo_base = os.path.basename(nfo_path)
            return send_from_directory(nfo_dir, nfo_base, as_attachment=True,
                                       download_name=f"{comic.title}.nfo")
    nfo_content = generate_nfo(comic.to_dict())
    return Response(nfo_content, mimetype='application/xml',
                    headers={'Content-Disposition': f'attachment; filename={comic.title}.nfo'})


@bp.route('/<int:comic_id>/cover', methods=['PUT'])
def update_cover(comic_id):
    import os
    import uuid
    from config import COVERS_DIR
    comic = Comic.query.get(comic_id)
    if not comic:
        return error_response(ErrorCode.NOT_FOUND, '漫画不存在')
    cover_file = request.files.get('cover')
    if not cover_file or cover_file.filename == '':
        return error_response(ErrorCode.BAD_REQUEST, '缺少封面文件')
    cover_ext = cover_file.filename.rsplit('.', 1)[1].lower()
    cover_name = f"{uuid.uuid4().hex}.{cover_ext}"
    cover_subdir = os.path.dirname(comic.filename) if comic.filename else ''
    cover_target_dir = os.path.join(COVERS_DIR, cover_subdir) if cover_subdir else COVERS_DIR
    os.makedirs(cover_target_dir, exist_ok=True)
    cover_path = os.path.join(cover_target_dir, cover_name)
    cover_file.save(cover_path)
    if comic.cover:
        old_cover = os.path.join(COVERS_DIR, comic.cover)
        if os.path.exists(old_cover):
            os.remove(old_cover)
    comic.cover = (os.path.join(cover_subdir, cover_name) if cover_subdir else cover_name).replace('\\', '/')
    db.session.commit()
    return success_response(data=comic.to_dict(), message='封面更新成功')


@bp.route('/batch/replace-tag', methods=['POST'])
def batch_replace_tag():
    data = request.get_json(silent=True) or {}
    old_tag = data.get('old_tag', '').strip()
    new_tag = data.get('new_tag', '').strip()

    if not old_tag:
        return error_response(ErrorCode.BAD_REQUEST, '原标签不能为空')
    if not new_tag:
        return error_response(ErrorCode.BAD_REQUEST, '新标签不能为空')
    if old_tag.lower() == new_tag.lower():
        return error_response(ErrorCode.BAD_REQUEST, '原标签和新标签相同，无需替换')

    old_candidates = [old_tag.lower()]
    reversed_tags = reverse_map_tag(old_tag)
    for rt in reversed_tags:
        if rt.lower() not in old_candidates:
            old_candidates.append(rt.lower())

    conditions = []
    for cand in old_candidates:
        conditions.append(db.func.lower(Comic.tags).contains(cand))
    comics = Comic.query.filter(db.or_(*conditions)).all()

    updated_count = 0
    for comic in comics:
        tag_list = [t.strip() for t in comic.tags.split(',') if t.strip()]
        new_tags = []
        changed = False
        for tag in tag_list:
            if tag.lower() in old_candidates:
                new_tags.append(new_tag)
                changed = True
            else:
                new_tags.append(tag)
        if changed:
            comic.tags = ','.join(new_tags)
            updated_count += 1

    if updated_count > 0:
        db.session.commit()

    return success_response(data={
        'updated_count': updated_count,
        'total_matched': len(comics),
        'old_tag': old_tag,
        'new_tag': new_tag,
    }, message=f'已将 {updated_count} 个漫画中的标签「{old_tag}」替换为「{new_tag}」')


def _normalize_title(title):
    import re
    if not title:
        return ''
    t = title.lower()
    t = re.sub(r'\s+', '', t)
    t = re.sub(r'[^\w\s\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', '', t)
    return t


@bp.route('/check-titles', methods=['POST', 'OPTIONS'])
def check_titles():
    if request.method == 'OPTIONS':
        return success_response(data={})
    data = request.get_json(silent=True) or {}
    titles = data.get('titles', [])
    if not titles or not isinstance(titles, list):
        return error_response(ErrorCode.BAD_REQUEST, 'titles 必须为非空数组')

    all_comics = Comic.query.with_entities(Comic.title, Comic.title_jp).all()
    db_pairs = []
    for c in all_comics:
        if c[0]:
            db_pairs.append((_normalize_title(c[0]), c[0]))
        if c[1]:
            db_pairs.append((_normalize_title(c[1]), c[1]))

    matches = {}
    for title in titles:
        norm = _normalize_title(title)
        if not norm or len(norm) < 2:
            continue
        best = None
        best_len = 0
        for db_norm, db_title in db_pairs:
            if norm == db_norm:
                best = db_title
                best_len = len(db_norm)
                break
            if len(norm) >= 4 and (norm in db_norm or db_norm in norm):
                if len(db_norm) > best_len:
                    best = db_title
                    best_len = len(db_norm)
        if best:
            matches[norm] = best

    return success_response(data={'matches': matches})
