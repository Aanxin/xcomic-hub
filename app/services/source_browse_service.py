"""源浏览服务：选源 + 调用（薄封装）。"""

from app.sources.source_registry import create_source, get_registry, list_sources

# 默认语言筛选：中文
DEFAULT_LANGUAGE = 'chinese'


class SourceBrowseService:

    @staticmethod
    def get_sources():
        return list_sources()

    @staticmethod
    def latest(source_id, page=1, language=DEFAULT_LANGUAGE, cursor=None, category='home', period='all', sort=None):
        """按大类浏览列表；category 默认 home（路由到源 latest），period 为排行时间范围，
        sort 为热度时间范围（源支持时使用）。"""
        source = create_source(source_id)
        return source.browse(category=category, page=page, language=language, cursor=cursor, period=period, sort=sort)

    @staticmethod
    def search(source_id, keyword, page=1, language=DEFAULT_LANGUAGE, cursor=None, sort=None,
               exact_tag=False):
        source = create_source(source_id)
        return source.search(keyword, page=page, language=language, cursor=cursor, sort=sort,
                             exact_tag=exact_tag)

    @staticmethod
    def find_source_by_url(url):
        """遍历注册源，返回可处理该 URL 的源。"""
        for source in get_registry().sources():
            if source.can_handle(url):
                return source
        return None

    @staticmethod
    def gallery_details(url):
        """根据 URL 自动识别源并取详情，并附加分组标签（对齐 detail 页 group_tags 体系）。"""
        source = SourceBrowseService.find_source_by_url(url)
        if source is None:
            raise ValueError('无法识别的画廊地址')
        details = source.gallery_details(url)
        SourceBrowseService._attach_grouped_tags(details)
        return details

    @staticmethod
    def _attach_grouped_tags(details):
        """把 tags 逗号串分组为 grouped_tags/uncat_tags，并做中文映射。"""
        from app.utils.file_utils import group_tags
        from app.utils.tag_utils import map_tag

        grouped, uncat = group_tags(details.get('tags', ''))
        details['grouped_tags'] = [
            {
                'category': map_tag(cat) or cat,
                'raw_category': cat,
                'tags': [map_tag(v) for v in vals],
                'raw_tags': list(vals),
            }
            for cat, vals in grouped.items()
        ]
        details['uncat_tags'] = [map_tag(t) for t in uncat]
        details['raw_uncat_tags'] = list(uncat)
