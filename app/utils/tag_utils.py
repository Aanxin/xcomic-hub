def get_tag_mapping():
    from app.models import Setting
    raw = Setting.get('tag_mapping', '')
    if not raw:
        return {}
    mapping = {}
    for line in raw.split('\n'):
        line = line.strip()
        if '=' not in line:
            continue
        key, val = line.split('=', 1)
        mapping[key.strip().lower()] = val.strip()
    return mapping


def map_tag(tag):
    if not tag:
        return tag
    mapping = get_tag_mapping()
    return mapping.get(tag.lower(), tag)


def reverse_map_tag(display_name):
    if not display_name:
        return [display_name]
    mapping = get_tag_mapping()
    originals = []
    for eng, chn in mapping.items():
        if chn.lower() == display_name.lower():
            originals.append(eng)
    if originals:
        return originals
    return [display_name]
