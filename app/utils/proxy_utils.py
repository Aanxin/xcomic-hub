import re
import threading
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

# 代理旁路默认后缀：E-Hentai H@H 图片节点是住宅线路缓存，
# 经代理（尤其境外出口/数据中心 IP）访问常被节点拒绝，表现为 SSL 握手中断；直连通常可达
DEFAULT_PROXY_BYPASS = 'hath.network'

_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    ' (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)

_thread_local = threading.local()


def get_thread_session():
    """线程（gevent 下为协程）本地复用的 requests.Session。

    连接池化避免每请求 TCP+TLS 握手；延迟创建以兼容 gevent
    monkeypatch（worker 首次使用时 socket 才已被补丁）。
    """
    session = getattr(_thread_local, 'session', None)
    if session is None:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=4)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        session.headers['User-Agent'] = _USER_AGENT
        _thread_local.session = session
    return session


def cookie_header_to_dict(cookie):
    """'k1=v1; k2=v2' 字符串 -> dict，供请求级 cookies 参数使用。"""
    jar = {}
    for part in (cookie or '').split(';'):
        part = part.strip()
        if '=' in part:
            key, _, val = part.partition('=')
            jar[key.strip()] = val.strip()
    return jar


def encoding_from_headers(resp):
    """从 Content-Type 头解析 charset，无则 None（调用方回退 utf-8）。

    不用 apparent_encoding：字符集探测器需扫描整个响应体，大页面
    单次可达数十毫秒，抓取数百页时开销显著；受支持的源站均为 UTF-8。
    """
    m = re.search(r'charset=([\w-]+)', resp.headers.get('Content-Type', ''), re.I)
    return m.group(1) if m else None


def _host_matches_bypass(url):
    """目标 URL 的 host 是否命中代理旁路后缀列表（命中则直连不走代理）。"""
    from app.models import Setting

    raw = Setting.get('proxy_bypass', DEFAULT_PROXY_BYPASS)
    suffixes = [s.strip().lower() for s in raw.split(',') if s.strip()]
    if not suffixes:
        return False
    try:
        host = (urlparse(url.strip()).hostname or '').lower()
    except (ValueError, AttributeError):
        return False
    return any(host == s or host.endswith('.' + s) for s in suffixes)


def get_proxy_handler(url=None):
    from app.models import Setting
    if Setting.get('proxy_enabled', '0') != '1':
        return None
    if url is not None and _host_matches_bypass(url):
        return None
    proxy_type = Setting.get('proxy_type', 'http')
    host = Setting.get('proxy_host', '').strip()
    port = Setting.get('proxy_port', '').strip()
    user = Setting.get('proxy_user', '').strip()
    pwd = Setting.get('proxy_pass', '').strip()
    if not host:
        return None
    auth = f"{user}:{pwd}@" if user else ""
    if proxy_type == 'socks5':
        scheme = 'socks5'
        proxy_url = f"socks5://{auth}{host}"
        if port:
            proxy_url += f":{port}"
    elif proxy_type == 'https':
        scheme = 'https'
        proxy_url = f"https://{auth}{host}"
        if port:
            proxy_url += f":{port}"
    else:
        scheme = 'http'
        proxy_url = f"http://{auth}{host}"
        if port:
            proxy_url += f":{port}"
    return {'http': proxy_url, 'https': proxy_url}


def get_cookie_for_url(url):
    from app.models import Setting
    url_lower = url.lower()
    if 'exhentai.org' in url_lower:
        return Setting.get('cookie_exhentai', '').strip()
    elif 'e-hentai.org' in url_lower or 'ehtracker.org' in url_lower:
        return Setting.get('cookie_ehentai', '').strip()
    elif 'nhentai.net' in url_lower:
        return Setting.get('cookie_nhentai', '').strip()
    return ''


def parse_proxy_url(proxy_url):
    parsed = urlparse(proxy_url)
    return {
        'host': parsed.hostname or '',
        'port': parsed.port or 1080,
        'user': parsed.username or '',
        'pwd': parsed.password or '',
    }


def urlopen_with_proxy(url, timeout=15, retries=3):
    """获取 URL 内容，自动附加 UA/Cookie/代理。失败自动重试。

    GFW 的 TCP RST 具有随机性，重试可提高成功率。
    Cookie/代理按请求级参数传入，不污染共享 Session 状态。
    重试覆盖全部 RequestException（连接/超时/SSL 等）；非 2xx 同样按
    瞬时错误处理（限流/抖动重试可自愈），耗尽后抛最后一次异常。
    """
    last_exc = None
    for attempt in range(retries):
        try:
            session = get_thread_session()
            kwargs = {'timeout': timeout}

            cookie = get_cookie_for_url(url)
            if cookie:
                kwargs['cookies'] = cookie_header_to_dict(cookie)

            proxy_dict = get_proxy_handler(url)
            if proxy_dict:
                kwargs['proxies'] = proxy_dict

            resp = session.get(url, **kwargs)
            if resp.status_code >= 400:
                raise requests.HTTPError(
                    f'HTTP {resp.status_code}: {url}', response=resp)
            resp.encoding = encoding_from_headers(resp) or 'utf-8'
            return resp.text
        except requests.RequestException as e:
            last_exc = e
            if attempt + 1 < retries:
                import time
                time.sleep(1 * (attempt + 1))
    raise last_exc
