import re
from urllib.parse import urlparse

import requests


def get_proxy_handler():
    from app.models import Setting
    if Setting.get('proxy_enabled', '0') != '1':
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


def urlopen_with_proxy(url, timeout=15):
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

    cookie = get_cookie_for_url(url)
    if cookie:
        for part in cookie.split(';'):
            part = part.strip()
            if '=' in part:
                key, _, val = part.partition('=')
                session.cookies.set(key.strip(), val.strip())

    proxy_dict = get_proxy_handler()
    if proxy_dict:
        session.proxies = proxy_dict

    resp = session.get(url, timeout=timeout)
    resp.encoding = resp.apparent_encoding or 'utf-8'
    return resp.text
