import os
import uuid
import shutil

from app.nfo_parser import generate_nfo
from app.utils.file_utils import safe_filename, resolve_conflict
from config import NFO_DIR, COVERS_DIR


class NfoService:
    @staticmethod
    def save_comic_nfo(comic):
        nfo_content = generate_nfo(comic.to_dict())
        if comic.nfo_file:
            nfo_path = os.path.join(NFO_DIR, comic.nfo_file)
            if os.path.dirname(nfo_path):
                os.makedirs(os.path.dirname(nfo_path), exist_ok=True)
            if os.path.exists(nfo_path):
                with open(nfo_path, 'w', encoding='utf-8') as f:
                    f.write(nfo_content)
                return

        nfo_base = os.path.splitext(os.path.basename(comic.filename))[0] if comic.filename else uuid.uuid4().hex
        nfo_name = f"{nfo_base}.nfo"
        nfo_name = safe_filename(nfo_name)
        if not nfo_name:
            nfo_name = f"{uuid.uuid4().hex}.nfo"

        nfo_subdir = ''
        if comic.filename:
            parent = os.path.dirname(comic.filename)
            if parent:
                nfo_subdir = parent

        target_dir = os.path.join(NFO_DIR, nfo_subdir) if nfo_subdir else NFO_DIR
        nfo_name = resolve_conflict(target_dir, nfo_name)
        nfo_rel = os.path.join(nfo_subdir, nfo_name) if nfo_subdir else nfo_name

        nfo_path = os.path.join(NFO_DIR, nfo_rel)
        if os.path.dirname(nfo_path):
            os.makedirs(os.path.dirname(nfo_path), exist_ok=True)
        with open(nfo_path, 'w', encoding='utf-8') as f:
            f.write(nfo_content)
        comic.nfo_file = nfo_rel.replace('\\', '/')

    @staticmethod
    def save_collection_nfo(col):
        col_safe = safe_filename(col.name) or uuid.uuid4().hex
        nfo_name = f"{col_safe}.nfo"
        nfo_subdir = col_safe
        nfo_target_dir = os.path.join(NFO_DIR, nfo_subdir)
        os.makedirs(nfo_target_dir, exist_ok=True)
        nfo_name = resolve_conflict(nfo_target_dir, nfo_name)
        nfo_rel = os.path.join(nfo_subdir, nfo_name).replace('\\', '/')

        nfo_content = generate_nfo({
            'title': col.name,
            'plot': col.description or '',
            'genre': '',
            'tags': '',
        })

        if col.nfo_file:
            nfo_path = os.path.join(NFO_DIR, col.nfo_file)
            if os.path.dirname(nfo_path):
                os.makedirs(os.path.dirname(nfo_path), exist_ok=True)
            if os.path.exists(nfo_path):
                with open(nfo_path, 'w', encoding='utf-8') as f:
                    f.write(nfo_content)
                return
            col.nfo_file = nfo_rel
        else:
            nfo_path = os.path.join(NFO_DIR, nfo_rel)
            if os.path.dirname(nfo_path):
                os.makedirs(os.path.dirname(nfo_path), exist_ok=True)
            with open(nfo_path, 'w', encoding='utf-8') as f:
                f.write(nfo_content)
            col.nfo_file = nfo_rel

    @staticmethod
    def sync_collection_cover(col):
        from app.models import Comic
        first_comic = Comic.query.filter_by(collection_id=col.id)\
            .order_by(Comic.volume.asc(), Comic.id.asc()).first()
        if first_comic and first_comic.cover:
            old_cover_path = os.path.join(COVERS_DIR, first_comic.cover)
            if os.path.exists(old_cover_path):
                col_safe = safe_filename(col.name)
                if col_safe:
                    if col.cover:
                        old_col_cover = os.path.join(COVERS_DIR, col.cover)
                        if os.path.exists(old_col_cover) and old_col_cover != old_cover_path:
                            os.remove(old_col_cover)
                            old_col_cover_dir = os.path.dirname(old_col_cover)
                            if old_col_cover_dir and old_col_cover_dir != COVERS_DIR and os.path.isdir(old_col_cover_dir) and not os.listdir(old_col_cover_dir):
                                os.rmdir(old_col_cover_dir)

                    cover_subdir = col_safe
                    cover_target_dir = os.path.join(COVERS_DIR, cover_subdir)
                    os.makedirs(cover_target_dir, exist_ok=True)
                    cover_basename = os.path.basename(first_comic.cover)
                    cover_ext = os.path.splitext(cover_basename)[1]
                    cover_name = f"{uuid.uuid4().hex}{cover_ext}"
                    cover_new_name = resolve_conflict(cover_target_dir, cover_name)
                    cover_new_rel = os.path.join(cover_subdir, cover_new_name).replace('\\', '/')
                    cover_new_path = os.path.join(COVERS_DIR, cover_new_rel)
                    shutil.copy2(old_cover_path, cover_new_path)
                    col.cover = cover_new_rel
                else:
                    col.cover = first_comic.cover
            else:
                col.cover = first_comic.cover
        else:
            col.cover = ''
