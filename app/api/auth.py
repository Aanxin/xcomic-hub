import jwt
import time
from functools import wraps
from flask import request, current_app
from app.api.utils import error_response, ErrorCode


def generate_device_token(device_id, expires_in=86400 * 30):
    now = int(time.time())
    payload = {
        'device_id': device_id,
        'iat': now,
        'exp': now + expires_in,
        'type': 'device',
    }
    token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')
    return token


def decode_token(token):
    try:
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
        return payload, None
    except jwt.ExpiredSignatureError:
        return None, 'Token已过期'
    except jwt.InvalidTokenError:
        return None, '无效Token'


def device_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header:
            return error_response(ErrorCode.UNAUTHORIZED, '缺少Authorization头，请先连接设备')
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return error_response(ErrorCode.UNAUTHORIZED, 'Authorization格式错误')
        token = parts[1]
        payload, err = decode_token(token)
        if err:
            return error_response(ErrorCode.UNAUTHORIZED, err)
        if payload.get('type') != 'device':
            return error_response(ErrorCode.UNAUTHORIZED, '请使用设备Token')

        device_id = payload.get('device_id', '')
        from app.models import Device
        device = Device.query.filter_by(device_id=device_id).first()
        if not device:
            return error_response(ErrorCode.UNAUTHORIZED, '设备未注册，请先连接')

        from datetime import datetime
        device.connect_count += 1
        device.last_active_at = datetime.utcnow()
        from app import db
        db.session.commit()

        request.current_device = device
        return f(*args, **kwargs)
    return decorated


def optional_device(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == 'bearer':
                token = parts[1]
                payload, err = decode_token(token)
                if not err and payload.get('type') == 'device':
                    device_id = payload.get('device_id', '')
                    from app.models import Device
                    device = Device.query.filter_by(device_id=device_id).first()
                    if device:
                        request.current_device = device
                        return f(*args, **kwargs)
        request.current_device = None
        return f(*args, **kwargs)
    return decorated
