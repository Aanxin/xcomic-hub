from abc import ABC, abstractmethod


class AbstractTorrentClient(ABC):

    @abstractmethod
    def login(self):
        pass

    @abstractmethod
    def add_torrent(self, torrent_url, category='', savepath=''):
        pass

    @abstractmethod
    def add_torrent_by_file(self, torrent_path, category='', savepath=''):
        pass

    @abstractmethod
    def get_torrents_info(self, hashes=None):
        pass

    @abstractmethod
    def delete_torrent(self, info_hash, delete_files=True):
        pass

    @abstractmethod
    def is_configured(self):
        pass


class QbittorrentClientAdapter(AbstractTorrentClient):

    def __init__(self, qb_client=None):
        if qb_client is None:
            from app.clients.qbittorrent_client import QbittorrentClient
            qb_client = QbittorrentClient()
        self._client = qb_client

    def login(self):
        return self._client.login()

    def add_torrent(self, torrent_url, category='', savepath=''):
        return self._client.add_torrent(torrent_url, category, savepath)

    def add_torrent_by_file(self, torrent_path, category='', savepath=''):
        return self._client.add_torrent_by_file(torrent_path, category, savepath)

    def get_torrents_info(self, hashes=None):
        return self._client.get_torrents_info(hashes=hashes)

    def delete_torrent(self, info_hash, delete_files=True):
        return self._client.delete_torrent(info_hash, delete_files)

    def is_configured(self):
        return self._client.is_configured()