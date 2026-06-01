from abc import ABC, abstractmethod


class BaseScraper(ABC):
    @abstractmethod
    def scrape(self, html_content, source_url=''):
        pass

    @abstractmethod
    def can_handle(self, url, html_content=''):
        pass
