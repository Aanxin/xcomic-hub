from flask import jsonify
from functools import wraps


class ErrorCode:
    SUCCESS = 0
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409
    VALIDATION_ERROR = 422
    INTERNAL_ERROR = 500
    SERVICE_UNAVAILABLE = 503


ERROR_MESSAGES = {
    ErrorCode.BAD_REQUEST: '请求参数错误',
    ErrorCode.UNAUTHORIZED: '未授权，请先登录',
    ErrorCode.FORBIDDEN: '权限不足',
    ErrorCode.NOT_FOUND: '资源不存在',
    ErrorCode.CONFLICT: '资源冲突',
    ErrorCode.VALIDATION_ERROR: '数据验证失败',
    ErrorCode.INTERNAL_ERROR: '服务器内部错误',
    ErrorCode.SERVICE_UNAVAILABLE: '服务暂不可用',
}


def success_response(data=None, message='操作成功', code=ErrorCode.SUCCESS, status_code=200):
    resp = {
        'code': code,
        'message': message,
    }
    if data is not None:
        resp['data'] = data
    return jsonify(resp), status_code


def error_response(code=ErrorCode.BAD_REQUEST, message=None, details=None, status_code=None):
    if message is None:
        message = ERROR_MESSAGES.get(code, '未知错误')
    if status_code is None:
        status_code = min(code, 599) if 400 <= code <= 599 else 400
    resp = {
        'code': code,
        'message': message,
    }
    if details is not None:
        resp['details'] = details
    return jsonify(resp), status_code


def paginate_response(query, page, per_page, serializer=None):
    per_page = min(max(per_page, 1), 100)
    page = max(page, 1)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    items = pagination.items
    if serializer:
        items = [serializer(item) for item in items]
    return {
        'items': items,
        'pagination': {
            'page': pagination.page,
            'per_page': pagination.per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_prev': pagination.has_prev,
            'has_next': pagination.has_next,
        }
    }


def validate_required(data, fields):
    missing = []
    for field in fields:
        if isinstance(field, tuple):
            name, label = field
        else:
            name = label = field
        if data.get(name) is None or data.get(name) == '':
            missing.append(label)
    if missing:
        return False, missing
    return True, []
