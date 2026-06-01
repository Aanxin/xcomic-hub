import os
import uuid
import shutil
import threading

from datetime import datetime
from app import db
from app.models import Comic, Collection, ChunkedUpload, Setting
from app.nfo_parser import parse_nfo
from app.utils.file_utils import safe_filename, resolve_conflict, get_storage_subdir
from app.services.nfo_service import NfoService
from app.reader import generate_cover_from_archive, generate_cover_from_image
from config import COMICS_DIR, COVERS_DIR, NFO_DIR, DATA_DIR, IMAGE_EXTENSIONS, ARCHIVE_EXTENSIONS

CHUNKS_DIR = os.path.join(DATA_DIR, 'chunks')


class UploadService:
    @staticmethod
    def assemble_chunked_upload(upload_id):
        from app import create_app
        app = create_app()
        with app.app_context():
            cu = ChunkedUpload.query.get(upload_id)
            if not cu:
                return

            try:
                chunk_dir = os.path.join(CHUNKS_DIR, upload_id)
                safe_name = safe_filename(cu.original_filename)
                if not safe_name:
                    ext = cu.original_filename.rsplit('.', 1)[1].lower() if '.' in cu.original_filename else 'zip'
                    safe_name = f"{uuid.uuid4().hex}.{ext}"

                target_dir = COMICS_DIR
                collection_obj = None
                storage_subdir = get_storage_subdir(cu.original_filename, cu.collection_name or None)

                if cu.collection_name:
                    collection_obj = Collection.query.filter_by(name=cu.collection_name).first()
                    if not collection_obj:
                        collection_obj = Collection(name=cu.collection_name)
                        db.session.add(collection_obj)
                        db.session.flush()

                target_dir = os.path.join(COMICS_DIR, storage_subdir)
                os.makedirs(target_dir, exist_ok=True)

                safe_name = resolve_conflict(target_dir, safe_name)
                dst_path = os.path.join(target_dir, safe_name)

                rel_filename = os.path.join(storage_subdir, safe_name).replace('\\', '/')

                with open(dst_path, 'wb') as outf:
                    for i in range(cu.total_chunks):
                        chunk_path = os.path.join(chunk_dir, str(i))
                        if not os.path.exists(chunk_path):
                            raise Exception(f'分片 {i} 不存在')
                        with open(chunk_path, 'rb') as cf:
                            shutil.copyfileobj(cf, outf)

                file_size = os.path.getsize(dst_path)

                comic_base = os.path.splitext(cu.original_filename)[0]
                comic_data = {
                    'title': comic_base,
                    'filename': rel_filename,
                    'file_size': file_size,
                }

                if collection_obj:
                    comic_data['collection_id'] = collection_obj.id
                if cu.volume:
                    comic_data['volume'] = cu.volume

                if cu.nfo_filename:
                    nfo_temp_dir = os.path.join(CHUNKS_DIR, '_nfo_temp')
                    nfo_sub_dirs = []
                    if os.path.exists(nfo_temp_dir):
                        nfo_sub_dirs = os.listdir(nfo_temp_dir)
                    for nfo_id in nfo_sub_dirs:
                        candidate = os.path.join(nfo_temp_dir, nfo_id, cu.nfo_filename)
                        if os.path.exists(candidate):
                            with open(candidate, 'r', encoding='utf-8', errors='ignore') as f:
                                nfo_content = f.read()
                            nfo_data = parse_nfo(nfo_content)
                            if nfo_data.get('title'):
                                comic_data['title'] = nfo_data['title']
                            for key in ['author', 'genre', 'category', 'date', 'plot', 'rating', 'rating_count', 'tags', 'status', 'publisher', 'language', 'uploader', 'source_url', 'torrent_urls']:
                                if nfo_data.get(key):
                                    comic_data[key] = nfo_data[key]
                            if nfo_data.get('is_translated'):
                                comic_data['is_translated'] = True
                            nfo_name = safe_filename(cu.nfo_filename)
                            if not nfo_name:
                                nfo_name = f"{uuid.uuid4().hex}.nfo"
                            nfo_subdir = os.path.dirname(rel_filename) if rel_filename else ''
                            nfo_target_dir = os.path.join(NFO_DIR, nfo_subdir) if nfo_subdir else NFO_DIR
                            os.makedirs(nfo_target_dir, exist_ok=True)
                            nfo_name = resolve_conflict(nfo_target_dir, nfo_name)
                            nfo_dst = os.path.join(nfo_target_dir, nfo_name)
                            shutil.copy2(candidate, nfo_dst)
                            nfo_rel = os.path.join(nfo_subdir, nfo_name) if nfo_subdir else nfo_name
                            comic_data['nfo_file'] = nfo_rel.replace('\\', '/')
                            shutil.rmtree(os.path.join(nfo_temp_dir, nfo_id), ignore_errors=True)
                            break

                if cu.manual_title:
                    comic_data['title'] = cu.manual_title
                if cu.manual_author:
                    comic_data['author'] = cu.manual_author

                if cu.cover_filename:
                    cover_temp_dir = os.path.join(CHUNKS_DIR, '_cover_temp')
                    if os.path.exists(cover_temp_dir):
                        for cover_id in os.listdir(cover_temp_dir):
                            candidate = os.path.join(cover_temp_dir, cover_id, cu.cover_filename)
                            if os.path.exists(candidate):
                                cover_ext = cu.cover_filename.rsplit('.', 1)[1].lower()
                                cover_name = f"{uuid.uuid4().hex}.{cover_ext}"
                                cover_subdir = os.path.dirname(rel_filename) if rel_filename else ''
                                cover_target_dir = os.path.join(COVERS_DIR, cover_subdir) if cover_subdir else COVERS_DIR
                                os.makedirs(cover_target_dir, exist_ok=True)
                                cover_dst = os.path.join(cover_target_dir, cover_name)
                                shutil.copy2(candidate, cover_dst)
                                comic_data['cover'] = (os.path.join(cover_subdir, cover_name) if cover_subdir else cover_name).replace('\\', '/')
                                shutil.rmtree(os.path.join(cover_temp_dir, cover_id), ignore_errors=True)
                                break
                else:
                    auto_cover_enabled = Setting.get('auto_cover', '1') == '1'
                    if auto_cover_enabled:
                        cover_width = int(Setting.get('cover_width', '300'))
                        file_ext = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
                        if file_ext in ARCHIVE_EXTENSIONS:
                            auto_cover = generate_cover_from_archive(dst_path, cover_width)
                            if auto_cover:
                                cover_subdir = os.path.dirname(rel_filename) if rel_filename else ''
                                if cover_subdir:
                                    new_cover_rel = os.path.join(cover_subdir, auto_cover).replace('\\', '/')
                                    old_cover_path = os.path.join(COVERS_DIR, auto_cover)
                                    new_cover_dir = os.path.join(COVERS_DIR, cover_subdir)
                                    os.makedirs(new_cover_dir, exist_ok=True)
                                    new_cover_path = os.path.join(new_cover_dir, auto_cover)
                                    if os.path.exists(old_cover_path) and not os.path.exists(new_cover_path):
                                        shutil.move(old_cover_path, new_cover_path)
                                    auto_cover = new_cover_rel
                                comic_data['cover'] = auto_cover
                        elif file_ext in IMAGE_EXTENSIONS:
                            auto_cover = generate_cover_from_image(dst_path, cover_width)
                            if auto_cover:
                                cover_subdir = os.path.dirname(rel_filename) if rel_filename else ''
                                if cover_subdir:
                                    new_cover_rel = os.path.join(cover_subdir, auto_cover).replace('\\', '/')
                                    old_cover_path = os.path.join(COVERS_DIR, auto_cover)
                                    new_cover_dir = os.path.join(COVERS_DIR, cover_subdir)
                                    os.makedirs(new_cover_dir, exist_ok=True)
                                    new_cover_path = os.path.join(new_cover_dir, auto_cover)
                                    if os.path.exists(old_cover_path) and not os.path.exists(new_cover_path):
                                        shutil.move(old_cover_path, new_cover_path)
                                    auto_cover = new_cover_rel
                                comic_data['cover'] = auto_cover

                comic = Comic(**comic_data)
                db.session.add(comic)
                db.session.flush()
                cu.comic_id = comic.id

                if collection_obj:
                    NfoService.sync_collection_cover(collection_obj)
                    if not collection_obj.nfo_file:
                        NfoService.save_collection_nfo(collection_obj)

                cu.status = 'completed'
                db.session.commit()

            except Exception as e:
                print(f'[上传] 分片合并失败 upload_id={upload_id}: {e}')
                import traceback
                traceback.print_exc()
                cu.status = 'failed'
                cu.error = str(e)
                db.session.commit()

            finally:
                if os.path.exists(chunk_dir):
                    shutil.rmtree(chunk_dir, ignore_errors=True)
