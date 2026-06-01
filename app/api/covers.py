from flask import Blueprint, request, send_from_directory
import os
from config import COVERS_DIR
from app.api.utils import success_response, error_response, ErrorCode

bp = Blueprint('api_covers', __name__, url_prefix='/api/v1/covers')


@bp.route('/<path:filename>', methods=['GET'])
def get_cover(filename):
    cover_path = os.path.join(COVERS_DIR, filename)
    cover_dir = os.path.dirname(cover_path)
    cover_base = os.path.basename(cover_path)
    if os.path.exists(cover_path):
        return send_from_directory(cover_dir, cover_base)
    return error_response(ErrorCode.NOT_FOUND, '封面不存在')
