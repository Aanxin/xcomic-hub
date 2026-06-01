import xml.etree.ElementTree as ET
from typing import Optional


def parse_nfo(nfo_content: str) -> dict:
    result = {
        'title': '',
        'title_jp': '',
        'author': '',
        'genre': '',
        'category': '',
        'date': '',
        'plot': '',
        'rating': 0.0,
        'rating_count': 0,
        'tags': '',
        'status': '',
        'publisher': '',
        'language': '',
        'is_translated': False,
        'uploader': '',
        'page_count': 0,
        'favorited': 0,
        'source_url': '',
        'torrent_urls': '',
    }

    try:
        root = ET.fromstring(nfo_content)
    except ET.ParseError as e:
        print(f'[NFO] XML解析失败: {e}')
        return result

    str_fields = ['title', 'title_jp', 'author', 'genre', 'category', 'date',
                  'plot', 'tags', 'status', 'publisher', 'language', 'uploader', 'source_url', 'torrent_urls']
    int_fields = ['page_count', 'favorited', 'rating_count']
    bool_fields = ['is_translated']

    for field in str_fields:
        elem = root.find(field)
        if elem is not None and elem.text:
            result[field] = elem.text.strip()

    for field in int_fields:
        elem = root.find(field)
        if elem is not None and elem.text:
            try:
                result[field] = int(elem.text.strip())
            except ValueError as e:
                print(f'[NFO] 整数字段 {field} 解析失败: {e}')

    for field in bool_fields:
        elem = root.find(field)
        if elem is not None and elem.text:
            result[field] = elem.text.strip().lower() in ('true', '1', 'yes')

    elem = root.find('rating')
    if elem is not None and elem.text:
        try:
            result['rating'] = float(elem.text.strip())
        except ValueError as e:
            print(f'[NFO] rating字段解析失败: {e}')
            result['rating'] = 0.0

    return result


def parse_nfo_file(filepath: str) -> Optional[dict]:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return parse_nfo(content)
    except (IOError, OSError) as e:
        print(f'[NFO] 读取文件失败 {filepath}: {e}')
        return None


def generate_nfo(comic_dict: dict) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<comic>')

    fields = ['title', 'title_jp', 'author', 'genre', 'category', 'date',
              'plot', 'rating', 'rating_count', 'tags', 'status', 'publisher', 'language',
              'is_translated', 'uploader', 'page_count', 'favorited', 'source_url', 'torrent_urls']
    for field in fields:
        value = comic_dict.get(field, '')
        lines.append(f'  <{field}>{value}</{field}>')

    lines.append('</comic>')
    return '\n'.join(lines)
