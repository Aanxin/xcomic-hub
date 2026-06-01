from flask import Blueprint, request
from app import db
from app.models import Comic, Setting
from app.utils.file_utils import group_tags
from app.utils.tag_utils import get_tag_mapping, map_tag, reverse_map_tag
from app.api.utils import success_response, error_response, ErrorCode

bp = Blueprint('api_tags', __name__, url_prefix='/api/v1/tags')


@bp.route('', methods=['GET'])
def list_tags():
    category = request.args.get('category', '').strip()
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)

    comics = Comic.query.filter(Comic.tags != '').all()
    tag_count = {}

    for comic in comics:
        if not comic.tags:
            continue
        grouped, uncat = group_tags(comic.tags)
        for cat, tags in grouped.items():
            for tag in tags:
                key = f"{cat}:{tag}"
                tag_count[key] = tag_count.get(key, 0) + 1
        for tag in uncat:
            tag_count[tag] = tag_count.get(tag, 0) + 1

    results = []
    for tag_str, count in tag_count.items():
        cat = ''
        val = tag_str
        if ':' in tag_str:
            parts = tag_str.split(':', 1)
            cat = parts[0]
            val = parts[1]

        if category and cat.lower() != category.lower():
            continue
        if search:
            if search.lower() not in tag_str.lower() and search.lower() not in map_tag(tag_str).lower():
                continue

        display_name = map_tag(tag_str)
        display_cat = map_tag(cat) if cat else ''
        display_val = map_tag(val)
        results.append({
            'tag': display_name,
            'raw_tag': tag_str,
            'category': display_cat or cat,
            'raw_category': cat,
            'value': display_val,
            'raw_value': val,
            'count': count,
        })

    results.sort(key=lambda x: x['count'], reverse=True)

    total = len(results)
    start = (page - 1) * per_page
    end = start + per_page
    paged = results[start:end]

    return success_response(data={
        'items': paged,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'pages': (total + per_page - 1) // per_page,
        }
    })


@bp.route('/categories', methods=['GET'])
def list_categories():
    comics = Comic.query.filter(Comic.tags != '').all()
    cat_count = {}

    for comic in comics:
        if not comic.tags:
            continue
        grouped, uncat = group_tags(comic.tags)
        for cat, tags in grouped.items():
            if cat not in cat_count:
                cat_count[cat] = {'tag_count': 0, 'comic_count': 0}
            cat_count[cat]['tag_count'] += len(tags)
            cat_count[cat]['comic_count'] += 1
        if uncat:
            if '' not in cat_count:
                cat_count[''] = {'tag_count': 0, 'comic_count': 0}
            cat_count['']['tag_count'] += len(uncat)
            cat_count['']['comic_count'] += 1

    results = []
    for cat, info in cat_count.items():
        display_cat = map_tag(cat) if cat else '(未分类)'
        results.append({
            'category': display_cat,
            'raw_category': cat,
            'tag_count': info['tag_count'],
            'comic_count': info['comic_count'],
        })
    results.sort(key=lambda x: x['tag_count'], reverse=True)

    return success_response(data=results)


@bp.route('/mapping', methods=['GET'])
def get_mapping():
    mapping = get_tag_mapping()
    items = []
    for original, display in mapping.items():
        items.append({
            'original': original,
            'display': display,
        })
    return success_response(data=items)


@bp.route('/mapping', methods=['PUT'])
def update_mapping():
    data = request.get_json(silent=True) or {}
    if not data or 'mappings' not in data:
        return error_response(ErrorCode.BAD_REQUEST, '缺少mappings字段')

    mappings = data['mappings']
    if not isinstance(mappings, list):
        return error_response(ErrorCode.BAD_REQUEST, 'mappings必须为数组')

    lines = []
    for item in mappings:
        if isinstance(item, dict):
            original = item.get('original', '').strip()
            display = item.get('display', '').strip()
            if original and display:
                lines.append(f"{original}={display}")
        elif isinstance(item, str):
            if '=' in item:
                lines.append(item.strip())

    Setting.set('tag_mapping', '\n'.join(lines))
    db.session.commit()

    return success_response(data=get_tag_mapping(), message='标签映射已更新')


@bp.route('/mapping', methods=['POST'])
def add_mapping():
    data = request.get_json(silent=True) or {}
    original = data.get('original', '').strip()
    display = data.get('display', '').strip()

    if not original or not display:
        return error_response(ErrorCode.BAD_REQUEST, 'original和display不能为空')

    mapping = get_tag_mapping()
    mapping[original.lower()] = display

    lines = [f"{k}={v}" for k, v in mapping.items()]
    Setting.set('tag_mapping', '\n'.join(lines))
    db.session.commit()

    return success_response(data={
        'original': original,
        'display': display,
    }, message='标签映射已添加')


@bp.route('/mapping/<original>', methods=['DELETE'])
def delete_mapping(original):
    original = original.strip().lower()
    mapping = get_tag_mapping()

    if original not in mapping:
        return error_response(ErrorCode.NOT_FOUND, '映射规则不存在')

    del mapping[original]
    lines = [f"{k}={v}" for k, v in mapping.items()]
    Setting.set('tag_mapping', '\n'.join(lines))
    db.session.commit()

    return success_response(message='标签映射已删除')


@bp.route('/search', methods=['GET'])
def search_tags():
    q = request.args.get('q', '').strip()
    limit = request.args.get('limit', 20, type=int)
    limit = min(max(limit, 1), 100)

    comics = Comic.query.filter(Comic.tags != '').all()
    tag_count = {}

    for comic in comics:
        if not comic.tags:
            continue
        grouped, uncat = group_tags(comic.tags)
        for cat, tags in grouped.items():
            for tag in tags:
                key = f"{cat}:{tag}"
                tag_count[key] = tag_count.get(key, 0) + 1
        for tag in uncat:
            tag_count[tag] = tag_count.get(tag, 0) + 1

    results = []
    q_lower = q.lower() if q else ''
    for tag_str, count in tag_count.items():
        if q and q_lower not in tag_str.lower() and q_lower not in map_tag(tag_str).lower():
            continue
        display = map_tag(tag_str)
        results.append({
            'tag': display,
            'raw_tag': tag_str,
            'count': count,
        })

    results.sort(key=lambda x: x['count'], reverse=True)
    return success_response(data=results[:limit])


@bp.route('/<tag_path>/comics', methods=['GET'])
def get_tag_comics(tag_path):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    originals = reverse_map_tag(tag_path)
    conditions = [Comic.tags.contains(v) for v in originals]
    query = Comic.query.filter(db.or_(*conditions))

    if ':' in tag_path:
        cat, val = tag_path.split(':', 1)
        originals2 = reverse_map_tag(val)
        cat_conditions = [Comic.tags.contains(f"{cat}:{v}") for v in originals2]
        query = Comic.query.filter(db.or_(*cat_conditions))

    query = query.order_by(Comic.updated_at.desc())
    total = query.count()
    comics = query.offset((page - 1) * per_page).limit(per_page).all()

    return success_response(data={
        'items': [c.to_dict() for c in comics],
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'pages': (total + per_page - 1) // per_page,
        }
    })
