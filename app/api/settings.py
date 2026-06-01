import json

from flask import Blueprint, request, Response
from app import db
from app.models import Setting, Comic
from app.utils.proxy_utils import parse_proxy_url
from app.clients.qbittorrent_client import QbittorrentClient
from app.clients.http_client import urlopen_native
from app.api.utils import success_response, error_response, ErrorCode
from app.api.auth import device_required

bp = Blueprint('api_settings', __name__, url_prefix='/api/v1/settings')


@bp.route('', methods=['GET'])
@device_required
def get_settings():
    keys = [
        'site_name', 'per_page', 'max_content_length', 'chunk_size',
        'upload_interval', 'auto_cover', 'cover_width', 'cover_quality',
        'proxy_enabled', 'proxy_type', 'proxy_host', 'proxy_port',
        'proxy_user', 'cookie_ehentai', 'cookie_exhentai', 'cookie_nhentai',
        'qb_enabled', 'qb_host', 'qb_port', 'qb_user', 'qb_category',
        'qb_download_path', 'tag_mapping',
    ]
    data = {}
    for key in keys:
        data[key] = Setting.get(key, '')
    data['proxy_pass'] = '******' if Setting.get('proxy_pass', '') else ''
    data['qb_pass'] = '******' if Setting.get('qb_pass', '') else ''
    return success_response(data=data)


@bp.route('', methods=['PUT'])
@device_required
def update_settings():
    data = request.get_json(silent=True) or {}
    if not data:
        return error_response(ErrorCode.BAD_REQUEST, '无效数据')

    int_fields = {
        'per_page': (1, 100),
        'max_content_length': (100, 51200),
        'chunk_size': (1, 100),
        'cover_width': (100, 1000),
        'cover_quality': (10, 100),
    }
    float_fields = {
        'upload_interval': (0, 30),
    }

    for field, (min_val, max_val) in int_fields.items():
        if field in data:
            try:
                val = int(data[field])
                if val < min_val or val > max_val:
                    return error_response(ErrorCode.BAD_REQUEST,
                                          f'{field} 必须在 {min_val}-{max_val} 之间')
            except (ValueError, TypeError):
                return error_response(ErrorCode.BAD_REQUEST, f'{field} 必须为整数')

    for field, (min_val, max_val) in float_fields.items():
        if field in data:
            try:
                val = float(data[field])
                if val < min_val or val > max_val:
                    return error_response(ErrorCode.BAD_REQUEST,
                                          f'{field} 必须在 {min_val}-{max_val} 之间')
            except (ValueError, TypeError):
                return error_response(ErrorCode.BAD_REQUEST, f'{field} 必须为数值')

    str_fields = [
        'site_name', 'auto_cover', 'proxy_enabled', 'proxy_type',
        'proxy_host', 'proxy_port', 'proxy_user',
        'cookie_ehentai', 'cookie_exhentai', 'cookie_nhentai',
        'qb_enabled', 'qb_host', 'qb_port', 'qb_user', 'qb_category',
        'qb_download_path', 'tag_mapping',
    ]
    for field in str_fields:
        if field in data:
            Setting.set(field, str(data[field]).strip())

    for field, (min_val, max_val) in int_fields.items():
        if field in data:
            Setting.set(field, str(int(data[field])))

    for field, (min_val, max_val) in float_fields.items():
        if field in data:
            Setting.set(field, str(float(data[field])))

    if 'proxy_pass' in data and data['proxy_pass'] != '******':
        Setting.set('proxy_pass', str(data['proxy_pass']).strip())
    if 'qb_pass' in data and data['qb_pass'] != '******':
        Setting.set('qb_pass', str(data['qb_pass']).strip())

    return success_response(message='设置已保存')


@bp.route('/backup', methods=['GET'])
@device_required
def backup_settings():
    settings = Setting.query.all()
    data = {s.key: s.value for s in settings}
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content,
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=manhua_settings.json'}
    )


