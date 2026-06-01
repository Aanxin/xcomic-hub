from app.services.nfo_service import NfoService
from app.services.download_service import DownloadService, get_next_queue_position
from app.services.upload_service import UploadService
from app.services.comic_service import ComicService
from app.services.collection_service import CollectionService
from app.services.scheduler_service import SchedulerService
from app.services.matching_service import fuzzy_match_score, normalize_title, parse_hashes
from app.services.task_service import TaskService
from app.services.duplication_checker import DuplicationChecker
from app.services.file_operation_service import FileOperationService
from app.services.scraping_service import ScrapingService
from app.services.torrent_service import TorrentService
from app.services.comic_import_service import ComicImportService
from app.services.progress_tracker import ProgressTracker
from app.services.download_orchestrator import DownloadOrchestrator