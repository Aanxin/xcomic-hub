from flask import Blueprint
from app import db
from app.models import Comic, Collection, ReadingHistory, DownloadTask, ChunkedUpload, Setting
from app.api.utils import success_response

bp = Blueprint('api_stats', __name__, url_prefix='/api/v1/stats')


@bp.route('', methods=['GET'])
def get_stats():
    total_comics = Comic.query.count()
    total_collections = Collection.query.count()
    total_size = db.session.query(db.func.sum(Comic.file_size)).scalar() or 0
    total_pages = db.session.query(db.func.sum(Comic.page_count)).scalar() or 0
    favorite_comics = Comic.query.filter_by(is_favorite=True).count()
    favorite_collections = Collection.query.filter_by(is_favorite=True).count()

    reading_stats = db.session.query(
        db.func.count(ReadingHistory.id),
        db.func.sum(ReadingHistory.read_count),
    ).first()
    total_reading_records = reading_stats[0] or 0
    total_read_count = reading_stats[1] or 0

    finished_count = 0
    all_histories = ReadingHistory.query.all()
    for h in all_histories:
        if h.total_pages > 0 and h.last_page >= h.total_pages:
            finished_count += 1

    downloading_tasks = DownloadTask.query.filter(
        DownloadTask.status.in_(['downloading', 'importing', 'matching', 'pending'])
    ).count()

    uploading_tasks = ChunkedUpload.query.filter(
        ChunkedUpload.status.in_(['pending', 'uploading', 'assembling'])
    ).count()

    site_name = Setting.get('site_name', 'xcomic')

    return success_response(data={
        'site_name': site_name,
        'comics': {
            'total': total_comics,
            'total_size': total_size,
            'total_pages': total_pages,
            'favorites': favorite_comics,
        },
        'collections': {
            'total': total_collections,
            'favorites': favorite_collections,
        },
        'reading': {
            'total_records': total_reading_records,
            'total_read_count': total_read_count,
            'finished_count': finished_count,
        },
        'tasks': {
            'downloading': downloading_tasks,
            'uploading': uploading_tasks,
        },
    })


@bp.route('/tags', methods=['GET'])
def get_tag_stats():
    from app.utils.file_utils import group_tags
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

    sorted_tags = sorted(tag_count.items(), key=lambda x: x[1], reverse=True)
    return success_response(data=[
        {'tag': tag, 'count': count} for tag, count in sorted_tags[:100]
    ])


@bp.route('/authors', methods=['GET'])
def get_author_stats():
    from sqlalchemy import func
    results = db.session.query(
        Comic.author, func.count(Comic.id)
    ).filter(Comic.author != '').group_by(Comic.author).order_by(
        func.count(Comic.id).desc()
    ).limit(50).all()
    return success_response(data=[
        {'author': author, 'count': count} for author, count in results
    ])
