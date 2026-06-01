import os
import uuid
import shutil
import threading
from datetime import datetime

from flask import Blueprint, request
from app import db
from app.models import ChunkedUpload, Setting
from app.services.upload_service import UploadService, CHUNKS_DIR
from app.utils.file_utils import safe_filename, allowed_file, get_storage_subdir, resolve_conflict
from app.api.utils import success_response, error_response, ErrorCode
from config import COMICS_DIR

bp = Blueprint('api_uploads', __name__, url_prefix='/api/v1/uploads')


@bp.route('/init', methods=['POST'])
def init_upload():
    data = request.get_json(silent=True) or {}
    if not data or not data.get('filename') or data.get('file_size') is None:
        return error_response(ErrorCode.BAD_REQUEST, '缺少文件名或文件大小')

    filename = data['filename']
    file_size = int(data['file_size'])

    if not allowed_file(filename):
        return error_response(ErrorCode.BAD_REQUEST, f'不支持的文件格式：{filename}')

    safe_name = safe_filename(filename)
    if not safe_name:
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'zip'
        safe_name = f"{uuid.uuid4().hex}.{ext}"

    collection_name = data.get('collection_name', '').strip()
    volume = data.get('volume', '').strip()

    storage_subdir = get_storage_subdir(filename, collection_name or None)
    target_dir = os.path.join(COMICS_DIR, storage_subdir)

    rel_path = os.path.join(storage_subdir, safe_name).replace('\\', '/')

    from app.models import Comic
    existing_comic = Comic.query.filter_by(filename=rel_path).first()
    if existing_comic:
        return error_response(ErrorCode.CONFLICT, f'文件已存在：{filename}')

    if os.path.exists(os.path.join(target_dir, safe_name)):
        return error_response(ErrorCode.CONFLICT, f'文件已存在：{filename}')

    default_chunk_size = int(Setting.get('chunk_size', '5')) * 1024 * 1024
    chunk_size = int(data.get('chunk_size', default_chunk_size))
    total_chunks = (file_size + chunk_size - 1) // chunk_size if file_size > 0 else 1

    upload_id = uuid.uuid4().hex

    existing = ChunkedUpload.query.filter_by(
        original_filename=filename, file_size=file_size, status='paused'
    ).first()
    if existing:
        return success_response(data=existing.to_dict())

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

    return success_response(data=cu.to_dict(), message='上传任务已创建')


@bp.route('/chunk', methods=['POST'])
def upload_chunk():
    upload_id = request.form.get('upload_id', '')
    chunk_index = request.form.get('chunk_index', '')

    if not upload_id or chunk_index == '':
        return error_response(ErrorCode.BAD_REQUEST, '缺少upload_id或chunk_index')

    chunk_index = int(chunk_index)
    cu = ChunkedUpload.query.get(upload_id)
    if not cu:
        return error_response(ErrorCode.NOT_FOUND, '上传任务不存在')

    if cu.status == 'cancelled':
        return error_response(ErrorCode.BAD_REQUEST, '上传已取消')

    if cu.status == 'paused':
        cu.status = 'uploading'
        db.session.commit()

    chunk_file = request.files.get('chunk')
    if not chunk_file:
        return error_response(ErrorCode.BAD_REQUEST, '缺少分片数据')

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

    return success_response(data=cu.to_dict())


@bp.route('/complete', methods=['POST'])
def complete_upload():
    data = request.get_json(silent=True) or {}
    upload_id = data.get('upload_id', '')
    cu = ChunkedUpload.query.get(upload_id)
    if not cu:
        return error_response(ErrorCode.NOT_FOUND, '上传任务不存在')

    uploaded = cu.uploaded_chunks
    if len(uploaded) < cu.total_chunks:
        return error_response(ErrorCode.BAD_REQUEST,
                              f'分片不完整：{len(uploaded)}/{cu.total_chunks}')

    cu.status = 'assembling'
    db.session.commit()

    thread = threading.Thread(
        target=UploadService.assemble_chunked_upload,
        args=(upload_id,),
        daemon=True,
    )
    thread.start()

    return success_response(data=cu.to_dict(), message='文件正在合并处理中')


@bp.route('/cancel', methods=['POST'])
def cancel_upload():
    data = request.get_json(silent=True) or {}
    upload_id = data.get('upload_id', '')
    cu = ChunkedUpload.query.get(upload_id)
    if not cu:
        return error_response(ErrorCode.NOT_FOUND, '上传任务不存在')

    cu.status = 'cancelled'
    db.session.commit()

    chunk_dir = os.path.join(CHUNKS_DIR, upload_id)
    if os.path.exists(chunk_dir):
        shutil.rmtree(chunk_dir, ignore_errors=True)

    return success_response(message='上传已取消')


@bp.route('/pause', methods=['POST'])
def pause_upload():
    data = request.get_json(silent=True) or {}
    upload_id = data.get('upload_id', '')
    cu = ChunkedUpload.query.get(upload_id)
    if not cu:
        return error_response(ErrorCode.NOT_FOUND, '上传任务不存在')

    cu.status = 'paused'
    db.session.commit()
    return success_response(data=cu.to_dict())


@bp.route('/<upload_id>/status', methods=['GET'])
def upload_status(upload_id):
    cu = ChunkedUpload.query.get(upload_id)
    if not cu:
        return error_response(ErrorCode.NOT_FOUND, '上传任务不存在')
    return success_response(data=cu.to_dict())


@bp.route('/nfo', methods=['POST'])
def upload_nfo():
    nfo_file = request.files.get('nfo_file')
    if not nfo_file or nfo_file.filename == '':
        return error_response(ErrorCode.BAD_REQUEST, '缺少NFO文件')

    safe = safe_filename(nfo_file.filename) or f'{uuid.uuid4().hex}.nfo'
    nfo_temp_dir = os.path.join(CHUNKS_DIR, '_nfo_temp')
    os.makedirs(nfo_temp_dir, exist_ok=True)
    nfo_id = uuid.uuid4().hex
    nfo_sub_dir = os.path.join(nfo_temp_dir, nfo_id)
    os.makedirs(nfo_sub_dir, exist_ok=True)
    nfo_path = os.path.join(nfo_sub_dir, safe)
    nfo_file.save(nfo_path)

    return success_response(data={
        'nfo_id': nfo_id,
        'nfo_filename': safe,
        'original_name': nfo_file.filename,
    })


@bp.route('/cover', methods=['POST'])
def upload_cover():
    cover_file = request.files.get('cover_file')
    if not cover_file or cover_file.filename == '':
        return error_response(ErrorCode.BAD_REQUEST, '缺少封面文件')

    safe = safe_filename(cover_file.filename) or f'{uuid.uuid4().hex}.jpg'
    cover_temp_dir = os.path.join(CHUNKS_DIR, '_cover_temp')
    os.makedirs(cover_temp_dir, exist_ok=True)
    cover_id = uuid.uuid4().hex
    cover_sub_dir = os.path.join(cover_temp_dir, cover_id)
    os.makedirs(cover_sub_dir, exist_ok=True)
    cover_path = os.path.join(cover_sub_dir, safe)
    cover_file.save(cover_path)

    return success_response(data={
        'cover_id': cover_id,
        'cover_filename': safe,
        'original_name': cover_file.filename,
    })


@bp.route('/tasks', methods=['GET'])
def list_upload_tasks():
    status = request.args.get('status', '').strip()
    query = ChunkedUpload.query
    if status:
        query = query.filter(ChunkedUpload.status == status)
    tasks = query.order_by(ChunkedUpload.created_at.desc()).limit(50).all()
    return success_response(data=[t.to_dict() for t in tasks])
