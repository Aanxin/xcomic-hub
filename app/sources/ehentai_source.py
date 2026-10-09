"""E-Hentai 漫画源实现。"""

import re
import time

from app.sources.base_source import (
    BaseSource, GalleryCard, GalleryListResult, PageImage, QuotaError,
    UnsupportedCategory,
)
from app.utils.proxy_utils import urlopen_with_proxy

BASE_URL = 'https://e-hentai.org'

# 排行榜时间范围 → E-Hentai toplist.php 的 tl 参数（画廊类排行）
_TOPLIST_TL = {
    'all': 11,    # 有史以来
    'year': 12,   # 过去一年
    'month': 13,  # 过去一月
    'day': 15,    # 过去一天
}

# 查看页请求间隔（秒），遵守站点频率限制
VIEWER_REQUEST_INTERVAL = 1.5

# E-Hentai 配额占位图路径特征（509=站点带宽，1004=H@H 配额）
QUOTA_IMAGE_MARKERS = ('/509.png', '/1004.png')

# 注入点：测试中替换为 no-op
_sleep = time.sleep


def _rows(html):
    """切分画廊行块：表格模式按 <tr>，Thumbnail 模式（账号 Cookie 偏好）按 gl1t 卡片块。"""
    return re.split(r'<tr[^>]*>|<div class="gl1t">', html)[1:]


def _parse_card(row):
    link = re.search(r'href="(https://e-hentai\.org/g/\d+/[0-9a-f]+/)"', row)
    if not link:
        return None
    url = link.group(1)

    # 标题类名：表格模式为 "glink"，Thumbnail 模式为 "gl4t glname glink"
    title_m = re.search(r'class="[^"]*\bglink\b[^"]*">(.*?)</div>', row, re.DOTALL)
    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else url

    # 缩略图：优先 data-src(懒加载)，回退 src
    thumb_m = re.search(r'<img[^>]+(?:data-src|src)="(https://[^"]+)"', row)
    cover_url = thumb_m.group(1) if thumb_m else ''

    pages_m = re.search(r'(\d+)\s*pages', row)
    page_count = int(pages_m.group(1)) if pages_m else 0

    return GalleryCard(url=url, title=title, cover_url=cover_url, page_count=page_count)


def _has_next_page(html):
    """新版游标分页：searchnav 内存在 id="dnext" 的 Next 链接；兼容旧版 ptt 表箭头。"""
    if re.search(r'<a[^>]+id="dnext"[^>]*>', html):
        return True
    m = re.search(r'class="ptt".*?</table>', html, re.DOTALL)
    if not m:
        return False
    return bool(re.search(r'<a[^>]*>(&gt;|&rsaquo;)</a>', m.group(0)))


def _next_cursor(html):
    """从新版分页 Next 链接中提取游标（next= 参数），无则返回空串。

    HTML 中 & 会转义为 &amp;，两者都需匹配。
    """
    m = re.search(r'<a[^>]+id="dnext"[^>]+href="[^"]*[?&](?:amp;)?next=(\d+)"', html)
    return m.group(1) if m else ''


def _parse_toplist_card(row):
    """toplist 行（2026-08 结构）：行首 <p>#N</p> 排名 + 标准 glname/glink 画廊单元格。"""
    rank_m = re.search(r'<p>#(\d+)</p>', row)
    if not rank_m:
        return None
    card = _parse_card(row)
    if not card:
        return None
    card.rank = int(rank_m.group(1))
    return card


def _parse_viewer_page(html, viewer_url):
    """解析查看页：原图 URL + onerror nl key（坏节点换源上下文）。

    命中配额占位图（509/1004）时抛 QuotaError——下载它只会得到占位图，
    且该限制为 IP 级，换节点无效。
    """
    img = re.search(r'<img[^>]+id="img"[^>]+src="(https://[^"]+)"', html)
    if not img:
        img = re.search(r'<img[^>]+src="(https://[^"]+)"[^>]+id="img"', html)
    if not img:
        return None
    src = img.group(1).lower()
    if any(marker in src for marker in QUOTA_IMAGE_MARKERS):
        raise QuotaError('E-Hentai 带宽配额限制（509/1004）')
    nl = re.search(r'nl\(\'([^\']+)\'\)', html)
    return PageImage(
        url=img.group(1),
        viewer_url=viewer_url,
        nl_key=nl.group(1) if nl else '',
    )


