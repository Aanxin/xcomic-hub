import os
import uuid
import shutil

from app import db
from app.models import Collection, Comic
from app.utils.file_utils import safe_filename, resolve_conflict
from app.services.nfo_service import NfoService
from config import COMICS_DIR, COVERS_DIR, NFO_DIR


class CollectionService:
    @staticmethod
    def toggle_favorite(collection_id):
        col = Collection.query.get_or_404(collection_id)
        col.is_favorite = not col.is_favorite
        db.session.commit()
        return col.is_favorite

    @staticmethod
    def update_collection(collection_id, form_data, cover_file=None):
        col = Collection.query.get_or_404(collection_id)
        new_name = form_data.get('name', '').strip()
        if new_name and new_name != col.name:
            existing = Collection.query.filter_by(name=new_name).first()
            if existing and existing.id != col.id:
                return col, f'合集名称「{new_name}」已存在'

            old_dir_name = safe_filename(col.name)
            new_dir_name = safe_filename(new_name)
            col.name = new_name

            if old_dir_name and new_dir_name and old_dir_name != new_dir_name:
                old_comic_dir = os.path.join(COMICS_DIR, old_dir_name)
                new_comic_dir = os.path.join(COMICS_DIR, new_dir_name)
                if os.path.exists(old_comic_dir) and not os.path.exists(new_comic_dir):
                    shutil.move(old_comic_dir, new_comic_dir)
                    for c in col.comics.all():
                        if c.filename:
                            basename = os.path.basename(c.filename)
                            c.filename = os.path.join(new_dir_name, basename).replace('\\', '/')
                        if c.nfo_file:
                            nfo_basename = os.path.basename(c.nfo_file)
                            old_nfo_dir = os.path.join(NFO_DIR, old_dir_name)
                            new_nfo_dir = os.path.join(NFO_DIR, new_dir_name)
                            if os.path.exists(old_nfo_dir) and not os.path.exists(new_nfo_dir):
                                os.makedirs(new_nfo_dir, exist_ok=True)
                                old_nfo_path = os.path.join(NFO_DIR, c.nfo_file)
                                if os.path.exists(old_nfo_path):
                                    shutil.move(old_nfo_path, os.path.join(new_nfo_dir, nfo_basename))
                                    c.nfo_file = os.path.join(new_dir_name, nfo_basename).replace('\\', '/')
                        if c.cover:
                            cover_basename = os.path.basename(c.cover)
                            old_cover_dir = os.path.join(COVERS_DIR, old_dir_name)
                            new_cover_dir = os.path.join(COVERS_DIR, new_dir_name)
                            if os.path.exists(old_cover_dir) and not os.path.exists(new_cover_dir):
                                os.makedirs(new_cover_dir, exist_ok=True)
                                old_cover_path = os.path.join(COVERS_DIR, c.cover)
                                if os.path.exists(old_cover_path):
                                    shutil.move(old_cover_path, os.path.join(new_cover_dir, cover_basename))
                                    c.cover = os.path.join(new_dir_name, cover_basename).replace('\\', '/')

                old_nfo_dir = os.path.join(NFO_DIR, old_dir_name)
                if os.path.isdir(old_nfo_dir) and not os.listdir(old_nfo_dir):
                    os.rmdir(old_nfo_dir)

                old_cover_dir = os.path.join(COVERS_DIR, old_dir_name)
                if os.path.isdir(old_cover_dir) and not os.listdir(old_cover_dir):
                    os.rmdir(old_cover_dir)

            if col.nfo_file:
                old_nfo_path = os.path.join(NFO_DIR, col.nfo_file)
                if os.path.exists(old_nfo_path):
                    nfo_basename = os.path.basename(col.nfo_file)
                    new_nfo_subdir = new_dir_name
                    new_nfo_target_dir = os.path.join(NFO_DIR, new_nfo_subdir)
                    os.makedirs(new_nfo_target_dir, exist_ok=True)
                    new_nfo_name = f"{safe_filename(new_name) or uuid.uuid4().hex}.nfo"
                    new_nfo_name = resolve_conflict(new_nfo_target_dir, new_nfo_name)
                    new_nfo_path = os.path.join(new_nfo_target_dir, new_nfo_name)
                    if new_nfo_path != old_nfo_path:
                        shutil.move(old_nfo_path, new_nfo_path)
                        old_nfo_parent = os.path.dirname(old_nfo_path)
                        if old_nfo_parent and old_nfo_parent != NFO_DIR and os.path.isdir(old_nfo_parent) and not os.listdir(old_nfo_parent):
                            os.rmdir(old_nfo_parent)
                    col.nfo_file = os.path.join(new_nfo_subdir, new_nfo_name).replace('\\', '/')

            if col.cover:
                old_col_cover_path = os.path.join(COVERS_DIR, col.cover)
                if os.path.exists(old_col_cover_path):
                    cover_basename = os.path.basename(col.cover)
                    new_cover_subdir = new_dir_name
                    new_cover_target_dir = os.path.join(COVERS_DIR, new_cover_subdir)
                    os.makedirs(new_cover_target_dir, exist_ok=True)
                    new_cover_name = resolve_conflict(new_cover_target_dir, cover_basename)
                    new_cover_path = os.path.join(new_cover_target_dir, new_cover_name)
                    if new_cover_path != old_col_cover_path:
                        shutil.move(old_col_cover_path, new_cover_path)
                        old_cover_parent = os.path.dirname(old_col_cover_path)
                        if old_cover_parent and old_cover_parent != COVERS_DIR and os.path.isdir(old_cover_parent) and not os.listdir(old_cover_parent):
                            os.rmdir(old_cover_parent)
                    col.cover = os.path.join(new_cover_subdir, new_cover_name).replace('\\', '/')

        col.description = form_data.get('description', '').strip()

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
                    old_cover_dir = os.path.dirname(old_cover)
                    if old_cover_dir and old_cover_dir != COVERS_DIR and os.path.isdir(old_cover_dir) and not os.listdir(old_cover_dir):
                        os.rmdir(old_cover_dir)
            col.cover = os.path.join(cover_subdir, cover_name).replace('\\', '/')
        else:
            NfoService.sync_collection_cover(col)

        NfoService.save_collection_nfo(col)
        db.session.commit()
        return col, None
