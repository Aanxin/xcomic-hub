from flask import Blueprint, request, send_from_directory, Response
from app import db
from app.models import Collection, Comic, ReadingHistory
from app.services.collection_service import CollectionService
from app.services.nfo_service import NfoService
from app.nfo_parser import generate_nfo
from app.api.utils import success_response, error_response, ErrorCode, paginate_response
from app.api.auth import optional_device
from config import NFO_DIR

bp = Blueprint('api_collections', __name__, url_prefix='/api/v1/collections')


@bp.route('', methods=['GET'])
@optional_device
def list_collections():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '').strip()
    sort = request.args.get('sort', 'updated')
    view_filter = request.args.get('filter', '')

    query = Collection.query

    if search:
        query = query.filter(Collection.name.contains(search))

    if view_filter == 'favorite':
        query = query.filter(Collection.is_favorite == True)

    sort_map = {
        'updated': Collection.updated_at.desc(),
        'created': Collection.created_at.desc(),
        'name': Collection.name.asc(),
    }
    order = sort_map.get(sort, sort_map['updated'])
    query = query.order_by(order)

    result = paginate_response(query, page, per_page, lambda col: col.to_dict())
    return success_response(data=result)


@bp.route('/<int:collection_id>', methods=['GET'])
@optional_device
def get_collection(collection_id):
    col = Collection.query.get(collection_id)
    if not col:
        return error_response(ErrorCode.NOT_FOUND, '合集不存在')
    data = col.to_dict()
    comics = col.comics.all()
    comic_ids = [c.id for c in comics]
    history_map = {}
    if comic_ids:
        histories = ReadingHistory.query.filter(ReadingHistory.comic_id.in_(comic_ids)).all()
        history_map = {h.comic_id: h.to_dict() for h in histories}
    data['comics'] = [c.to_dict() for c in comics]
    for comic_data in data['comics']:
        comic_data['reading_history'] = history_map.get(comic_data['id'])
    return success_response(data=data)


@bp.route('', methods=['POST'])
def create_collection():
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    if not name:
        return error_response(ErrorCode.BAD_REQUEST, '合集名称不能为空')
    existing = Collection.query.filter_by(name=name).first()
    if existing:
        return error_response(ErrorCode.CONFLICT, f'合集名称「{name}」已存在')
    col = Collection(
        name=name,
        description=data.get('description', ''),
    )
    db.session.add(col)
    db.session.commit()
    return success_response(data=col.to_dict(), message='创建成功', status_code=201)


@bp.route('/<int:collection_id>', methods=['PUT'])
def update_collection(collection_id):
    import os
    import uuid
    from config import COVERS_DIR
    from app.utils.file_utils import safe_filename, resolve_conflict

    col = Collection.query.get(collection_id)
    if not col:
        return error_response(ErrorCode.NOT_FOUND, '合集不存在')

    if request.content_type and 'multipart/form-data' in request.content_type:
        form_data = request.form
        cover_file = request.files.get('cover')
    else:
        form_data = request.get_json(silent=True) or {}
        cover_file = None

    new_name = form_data.get('name', '').strip()
    if new_name and new_name != col.name:
        existing = Collection.query.filter_by(name=new_name).first()
        if existing and existing.id != col.id:
            return error_response(ErrorCode.CONFLICT, f'合集名称「{new_name}」已存在')
        col.name = new_name

    description = form_data.get('description', '')
    if description is not None:
        col.description = description.strip() if isinstance(description, str) else ''

    if cover_file and cover_file.filename != '':
        cover_ext = cover_file.filename.rsplit('.', 1)[1].lower()
        cover_name = f"{uuid.uuid4().hex}.{cover_ext}"
        col_safe = safe_filename(col.name) or uuid.uuid4().hex
        cover_subdir = col_safe
        cover_target_dir = os.path.join(COVERS_DIR, cover_subdir)
        os.makedirs(cover_target_dir, exist_ok=True)
        cover_name = resolve_conflict(cover_target_dir, cover_name)
        cover_path = os.path.join(cover_target_dir, cover_name)
        cover_file.save(cover_path)
        if col.cover:
            old_cover = os.path.join(COVERS_DIR, col.cover)
            if os.path.exists(old_cover) and old_cover != cover_path:
                os.remove(old_cover)
        col.cover = os.path.join(cover_subdir, cover_name).replace('\\', '/')

    NfoService.save_collection_nfo(col)
    db.session.commit()
    return success_response(data=col.to_dict(), message='更新成功')


@bp.route('/<int:collection_id>', methods=['DELETE'])
def delete_collection(collection_id):
    col = Collection.query.get(collection_id)
    if not col:
        return error_response(ErrorCode.NOT_FOUND, '合集不存在')
    comics_count = col.comics.count()
    if comics_count > 0:
        return error_response(ErrorCode.CONFLICT, f'合集中还有 {comics_count} 本漫画，请先移除')
    db.session.delete(col)
    db.session.commit()
    return success_response(message='删除成功')


@bp.route('/<int:collection_id>/favorite', methods=['POST'])
def toggle_favorite(collection_id):
    col = Collection.query.get(collection_id)
    if not col:
        return error_response(ErrorCode.NOT_FOUND, '合集不存在')
    favorite = CollectionService.toggle_favorite(collection_id)
    return success_response(data={'is_favorite': favorite})


@bp.route('/<int:collection_id>/nfo', methods=['GET'])
def export_nfo(collection_id):
    import os
    col = Collection.query.get(collection_id)
    if not col:
        return error_response(ErrorCode.NOT_FOUND, '合集不存在')
    NfoService.save_collection_nfo(col)
    db.session.commit()
    if col.nfo_file:
        nfo_path = os.path.join(NFO_DIR, col.nfo_file)
        if os.path.exists(nfo_path):
            nfo_dir = os.path.dirname(nfo_path)
            nfo_base = os.path.basename(nfo_path)
            return send_from_directory(nfo_dir, nfo_base, as_attachment=True,
                                       download_name=f"{col.name}.nfo")
    nfo_content = generate_nfo(col.to_dict())
    return Response(nfo_content, mimetype='application/xml',
                    headers={'Content-Disposition': f'attachment; filename={col.name}.nfo'})


@bp.route('/<int:collection_id>/comics', methods=['GET'])
def list_collection_comics(collection_id):
    col = Collection.query.get(collection_id)
    if not col:
        return error_response(ErrorCode.NOT_FOUND, '合集不存在')
    comics = col.comics.order_by(Comic.volume.asc(), Comic.id.asc()).all()
    comic_ids = [c.id for c in comics]
    history_map = {}
    if comic_ids:
        histories = ReadingHistory.query.filter(ReadingHistory.comic_id.in_(comic_ids)).all()
        history_map = {h.comic_id: h.to_dict() for h in histories}
    result = []
    for c in comics:
        d = c.to_dict()
        d['reading_history'] = history_map.get(c.id)
        result.append(d)
    return success_response(data=result)
