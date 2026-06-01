from flask import Blueprint, request
from app import db
from app.models import ReadingHistory, Comic
from app.api.utils import success_response, error_response, ErrorCode, paginate_response
from app.api.auth import optional_device

bp = Blueprint('api_history', __name__, url_prefix='/api/v1/history')


@bp.route('', methods=['GET'])
@optional_device
def list_history():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    sort = request.args.get('sort', 'last_read')

    query = ReadingHistory.query

    sort_map = {
        'last_read': ReadingHistory.last_read_at.desc(),
        'read_count': ReadingHistory.read_count.desc(),
        'progress': ReadingHistory.last_page.desc(),
    }
    order = sort_map.get(sort, sort_map['last_read'])
    query = query.order_by(order)

    result = paginate_response(query, page, per_page)

    enriched_items = []
    for item_dict in result['items']:
        comic = Comic.query.get(item_dict.get('comic_id'))
        if comic:
            item_dict['comic'] = comic.to_dict()
        enriched_items.append(item_dict)
    result['items'] = enriched_items

    return success_response(data=result)


@bp.route('/<int:comic_id>', methods=['GET'])
def get_history(comic_id):
    history = ReadingHistory.query.filter_by(comic_id=comic_id).first()
    if not history:
        return success_response(data={
            'comic_id': comic_id,
            'last_page': 1,
            'total_pages': 0,
            'read_count': 0,
            'last_read_at': None,
        })
    data = history.to_dict()
    comic = Comic.query.get(comic_id)
    if comic:
        data['comic'] = comic.to_dict()
    return success_response(data=data)


@bp.route('/<int:comic_id>', methods=['DELETE'])
def delete_history(comic_id):
    history = ReadingHistory.query.filter_by(comic_id=comic_id).first()
    if not history:
        return error_response(ErrorCode.NOT_FOUND, '阅读记录不存在')
    db.session.delete(history)
    db.session.commit()
    return success_response(message='阅读记录已删除')


@bp.route('/clear', methods=['POST'])
def clear_history():
    ReadingHistory.query.delete()
    db.session.commit()
    return success_response(message='所有阅读记录已清除')


@bp.route('/recent', methods=['GET'])
@optional_device
def recent_reads():
    count = request.args.get('count', 10, type=int)
    count = min(max(count, 1), 50)
    histories = ReadingHistory.query.order_by(
        ReadingHistory.last_read_at.desc()
    ).limit(count).all()

    result = []
    for h in histories:
        data = h.to_dict()
        comic = Comic.query.get(h.comic_id)
        if comic:
            data['comic'] = comic.to_dict()
        result.append(data)
    return success_response(data=result)
