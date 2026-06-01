from datetime import datetime

from app import db
from app.models import DownloadTask
from app.services.matching_service import parse_hashes


class ProgressTracker:

    def __init__(self, torrent_service=None, task_service=None, matching_service=None,
                 comic_import_service=None):
        if torrent_service is None:
            from app.services.torrent_service import TorrentService
            torrent_service = TorrentService()
        if task_service is None:
            from app.services.task_service import TaskService
            task_service = TaskService()
        if matching_service is None:
            from app.services.matching_service import MatchingService
            matching_service = MatchingService()
        if comic_import_service is None:
            from app.services.comic_import_service import ComicImportService
            comic_import_service = ComicImportService()
        self.torrent_service = torrent_service
        self.task_service = task_service
        self.matching_service = matching_service
        self.comic_import_service = comic_import_service

    def update_download_progress(self):
        downloading = self.task_service.get_active_tasks()
        if not downloading:
            return

        torrents = self.torrent_service.get_torrents_info()
        if not torrents:
            for task in downloading:
                if task.status != 'matching':
                    task.qb_state = 'not_found'
            db.session.commit()
            return

        used_hashes = set()
        for task in downloading:
            for h in parse_hashes(task.qb_info_hash):
                used_hashes.add(h.upper())

        for task in downloading:
            self._update_single_task_progress(task, torrents, used_hashes)

    def _update_single_task_progress(self, task, torrents, used_hashes):
        info, matched_hash, in_hash_phase = self.matching_service.match_task_to_torrent(
            task, torrents, used_hashes)

        if info and matched_hash:
            if task.qb_info_hash and task.qb_info_hash != matched_hash:
                task.qb_info_hash = matched_hash
            used_hashes.add(matched_hash.upper())

            self._apply_torrent_info(task, info)

            if task.status == 'matching':
                task.status = 'downloading'
                task.message = '种子匹配成功，下载中'

            self._check_download_completion(task, info)
        else:
            self._handle_no_match(task, in_hash_phase)

        db.session.commit()

    def _apply_torrent_info(self, task, info):
        task.qb_progress = round(info.get('progress', 0) * 100, 1)
        task.qb_state = info.get('state', '')

    def _check_download_completion(self, task, info):
        state = info.get('state', '')
        if state in ('uploading', 'stalledUP', 'queuedUP', 'forcedUP') and info.get('progress', 0) >= 1.0:
            self._handle_download_complete(task)
        elif state in ('error', 'missingFiles', 'unknown'):
            task.status = 'error'
            task.message = f'下载失败: {state}'
        else:
            task.message = f'下载中 {task.qb_progress:.1f}%'

    def _handle_download_complete(self, task):
        task.status = 'importing'
        task.message = '下载完成，正在导入...'
        try:
            self.comic_import_service.import_downloaded_comic(task)
            if task.status != 'done':
                task.status = 'done'
                task.message = '下载完成并已导入'
        except Exception as ie:
            task.status = 'error'
            task.message = f'导入失败: {str(ie)}'

    def _handle_no_match(self, task, in_hash_phase):
        task.qb_progress = 0
        task.qb_state = 'not_found'

        task_age = (datetime.utcnow() - task.created_at).total_seconds() if task.created_at else 0
        if in_hash_phase:
            task.message = f'等待hash匹配中... ({task_age:.0f}s/300s)'
        else:
            task.message = f'等待模糊匹配中... (标题: {task.title or "无"})'

        if task.updated_at:
            not_found_duration = (datetime.utcnow() - task.updated_at).total_seconds()
        else:
            not_found_duration = 0

        if not_found_duration > 1800:
            task.status = 'error'
            task.message = '长时间未找到种子，可能已被删除或hash不匹配'