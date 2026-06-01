from app.models import Setting
from app.services.matching_service import parse_hashes
from config import DOWNLOAD_DIR


class TorrentService:

    def __init__(self, torrent_client=None):
        if torrent_client is None:
            from app.clients.torrent_client_adapter import QbittorrentClientAdapter
            torrent_client = QbittorrentClientAdapter()
        self._client = torrent_client

    def is_enabled(self):
        return Setting.get('qb_enabled', '0') == '1' and self._client.is_configured()

    def add_torrent_from_url(self, torrent_url):
        category = Setting.get('qb_category', '').strip()
        savepath = Setting.get('qb_download_path', '').strip()
        return self._client.add_torrent(torrent_url, category, savepath)

    def add_torrent_from_file(self, torrent_file):
        import os
        category = Setting.get('qb_category', '').strip()
        savepath = Setting.get('qb_download_path', '').strip()
        torrent_path = os.path.join(DOWNLOAD_DIR, torrent_file)
        if os.path.exists(torrent_path):
            return self._client.add_torrent_by_file(torrent_path, category, savepath)
        else:
            return False, f'种子文件不存在: {torrent_file}', ''

    def get_torrents_info(self, hashes=None):
        return self._client.get_torrents_info(hashes=hashes)

    def get_torrent_info_by_hash(self, info_hash):
        if not info_hash:
            return None, None
        torrents = self.get_torrents_info(hashes=info_hash)
        if torrents:
            t = torrents[0]
            content_path = t.get('content_path', '')
            save_path = t.get('save_path', '')
            name = t.get('name', '')
            return t, {'content_path': content_path, 'save_path': save_path, 'name': name}
        return None, None

    def delete_torrent(self, info_hash, delete_files=True):
        for h in parse_hashes(info_hash):
            try:
                self._client.delete_torrent(h, delete_files=delete_files)
            except Exception:
                pass