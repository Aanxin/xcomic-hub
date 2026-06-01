import os
import re
import uuid
import hashlib
import threading
import subprocess
import json as _json
import base64
import time as _time
from urllib.parse import urlencode

from app.clients.http_client import urlopen_native
from config import DOWNLOAD_DIR


_qb_session = {'cookie': '', 'base_url': '', 'expires': 0}
_qb_session_lock = threading.Lock()
_qb_add_lock = threading.Lock()


def _extract_hash_from_url(url):
    if not url:
        return ''
    m = re.search(r'/([a-fA-F0-9]{40})\.torrent', url)
    if m:
        return m.group(1).lower()
    m = re.search(r'/([a-fA-F0-9]{64})\.torrent', url)
    if m:
        return m.group(1).lower()
    return ''


def _bencode_find_info(data):
    pos = 0
    length = len(data)

    def skip_value(p):
        if p >= length:
            return p
        ch = data[p:p+1]
        if ch == b'd':
            p += 1
            while p < length and data[p:p+1] != b'e':
                p = skip_value(p)
                if p >= length:
                    break
                p = skip_value(p)
            if p < length:
                p += 1
            return p
        elif ch == b'l':
            p += 1
            while p < length and data[p:p+1] != b'e':
                p = skip_value(p)
            if p < length:
                p += 1
            return p
        elif ch == b'i':
            end = data.find(b'e', p + 1)
            return end + 1 if end >= 0 else length
        else:
            colon = data.find(b':', p, p + 20)
            if colon < 0:
                return length
            try:
                slen = int(data[p:colon])
            except ValueError:
                return length
            return colon + 1 + slen

    if data[0:1] != b'd':
        return None
    pos = 1
    while pos < length and data[pos:pos+1] != b'e':
        key_start = pos
        key_end = skip_value(key_start)
        key = data[key_start:key_end]
        val_start = key_end
        if key == b'4:info':
            val_end = skip_value(val_start)
            return data[val_start:val_end]
        pos = skip_value(val_start)
    return None


def get_torrent_info_hash(torrent_path):
    try:
        with open(torrent_path, 'rb') as f:
            data = f.read()
        info_data = _bencode_find_info(data)
        if not info_data:
            print(f'[种子] 未找到info字典: {torrent_path}')
            return ''
        is_v2_only = b'piece layers' in info_data and b'pieces' not in info_data
        if is_v2_only:
            info_hash = hashlib.sha256(info_data).hexdigest()
            print(f'[种子] v2种子(SHA-256): hash={info_hash}')
        else:
            info_hash = hashlib.sha1(info_data).hexdigest()
            has_v2 = b'piece layers' in info_data or b'file tree' in info_data
            if has_v2:
                print(f'[种子] 混合种子(v1 SHA-1): hash={info_hash}')
            else:
                print(f'[种子] v1种子(SHA-1): hash={info_hash}')
        return info_hash
    except Exception as e:
        print(f'[种子] 解析info_hash失败: {e}')
        return ''


