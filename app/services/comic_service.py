import os
import uuid
import shutil

from app import db
from app.models import Comic, ReadingHistory
from app.nfo_parser import parse_nfo
from app.utils.file_utils import safe_filename, resolve_conflict, get_storage_subdir, move_comic_file, group_tags
from app.services.nfo_service import NfoService
from app.reader import is_readable, cleanup_pages
from config import COMICS_DIR, COVERS_DIR, NFO_DIR


class ComicService:
    @staticmethod
    def delete_comic(comic_id):
        comic = Comic.query.get_or_404(comic_id)

        if comic.filename:
            file_path = os.path.join(COMICS_DIR, comic.filename)
            if os.path.exists(file_path):
                os.remove(file_path)

        if comic.cover:
            cover_path = os.path.join(COVERS_DIR, comic.cover)
            if os.path.exists(cover_path):
                os.remove(cover_path)
                cover_dir = os.path.dirname(cover_path)
                if cover_dir and cover_dir != COVERS_DIR and os.path.isdir(cover_dir) and not os.listdir(cover_dir):
                    os.rmdir(cover_dir)

        if comic.nfo_file:
            nfo_path = os.path.join(NFO_DIR, comic.nfo_file)
            if os.path.exists(nfo_path):
                os.remove(nfo_path)
                nfo_dir = os.path.dirname(nfo_path)
                if nfo_dir and nfo_dir != NFO_DIR and os.path.isdir(nfo_dir) and not os.listdir(nfo_dir):
                    os.rmdir(nfo_dir)

        cleanup_pages(comic_id)

        db.session.delete(comic)
        db.session.commit()
        return True

    @staticmethod
    def update_comic(comic_id, form_data, nfo_file=None, cover_file=None):
        comic = Comic.query.get_or_404(comic_id)

        comic.title = form_data.get('title', comic.title)
        comic.title_jp = form_data.get('title_jp', comic.title_jp)
        comic.author = form_data.get('author', comic.author)
        comic.genre = form_data.get('genre', comic.genre)
        comic.category = form_data.get('category', comic.category)
        comic.date = form_data.get('date', comic.date)
        comic.plot = form_data.get('plot', comic.plot)
        rating_str = form_data.get('rating', '')
        try:
            comic.rating = float(rating_str) if rating_str else 0.0
        except ValueError:
            comic.rating = 0.0
        comic.tags = form_data.get('tags', comic.tags)
        comic.status = form_data.get('status', comic.status)
        comic.publisher = form_data.get('publisher', comic.publisher)
        comic.language = form_data.get('language', comic.language)
        comic.is_translated = form_data.get('is_translated') == 'on'
        comic.uploader = form_data.get('uploader', comic.uploader)
        comic.source_url = form_data.get('source_url', comic.source_url)
        comic.torrent_urls = form_data.get('torrent_urls', comic.torrent_urls)
        comic.volume = form_data.get('volume', comic.volume)
        page_count_str = form_data.get('page_count', '')
        try:
            comic.page_count = int(page_count_str) if page_count_str else 0
        except ValueError:
            comic.page_count = 0
        favorited_str = form_data.get('favorited', '')
        try:
            comic.favorited = int(favorited_str) if favorited_str else 0
        except ValueError:
            comic.favorited = 0
        rating_count_str = form_data.get('rating_count', '')
        try:
            comic.rating_count = int(rating_count_str) if rating_count_str else 0
        except ValueError:
            comic.rating_count = 0

        collection_name = form_data.get('collection_name', '').strip()
        old_collection = comic.collection
        old_collection_name = old_collection.name if old_collection else ''

        if collection_name:
            from app.models import Collection
            col = Collection.query.filter_by(name=collection_name).first()
            if not col:
                col = Collection(name=collection_name)
                db.session.add(col)
                db.session.flush()
            comic.collection_id = col.id
        else:
            comic.collection_id = None

        if old_collection_name != collection_name and comic.filename:
            old_path = os.path.join(COMICS_DIR, comic.filename)
            if os.path.exists(old_path):
                basename = os.path.basename(comic.filename)
                new_subdir = get_storage_subdir(basename, collection_name or None)
                new_rel = os.path.join(new_subdir, basename).replace('\\', '/')
                target_path = os.path.join(COMICS_DIR, new_rel)

                if collection_name and os.path.exists(target_path) and target_path != old_path:
                    collection_name = ''
                    comic.collection_id = None
                    new_subdir = get_storage_subdir(basename, None)
                    new_rel = os.path.join(new_subdir, basename).replace('\\', '/')
                    target_path = os.path.join(COMICS_DIR, new_rel)

                if not collection_name and old_collection_name:
                    default_subdir = get_storage_subdir(basename, None)
                    default_rel = os.path.join(default_subdir, basename).replace('\\', '/')
                    default_target = os.path.join(COMICS_DIR, default_rel)
                    if os.path.exists(default_target) and default_target != old_path:
                        collection_name = old_collection_name
                        from app.models import Collection
                        col = Collection.query.filter_by(name=old_collection_name).first()
                        if col:
                            comic.collection_id = col.id
                        new_subdir = get_storage_subdir(basename, collection_name or None)
                        new_rel = os.path.join(new_subdir, basename).replace('\\', '/')
                        target_path = os.path.join(COMICS_DIR, new_rel)

                if comic.collection_id is not None or not collection_name:
                    if target_path != old_path:
                        new_target_dir = os.path.dirname(target_path)
                        os.makedirs(new_target_dir, exist_ok=True)
                        target_path = move_comic_file(old_path, target_path)
                        comic.filename = os.path.relpath(target_path, COMICS_DIR).replace('\\', '/')

            if comic.nfo_file and (comic.collection_id is not None or not collection_name):
                old_nfo_path = os.path.join(NFO_DIR, comic.nfo_file)
                if os.path.exists(old_nfo_path):
                    nfo_basename = os.path.basename(comic.nfo_file)
                    nfo_subdir = os.path.dirname(comic.filename) if comic.filename else ''
                    nfo_target_dir = os.path.join(NFO_DIR, nfo_subdir) if nfo_subdir else NFO_DIR
                    os.makedirs(nfo_target_dir, exist_ok=True)
                    nfo_new_name = resolve_conflict(nfo_target_dir, nfo_basename)
                    nfo_new_rel = os.path.join(nfo_subdir, nfo_new_name) if nfo_subdir else nfo_new_name
                    nfo_new_path = os.path.join(NFO_DIR, nfo_new_rel)
                    if nfo_new_path != old_nfo_path:
                        shutil.move(old_nfo_path, nfo_new_path)
                        old_nfo_dir = os.path.dirname(old_nfo_path)
                        if old_nfo_dir and old_nfo_dir != NFO_DIR and os.path.isdir(old_nfo_dir) and not os.listdir(old_nfo_dir):
                            os.rmdir(old_nfo_dir)
                        comic.nfo_file = nfo_new_rel.replace('\\', '/')

            if comic.cover and (comic.collection_id is not None or not collection_name):
                old_cover_path = os.path.join(COVERS_DIR, comic.cover)
                if os.path.exists(old_cover_path):
                    cover_basename = os.path.basename(comic.cover)
                    cover_subdir = os.path.dirname(comic.filename) if comic.filename else ''
                    cover_target_dir = os.path.join(COVERS_DIR, cover_subdir) if cover_subdir else COVERS_DIR
                    os.makedirs(cover_target_dir, exist_ok=True)
                    cover_new_name = resolve_conflict(cover_target_dir, cover_basename)
                    cover_new_rel = os.path.join(cover_subdir, cover_new_name) if cover_subdir else cover_new_name
                    cover_new_path = os.path.join(COVERS_DIR, cover_new_rel)
                    if cover_new_path != old_cover_path:
                        shutil.move(old_cover_path, cover_new_path)
                        old_cover_dir = os.path.dirname(old_cover_path)
                        if old_cover_dir and old_cover_dir != COVERS_DIR and os.path.isdir(old_cover_dir) and not os.listdir(old_cover_dir):
                            os.rmdir(old_cover_dir)
                        comic.cover = cover_new_rel.replace('\\', '/')

        if old_collection and old_collection.id != comic.collection_id:
            from app.models import Collection
            remaining = Comic.query.filter_by(collection_id=old_collection.id).count()
            if remaining == 0:
                if old_collection.cover and old_collection.cover == comic.cover:
                    old_collection.cover = ''
                db.session.delete(old_collection)

        if comic.collection:
            NfoService.sync_collection_cover(comic.collection)
            if not comic.collection.nfo_file:
                NfoService.save_collection_nfo(comic.collection)

        if nfo_file and nfo_file.filename != '':
            nfo_content = nfo_file.read().decode('utf-8', errors='ignore')
            nfo_data = parse_nfo(nfo_content)
            for key in ['title', 'title_jp', 'author', 'genre', 'category', 'date', 'plot', 'tags', 'status', 'publisher', 'language', 'uploader', 'source_url', 'torrent_urls']:
                if nfo_data.get(key):
                    setattr(comic, key, nfo_data[key])
            if nfo_data.get('is_translated'):
                comic.is_translated = True
            if nfo_data.get('rating'):
                comic.rating = nfo_data['rating']
            if nfo_data.get('rating_count'):
                comic.rating_count = nfo_data['rating_count']

            if comic.nfo_file:
                old_nfo = os.path.join(NFO_DIR, comic.nfo_file)
                if os.path.exists(old_nfo):
                    os.remove(old_nfo)

            nfo_name = safe_filename(nfo_file.filename)
            if not nfo_name:
                nfo_name = f"{uuid.uuid4().hex}.nfo"
            nfo_subdir = os.path.dirname(comic.filename) if comic.filename else ''
            nfo_target_dir = os.path.join(NFO_DIR, nfo_subdir) if nfo_subdir else NFO_DIR
            os.makedirs(nfo_target_dir, exist_ok=True)
            nfo_name = resolve_conflict(nfo_target_dir, nfo_name)
            nfo_path = os.path.join(nfo_target_dir, nfo_name)
            with open(nfo_path, 'w', encoding='utf-8') as f:
                f.write(nfo_content)
            comic.nfo_file = (os.path.join(nfo_subdir, nfo_name) if nfo_subdir else nfo_name).replace('\\', '/')

        if cover_file and cover_file.filename != '':
            cover_ext = cover_file.filename.rsplit('.', 1)[1].lower()
            cover_name = f"{uuid.uuid4().hex}.{cover_ext}"
            cover_subdir = os.path.dirname(comic.filename) if comic.filename else ''
            cover_target_dir = os.path.join(COVERS_DIR, cover_subdir) if cover_subdir else COVERS_DIR
            os.makedirs(cover_target_dir, exist_ok=True)
            cover_path = os.path.join(cover_target_dir, cover_name)
            cover_file.save(cover_path)
            if comic.cover:
                old_cover = os.path.join(COVERS_DIR, comic.cover)
                if os.path.exists(old_cover):
                    os.remove(old_cover)
                    old_cover_dir = os.path.dirname(old_cover)
                    if old_cover_dir and old_cover_dir != COVERS_DIR and os.path.isdir(old_cover_dir) and not os.listdir(old_cover_dir):
                        os.rmdir(old_cover_dir)
            comic.cover = (os.path.join(cover_subdir, cover_name) if cover_subdir else cover_name).replace('\\', '/')

        NfoService.save_comic_nfo(comic)

        db.session.commit()
        return comic

    @staticmethod
    def toggle_favorite(comic_id):
        comic = Comic.query.get_or_404(comic_id)
        comic.is_favorite = not comic.is_favorite
        db.session.commit()
        return comic.is_favorite

    @staticmethod
    def get_detail(comic_id):
        comic = Comic.query.get_or_404(comic_id)
        readable = is_readable(comic.filename)
        history = ReadingHistory.query.filter_by(comic_id=comic_id).first()
        grouped_tags_result, uncat_tags = group_tags(comic.tags)
        collection_comics = []
        if comic.collection_id:
            collection_comics = Comic.query.filter_by(collection_id=comic.collection_id)\
                .order_by(Comic.volume.asc(), Comic.id.asc()).all()
        return {
            'comic': comic,
            'readable': readable,
            'history': history,
            'grouped_tags': grouped_tags_result,
            'uncat_tags': uncat_tags,
            'collection_comics': collection_comics,
        }
