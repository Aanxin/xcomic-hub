from app.models import ReadingHistory


class ComicDataEnricher:
    """漫画数据组装器，统一处理阅读历史等关联数据的批量查询与组装。"""

    @staticmethod
    def enrich_with_reading_history(paginated_result):
        """为分页结果中的漫画添加阅读历史数据。

        Args:
            paginated_result: paginate_response 返回的结果字典，包含 items 列表

        Returns:
            原地修改并返回 paginated_result
        """
        if not paginated_result.get('items'):
            return paginated_result

        comic_ids = [item['id'] for item in paginated_result['items']]
        history_map = ComicDataEnricher._batch_fetch_reading_history(comic_ids)

        for item in paginated_result['items']:
            item['reading_history'] = history_map.get(item['id'])

        return paginated_result

    @staticmethod
    def enrich_comics_with_history(comics):
        """为漫画对象列表添加阅读历史数据，返回带 history 的 dict 列表。

        适用于合集详情、合集漫画列表等场景。

        Args:
            comics: Comic 模型对象列表

        Returns:
            包含 reading_history 字段的 dict 列表
        """
        if not comics:
            return []

        comic_ids = [c.id for c in comics]
        history_map = ComicDataEnricher._batch_fetch_reading_history(comic_ids)

        result = []
        for comic in comics:
            comic_dict = comic.to_dict()
            comic_dict['reading_history'] = history_map.get(comic.id)
            result.append(comic_dict)

        return result

    @staticmethod
    def _batch_fetch_reading_history(comic_ids):
        """批量获取阅读历史数据，避免 N+1 查询。

        Args:
            comic_ids: 漫画 ID 列表

        Returns:
            {comic_id: history_dict} 映射字典
        """
        if not comic_ids:
            return {}

        histories = ReadingHistory.query.filter(
            ReadingHistory.comic_id.in_(comic_ids)
        ).all()

        return {h.comic_id: h.to_dict() for h in histories}
