from app import db
from app.models import DownloadTask


class TaskService:

    def __init__(self, db_session=None):
        self.db_session = db_session or db.session

    def get_task(self, task_id):
        return DownloadTask.query.get(task_id)

    def update_task_status(self, task_id, status, message):
        task = self.get_task(task_id)
        if task:
            task.status = status
            task.message = message
            self.db_session.commit()
        return task

    def update_task_nfo_path(self, task_id, nfo_path):
        task = self.get_task(task_id)
        if task:
            task.nfo_path = nfo_path
            self.db_session.commit()
        return task

    def update_task_hash(self, task_id, info_hash):
        task = self.get_task(task_id)
        if task:
            task.qb_info_hash = info_hash
            self.db_session.commit()
        return task

    def update_task_progress(self, task_id, progress, state, status, message):
        task = self.get_task(task_id)
        if task:
            task.qb_progress = progress
            task.qb_state = state
            task.status = status
            task.message = message
            self.db_session.commit()
        return task

    def mark_task_error(self, task_id, message):
        return self.update_task_status(task_id, 'error', message)

    def mark_task_done(self, task_id, message='下载完成'):
        return self.update_task_status(task_id, 'done', message)

    def is_duplicate_url(self, url, exclude_task_id=None):
        query = DownloadTask.query.filter(
            DownloadTask.url == url,
            DownloadTask.status.in_(['downloading', 'importing', 'matching', 'done'])
        )
        if exclude_task_id:
            query = query.filter(DownloadTask.id != exclude_task_id)
        return query.first()

    def get_active_tasks(self):
        return DownloadTask.query.filter(
            DownloadTask.status.in_(['downloading', 'importing', 'matching'])
        ).all()

    def get_waiting_tasks(self):
        return DownloadTask.query.filter(
            DownloadTask.queue == 'waiting',
            DownloadTask.status == 'pending'
        ).order_by(DownloadTask.queue_position.asc(), DownloadTask.created_at.asc()).all()

    def set_task_queue(self, task_id, queue, status, message):
        task = self.get_task(task_id)
        if task:
            task.queue = queue
            task.status = status
            task.message = message
            self.db_session.commit()
        return task

    def set_task_comic_id(self, task_id, comic_id):
        task = self.get_task(task_id)
        if task:
            task.comic_id = comic_id
            self.db_session.commit()
        return task

    def set_task_title(self, task_id, title):
        task = self.get_task(task_id)
        if task:
            task.title = title
            self.db_session.commit()
        return task