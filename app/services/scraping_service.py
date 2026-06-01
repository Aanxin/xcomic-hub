from app.utils.proxy_utils import urlopen_with_proxy
from app.utils.html_utils import decode_html_entities
from app.scrapers.scraper_factory import ScraperFactory


class ScrapingService:

    def scrape_comic_info(self, url):
        html_content = urlopen_with_proxy(url)
        result = {'source_url': url}

        scraper = ScraperFactory.create_scraper(url, html_content)
        scraped = scraper.scrape(html_content, url)
        for k, v in scraped.items():
            if v:
                result[k] = v
        if 'source_url' not in result:
            result['source_url'] = url

        decode_html_entities(result)
        return result