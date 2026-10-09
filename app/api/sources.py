"""漫画源浏览 API：源列表 / 搜索 / 最新 / 画廊详情 / 图片代理 / 抓取。"""

import hashlib
import os

from flask import Blueprint, request, Response, send_from_directory

from app.api.auth import optional_device
from app.api.utils import success_response, error_response, ErrorCode
from app.services.source_browse_service import SourceBrowseService
from app.sources.base_source import UnsupportedCategory
from app.sources.image_proxy import fetch_image, is_allowed_image_url
from config import IMAGE_CACHE_DIR

bp = Blueprint('api_sources', __name__, url_prefix='/api/v1/sources')

# 内容类型 -> 缓存扩展名（不在表内的类型不落盘缓存）
_CT_EXT = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/gif': '.gif',
}


@bp.route('', methods=['GET'])
@optional_device
def list_sources():
    return success_response(data=SourceBrowseService.get_sources())


@bp.route('/<source_id>/latest', methods=['GET'])
@optional_device
def latest(source_id):
    page = request.args.get('page', 1, type=int) or 1
    cursor = (request.args.get('cursor') or '').strip() or None
    category = (request.args.get('category') or 'home').strip().lower()
    period = (request.args.get('period') or 'all').strip().lower()
    sort = (request.args.get('sort') or '').strip().lower() or None
    language = _parse_language_arg()
    try:
        result = SourceBrowseService.latest(source_id, page=page, language=language, cursor=cursor, category=category, period=period, sort=sort)
    except UnsupportedCategory as e:
        return error_response(ErrorCode.BAD_REQUEST, str(e))
    except ValueError:
        return error_response(ErrorCode.NOT_FOUND, f'未知漫画源: {source_id}')
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f'获取列表失败: {e}')
    _annotate_library(result)
    return success_response(data=result.to_dict())


def _annotate_library(result):
    """按 Comic.source_url 批量标注列表项是否已在库中（in_library）。"""
    from app.models import Comic
    from app.sources.base_source import GalleryCard

    urls = {c.url for c in result.items if isinstance(c, GalleryCard)}
    if not urls:
        return
    existing = {row[0] for row in Comic.query.with_entities(Comic.source_url).filter(
        Comic.source_url.in_(urls))}
    for c in result.items:
        if isinstance(c, GalleryCard):
            c.in_library = c.url in existing


@bp.route('/<source_id>/search', methods=['GET'])
@optional_device
def search(source_id):
    keyword = (request.args.get('keyword') or '').strip()
    if not keyword:
        return error_response(ErrorCode.BAD_REQUEST, '缺少搜索关键词')
    page = request.args.get('page', 1, type=int) or 1
    cursor = (request.args.get('cursor') or '').strip() or None
    sort = (request.args.get('sort') or '').strip().lower() or None
    # tag 点击搜索：源用其站点精确 tag 语法（如 EH 引号+$），手动搜索不传
    exact_tag = (request.args.get('exact_tag') or '').strip().lower() in ('1', 'true')
    language = _parse_language_arg()
    try:
        result = SourceBrowseService.search(source_id, keyword, page=page, language=language, cursor=cursor, sort=sort, exact_tag=exact_tag)
    except ValueError:
        return error_response(ErrorCode.NOT_FOUND, f'未知漫画源: {source_id}')
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f'搜索失败: {e}')
    _annotate_library(result)
    return success_response(data=result.to_dict())


def _parse_language_arg():
    """解析 language 查询参数：缺省默认中文，'all' 表示不过滤。"""
    from app.services.source_browse_service import DEFAULT_LANGUAGE
    language = (request.args.get('language') or '').strip().lower()
    if language in ('all', 'none'):
        return None
    return language or DEFAULT_LANGUAGE


@bp.route('/gallery', methods=['GET'])
@optional_device
def gallery_details():
    url = (request.args.get('url') or '').strip()
    if not url:
        return error_response(ErrorCode.BAD_REQUEST, '缺少画廊地址')
    try:
        details = SourceBrowseService.gallery_details(url)
    except ValueError as e:
        return error_response(ErrorCode.BAD_REQUEST, str(e))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f'获取详情失败: {e}')
    return success_response(data=details)


@bp.route('/image', methods=['GET'])
def proxy_image():
    """图片代理：白名单校验后带 Referer/Cookie 拉取并转发，成功响应落盘缓存。

    浏览器缓存只有单设备效果；磁盘缓存让换设备/清缓存后的网格缩略图
    不再穿透到源站。
    """
    url = (request.args.get('url') or '').strip()
    if not url:
        return error_response(ErrorCode.BAD_REQUEST, '缺少图片地址')
    if not is_allowed_image_url(url):
        return error_response(ErrorCode.BAD_REQUEST, '不允许的图片地址')

    cache_key = hashlib.md5(url.encode('utf-8')).hexdigest()
    for content_type, ext in _CT_EXT.items():
        cached_path = os.path.join(IMAGE_CACHE_DIR, cache_key + ext)
        if os.path.exists(cached_path) and os.path.getsize(cached_path) > 0:
            resp = send_from_directory(IMAGE_CACHE_DIR, cache_key + ext,
                                       mimetype=content_type)
            resp.headers['Cache-Control'] = 'public, max-age=86400'
            return resp

    import requests as _requests
    try:
        content, content_type = fetch_image(url)
    except _requests.Timeout:
        return error_response(504, '图片获取超时')
    except _requests.HTTPError as e:
        return error_response(502, f'图片获取失败: {e}')
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f'图片获取失败: {e}')

    ext = _CT_EXT.get(content_type.split(';')[0].strip().lower())
    if ext and content:
        try:
            os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
            with open(os.path.join(IMAGE_CACHE_DIR, cache_key + ext), 'wb') as f:
                f.write(content)
        except OSError:
            pass  # 缓存写失败不影响本次响应

    resp = Response(content, mimetype=content_type)
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


@bp.route('/scrape', methods=['POST'])
@optional_device
def start_scrape():
    from app.services.image_scrape_service import ImageScrapeService

    url = (request.get_json(silent=True) or {}).get('url', '').strip()
    if not url:
        return error_response(ErrorCode.BAD_REQUEST, '缺少画廊地址')

    # 同一画廊已有进行中的任务则拒绝
    from app.models import ScrapeTask
    active = ScrapeTask.query.filter_by(url=url).filter(
        ScrapeTask.status.in_(['pending', 'running'])
    ).first()
    if active is not None:
        return error_response(409, '该画廊已有进行中的抓取任务')

    try:
        task_id = ImageScrapeService.start_scrape(url)
    except ValueError as e:
        return error_response(ErrorCode.BAD_REQUEST, str(e))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, f'发起抓取失败: {e}')
    return success_response(data={'task_id': task_id})
