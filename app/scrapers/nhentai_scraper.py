import re
from datetime import datetime as _dt
from app.scrapers.base_scraper import BaseScraper
from app.utils.proxy_utils import urlopen_with_proxy
from app.utils.html_utils import decode_html_entities


class NhentaiScraper(BaseScraper):
    def can_handle(self, url, html_content=''):
        if url and 'nhentai.net' in url:
            return True
        if html_content and 'property="og:site_name" content="nhentai"' in html_content:
            return True
        return False

    def scrape(self, html_content, source_url=''):
        result = {}

        if source_url:
            result['source_url'] = source_url

        self._parse_title(html_content, result)
        self._parse_cover(html_content, result)
        self._parse_source_url(html_content, result, source_url)
        self._parse_tags(html_content, result)
        self._parse_favorites(html_content, result)
        self._parse_download(html_content, result)

        if not self._has_tags_section(html_content):
            self._fallback_api(html_content, result)

        decode_html_entities(result)
        return result

    def _parse_title(self, html_content, result):
        h1_match = re.search(r'<h1\s+class="title">(.*?)</h1>', html_content, re.DOTALL)
        if h1_match:
            h1_html = h1_match.group(1)
            before = re.search(r'class="before">(.*?)</span>', h1_html, re.DOTALL)
            pretty = re.search(r'class="pretty">(.*?)</span>', h1_html, re.DOTALL)
            after = re.search(r'class="after">(.*?)</span>', h1_html, re.DOTALL)
            parts = []
            if before:
                parts.append(re.sub(r'<[^>]+>', '', before.group(1)).strip())
            if pretty:
                parts.append(re.sub(r'<[^>]+>', '', pretty.group(1)).strip())
            if after:
                parts.append(re.sub(r'<[^>]+>', '', after.group(1)).strip())
            if parts:
                result['title'] = ' '.join(parts)

        h2_match = re.search(r'<h2\s+class="title">(.*?)</h2>', html_content, re.DOTALL)
        if h2_match:
            h2_text = re.sub(r'<[^>]+>', '', h2_match.group(1)).strip()
            if h2_text:
                result['title_jp'] = h2_text

    def _parse_cover(self, html_content, result):
        og_image = re.search(r'property="og:image"\s+content="([^"]+)"', html_content)
        if og_image:
            result['cover_url'] = og_image.group(1).strip()

    def _parse_source_url(self, html_content, result, source_url):
        og_url = re.search(r'property="og:url"\s+content="([^"]+)"', html_content)
        if og_url:
            result['source_url'] = og_url.group(1).strip()
        elif source_url:
            result['source_url'] = source_url

    def _append_tags(self, result, new_tags):
        existing = result.get('tags', '')
        if not new_tags:
            return
        tag_str = ','.join(new_tags)
        result['tags'] = existing + (',' if existing else '') + tag_str

    def _parse_tags(self, html_content, result):
        tags_section_match = re.search(r'<section\s+id="tags">(.*?)</section>', html_content, re.DOTALL)
        if not tags_section_match:
            return

        tags_html = tags_section_match.group(1)
        tag_containers = re.findall(r'<div\s+class="tag-container\s+field-name">(.*?)</div>', tags_html, re.DOTALL)
        for container in tag_containers:
            label_match = re.match(r'\s*(\w[\w\s]*?):\s*', container)
            if not label_match:
                continue
            label = label_match.group(1).strip().lower()
            names = re.findall(r'<span\s+class="name[^"]*">(.*?)</span>', container)
            names = [re.sub(r'<[^>]+>', '', n).strip() for n in names if n.strip()]

            if label == 'parodies':
                if names:
                    self._append_tags(result, [f'parody:{n}' for n in names])
            elif label == 'tags':
                if names:
                    self._append_tags(result, [f'tag:{n}' for n in names])
            elif label == 'artists':
                if names:
                    result['author'] = ', '.join(names)
                    self._append_tags(result, [f'artist:{n}' for n in names])
            elif label == 'groups':
                if names:
                    self._append_tags(result, [f'group:{n}' for n in names])
            elif label == 'languages':
                for n in names:
                    nl = n.lower()
                    if nl == 'chinese':
                        result['language'] = 'Chinese'
                    elif nl == 'translated':
                        result['is_translated'] = True
                    elif nl == 'english':
                        result['language'] = result.get('language', 'English')
                    elif nl == 'japanese':
                        if not result.get('language'):
                            result['language'] = 'Japanese'
                if names:
                    self._append_tags(result, [f'language:{n}' for n in names])
            elif label == 'categories':
                if names:
                    result['category'] = ', '.join([n.capitalize() for n in names])
                    self._append_tags(result, [f'category:{n}' for n in names])
            elif label == 'pages':
                if names:
                    try:
                        result['page_count'] = int(names[0])
                    except ValueError as e:
                        print(f'[采集] nhentai页数解析失败: {e}')
                    self._append_tags(result, [f'pages:{names[0]}'])
            elif label == 'uploaded':
                time_match = re.search(r'datetime="([^"]+)"', container)
                if time_match:
                    result['date'] = time_match.group(1)[:10]
                    self._append_tags(result, [f'uploaded:{time_match.group(1)[:10]}'])

    def _parse_favorites(self, html_content, result):
        fav_match = re.search(r'id="favorite"[^>]*>.*?<span\s+class="count">(\d+)</span>', html_content, re.DOTALL)
        if fav_match:
            result['favorited'] = int(fav_match.group(1))

    def _parse_download(self, html_content, result):
        download_match = re.search(r'<a\s+id="download"[^>]*href="([^"]+)"', html_content)
        if download_match:
            download_url = download_match.group(1).strip()
            if download_url.startswith('/'):
                download_url = 'https://nhentai.net' + download_url
            self._fetch_torrent(download_url, result)
            return

        button_match = re.search(r'<button[^>]+id="download"', html_content)
        if button_match:
            gallery_id_match = re.search(r'nhentai\.net/g/(\d+)', html_content)
            if gallery_id_match:
                download_url = f"https://nhentai.net/g/{gallery_id_match.group(1)}/download"
                self._fetch_torrent(download_url, result)

    def _fetch_torrent(self, download_url, result):
        try:
            download_html = urlopen_with_proxy(download_url)
            torrent_links = re.findall(r'href="([^"]*\.torrent[^"]*)"', download_html)
            if torrent_links:
                result['torrent_urls'] = ','.join(torrent_links)
        except Exception as _e:
            print(f'[采集] nhentai 种子页面请求失败: {_e}')
            result['torrent_urls'] = download_url

    def _has_tags_section(self, html_content):
        return bool(re.search(r'<section\s+id="tags">(.*?)</section>', html_content, re.DOTALL))

    def _fallback_api(self, html_content, result):
        gallery_id_match = re.search(r'nhentai\.net/g/(\d+)', html_content)
        if not gallery_id_match:
            return
        gallery_id = gallery_id_match.group(1)
        api_url = f"https://nhentai.net/api/v2/gallery/{gallery_id}"
        try:
            import json as _json
            api_html = urlopen_with_proxy(api_url)
            api_data = _json.loads(api_html)
            if api_data.get('data') and api_data['data'].get('gallery'):
                g = api_data['data']['gallery']
                if g.get('english_title'):
                    result['title'] = g['english_title']
                if g.get('japanese_title'):
                    result['title_jp'] = g['japanese_title']
                if g.get('num_pages'):
                    result['page_count'] = g['num_pages']
                    self._append_tags(result, [f'pages:{g["num_pages"]}'])
                if g.get('upload_date'):
                    upload_str = _dt.utcfromtimestamp(g['upload_date']).strftime('%Y-%m-%d')
                    result['date'] = upload_str
                    self._append_tags(result, [f'uploaded:{upload_str}'])
                if g.get('tags'):
                    tags = []
                    for tag in g['tags']:
                        tag_type = tag.get('type', '')
                        tag_name = tag.get('name', '')
                        if tag_type == 'artist':
                            result['author'] = tag_name
                            tags.append(f"artist:{tag_name}")
                        elif tag_type == 'language':
                            if tag_name.lower() == 'chinese':
                                result['language'] = 'Chinese'
                            elif tag_name.lower() == 'translated':
                                result['is_translated'] = True
                            tags.append(f"language:{tag_name}")
                        elif tag_type == 'category':
                            result['category'] = tag_name.capitalize()
                            tags.append(f"category:{tag_name}")
                        elif tag_type and tag_name:
                            tags.append(f"{tag_type}:{tag_name}")
                    if tags:
                        self._append_tags(result, tags)
        except Exception as _e:
            print(f'[采集] nhentai API 请求失败: {_e}')
