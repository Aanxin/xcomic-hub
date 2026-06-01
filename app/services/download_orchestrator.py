import os
import json
import traceback

from app import db
from app.nfo_parser import generate_nfo
from app.utils.file_utils import safe_filename
from config import DOWNLOAD_DIR


class DownloadOrchestrator:

    def __init__(self, task_service=None, scraping_service=None, torrent_service=None,
                 duplication_checker=None, matching_service=None, file_service=None,
                 comic_import_service=None, progress_tracker=None):
        if task_service is None:
            from app.services.task_service import TaskService
            task_service = TaskService()
        if scraping_service is None:
            from app.services.scraping_service import ScrapingService
            scraping_service = ScrapingService()
        if torrent_service is None:
            from app.services.torrent_service import TorrentService
            torrent_service = TorrentService()
        if duplication_checker is None:
            from app.services.duplication_checker import DuplicationChecker
            duplication_checker = DuplicationChecker()
        if matching_service is None:
            from app.services.matching_service import MatchingService
            matching_service = MatchingService()
        if file_service is None:
            from app.services.file_operation_service import FileOperationService
            file_service = FileOperationService()
        if comic_import_service is None:
            from app.services.comic_import_service import ComicImportService
            comic_import_service = ComicImportService()
        if progress_tracker is None:
            from app.services.progress_tracker import ProgressTracker
            progress_tracker = ProgressTracker()
        self.task_service = task_service
        self.scraping_service = scraping_service
        self.torrent_service = torrent_service
        self.duplication_checker = duplication_checker
        self.matching_service = matching_service
        self.file_service = file_service
        self.comic_import_service = comic_import_service
        self.progress_tracker = progress_tracker

    def run_add_task(self, task_id):
        task = self.task_service.get_task(task_id)
        if not task:
            return

        try:
            self._validate_input(task)
            self._check_url_duplication(task)
            comic_info = self._collect_comic_info(task)
            self._save_nfo(task, comic_info)
            self._check_content_duplication(task, comic_info)
            self._handle_torrent_addition(task, comic_info)

        except _TaskError as e:
            self.task_service.mark_task_error(task.id, str(e))
            self.file_service.cleanup_temp_files(
                nfo_path=getattr(task, 'nfo_path', None),
                torrent_file=task.torrent_file
            )
        except Exception as e:
            self.task_service.mark_task_error(task.id, str(e))
            self.file_service.cleanup_temp_files(torrent_file=task.torrent_file)

    def _validate_input(self, task):
        url = task.url or ''
        torrent_file = task.torrent_file or ''
        if not url and not torrent_file:
            raise _TaskError('没有提供网址或种子文件')

    def _check_url_duplication(self, task):
        url = task.url or ''
        if url:
            existing = self.task_service.is_duplicate_url(url, exclude_task_id=task.id)
            if existing:
                raise _TaskError(f'该链接已在下载队列中 (任务: {existing.title or existing.id})')

    def _collect_comic_info(self, task):
        result = {}
        nfo_data = task.nfo_data

        if nfo_data:
            try:
                result = json.loads(nfo_data)
                self.task_service.update_task_status(task.id, task.status, '使用预填 NFO 数据...')
            except (json.JSONDecodeError, TypeError):
                result = {}

        url = task.url or ''
        if url and not result.get('title'):
            self.task_service.update_task_status(task.id, 'scraping', '正在采集页面信息...')
            result = self.scraping_service.scrape_comic_info(url)

        if not result.get('title'):
            torrent_file = task.torrent_file or ''
            if torrent_file:
                result['title'] = os.path.splitext(os.path.basename(torrent_file))[0]
            elif url:
                result['title'] = url.split('/')[-2] if '/' in url else url

        self.task_service.set_task_title(task.id, result.get('title', ''))
        return result

    def _save_nfo(self, task, comic_info):
        self.task_service.update_task_status(task.id, 'saving_nfo', '正在保存 NFO...')

        download_dir = DOWNLOAD_DIR
        os.makedirs(download_dir, exist_ok=True)

        safe_title = safe_filename(comic_info.get('title', 'unknown')) or 'unknown'
        nfo_path = os.path.join(download_dir, f"{safe_title}.nfo")
        nfo_content = generate_nfo(comic_info)
        with open(nfo_path, 'w', encoding='utf-8') as f:
            f.write(nfo_content)

        self.task_service.update_task_nfo_path(task.id, nfo_path)
        self.task_service.update_task_status(task.id, 'saving_nfo', f'NFO 已保存: {safe_title}.nfo')

    def _check_content_duplication(self, task, comic_info):
        title = comic_info.get('title', '')
        source_url = comic_info.get('source_url', '')
        duplicate = self.duplication_checker.check_duplicate(title, source_url)

        if duplicate:
            nfo_path = getattr(task, 'nfo_path', None)
            if nfo_path and os.path.exists(nfo_path):
                try:
                    os.remove(nfo_path)
                except Exception:
                    pass
            raise _TaskError(f'库中已存在: {duplicate.title} (ID: {duplicate.id})')

    def _handle_torrent_addition(self, task, comic_info):
        torrent_file = task.torrent_file or ''
        torrent_url_list = []
        if comic_info.get('torrent_urls'):
            torrent_url_list = [u.strip() for u in comic_info['torrent_urls'].split(',') if u.strip()]

        task.torrent_urls = ','.join(torrent_url_list)
        has_torrent_source = torrent_file or torrent_url_list

        if has_torrent_source and self.torrent_service.is_enabled():
            self.task_service.update_task_status(task.id, 'adding_torrent', '正在添加种子到 qBittorrent...')

            if torrent_file:
                ok, err, info_hash = self.torrent_service.add_torrent_from_file(torrent_file)
            elif torrent_url_list:
                ok, err, info_hash = self.torrent_service.add_torrent_from_url(torrent_url_list[0])
            else:
                ok, err, info_hash = False, '没有种子链接或文件', ''

            if ok:
                if info_hash:
                    self.task_service.update_task_hash(task.id, info_hash)
                    self.task_service.update_task_status(task.id, 'downloading', '已添加种子，匹配成功')
                else:
                    self.task_service.update_task_status(task.id, 'matching', '已添加种子，等待匹配...')
            else:
                self.task_service.mark_task_error(task.id, f'添加种子失败: {err}')
        elif has_torrent_source:
            if torrent_file:
                self.task_service.mark_task_done(task.id, '已上传种子文件（qBittorrent 未启用）')
            else:
                self.task_service.mark_task_done(task.id, f'找到 {len(torrent_url_list)} 个种子链接（qBittorrent 未启用）')
        else:
            self.task_service.mark_task_done(task.id, '未找到种子链接')

        db.session.commit()

        if torrent_file:
            try:
                tp = os.path.join(DOWNLOAD_DIR, torrent_file)
                if os.path.exists(tp):
                    os.remove(tp)
            except Exception:
                pass

    def update_download_progress(self):
        self.progress_tracker.update_download_progress()

    def delete_task(self, task):
        self.file_service.cleanup_temp_files(nfo_path=task.nfo_path, torrent_file=task.torrent_file)

        if task.qb_info_hash:
            self.torrent_service.delete_torrent(task.qb_info_hash, delete_files=True)

        if task.title:
            self.file_service.cleanup_download_dir(task.title)

        db.session.delete(task)
        db.session.commit()


class _TaskError(Exception):
    pass