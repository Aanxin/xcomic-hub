"""图片代理安全工具：URL 域名白名单校验（SSRF 防护）+ 带防盗链头的图片抓取。"""

import time

import requests
from urllib.parse import urlparse

from app.utils.proxy_utils import (
    cookie_header_to_dict, get_cookie_for_url, get_proxy_handler,
    get_thread_session,
)

# 允许的图片/资源域名（精确匹配或子域后缀匹配）
ALLOWED_SUFFIXES = (
    'nhentai.net',
    'e-hentai.org',
    'exhentai.org',
    'ehgt.org',
    'hath.network',
)

# 域名 -> 防盗链 Referer
REFERER_MAP = (
    (('e-hentai.org', 'exhentai.org', 'ehgt.org', 'hath.network'), 'https://e-hentai.org/'),
    (('nhentai.net',), 'https://nhentai.net/'),
)


def _referer_for(url):
    url_lower = url.lower()
    for domains, referer in REFERER_MAP:
        if any(d in url_lower for d in domains):
            return referer
    return ''


def _fetch_response(url, timeout=15, stream=False):
    """复用线程本地 Session 发起 GET，Cookie/Referer/代理按请求级传入。"""
    session = get_thread_session()
    kwargs = {'timeout': timeout, 'stream': stream}

    referer = _referer_for(url)
    if referer:
        kwargs['headers'] = {'Referer': referer}

    cookie = get_cookie_for_url(url)
    if cookie:
        kwargs['cookies'] = cookie_header_to_dict(cookie)

    proxy_dict = get_proxy_handler(url)
    if proxy_dict:
        kwargs['proxies'] = proxy_dict

    return session.get(url, **kwargs)


def fetch_image(url, timeout=15, max_read_seconds=120):
    """抓取图片，返回 (bytes, content_type)。非 200 抛 requests 异常。

    流式读取并施加总时间预算：requests 的 timeout 只限制连接建立与
    相邻两次读之间的间隙，坏 H@H 节点慢速滴流（每隔 <timeout 秒滴
    一个字节）永远不会触发读超时，单张图可拖数小时并卡死整个串行
    下载队列。总预算兜底切断，抛 requests.Timeout 交由上层换节点。
    """
    resp = _fetch_response(url, timeout=timeout, stream=True)
    try:
        resp.raise_for_status()
        content_type = resp.headers.get('Content-Type', 'image/jpeg')
        deadline = time.monotonic() + max_read_seconds
        chunks = []
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            chunks.append(chunk)
            if time.monotonic() > deadline:
                raise requests.Timeout(
                    f'图片传输超过 {max_read_seconds}s 未完成，疑似慢速节点: {url}')
        content = b''.join(chunks)
    finally:
        resp.close()
    return content, content_type


def is_allowed_image_url(url):
    """校验图片 URL 是否命中源域名白名单。

    规则：
    - 仅 http/https
    - host 等于白名单域名，或以 .<域名> 结尾（子域）
    - host 不含 @（userinfo 混淆由 urlparse 剥离后天然失效）
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False

    if parsed.scheme not in ('http', 'https'):
        return False

    host = parsed.hostname
    if not host:
        return False
    host = host.lower()

    for suffix in ALLOWED_SUFFIXES:
        if host == suffix or host.endswith('.' + suffix):
            return True
    return False
