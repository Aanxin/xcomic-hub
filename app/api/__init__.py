from flask import Blueprint
from app.api.auth_routes import bp as auth_bp
from app.api.comics import bp as comics_bp
from app.api.collections import bp as collections_bp
from app.api.uploads import bp as uploads_bp
from app.api.downloads import bp as downloads_bp
from app.api.scraper import bp as scraper_bp
from app.api.settings import bp as settings_bp
from app.api.history import bp as history_bp
from app.api.stats import bp as stats_bp
from app.api.covers import bp as covers_bp
from app.api.tags import bp as tags_bp


api_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')


def register_api_blueprints(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(comics_bp)
    app.register_blueprint(collections_bp)
    app.register_blueprint(uploads_bp)
    app.register_blueprint(downloads_bp)
    app.register_blueprint(scraper_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(covers_bp)
    app.register_blueprint(tags_bp)

    @app.route('/api/v1/')
    def api_v1_index():
        return jsonify({
            'code': 0,
            'message': 'xcomic API v1',
            'data': {
                'version': 'v1',
                'endpoints': [
                    '/api/v1/auth',
                    '/api/v1/comics',
                    '/api/v1/collections',
                    '/api/v1/uploads',
                    '/api/v1/downloads',
                    '/api/v1/scraper',
                    '/api/v1/settings',
                    '/api/v1/history',
                    '/api/v1/stats',
                    '/api/v1/tags',
                    '/api/v1/covers',
                ]
            }
        })

    @app.errorhandler(404)
    def api_not_found(e):
        if request.path.startswith('/api/'):
            return jsonify({
                'code': 404,
                'message': '接口不存在',
            }), 404
        return e

    @app.errorhandler(405)
    def api_method_not_allowed(e):
        if request.path.startswith('/api/'):
            return jsonify({
                'code': 405,
                'message': '请求方法不允许',
            }), 405
        return e

    @app.errorhandler(413)
    def api_request_entity_too_large(e):
        if request.path.startswith('/api/'):
            return jsonify({
                'code': 413,
                'message': '请求体过大',
            }), 413
        return e

    @app.errorhandler(500)
    def api_internal_error(e):
        if request.path.startswith('/api/'):
            return jsonify({
                'code': 500,
                'message': '服务器内部错误',
            }), 500
        return e


from flask import jsonify, request