@bp.route('/import', methods=['POST'])
@device_required
def import_settings():
    if 'file' not in request.files:
        data = request.get_json(silent=True) or {}
        if not data:
            return error_response(ErrorCode.BAD_REQUEST, '请上传文件或提供JSON数据')
        if not isinstance(data, dict):
            return error_response(ErrorCode.BAD_REQUEST, '数据格式错误：需要JSON对象')
        count = 0
        for key, value in data.items():
            if isinstance(value, str):
                Setting.set(key, value)
                count += 1
        db.session.commit()
        return success_response(message=f'导入成功，已更新 {count} 项设置')

    f = request.files['file']
    if not f.filename:
        return error_response(ErrorCode.BAD_REQUEST, '未选择文件')
    try:
        content = f.read().decode('utf-8')
        data = json.loads(content)
        if not isinstance(data, dict):
            return error_response(ErrorCode.BAD_REQUEST, '文件格式错误：需要JSON对象')
        count = 0
        for key, value in data.items():
            if isinstance(value, str):
                Setting.set(key, value)
                count += 1
        db.session.commit()
        return success_response(message=f'导入成功，已更新 {count} 项设置')
    except json.JSONDecodeError:
        return error_response(ErrorCode.BAD_REQUEST, '文件格式错误：无效的JSON')
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f'导入失败: {str(e)}')


@bp.route('/test-proxy', methods=['POST'])
@device_required
def test_proxy():
    import time
    data = request.get_json(silent=True) or {}
    enabled = data.get('proxy_enabled', '0')
    if enabled != '1':
        return success_response(data={'success': False, 'message': '代理未启用'})

    proxy_type = data.get('proxy_type', 'http')
    host = data.get('proxy_host', '').strip()
    port = data.get('proxy_port', '').strip()
    user = data.get('proxy_user', '').strip()
    pwd = data.get('proxy_pass', '').strip()

    if not host:
        return success_response(data={'success': False, 'message': '代理地址不能为空'})

    auth = f"{user}:{pwd}@" if user else ""
    if proxy_type == 'socks5':
        proxy_url = f"socks5://{auth}{host}"
        if port:
            proxy_url += f":{port}"
    elif proxy_type == 'https':
        proxy_url = f"https://{auth}{host}"
        if port:
            proxy_url += f":{port}"
    else:
        proxy_url = f"http://{auth}{host}"
        if port:
            proxy_url += f":{port}"

    proxy_dict = {'http': proxy_url, 'https': proxy_url}
    test_url = 'https://e-hentai.org/'
    start = time.time()

    try:
        from urllib.request import urlopen, Request, build_opener, ProxyHandler
        req = Request(test_url, headers={'User-Agent': 'Mozilla/5.0'})

        if proxy_type == 'socks5':
            try:
                import socks
                import socket
                old_socket = socket.socket
                parsed = parse_proxy_url(proxy_url)
                if parsed['user']:
                    socks.set_default_proxy(socks.SOCKS5, parsed['host'], parsed['port'],
                                            True, parsed['user'], parsed['pwd'])
                else:
                    socks.set_default_proxy(socks.SOCKS5, parsed['host'], parsed['port'])
                socket.socket = socks.socksocket
                try:
                    resp = urlopen(req, timeout=15)
                    resp.read()
                finally:
                    socket.socket = old_socket
            except ImportError:
                return success_response(data={
                    'success': False,
                    'message': 'SOCKS5 需要 PySocks 库'
                })
        else:
            handler = ProxyHandler(proxy_dict)
            opener = build_opener(handler)
            resp = opener.open(req, timeout=15)
            resp.read()

        elapsed = round((time.time() - start) * 1000)
        return success_response(data={
            'success': True,
            'message': f'连接成功（耗时 {elapsed}ms）'
        })
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        return success_response(data={
            'success': False,
            'message': f'连接失败: {str(e)}（耗时 {elapsed}ms）'
        })


@bp.route('/test-qbittorrent', methods=['POST'])
@device_required
def test_qbittorrent():
    import time
    data = request.get_json(silent=True) or {}
    host = data.get('qb_host', '').strip()
    port = data.get('qb_port', '').strip()
    user = data.get('qb_user', 'admin').strip()
    pwd = data.get('qb_pass', '').strip()

    if not host:
        return success_response(data={'success': False, 'message': '请填写 qBittorrent 地址'})

    start = time.time()
    try:
        qb = QbittorrentClient(host=host, port=port, username=user, password=pwd)
        qb_info, qb_err = qb.login()
        elapsed = round((time.time() - start) * 1000)

        if qb_err:
            return success_response(data={
                'success': False,
                'message': f'{qb_err}（耗时 {elapsed}ms）'
            })

        version_resp = urlopen_native(
            f"{qb_info['base_url']}/api/v2/app/version",
            headers={'Cookie': qb_info['cookie']},
            timeout=10
        )
        version = version_resp.get('body', '').strip()
        return success_response(data={
            'success': True,
            'message': f'连接成功 v{version}（耗时 {elapsed}ms）'
        })
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        return success_response(data={
            'success': False,
            'message': f'连接失败: {str(e)}（耗时 {elapsed}ms）'
        })
