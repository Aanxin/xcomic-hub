from app.services.matching_service import (
    parse_hashes as _parse_hashes,
    get_next_queue_position,
    fuzzy_match_score,
    normalize_title as _normalize_title,
)
from app.services.download_orchestrator import DownloadOrchestrator


def _get_orchestrator():
    return DownloadOrchestrator()


class DownloadService:

    @staticmethod
    def run_add_task(task_id):
        from app import create_app as _ca
        app = _ca()
        with app.app_context():
            orchestrator = _get_orchestrator()
            orchestrator.run_add_task(task_id)

    @staticmethod
    def update_download_progress():
        orchestrator = _get_orchestrator()
        orchestrator.update_download_progress()

    @staticmethod
    def delete_task(task):
        orchestrator = _get_orchestrator()
        orchestrator.delete_task(task)