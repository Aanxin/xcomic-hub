"""漫画源抽象基类与注册表。

每个源(如 E-Hentai / Nhentai)实现统一接口：
- search / latest: 列表与搜索，返回 GalleryListResult
- categories / browse: 大类切换（首页/订阅/热门/排行等，按站点能力）
- gallery_details: 结构化画廊详情
- page_image_urls: 全部原图 URL
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class UnsupportedCategory(ValueError):
    """源不支持请求的大类。"""


class QuotaError(Exception):
    """站点带宽/流量配额限制（如 E-Hentai 509 sad panda）。

    IP 级限制，换节点（?nl= 重载）无效，应直接终止并给出明确提示。
    """


@dataclass
class GalleryCard:
    """列表页的画廊卡片。rank 为排行名次（仅排行榜类源使用，0 表示无）。

    in_library：该画廊是否已在本地漫画库（API 层按 Comic.source_url 标注）。
    """
    url: str
    title: str
    cover_url: str = ''
    page_count: int = 0
    rank: int = 0
    in_library: bool = False

    def to_dict(self):
        return {
            'url': self.url,
            'title': self.title,
            'cover_url': self.cover_url,
            'page_count': self.page_count,
            'rank': self.rank,
            'in_library': self.in_library,
        }


@dataclass
class GalleryListResult:
    """列表/搜索结果。

    next_cursor：游标分页（如 E-Hentai 新版 next= 参数）的下一页游标；
    为空时表示该源使用数字页码（page=N）翻页。
    """
    items: list = field(default_factory=list)
    has_next: bool = False
    next_cursor: str = ''

    def to_dict(self):
        return {
            'items': [c.to_dict() if isinstance(c, GalleryCard) else c for c in self.items],
            'has_next': self.has_next,
            'next_cursor': self.next_cursor,
        }


@dataclass
class PageImage:
    """单页图片。

    url 为原图地址；viewer_url/nl_key 为坏节点重载上下文
    （E-Hentai：查看页地址 + onerror nl key，节点不可达时请求
    查看页?nl=key 由站点换节点返回新图片 URL）。
    """
    url: str
    viewer_url: str = ''
    nl_key: str = ''


class BaseSource(ABC):
    """漫画源基类。子类必须实现 source_id / name 与四个方法。"""

    source_id: str = ''
    name: str = ''
    # 该源可处理的域名（小写），用于 URL -> 源的自动识别
    domains: tuple = ()

    def can_handle(self, url) -> bool:
        """URL 是否属于本源（按 domains 匹配）。"""
        if not url or not self.domains:
            return False
        url_lower = url.lower()
        return any(domain in url_lower for domain in self.domains)

    @abstractmethod
    def search(self, keyword, page=1, language=None, cursor=None, sort=None,
               exact_tag=False) -> GalleryListResult:
        """按关键词搜索画廊。language 为语言筛选（如 'chinese'），None 不过滤。

        cursor 为游标分页的下一页游标（源支持时使用），None 时用数字页码。
        sort 为热度时间范围（'today'/'week'/'all'，源支持时使用），None 用站点默认。
        exact_tag=True 表示 keyword 是单个原始 tag（如 'female:glasses'），
        源应使用其站点的精确 tag 匹配语法（对齐站点画廊页点击 tag 的官方
        搜索语义，如 E-Hentai 的 "ns:tag$" 引号+$）；False 为普通关键词搜索。
        """

    @abstractmethod
    def latest(self, page=1, language=None, cursor=None, sort=None) -> GalleryListResult:
        """最新/默认列表。language 为语言筛选（如 'chinese'），None 不过滤。

        sort 为热度时间范围（'today'/'week'/'all'，源支持时使用），None 用站点默认。
        """

    def categories(self) -> list:
        """源支持的浏览大类（UI 据此渲染标签栏）。默认仅首页。"""
        return [{'id': 'home', 'name': '首页'}]

    def browse(self, category='home', page=1, language=None, cursor=None, period='all', sort=None) -> GalleryListResult:
        """按大类浏览。默认 home 路由到 latest()；period 为排行时间范围、
        sort 为热度时间范围（子类可选实现）。"""
        if category != 'home':
            raise UnsupportedCategory(f'{self.name or self.source_id} 不支持大类: {category}')
        return self.latest(page=page, language=language, cursor=cursor, sort=sort)

    @abstractmethod
    def gallery_details(self, url) -> dict:
        """结构化画廊详情：元数据 + 缩略图 URL 列表。"""

    @abstractmethod
    def page_image_urls(self, url, progress_cb=None) -> list:
        """返回画廊全部原图（按阅读顺序）。

        返回图片 URL 字符串列表；需坏节点重载的源（E-Hentai H@H）返回
        PageImage 列表（携带 viewer_url/nl_key 供 reload_image 换节点）。
        可选实现 reload_image(page)：返回换节点后的新 PageImage。
        progress_cb(done, total)：解析进度回调（total 为 0 表示总数尚未
        确定），供任务实时上报；无进度概念的源可忽略。
        """


class SourceRegistry:
    """源注册表。模式对齐 app.scrapers.scraper_factory.ScraperFactory。"""

    def __init__(self):
        self._sources = {}

    def register(self, source: BaseSource):
        if not source.source_id:
            raise ValueError('源必须定义非空 source_id')
        self._sources[source.source_id] = source

    def create_source(self, source_id: str) -> BaseSource:
        source = self._sources.get(source_id)
        if source is None:
            raise ValueError(f'未知漫画源: {source_id}')
        return source

    def sources(self) -> list:
        return list(self._sources.values())

    def list_sources(self) -> list:
        return [{'id': s.source_id, 'name': s.name, 'categories': s.categories()} for s in self._sources.values()]