class QbittorrentClient:
    def __init__(self, host=None, port=None, username=None, password=None):
        from app.models import Setting
        self.host = host or Setting.get('qb_host', '').strip()
        self.port = port or Setting.get('qb_port', '8080').strip()
        self.username = username or Setting.get('qb_user', 'admin').strip()
        self.password = password or Setting.get('qb_pass', '').strip()
        self.base_url = f"http://{self.host}:{self.port}"

    def is_configured(self):
        return bool(self.host)

    def login(self):
        with _qb_session_lock:
            now = _time.time()
            if _qb_session['cookie'] and now < _qb_session['expires']:
                return {'base_url': _qb_session['base_url'], 'cookie': _qb_session['cookie']}, None

        if not self.host:
            return None, 'qBittorrent 未配置'

        try:
            login_data = urlencode({'username': self.username, 'password': self.password}).encode()
            resp = urlopen_native(
                f"{self.base_url}/api/v2/auth/login",
                data=login_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=15
            )
            body = resp['body']
            if 'Ok.' not in body:
                print(f'[qBittorrent] 认证失败, 响应: {body}')
                return None, 'qBittorrent 认证失败'
            raw_cookie = resp.get('set_cookie', '') or resp['headers'].get('Set-Cookie', '')
            cookie_parts = []
            for part in raw_cookie.split(';'):
                part = part.strip()
                if '=' in part and part.split('=')[0].strip().upper() not in ('PATH', 'DOMAIN', 'EXPIRES', 'MAX-AGE', 'SECURE', 'HTTPONLY', 'SAMESITE'):
                    cookie_parts.append(part)
            cookie = '; '.join(cookie_parts)
            if not cookie:
                print(f'[qBittorrent] 登录成功但未获取到Cookie, set_cookie: {resp.get("set_cookie", "")}, headers: {resp.get("headers", {})}')
                return None, 'qBittorrent 登录成功但未获取到Cookie'
            print(f'[qBittorrent] 连接成功 {self.base_url}')

            with _qb_session_lock:
                _qb_session['cookie'] = cookie
                _qb_session['base_url'] = self.base_url
                _qb_session['expires'] = _time.time() + 300

            return {'base_url': self.base_url, 'cookie': cookie}, None
        except Exception as e:
            print(f'[qBittorrent] 连接失败 {self.base_url}: {e}')
            with _qb_session_lock:
                _qb_session['cookie'] = ''
                _qb_session['expires'] = 0
            return None, f'qBittorrent 连接失败: {str(e)}'

    def add_torrent(self, torrent_url, category='', savepath=''):
        qb_info, qb_err = self.login()
        if qb_err:
            return False, qb_err, ''

        base_url = qb_info['base_url']
        cookie = qb_info['cookie']

        url_hash = _extract_hash_from_url(torrent_url)
        if url_hash:
            print(f'[qBittorrent] 从URL提取到hash: {url_hash}')

        torrent_path = None
        info_hash = ''
        try:
            resp = urlopen_native(torrent_url, timeout=30)
            if resp.get('status') != 200:
                raise Exception(f'下载种子文件失败: HTTP {resp.get("status")}')
            torrent_data = resp['body'].encode('utf-8', errors='ignore')
            if not torrent_data or len(torrent_data) < 50:
                raise Exception(f'种子文件内容异常: {len(torrent_data)} bytes')
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            temp_name = f"_temp_{uuid.uuid4().hex}.torrent"
            torrent_path = os.path.join(DOWNLOAD_DIR, temp_name)
            with open(torrent_path, 'wb') as f:
                f.write(torrent_data)
            info_hash = get_torrent_info_hash(torrent_path)
            if not info_hash and url_hash:
                info_hash = url_hash
                print(f'[qBittorrent] 本地hash计算失败，使用URL中的hash: {info_hash}')
            elif info_hash and url_hash and info_hash.lower() != url_hash.lower():
                info_hash = f'{url_hash},{info_hash}'
                print(f'[qBittorrent] hash不一致，存储双hash(URL优先): {info_hash}')
            print(f'[qBittorrent] 种子文件已下载: {temp_name}, info_hash={info_hash}')
        except Exception as e:
            print(f'[qBittorrent] 下载种子文件失败，回退到URL方式: {e}')
            torrent_path = None

        if torrent_path and info_hash:
            ok, err, _ = self.add_torrent_by_file(torrent_path, category, savepath)
            try:
                if os.path.exists(torrent_path):
                    os.remove(torrent_path)
                    print(f'[qBittorrent] 已清理临时种子: {os.path.basename(torrent_path)}')
            except Exception:
                pass
            if ok:
                print(f'[qBittorrent] 通过文件上传添加种子，预知hash={info_hash}')
                return True, 'ok', info_hash
            else:
                print(f'[qBittorrent] 文件上传失败({err})，回退到URL方式')

        with _qb_add_lock:
            try:
                before_hashes = set()
                try:
                    before_resp = urlopen_native(
                        f"{base_url}/api/v2/torrents/info",
                        headers={'Cookie': cookie},
                        timeout=10
                    )
                    before_list = _json.loads(before_resp['body'])
                    for t in before_list:
                        h = t.get('hash', '')
                        if h:
                            before_hashes.add(h.upper())
                except Exception:
                    pass

                params = {'urls': torrent_url}
                if category:
                    params['category'] = category
                if savepath:
                    params['savepath'] = savepath
                data = urlencode(params).encode()
                resp = urlopen_native(
                    f"{base_url}/api/v2/torrents/add",
                    data=data,
                    headers={'Content-Type': 'application/x-www-form-urlencoded',
                             'Cookie': cookie},
                    timeout=30
                )
                body = resp['body']
                print(f'[qBittorrent] 添加种子响应: {body}, URL: {torrent_url}')

                if not info_hash:
                    if url_hash:
                        info_hash = url_hash
                        print(f'[qBittorrent] 使用URL中的hash: {info_hash}')
                    else:
                        for attempt in range(3):
                            _time.sleep(2 + attempt)
                            try:
                                after_resp = urlopen_native(
                                    f"{base_url}/api/v2/torrents/info",
                                    headers={'Cookie': cookie},
                                    timeout=10
                                )
                                after_list = _json.loads(after_resp['body'])
                                new_torrents = [t for t in after_list if t.get('hash', '').upper() not in before_hashes]
                                if len(new_torrents) == 1:
                                    t = new_torrents[0]
                                    info_hash = t.get('hash', '')
                                    print(f'[qBittorrent] 唯一新种子匹配: hash={info_hash}, name={t.get("name", "")}')
                                    break
                                elif len(new_torrents) > 1:
                                    for t in new_torrents:
                                        info_hash = t.get('hash', '')
                                        print(f'[qBittorrent] 多个新种子，取第一个: hash={info_hash}, name={t.get("name", "")}')
                                        break
                                    break
                            except Exception as _e:
                                print(f'[qBittorrent] 第{attempt+1}次获取新种子hash失败: {_e}')

                return resp['status'] == 200, 'ok', info_hash
            except Exception as e:
                print(f'[qBittorrent] 添加种子失败: {e}')
                import traceback
                traceback.print_exc()
                return False, str(e), ''
            finally:
                if torrent_path:
                    try:
                        if os.path.exists(torrent_path):
                            os.remove(torrent_path)
                            print(f'[qBittorrent] 已清理临时种子: {os.path.basename(torrent_path)}')
                    except Exception:
                        pass

    def add_torrent_by_file(self, torrent_path, category='', savepath=''):
        qb_info, qb_err = self.login()
        if qb_err:
            return False, qb_err, ''

        base_url = qb_info['base_url']
        cookie = qb_info['cookie']

        pre_hash = get_torrent_info_hash(torrent_path)
        if pre_hash:
            print(f'[qBittorrent] 种子文件预解析hash: {pre_hash}')

        with _qb_add_lock:
            try:
                with open(torrent_path, 'rb') as f:
                    torrent_data = f.read()

                boundary = uuid.uuid4().hex
                body_parts = []

                if category:
                    body_parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="category"\r\n\r\n{category}\r\n'.encode())
                if savepath:
                    body_parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="savepath"\r\n\r\n{savepath}\r\n'.encode())

                filename = os.path.basename(torrent_path)
                body_parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="torrents"; filename="{filename}"\r\nContent-Type: application/x-bittorrent\r\n\r\n'.encode())
                body_parts.append(torrent_data)
                body_parts.append(f'\r\n--{boundary}--\r\n'.encode())

                body = b''.join(body_parts)
                body_b64 = base64.b64encode(body).decode('ascii')

                req_info = {
                    'base_url': base_url,
                    'cookie': cookie,
                    'body_b64': body_b64,
                    'boundary': boundary,
                    'timeout': 30
                }

                script = (
                    "import http.client,json,sys,ssl,base64\n"
                    "a=json.loads(sys.stdin.read())\n"
                    "p=__import__('urllib.parse').urlparse(a['base_url'])\n"
                    "h=p.hostname\n"
                    "pt=p.port or (443 if p.scheme=='https' else 80)\n"
                    "if p.scheme=='https':\n"
                    "    ctx=ssl.create_default_context()\n"
                    "    c=http.client.HTTPSConnection(h,pt,context=ctx,timeout=a['timeout'])\n"
                    "else:\n"
                    "    c=http.client.HTTPConnection(h,pt,timeout=a['timeout'])\n"
                    "body=base64.b64decode(a['body_b64'])\n"
                    "c.request('POST','/api/v2/torrents/add',body=body,headers={'Content-Type':f'multipart/form-data; boundary={a[\"boundary\"]}','Cookie':a['cookie'],'Content-Length':str(len(body))})\n"
                    "r=c.getresponse()\n"
                    "print(json.dumps({'status':r.status,'body':r.read().decode('utf-8','ignore')}))\n"
                )

                result = subprocess.run(
                    ['python', '-c', script],
                    input=_json.dumps(req_info),
                    capture_output=True, text=True, timeout=40
                )
                if result.returncode != 0:
                    raise Exception(result.stderr.strip() or f'子进程退出码 {result.returncode}')
                resp_data = _json.loads(result.stdout.strip())
                print(f'[qBittorrent] 添加种子文件响应: {resp_data.get("body", "")}, 文件: {filename}')

                if pre_hash:
                    _time.sleep(2)
                    try:
                        check_resp = urlopen_native(
                            f"{base_url}/api/v2/torrents/info",
                            headers={'Cookie': cookie},
                            timeout=10
                        )
                        check_list = _json.loads(check_resp['body'])
                        for t in check_list:
                            if t.get('hash', '').lower() == pre_hash.lower():
                                print(f'[qBittorrent] hash验证成功: {pre_hash}, name={t.get("name", "")}')
                                return resp_data.get('status') == 200, 'ok', pre_hash
                    except Exception as _e:
                        print(f'[qBittorrent] hash验证查询失败: {_e}')
                    print(f'[qBittorrent] hash验证未找到，回退到前后对比')

                before_hashes = set()
                try:
                    before_resp = urlopen_native(
                        f"{base_url}/api/v2/torrents/info",
                        headers={'Cookie': cookie},
                        timeout=10
                    )
                    before_list = _json.loads(before_resp['body'])
                    for t in before_list:
                        h = t.get('hash', '')
                        if h:
                            before_hashes.add(h.upper())
                except Exception:
                    pass

                info_hash = pre_hash
                if not info_hash:
                    for attempt in range(3):
                        _time.sleep(2 + attempt)
                        try:
                            after_resp = urlopen_native(
                                f"{base_url}/api/v2/torrents/info",
                                headers={'Cookie': cookie},
                                timeout=10
                            )
                            after_list = _json.loads(after_resp['body'])
                            new_torrents = [t for t in after_list if t.get('hash', '').upper() not in before_hashes]
                            if len(new_torrents) == 1:
                                t = new_torrents[0]
                                qb_hash = t.get('hash', '')
                                if pre_hash and qb_hash.lower() != pre_hash.lower():
                                    info_hash = f'{qb_hash},{pre_hash}'
                                    print(f'[qBittorrent] hash不一致，存储双hash(qB优先): {info_hash}')
                                else:
                                    info_hash = qb_hash
                                print(f'[qBittorrent] 唯一新种子匹配: hash={info_hash}, name={t.get("name", "")}')
                                break
                            elif len(new_torrents) > 1:
                                for t in new_torrents:
                                    info_hash = t.get('hash', '')
                                    print(f'[qBittorrent] 多个新种子，取第一个: hash={info_hash}, name={t.get("name", "")}')
                                    break
                                break
                        except Exception as _e:
                            print(f'[qBittorrent] 第{attempt+1}次获取新种子hash失败: {_e}')

                return resp_data.get('status') == 200, 'ok', info_hash
            except subprocess.TimeoutExpired:
                return False, '请求超时', ''
            except Exception as e:
                print(f'[qBittorrent] 添加种子文件失败: {e}')
                import traceback
                traceback.print_exc()
                return False, str(e), ''

    def get_torrents_info(self, hashes=None):
        qb_info, qb_err = self.login()
        if not qb_info:
            return []
        base_url = qb_info['base_url']
        cookie = qb_info['cookie']
        try:
            params = {}
            if hashes:
                params['hashes'] = '|'.join(hashes) if isinstance(hashes, list) else hashes
            url = f"{base_url}/api/v2/torrents/info"
            if params:
                url += '?' + urlencode(params)
            resp = urlopen_native(url, headers={'Cookie': cookie}, timeout=10)
            return _json.loads(resp['body'])
        except Exception as e:
            print(f'[qBittorrent] 获取种子信息失败: {e}')
            return []

    def delete_torrent(self, info_hash, delete_files=True):
        qb_info, qb_err = self.login()
        if qb_err or not qb_info:
            return False, qb_err
        try:
            data = urlencode({
                'hashes': info_hash,
                'deleteFiles': 'true' if delete_files else 'false'
            }).encode()
            resp = urlopen_native(
                f"{qb_info['base_url']}/api/v2/torrents/delete",
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded',
                         'Cookie': qb_info['cookie']},
                timeout=10
            )
            print(f'[qBittorrent] 已删除种子: {info_hash}, 响应: {resp.get("body", "")}')
            return True, None
        except Exception as e:
            print(f'[qBittorrent] 删除种子失败: {e}')
            return False, str(e)
