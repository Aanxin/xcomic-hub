from flask import Blueprint, request
from datetime import datetime
from app import db
from app.models import Device
from app.api.auth import generate_device_token, decode_token, device_required
from app.api.utils import success_response, error_response, ErrorCode
from app.utils.tag_utils import get_tag_mapping

bp = Blueprint('api_auth', __name__, url_prefix='/api/v1/auth')


def _build_sync_data():
    mapping = get_tag_mapping()
    tag_mapping_list = [{'original': k, 'display': v} for k, v in mapping.items()]
    return {
        'tag_mapping': tag_mapping_list,
        'tag_mapping_version': str(len(mapping)),
    }


@bp.route('/connect', methods=['POST'])
def connect():
    data = request.get_json(silent=True) or {}
    device_id = data.get('device_id', '').strip()
    device_name = data.get('device_name', '').strip()
    device_type = data.get('device_type', '').strip()

    if not device_id:
        return error_response(ErrorCode.BAD_REQUEST, '设备标识不能为空')

    if len(device_id) < 1 or len(device_id) > 128:
        return error_response(ErrorCode.BAD_REQUEST, '设备标识长度应在1-128之间')

    sync = _build_sync_data()
    device = Device.query.filter_by(device_id=device_id).first()

    if device:
        device.connect_count += 1
        device.last_active_at = datetime.utcnow()
        if device_name:
            device.device_name = device_name
        if device_type:
            device.device_type = device_type
        db.session.commit()

        token = generate_device_token(device_id)
        return success_response(data={
            'access_token': token,
            'token_type': 'Bearer',
            'expires_in': 86400 * 30,
            'device_id': device_id,
            'device_name': device.device_name,
            'is_new_device': False,
            **sync,
        }, message='设备连接成功')

    device = Device(
        device_id=device_id,
        device_name=device_name or f'设备-{device_id[:8]}',
        device_type=device_type,
        connect_count=1,
        last_active_at=datetime.utcnow(),
    )
    db.session.add(device)
    db.session.commit()

    token = generate_device_token(device_id)
    return success_response(data={
        'access_token': token,
        'token_type': 'Bearer',
        'expires_in': 86400 * 30,
        'device_id': device_id,
        'device_name': device.device_name,
        'is_new_device': True,
        **sync,
    }, message='设备注册并连接成功')


@bp.route('/reconnect', methods=['POST'])
def reconnect():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header:
        return error_response(ErrorCode.UNAUTHORIZED, '缺少Token')
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return error_response(ErrorCode.UNAUTHORIZED, 'Token格式错误')
    token = parts[1]
    payload, err = decode_token(token)
    if err:
        return error_response(ErrorCode.UNAUTHORIZED, err)

    device_id = payload.get('device_id', '')

    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        return error_response(ErrorCode.UNAUTHORIZED, '设备未注册')

    device.connect_count += 1
    device.last_active_at = datetime.utcnow()
    db.session.commit()

    sync = _build_sync_data()
    new_token = generate_device_token(device_id)
    return success_response(data={
        'access_token': new_token,
        'token_type': 'Bearer',
        'expires_in': 86400 * 30,
        'device_id': device_id,
        'device_name': device.device_name,
        **sync,
    }, message='重新连接成功')


@bp.route('/sync', methods=['GET'])
def get_sync_data():
    sync = _build_sync_data()
    return success_response(data=sync)


@bp.route('/status', methods=['GET'])
def auth_status():
    total_devices = Device.query.count()
    return success_response(data={
        'total_devices': total_devices,
    })


@bp.route('/devices', methods=['GET'])
@device_required
def list_devices():
    devices = Device.query.order_by(Device.last_active_at.desc()).all()
    return success_response(data=[d.to_dict() for d in devices])


@bp.route('/devices/<int:device_db_id>', methods=['DELETE'])
@device_required
def remove_device(device_db_id):
    device = Device.query.get(device_db_id)
    if not device:
        return error_response(ErrorCode.NOT_FOUND, '设备不存在')
    current_device = request.current_device
    if device.device_id == current_device.device_id:
        return error_response(ErrorCode.BAD_REQUEST, '不能删除当前设备')
    db.session.delete(device)
    db.session.commit()
    return success_response(message='设备已删除')


@bp.route('/devices/<int:device_db_id>', methods=['PUT'])
@device_required
def update_device(device_db_id):
    device = Device.query.get(device_db_id)
    if not device:
        return error_response(ErrorCode.NOT_FOUND, '设备不存在')
    data = request.get_json(silent=True) or {}
    if data.get('device_name'):
        device.device_name = data['device_name'].strip()
    db.session.commit()
    return success_response(data=device.to_dict(), message='设备信息已更新')


@bp.route('/verify-device', methods=['POST'])
def verify_device():
    data = request.get_json(silent=True) or {}
    device_id = data.get('device_id', '').strip()
    if not device_id:
        return error_response(ErrorCode.BAD_REQUEST, '设备标识不能为空')
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        return success_response(data={
            'registered': False,
        })
    return success_response(data={
        'registered': True,
        'device_name': device.device_name,
        'last_active_at': device.last_active_at.isoformat() if device.last_active_at else None,
    })
