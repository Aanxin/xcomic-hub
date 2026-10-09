"""漫画源抽象层（类 Suwayomi 的 Source 插件模式）。"""

from app.sources.base_source import (
    BaseSource,
    GalleryCard,
    GalleryListResult,
    SourceRegistry,
)

__all__ = [
    'BaseSource',
    'GalleryCard',
    'GalleryListResult',
    'SourceRegistry',
]
