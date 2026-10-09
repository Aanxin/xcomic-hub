"""站点设置统一读写服务。

web 表单（routes.py /settings）与 REST API（api/settings.py）共用同一份
字段定义，避免两处手写解析/校验漂移。字段属性：类型（int/float/str）、
默认值、数值闭区间范围、是否敏感（API 读取时脱敏）。
"""


class SettingsService:

    MASK = '******'

    # key: (类型, 默认值, 最小值, 最大值)；数值型范围为闭区间，None 表示不设限
    FIELD_SPECS = {
        'site_name': ('str', 'xcomic', None, None),
        'per_page': ('int', '12', 1, 100),
        'max_content_length': ('int', '2048', 100, 51200),
        'chunk_size': ('int', '5', 1, 100),
        'upload_interval': ('float', '1', 0, 30),
        'auto_cover': ('str', '1', None, None),
        'cover_width': ('int', '300', 100, 1000),
        'cover_quality': ('int', '85', 10, 100),
        'proxy_enabled': ('str', '0', None, None),
        'proxy_type': ('str', 'http', None, None),
        'proxy_host': ('str', '', None, None),
        'proxy_port': ('str', '', None, None),
        'proxy_user': ('str', '', None, None),
        'proxy_pass': ('str', '', None, None),
        'proxy_bypass': ('str', 'hath.network', None, None),
        'cookie_ehentai': ('str', '', None, None),
        'cookie_exhentai': ('str', '', None, None),
        'cookie_nhentai': ('str', '', None, None),
        'qb_enabled': ('str', '0', None, None),
        'qb_host': ('str', '', None, None),
        'qb_port': ('str', '8080', None, None),
        'qb_user': ('str', 'admin', None, None),
        'qb_pass': ('str', '', None, None),
        'qb_category': ('str', '', None, None),
        'qb_download_path': ('str', '', None, None),
        'tag_mapping': ('str', '', None, None),
        'max_cache_size': ('int', '0', 0, None),
    }

    # API 读取时脱敏的字段
    SECRET_FIELDS = ('proxy_pass', 'qb_pass')

    # 校验错误信息中的字段中文名（未列出的用 key 本身）
    FIELD_LABELS = {
        'per_page': '每页显示数量',
        'max_content_length': '最大上传大小',
        'chunk_size': '分块上传大小',
        'upload_interval': '文件处理间隔',
        'cover_width': '封面宽度',
        'cover_quality': '封面图片质量',
        'max_cache_size': '缓存上限',
    }

    @classmethod
    def load_all(cls):
        """全部字段原始值（不脱敏，模板渲染用）。"""
        from app.models import Setting
        return {key: Setting.get(key, spec[1]) for key, spec in cls.FIELD_SPECS.items()}

    @classmethod
    def get_all(cls):
        """API 读取：全部字段值，敏感字段脱敏。"""
        data = cls.load_all()
        for key in cls.SECRET_FIELDS:
            if data[key]:
                data[key] = cls.MASK
        return data

    @classmethod
    def validate(cls, data):
        """校验字段类型与范围，返回错误信息；None 表示通过。

        只校验 data 中出现的已知字段；未知字段与敏感字段跳过
        （与既有行为一致：未知字段忽略，敏感字段无范围约束）。
        """
        for key, value in data.items():
            spec = cls.FIELD_SPECS.get(key)
            if spec is None or key in cls.SECRET_FIELDS:
                continue
            ftype, _, lo, hi = spec
            if ftype not in ('int', 'float'):
                continue
            try:
                num = int(value) if ftype == 'int' else float(value)
            except (TypeError, ValueError):
                label = cls.FIELD_LABELS.get(key, key)
                return f'{label}必须为{"整数" if ftype == "int" else "数值"}'
            if (lo is not None and num < lo) or (hi is not None and num > hi):
                label = cls.FIELD_LABELS.get(key, key)
                if lo is not None and hi is not None:
                    return f'{label}必须在 {lo}-{hi} 之间'
                if lo is not None:
                    return f'{label}必须不小于 {lo}'
                return f'{label}必须不大于 {hi}'
        return None

    @classmethod
    def save(cls, data):
        """写入字段。仅处理 FIELD_SPECS 内的字段；掩码占位不覆盖真实值。"""
        from app.models import Setting
        for key, value in data.items():
            spec = cls.FIELD_SPECS.get(key)
            if spec is None:
                continue
            if key in cls.SECRET_FIELDS and value == cls.MASK:
                continue
            ftype = spec[0]
            if ftype == 'int':
                value = str(int(value))
            elif ftype == 'float':
                value = str(float(value))
            else:
                value = str(value).strip()
            Setting.set(key, value)
