"""全局源注册表（模块级单例，默认注册内置源）。"""

from app.sources.base_source import BaseSource, SourceRegistry

_registry = SourceRegistry()


def _register_builtin():
    from app.sources.ehentai_source import EhentaiSource
    from app.sources.nhentai_source import NhentaiSource
    _registry.register(EhentaiSource())
    _registry.register(NhentaiSource())


_register_builtin()


def get_registry() -> SourceRegistry:
    return _registry


def _reset_registry():
    """仅供测试：清空并重置注册表。"""
    global _registry
    _registry = SourceRegistry()
    return _registry


def create_source(source_id: str) -> BaseSource:
    return get_registry().create_source(source_id)


def list_sources() -> list:
    return get_registry().list_sources()
