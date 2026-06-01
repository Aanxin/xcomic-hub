import re
import html as _html_mod


def decode_html_entities(result):
    for key in list(result.keys()):
        if isinstance(result[key], str):
            result[key] = _html_mod.unescape(result[key])
            result[key] = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), result[key])
            result[key] = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), result[key])
