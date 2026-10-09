"""Nhentai 漫画源实现。

站点已改版为 SvelteKit SSR，不再使用 window._gallery_list 内嵌 JSON。
本模块从 SvelteKit 渲染的 HTML 中解析画廊卡片、详情与图片 URL。
"""

import json
import re

from app.sources.base_source import BaseSource, GalleryCard, GalleryListResult
from app.utils.proxy_utils import urlopen_with_proxy

BASE_URL = 'https://nhentai.net'
IMAGE_BASE = 'https://i.nhentai.net/galleries'

# 搜索/浏览排序（热度时间范围）-> nhentai sort 参数
# 站点默认排序为 date（最新上传，2026-10 改版验证），热度排序均需显式传参
SORT_MAP = {
    'today': 'popular-today',
    'week': 'popular-week',
    'all': 'popular',
}

# nhentai 扩展名代码 -> 常规扩展名
EXT_MAP = {'j': 'jpg', 'p': 'png', 'g': 'gif', 'w': 'webp'}


def _parse_gallery_cards(html):
    """从 SvelteKit SSR 渲染的 HTML 中解析画廊卡片。

    新版 HTML 结构：
      <div class="gallery lang-gb">
        <a href="/g/675652/" class="cover" style="...">
          <!----><img loading="lazy" alt="标题" class="lazyload"
               src="https://t1.nhentai.net/galleries/123/cover.webp" .../>
          <!----> <div class="caption">标题</div>
        </a>
      </div>

    SvelteKit 的 <!----> 注释标签会干扰正则，先清理再匹配。
    """
    # 清理 SvelteKit 注释标签
    html = html.replace('<!---->', '')

    cards = []
    seen_urls = set()

    pattern = re.compile(
        r'<div class="gallery[^"]*">\s*'
        r'<a\s+href="/g/(\d+)/"[^>]*>\s*'
        r'<img[^>]*?'
        r'(?:src|data-src)="(https://t\d+\.nhentai\.net/galleries/(\d+)/[^"]+)"'
        r'[^>]*?'
        r'(?:alt="([^"]*)")?'
        r'.*?'
        r'<div class="caption">(.*?)</div>',
        re.DOTALL,
    )

    for m in pattern.finditer(html):
        gid = m.group(1)
        cover_url = m.group(2)
        media_id = m.group(3)
        alt_title = m.group(4) or ''
        caption_title = m.group(5) or ''

        url = f'{BASE_URL}/g/{gid}/'
        if url in seen_urls:
            continue
        seen_urls.add(url)

        title = caption_title.strip() or alt_title.strip() or f'Gallery {gid}'
        # 清理 HTML 实体
        title = title.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")

        cards.append(GalleryCard(
            url=url,
            title=title,
            cover_url=cover_url,
            page_count=0,  # 列表页不含页数，详情页才有
        ))

    return cards


def _has_next_page(html):
    """检查 SvelteKit 页面是否有下一页按钮（末页无 next 按钮）。

    2026-10 改版后翻页按钮为 aria-label="Next page" 的 class="next" 链接，
    href 中 & 转义为 &amp; 且 page= 不再紧跟 ?，旧正则失配。
    """
    return bool(re.search(
        r'<a[^>]*(?:class="[^"]*\bnext\b|aria-label="Next page")[^>]*>', html))


def _extract_gallery_info_json(html):
    """尝试从画廊页提取 gallery_info JSON（新版可能不存在，需 fallback）。

    新版 SvelteKit 可能以内嵌 script data 形式存储数据，格式可能变化。
    """
    # 旧版格式
    m = re.search(r'gallery_info\s*=\s*JSON\.parse\("(.*?)"\)', html, re.DOTALL)
    if m:
        try:
            payload = json.loads(f'"{m.group(1)}"')
            return json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            pass

    # 新版 SvelteKit 可能的格式：JSON 直接内嵌在 script 标签中
    # 或通过 __sveltekit 数据传递
    m = re.search(r'"media_id"\s*:\s*["\']?(\d+)["\']?', html)
    if m:
        media_id = m.group(1)
        pages = []
        for pm in re.finditer(r'"t"\s*:\s*["\']?([jpgw])["\']?', html):
            pages.append({'t': pm.group(1)})
        if pages:
            return {'media_id': media_id, 'images': {'pages': pages}}

    return None


