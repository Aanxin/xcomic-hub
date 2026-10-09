from flask import Blueprint

from app import db
from app.models import DownloadTask
from app.services.download_service import DownloadService
from app.api.utils import success_response, error_response, ErrorCode

bp = Blueprint('api_downloads', __name__, url_prefix='/api/v1/downloads')


@bp.route('/tasks', methods=['GET'])
def list_tasks():
    """统一下载列表：合并图片抓取（ScrapeTask）与种子下载（DownloadTask）。

    进行中在前（创建时间倒序），完成/失败在后（更新时间倒序）。
    """
    from app.models import ScrapeTask

    DownloadService.update_download_progress()

    items = []

    scrape_tasks = ScrapeTask.query.order_by(ScrapeTask.created_at.desc()).limit(50).all()
    download_tasks = DownloadTask.query.order_by(DownloadTask.created_at.desc()).limit(50).all()

    # 标题兜底：任务未写入标题（历史任务/详情获取前失败）时用已入库漫画名
    comic_ids = {t.comic_id for t in scrape_tasks + download_tasks if t.comic_id}
    comic_titles = {}
    if comic_ids:
        from app.models import Comic
        comic_titles = {c.id: c.title for c in
                        Comic.query.filter(Comic.id.in_(comic_ids)).all()}

    for t in scrape_tasks:
        pct = round(t.progress / t.total * 100, 1) if t.total else 0.0
        items.append({
            'type': 'scrape',
            'id': t.id,
            'title': t.title or comic_titles.get(t.comic_id) or t.url,
            'url': t.url,
            'source': t.source,
            'status': t.status,
            'message': t.message,
            'progress': t.progress,
            'total': t.total,
            'progress_pct': pct,
            'comic_id': t.comic_id,
            'created_at': t.created_at.isoformat() if t.created_at else None,
            'updated_at': t.updated_at.isoformat() if t.updated_at else None,
        })

    for t in download_tasks:
        items.append({
            'type': 'download',
            'id': t.id,
            'title': t.title or comic_titles.get(t.comic_id) or t.url,
            'url': t.url,
            'status': t.status,
            'message': t.message,
            'qb_state': t.qb_state,
            'progress_pct': t.qb_progress,
            'comic_id': t.comic_id,
            'created_at': t.created_at.isoformat() if t.created_at else None,
            'updated_at': t.updated_at.isoformat() if t.updated_at else None,
        })

    # 稳定排序两步：先各自时间倒序，再按"进行中在前、结束态在后"分组
    items.sort(key=lambda i: (i['updated_at'] or i['created_at'] or ''), reverse=True)
    items.sort(key=lambda i: i['status'] in ('done', 'error', 'failed'))
    return success_response(data={'items': items})


@bp.route('/tasks/<task_type>/<task_id>', methods=['DELETE'])
def delete_unified_task(task_type, task_id):
    """统一下载列表删除：scrape=图片抓取任务，download=种子任务。"""
    from app.models import ScrapeTask

    if task_type == 'scrape':
        task = ScrapeTask.query.get(task_id)
        if not task:
            return error_response(ErrorCode.NOT_FOUND, '抓取任务不存在')
        if task.status in ('pending', 'running'):
            # 取消而非拒绝删除：卡死/误触的任务只能靠重启服务解锁，
            # 队列会被一直占住。标记终态后，运行中的抓取协程会在下一个
            # 进度上报点被终态守卫协作终止（_update_task 抛 TaskCancelled）；
            # 已下载页保留在续传目录，重发同一画廊可续传。
            task.status = 'failed'
            task.message = '已手动取消；重新发起同一画廊可续传'
            db.session.commit()
            return success_response(message='抓取任务已取消')
        db.session.delete(task)
        db.session.commit()
        return success_response(message='抓取任务已删除')

    if task_type == 'download':
        task = DownloadTask.query.get(task_id)
        if not task:
            return error_response(ErrorCode.NOT_FOUND, '下载任务不存在')
        DownloadService.delete_task(task)
        return success_response(message='下载任务已删除')

    return error_response(ErrorCode.BAD_REQUEST, f'未知任务类型: {task_type}')


@bp.route('/<task_id>', methods=['GET'])
def get_task(task_id):
    task = DownloadTask.query.get(task_id)
    if not task:
        return error_response(ErrorCode.NOT_FOUND, '下载任务不存在')
    return success_response(data=task.to_dict())


@bp.route('/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    task = DownloadTask.query.get(task_id)
    if not task:
        return error_response(ErrorCode.NOT_FOUND, '下载任务不存在')
    DownloadService.delete_task(task)
    return success_response(message='下载任务已删除')