class EhentaiSource(BaseSource):
    source_id = 'ehentai'
    name = 'E-Hentai'
    domains = ('e-hentai.org', 'exhentai.org')

    def categories(self):
        return [
            {'id': 'home', 'name': '首页'},
            {'id': 'watched', 'name': '订阅'},
            {'id': 'popular', 'name': '热门'},
            {'id': 'toplist', 'name': '排行'},
        ]

    def browse(self, category='home', page=1, language=None, cursor=None, period='all', sort=None):
        from urllib.parse import quote_plus
        if category == 'toplist':
            # 画廊排行：独立表格结构，每页 50 条、Top 200 共 4 页（p=0..3）；
            # period 控制 tl 时间范围。数字页码分页，无游标
            tl = _TOPLIST_TL.get(period)
            if tl is None:
                raise UnsupportedCategory(f'不支持的排行时间范围: {period}')
            p = max(page - 1, 0)
            html = urlopen_with_proxy(f'{BASE_URL}/toplist.php?tl={tl}&p={p}')
            cards = [c for c in (_parse_toplist_card(row) for row in _rows(html)) if c]
            return GalleryListResult(items=cards, has_next=_has_next_page(html))
        if category == 'popular':
            # 热门：站点全局单页列表，不支持 f_search 语言筛选与分页参数
            return self._parse_list_html(urlopen_with_proxy(f'{BASE_URL}/popular'))
        if category == 'watched':
            # 订阅：需登录 Cookie，列表结构与首页一致
            url = f'{BASE_URL}/watched'
            if language:
                url += f'?f_search={quote_plus(f"language:{language}")}'
            url = self._page_url(url, page, cursor)
            return self._parse_list_html(urlopen_with_proxy(url))
        if category != 'home':
            raise UnsupportedCategory(f'{self.name} 不支持大类: {category}')
        return self.latest(page=page, language=language, cursor=cursor, sort=sort)

    def search(self, keyword, page=1, language=None, cursor=None, sort=None, exact_tag=False):
        from urllib.parse import quote_plus
        terms = []
        if language:
            terms.append(f'language:{language}')
        # 精确 tag 匹配用引号+$（站点 /tag/ 路由同义）：裸拼 ns:tag 会前缀
        # 命中更长 tag（实测 f:wolf 首页 25 条中 23 条来自 wolf girl 等污染）
        if exact_tag:
            terms.append(f'"{keyword}$"')
        else:
            terms.append(keyword)
        url = f'{BASE_URL}/?f_search={quote_plus(" ".join(terms))}'
        url = self._page_url(url, page, cursor)
        html = urlopen_with_proxy(url)
        return self._parse_list_html(html)

    def latest(self, page=1, language=None, cursor=None, sort=None):
        from urllib.parse import quote_plus
        if language:
            url = f'{BASE_URL}/?f_search={quote_plus(f"language:{language}")}'
        else:
            url = f'{BASE_URL}/'
        url = self._page_url(url, page, cursor)
        html = urlopen_with_proxy(url)
        return self._parse_list_html(html)

    @staticmethod
    def _page_url(url, page, cursor):
        """拼接分页参数：优先游标 next=，否则数字页码 page=N（从 0 开始）。"""
        sep = '&' if '?' in url else '?'
        if cursor:
            return f'{url}{sep}next={cursor}'
        return f'{url}{sep}page={page - 1}'

    def _parse_list_html(self, html):
        cards = [c for c in (_parse_card(row) for row in _rows(html)) if c]
        return GalleryListResult(
            items=cards,
            has_next=_has_next_page(html),
            next_cursor=_next_cursor(html),
        )

    def gallery_details(self, url):
        html = urlopen_with_proxy(url)
        from app.scrapers.ehentai_scraper import EhentaiScraper
        return EhentaiScraper().scrape(html, source_url=url)

    def page_image_urls(self, url, progress_cb=None):
        """收集画廊全部查看页链接，逐个请求解析原图。

        返回 PageImage 列表（携带 viewer_url/nl_key，坏节点时可 reload_image 换源）。
        多页画廊需翻 ?p=N 收集全部查看页；串行 + 间隔请求遵守频率限制。
        解析失败的查看页补试一轮，仍有缺失时抛错——静默少页会产生残缺 ZIP。
        progress_cb(done, total)：解析进度回调（total 为 0 表示总数尚未
        确定）。大画廊解析需数分钟，实时上报避免任务长时间零进度被
        误判卡死。
        """
        viewer_urls = self._collect_viewer_urls(url, progress_cb=progress_cb)

        def _report(done):
            if progress_cb:
                progress_cb(done, len(viewer_urls))

        _report(0)
        results = [None] * len(viewer_urls)
        missing = set(range(len(viewer_urls)))
        done = 0
        first_request = True
        for _round in range(2):
            if not missing:
                break
            for i in sorted(missing):
                if not first_request:
                    _sleep(VIEWER_REQUEST_INTERVAL)
                first_request = False
                try:
                    html = urlopen_with_proxy(viewer_urls[i])
                    page = _parse_viewer_page(html, viewer_urls[i])
                except QuotaError:
                    raise
                except Exception:
                    continue
                if page:
                    results[i] = page
                    missing.discard(i)
                    done += 1
                    _report(done)
        if missing:
            raise ValueError(
                f'{len(missing)}/{len(viewer_urls)} 个查看页解析失败，画廊不完整，请重试'
            )
        return results

    def reload_image(self, page):
        """坏节点重载：请求 查看页?nl=key，站点换节点返回新图片 URL。"""
        sep = '&' if '?' in page.viewer_url else '?'
        html = urlopen_with_proxy(f'{page.viewer_url}{sep}nl={page.nl_key}')
        new_page = _parse_viewer_page(html, page.viewer_url)
        if new_page is None:
            raise ValueError('换节点重载失败：查看页未解析到图片')
        return new_page

    def _collect_viewer_urls(self, gallery_url, progress_cb=None):
        """从画廊页(含多分页 ?p=N)收集全部查看页 /s/{key}/{gid}-{page} 链接。"""
        # exhentai 画廊的查看页链接域名同为 exhentai.org，需一并匹配
        viewer_pattern = re.compile(
            r'href="(https://(?:e-hentai|exhentai)\.org/s/[0-9a-f]+/\d+-\d+)"')
        collected = []

        page = 0
        while True:
            if page == 0:
                url = gallery_url
            else:
                sep = '&' if '?' in gallery_url else '?'
                url = f'{gallery_url}{sep}p={page}'
            html = urlopen_with_proxy(url)

            if page == 0 and re.search(r'<title>Gallery Not Available', html):
                raise ValueError('画廊不存在或已被移除')

            links = viewer_pattern.findall(html)
            if not links:
                break
            for link in links:
                if link not in collected:
                    collected.append(link)

            # 收集阶段总数未知，total 传 0（仅上报消息保持任务活跃）
            if progress_cb:
                progress_cb(len(collected), 0)

            # 无下一分页则停止
            if not re.search(r'href="[^"]*\?p=' + str(page + 1) + '"', html):
                break
            page += 1

        return collected