class NhentaiSource(BaseSource):
    source_id = 'nhentai'
    name = 'Nhentai'
    domains = ('nhentai.net',)

    def search(self, keyword, page=1, language=None, cursor=None, sort='today', exact_tag=False):
        # nhentai 的 q 命名空间语法（female:glasses）本身即精确 tag 匹配，
        # 无需 EH 式引号+$ 转换，exact_tag 参数仅为接口对齐
        from urllib.parse import quote_plus
        if language:
            query = quote_plus(f'language:{language} {keyword}')
        else:
            query = quote_plus(keyword)
        url = f'{BASE_URL}/search/?q={query}&page={page}'
        # sort 必须显式传参：站点默认排序已改为 date（最新上传），
        # popular-today 不再是默认，省略会显示最新而非今日热门
        sort_param = SORT_MAP.get(sort)
        if sort_param:
            url += f'&sort={sort_param}'
        html = urlopen_with_proxy(url)
        return self._parse_list_html(html)

    def latest(self, page=1, language=None, cursor=None, sort=None):
        if language:
            # 语言标签浏览页
            url = f'{BASE_URL}/language/{language}/?page={page}'
        else:
            url = f'{BASE_URL}/?page={page}'
        sort_param = SORT_MAP.get(sort)
        if sort_param:
            url += f'&sort={sort_param}'
        html = urlopen_with_proxy(url)
        return self._parse_list_html(html)

    def _parse_list_html(self, html):
        cards = _parse_gallery_cards(html)
        # has_next 完全按翻页按钮判定（2026-10 新版正则实测末页正确返回
        # False）；旧的数量兜底会在末页恰好满页时误报有下一页
        return GalleryListResult(items=cards, has_next=_has_next_page(html))

    def gallery_details(self, url):
        html = urlopen_with_proxy(url)
        from app.scrapers.nhentai_scraper import NhentaiScraper
        details = NhentaiScraper().scrape(html, source_url=url)
        return details

    def page_image_urls(self, url, progress_cb=None):
        html = urlopen_with_proxy(url)
        return self._extract_page_urls(html, url)

    def _extract_page_urls(self, html, gallery_url):
        """提取全部原图 URL。

        优先：SvelteKit 内嵌 JSON 的 pages 数组（含精确扩展名）；
        其次：旧版内嵌 JSON（media_id + images.pages）；
        最后：API v2 fallback。
        """
        # 1. SvelteKit 内嵌 JSON
        pages = self._sveltekit_pages(html)
        if pages:
            return pages

        # 2. 旧版 JSON
        info = _extract_gallery_info_json(html)
        if info and info.get('media_id'):
            media_id = info['media_id']
            pages = info.get('images', {}).get('pages', [])
            if pages:
                urls = []
                for page in pages:
                    ext = EXT_MAP.get(page.get('t', 'j'), 'jpg')
                    urls.append(f'{IMAGE_BASE}/{media_id}/{len(urls) + 1}.{ext}')
                return urls

        # 3. API fallback
        m = re.search(r'/g/(\d+)/', gallery_url)
        if m:
            return self._fetch_image_urls_from_api(m.group(1))
        return []

    @staticmethod
    def _sveltekit_pages(html):
        """从 SvelteKit 内嵌 JSON 的 pages 数组构造原图 URL。"""
        import json as _json
        for script in re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
            if 'media_id' not in script:
                continue
            try:
                outer = _json.loads(script)
            except (ValueError, TypeError):
                continue
            body = outer.get('body') if isinstance(outer, dict) else None
            if isinstance(body, str):
                try:
                    body = _json.loads(body)
                except (ValueError, TypeError):
                    continue
            if not isinstance(body, dict) or 'media_id' not in body:
                continue
            urls = []
            for page in body.get('pages', []):
                path = (page.get('path') or '').strip()
                if path:
                    urls.append(f'https://i.nhentai.net/{path}')
            if urls:
                return urls
        return None

    def _fetch_image_urls_from_api(self, gid):
        """通过 nhentai API v2 获取画廊图片信息。"""
        api_url = f'{BASE_URL}/api/v2/gallery/{gid}'
        try:
            html = urlopen_with_proxy(api_url, timeout=20)
            data = json.loads(html)
            media_id = data.get('media_id', '')
            images = data.get('images', {})
            pages = images.get('pages', [])
            urls = []
            for page in pages:
                ext = EXT_MAP.get(page.get('t', 'j'), 'jpg')
                urls.append(f'{IMAGE_BASE}/{media_id}/{len(urls) + 1}.{ext}')
            return urls
        except (json.JSONDecodeError, ValueError, Exception):
            return []
