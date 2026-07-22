from app import db
from app.models import Comic
from app.utils.sort_utils import resolve_direction, apply_order
from app.utils.tag_utils import reverse_map_tag


class ComicQueryService:
    """漫画查询服务，封装列表查询的搜索、过滤、排序等业务逻辑。"""

    # sort key -> (column, default_direction). Default directions preserve the
    # pre-`order`-param behavior exactly (backward compatible).
    SORT_MAP = {
        'updated': (Comic.updated_at, 'desc'),
        'created': (Comic.created_at, 'desc'),
        'title': (Comic.title, 'asc'),
        'rating': (Comic.rating, 'desc'),
        'size': (Comic.file_size, 'desc'),
    }

    @staticmethod
    def build_comic_query(search='', sort='updated', view_filter='', collection_id=None, order=None):
        """构建漫画查询对象，封装所有查询逻辑。

        Args:
            search: 搜索关键词，支持 author:/genre:/tag:/category:/publisher:/language: 前缀
            sort: 排序字段
            view_filter: 过滤器，支持 favorite/standalone
            collection_id: 合集 ID
            order: 排序方向 'asc'/'desc'（大小写不敏感）；缺省或非法时回退到字段默认方向

        Returns:
            配置好过滤和排序的 Query 对象
        """
        query = Comic.query

        query = ComicQueryService._apply_collection_filter(query, view_filter, collection_id)

        if search:
            query = ComicQueryService._apply_search_filter(query, search)

        if view_filter == 'favorite':
            query = query.filter(Comic.is_favorite == True)

        query = ComicQueryService._apply_sort(query, sort, order)

        return query

    @staticmethod
    def _apply_collection_filter(query, view_filter, collection_id):
        """应用合集相关过滤。"""
        if collection_id is not None:
            return query.filter(Comic.collection_id == collection_id)
        elif view_filter == 'standalone':
            return query.filter(Comic.collection_id.is_(None))
        return query

    @staticmethod
    def _apply_search_filter(query, search):
        """应用搜索过滤，封装复杂的标签映射逻辑。"""
        if search.startswith('author:'):
            val = search[7:].strip()
            originals = reverse_map_tag(val)
            conditions = [Comic.author.contains(v) for v in originals]
            return query.filter(db.or_(*conditions))
        elif search.startswith('genre:'):
            val = search[6:].strip()
            originals = reverse_map_tag(val)
            conditions = [Comic.genre.contains(v) for v in originals]
            return query.filter(db.or_(*conditions))
        elif search.startswith('tag:'):
            val = search[4:].strip()
            originals = reverse_map_tag(val)
            conditions = [Comic.tags.contains(v) for v in originals]
            return query.filter(db.or_(*conditions))
        elif search.startswith('category:'):
            val = search[9:].strip()
            return query.filter(Comic.category.contains(val))
        elif search.startswith('publisher:'):
            val = search[10:].strip()
            return query.filter(Comic.publisher.contains(val))
        elif search.startswith('language:'):
            val = search[9:].strip()
            return query.filter(Comic.language.contains(val))
        else:
            originals = reverse_map_tag(search)
            tag_conditions = [Comic.tags.contains(v) for v in originals]
            return query.filter(
                db.or_(
                    Comic.title.contains(search),
                    Comic.author.contains(search),
                    *tag_conditions,
                    Comic.genre.contains(search),
                )
            )

    @staticmethod
    def _apply_sort(query, sort, order=None):
        """应用排序逻辑。

        未知 sort 回退到 'updated'（保留既有行为）；order 缺省/非法时回退到
        该字段的默认方向（向后兼容）。
        """
        column, default_dir = ComicQueryService.SORT_MAP.get(sort, ComicQueryService.SORT_MAP['updated'])
        direction = resolve_direction(order, default_dir)
        return query.order_by(apply_order(column, direction))
