import re
from app.scrapers.base_scraper import BaseScraper
from app.utils.proxy_utils import urlopen_with_proxy
from app.utils.html_utils import decode_html_entities


class EhentaiScraper(BaseScraper):
    def can_handle(self, url, html_content=''):
        return True

    def scrape(self, html_content, source_url=''):
        result = {}

        self._parse_title(html_content, result)
        self._parse_category(html_content, result)
        self._parse_uploader(html_content, result)
        self._parse_rating(html_content, result)
        self._parse_tags(html_content, result)
        self._parse_meta(html_content, result)
        self._parse_cover(html_content, result)
        self._parse_torrents(html_content, result, source_url)

        if source_url:
            result['source_url'] = source_url

        decode_html_entities(result)
        return result

    def _parse_title(self, html_content, result):
        title_match = re.search(r'id=["\']gn["\'][^>]*>(.*?)</h1>', html_content, re.DOTALL)
        if title_match:
            result['title'] = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()

        jp_title_match = re.search(r'id=["\']gj["\'][^>]*>(.*?)</h1>', html_content, re.DOTALL)
        if jp_title_match:
            result['title_jp'] = re.sub(r'<[^>]+>', '', jp_title_match.group(1)).strip()

    def _parse_category(self, html_content, result):
        cat_match = re.search(r'id=["\']gdc["\'][^>]*>.*?class=["\']cs[^"\']*["\'][^>]*>(.*?)</div>', html_content, re.DOTALL)
        if cat_match:
            result['category'] = re.sub(r'<[^>]+>', '', cat_match.group(1)).strip()

    def _parse_uploader(self, html_content, result):
        uploader_match = re.search(r'id=["\']gdn["\'][^>]*>(.*?)</div>', html_content, re.DOTALL)
        if uploader_match:
            first_link = re.search(r'<a[^>]*>(.*?)</a>', uploader_match.group(1), re.DOTALL)
            if first_link:
                result['uploader'] = re.sub(r'<[^>]+>', '', first_link.group(1)).strip()

    def _parse_rating(self, html_content, result):
        rating_match = re.search(r'var\s+average_rating\s*=\s*([\d.]+)', html_content)
        if rating_match:
            try:
                result['rating'] = round(float(rating_match.group(1)), 2)
            except ValueError as e:
                print(f'[采集] 评分解析失败: {e}')

        rating_count_match = re.search(r'id=["\']rating_count["\'][^>]*>(.*?)</span>', html_content, re.DOTALL)
        if rating_count_match:
            try:
                inner_html = rating_count_match.group(1)
                nums = re.findall(r'(\d+)', inner_html)
                if nums:
                    result['rating_count'] = int(nums[0])
            except ValueError as e:
                print(f'[采集] 评分人数解析失败: {e}')

    def _parse_tags(self, html_content, result):
        tag_rows = re.findall(r'<tr>\s*<td[^>]*class=["\']tc["\'][^>]*>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>', html_content, re.DOTALL)
        tags = []
        artists = []
        for cat_html, vals_html in tag_rows:
            cat = re.sub(r'<[^>]+>', '', cat_html).strip().rstrip(':')
            vals = re.findall(r'>([^<]+)</a>', vals_html)
            for v in vals:
                v = v.strip()
                if v:
                    if cat.lower() == 'artist':
                        artists.append(v)
                    tags.append(f'{cat}:{v}' if cat else v)
        if artists:
            result['author'] = ', '.join(artists)
        if tags:
            result['tags'] = ','.join(tags)

    def _parse_meta(self, html_content, result):
        meta_pairs = re.findall(r'class=["\']gdt1["\'][^>]*>(.*?)</td>\s*<td[^>]*class=["\']gdt2["\'][^>]*>(.*?)</td>', html_content, re.DOTALL)
        for label_html, val_html in meta_pairs:
            label = re.sub(r'<[^>]+>', '', label_html).strip()
            val = re.sub(r'<[^>]+>', '', val_html).strip()
            if 'Posted' in label:
                result['posted'] = val
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', val)
                if date_match:
                    result['date'] = date_match.group(1)
                else:
                    year_match = re.search(r'(\d{4})', val)
                    if year_match:
                        result['date'] = year_match.group(1)
            elif 'Language' in label:
                lang = re.sub(r'<[^>]+>', '', val).strip()
                lang = re.sub(r'&nbsp;', '', lang).strip()
                is_tr = bool(re.search(r'(^|[^a-zA-Z])TR($|[^a-zA-Z])', lang, re.IGNORECASE))
                lang = re.sub(r'(^|[^a-zA-Z])TR($|[^a-zA-Z])', r'\1\2', lang, flags=re.IGNORECASE).strip()
                lang = re.sub(r'^[^a-zA-Z]+|[^a-zA-Z]+$', '', lang).strip()
                if lang:
                    result['language'] = lang
                if is_tr:
                    result['is_translated'] = True
            elif 'File Size' in label:
                result['file_size_text'] = val
            elif 'Length' in label:
                pages_match = re.search(r'(\d+)', val)
                if pages_match:
                    result['page_count'] = int(pages_match.group(1))
            elif 'Favorited' in label:
                fav_match = re.search(r'([\d,]+)', val)
                if fav_match:
                    result['favorited'] = int(fav_match.group(1).replace(',', ''))
            elif 'Parent' in label:
                result['parent'] = val
            elif 'Visible' in label:
                result['visible'] = val

    def _parse_cover(self, html_content, result):
        cover_match = re.search(r'id=["\']gd1["\'][^>]*>.*?background:\s*transparent\s+url\(([^)]+)\)', html_content, re.DOTALL)
        if cover_match:
            result['cover_url'] = cover_match.group(1).strip()

    def _parse_torrents(self, html_content, result, source_url):
        torrent_urls = re.findall(r'href="(https://ehtracker\.org/get/[^"]+\.torrent)"', html_content)
        if torrent_urls:
            result['torrent_urls'] = ','.join(torrent_urls)
            return

        popbase_match = re.search(r'gallerypopups\.php\?gid=(\d+)&t=([a-f0-9]+)', html_content)
        if popbase_match:
            gid = popbase_match.group(1)
            t = popbase_match.group(2)
            torrent_page_url = f"https://e-hentai.org/gallerytorrents.php?gid={gid}&t={t}"
            try:
                torrent_html = urlopen_with_proxy(torrent_page_url)
                torrent_links = re.findall(r'href="(https://ehtracker\.org/get/[^"]+\.torrent)"', torrent_html)
                if torrent_links:
                    result['torrent_urls'] = ','.join(torrent_links)
            except Exception as _e:
                print(f'[采集] E-Hentai 种子页面请求失败: {_e}')
