import os
import json

from app import db
from app.models import Comic, Setting
from app.nfo_parser import parse_nfo
from app.services.matching_service import fuzzy_match_score
from config import DOWNLOAD_DIR


class ComicImportService:

    def __init__(self, file_service=None, duplication_checker=None, matching_service=None,
                 torrent_service=None, task_service=None):
        if file_service is None:
            from app.services.file_operation_service import FileOperationService
            file_service = FileOperationService()
        if duplication_checker is None:
            from app.services.duplication_checker import DuplicationChecker
            duplication_checker = DuplicationChecker()
        if matching_service is None:
            from app.services.matching_service import MatchingService
            matching_service = MatchingService()
        if torrent_service is None:
            from app.services.torrent_service import TorrentService
            torrent_service = TorrentService()
        if task_service is None:
            from app.services.task_service import TaskService
            task_service = TaskService()
        self.file_service = file_service
        self.duplication_checker = duplication_checker
        self.matching_service = matching_service
        self.torrent_service = torrent_service
        self.task_service = task_service

    def import_downloaded_comic(self, task):
        if not task.title or not task.nfo_path:
            raise Exception('缺少标题或NFO路径，无法导入')

        nfo_data = self._load_nfo_data(task.nfo_path)
        import_title = nfo_data.get('title') or task.title
        import_source_url = nfo_data.get('source_url') or task.url or ''

        existing = self._check_existing_comic(import_title, import_source_url)
        if existing:
            self._handle_existing(task, existing)
            return

        comic_file, comic_fname, comic_file_score = self._locate_comic_file(task, nfo_data)
        if not comic_file or not os.path.exists(comic_file):
            raise Exception(f'未找到漫画文件: {task.title}')

        if comic_file_score < 50:
            raise Exception(f'文件匹配度过低({comic_file_score})，跳过: {comic_fname}')

        ext = os.path.splitext(comic_fname)[1].lower().lstrip('.')
        file_size = os.path.getsize(comic_file)
        if file_size == 0:
            raise Exception('文件大小为0，可能下载不完整')

        self.file_service.validate_comic_file(comic_file)

        dst_path, rel_filename, dst_size, ext = self.file_service.copy_to_comics_dir(comic_file, comic_fname)

        existing_by_file = self.duplication_checker.check_duplicate_by_filename(rel_filename)
        if existing_by_file:
            if os.path.exists(dst_path):
                os.remove(dst_path)
            self.task_service.set_task_comic_id(task.id, existing_by_file.id)
            self.task_service.mark_task_done(task.id, f'漫画文件已存在: {existing_by_file.title} (ID: {existing_by_file.id})')
            return

        comic_data = self._prepare_comic_data(task, nfo_data, comic_fname, rel_filename, dst_size)

        storage_subdir = os.path.dirname(rel_filename)
        nfo_rel = self.file_service.copy_nfo_file(task.nfo_path, storage_subdir)

        if nfo_rel:
            comic_data['nfo_file'] = nfo_rel

        cover_path = self.file_service.generate_cover(dst_path, ext, task.id, storage_subdir)
        if cover_path:
            comic_data['cover'] = cover_path

        comic = Comic(**comic_data)
        db.session.add(comic)
        db.session.flush()

        self.task_service.set_task_comic_id(task.id, comic.id)
        self.task_service.mark_task_done(task.id, '下载完成并已导入')

    def _load_nfo_data(self, nfo_path):
        if os.path.exists(nfo_path):
            with open(nfo_path, 'r', encoding='utf-8', errors='ignore') as f:
                nfo_content = f.read()
            return parse_nfo(nfo_content) or {}
        return {}

    def _check_existing_comic(self, title, source_url):
        existing = self.duplication_checker.check_duplicate_by_source_url(source_url)
        if existing:
            return existing
        if title:
            return self.duplication_checker.check_duplicate_by_title(title)
        return None

    def _handle_existing(self, task, existing):
        self.task_service.set_task_comic_id(task.id, existing.id)
        self.task_service.mark_task_done(task.id, f'漫画已存在: {existing.title} (ID: {existing.id})')

    def _locate_comic_file(self, task, nfo_data):
        comic_file = None
        comic_fname = None
        comic_file_score = 0
        qb_torrent_name = ''

        if task.qb_info_hash:
            torrent_info, details = self.torrent_service.get_torrent_info_by_hash(task.qb_info_hash)
            if details:
                content_path = details['content_path']
                save_path = details['save_path']
                qb_torrent_name = details['name']

                if content_path and os.path.exists(content_path):
                    if os.path.isfile(content_path):
                        comic_file = content_path
                        comic_fname = os.path.basename(content_path)
                        comic_file_score = 100
                    elif os.path.isdir(content_path):
                        comic_file, comic_fname = self.matching_service.find_comic_in_dir(
                            content_path, task.title, nfo_data)
                        if comic_file:
                            comic_file_score = 90
                        if not comic_file:
                            zip_path = self.file_service.pack_images_to_zip(
                                content_path, qb_torrent_name or task.title)
                            if zip_path:
                                comic_file = zip_path
                                comic_fname = os.path.basename(zip_path)
                                comic_file_score = 85
                elif save_path and qb_torrent_name:
                    candidate = os.path.join(save_path, qb_torrent_name)
                    if os.path.isfile(candidate):
                        comic_file = candidate
                        comic_fname = qb_torrent_name
                        comic_file_score = 90
                    elif os.path.isdir(candidate):
                        comic_file, comic_fname = self.matching_service.find_comic_in_dir(
                            candidate, task.title, nfo_data)
                        if comic_file:
                            comic_file_score = 80
                        if not comic_file:
                            zip_path = self.file_service.pack_images_to_zip(
                                candidate, qb_torrent_name or task.title)
                            if zip_path:
                                comic_file = zip_path
                                comic_fname = os.path.basename(zip_path)
                                comic_file_score = 75

        if not comic_file and qb_torrent_name:
            download_dir = DOWNLOAD_DIR
            candidate = os.path.join(download_dir, qb_torrent_name)
            if os.path.isfile(candidate):
                comic_file = candidate
                comic_fname = qb_torrent_name
                comic_file_score = 90

        if not comic_file:
            download_dir = DOWNLOAD_DIR
            if os.path.isdir(download_dir):
                comic_file, comic_fname, comic_file_score = self.matching_service.find_comic_in_download_dir(
                    download_dir, task.title, nfo_data, task.qb_info_hash)

        return comic_file, comic_fname, comic_file_score

    def _prepare_comic_data(self, task, nfo_data, comic_fname, rel_filename, file_size):
        comic_base = os.path.splitext(comic_fname)[0]
        comic_data = {
            'title': nfo_data.get('title') or comic_base,
            'filename': rel_filename,
            'file_size': file_size,
        }

        for key in ['author', 'genre', 'category', 'date', 'plot', 'rating', 'rating_count',
                     'tags', 'status', 'publisher', 'language', 'uploader', 'source_url', 'torrent_urls']:
            if nfo_data.get(key):
                comic_data[key] = nfo_data[key]
        if nfo_data.get('is_translated'):
            comic_data['is_translated'] = True
        if nfo_data.get('title_jp'):
            comic_data['title_jp'] = nfo_data['title_jp']
        if nfo_data.get('page_count'):
            comic_data['page_count'] = nfo_data['page_count']
        if nfo_data.get('favorited'):
            comic_data['favorited'] = nfo_data['favorited']

        return comic_data