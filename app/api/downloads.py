import os
import uuid
import json

from flask import Blueprint, request
from app import db
from app.models import DownloadTask
from app.services.download_service import DownloadService, get_next_queue_position
from app.utils.file_utils import safe_filename, resolve_conflict
from app.api.utils import success_response, error_response, ErrorCode
from config import DOWNLOAD_DIR

bp = Blueprint('api_downloads', __name__, url_prefix='/api/v1/downloads')


@bp.route('/start', methods=['POST'])
def start_download():
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    if not url:
        return error_response(ErrorCode.BAD_REQUEST, '请输入网址')
    if not url.startswith(('http://', 'https://')):
        return error_response(ErrorCode.BAD_REQUEST, '网址必须以 http:// 或 https:// 开头')

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

    return success_response(data=task.to_dict(), message='下载任务已创建')


@bp.route('/torrent', methods=['POST'])
def upload_torrent():
    torrent_file_obj = request.files.get('torrent_file')
    if not torrent_file_obj or torrent_file_obj.filename == '':
        return error_response(ErrorCode.BAD_REQUEST, '请选择种子文件')

    filename = torrent_file_obj.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext != 'torrent':
        return error_response(ErrorCode.BAD_REQUEST, '仅支持 .torrent 文件')

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

    return success_response(data=task.to_dict(), message='种子文件已上传')


@bp.route('/nfo', methods=['POST'])
def add_nfo_task():
    data = request.get_json(silent=True) or {}
    source_url = data.get('source_url', '').strip()
    title = data.get('title', '').strip()
    if not source_url:
        return error_response(ErrorCode.BAD_REQUEST, 'NFO 数据中缺少 source_url')

    task_id = uuid.uuid4().hex[:8]
    task = DownloadTask(
        id=task_id,
        url=source_url,
        title=title or source_url,
        status='pending',
        message='等待队列中 (NFO)',
        queue='waiting',
        queue_position=get_next_queue_position(),
        nfo_data=json.dumps(data, ensure_ascii=False),
    )
    db.session.add(task)
    db.session.commit()

    return success_response(data=task.to_dict(), message='NFO 任务已添加到队列')


@bp.route('/tasks', methods=['GET'])
def list_tasks():
    DownloadService.update_download_progress()
    waiting = DownloadTask.query.filter_by(queue='waiting')\
        .order_by(DownloadTask.queue_position.asc(), DownloadTask.created_at.asc()).all()
    downloading = DownloadTask.query.filter(
        DownloadTask.queue == 'downloading',
        DownloadTask.status.notin_(['done', 'error'])
    ).order_by(DownloadTask.created_at.desc()).all()
    done = DownloadTask.query.filter(
        DownloadTask.status.in_(['done', 'error'])
    ).order_by(DownloadTask.updated_at.desc()).limit(30).all()
    return success_response(data={
        'waiting': [t.to_dict() for t in waiting],
        'downloading': [t.to_dict() for t in downloading],
        'done': [t.to_dict() for t in done],
    })


@bp.route('/progress', methods=['GET'])
def get_progress():
    DownloadService.update_download_progress()
    tasks = DownloadTask.query.filter(
        DownloadTask.queue == 'downloading',
        DownloadTask.status.in_(['downloading', 'importing', 'matching', 'done', 'error'])
    ).all()
    return success_response(data=[t.to_dict() for t in tasks])


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
