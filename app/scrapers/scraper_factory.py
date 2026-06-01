from app.scrapers.base_scraper import BaseScraper
from app.scrapers.nhentai_scraper import NhentaiScraper
from app.scrapers.ehentai_scraper import EhentaiScraper


class ScraperFactory:
    _scrapers = [
        NhentaiScraper(),
        EhentaiScraper(),
    ]

    @classmethod
    def create_scraper(cls, url='', html_content=''):
        for scraper in cls._scrapers:
            if scraper.can_handle(url, html_content):
                return scraper
        return cls._scrapers[-1]

    @classmethod
    def register_scraper(cls, scraper):
        cls._scrapers.insert(-1, scraper)
