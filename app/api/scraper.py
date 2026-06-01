from flask import Blueprint, request
from app.scrapers.scraper_factory import ScraperFactory
from app.utils.proxy_utils import urlopen_with_proxy
from app.api.utils import success_response, error_response, ErrorCode

bp = Blueprint('api_scraper', __name__, url_prefix='/api/v1/scraper')


@bp.route('/scrape', methods=['POST'])
def scrape_info():
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()

    if not url:
        return error_response(ErrorCode.BAD_REQUEST, '请输入网址')
    if not url.startswith(('http://', 'https://')):
        return error_response(ErrorCode.BAD_REQUEST, '网址必须以 http:// 或 https:// 开头')

    try:
        html_content = urlopen_with_proxy(url)
    except Exception as e:
        return error_response(ErrorCode.BAD_REQUEST, f'无法获取网页: {str(e)}')

    scraper = ScraperFactory.create_scraper(url, html_content)
    result = scraper.scrape(html_content, url)
    return success_response(data=result)


@bp.route('/scrape-html', methods=['POST'])
def scrape_html():
    data = request.get_json(silent=True) or {}
    html_content = data.get('html', '')
    url = data.get('url', '').strip()

    if not html_content:
        return error_response(ErrorCode.BAD_REQUEST, '请提供HTML内容')

    scraper = ScraperFactory.create_scraper(url, html_content)
    result = scraper.scrape(html_content, url)
    return success_response(data=result)
