import os
import re
import uuid
import shutil
import hashlib

from config import COMICS_DIR, ALLOWED_EXTENSIONS

DEFAULT_DIR = 'Default'


def safe_filename(filename):
    name = filename.replace('\x00', '')
    name = name.replace('\\', '/').split('/')[-1]
    name = re.sub(r'^[.]+', '', name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip()
    if len(name.encode('utf-8')) > 240:
        while len(name.encode('utf-8')) > 240 and name:
            name = name[:-1]
        name = name.rstrip('_').rstrip()
    if not name:
        return ''
    return name


def resolve_conflict(directory, filename):
    target = os.path.join(directory, filename)
    if not os.path.exists(target):
        return filename
    base, ext = os.path.splitext(filename)
    new_name = f"{base}_{uuid.uuid4().hex[:8]}{ext}"
    while os.path.exists(os.path.join(directory, new_name)):
        new_name = f"{base}_{uuid.uuid4().hex[:8]}{ext}"
    return new_name


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_storage_subdir(filename, collection_name=None):
    if collection_name:
        col_safe = safe_filename(collection_name)
        if col_safe:
            return col_safe
    h = hashlib.md5(filename.encode('utf-8')).hexdigest()
    return os.path.join(DEFAULT_DIR, h[:2])


def move_comic_file(old_path, new_path):
    if os.path.exists(new_path):
        base, ext = os.path.splitext(new_path)
        counter = 1
        while os.path.exists(f"{base}_{counter}{ext}"):
            counter += 1
        new_path = f"{base}_{counter}{ext}"
    new_dir = os.path.dirname(new_path)
    if new_dir:
        os.makedirs(new_dir, exist_ok=True)
    shutil.move(old_path, new_path)
    old_dir = os.path.dirname(old_path)
    if old_dir and old_dir != COMICS_DIR and not os.listdir(old_dir):
        os.rmdir(old_dir)
    return new_path


def get_dir_size(path):
    total = 0
    if not os.path.exists(path):
        return 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    else:
        return f"{size_bytes / 1024 / 1024 / 1024:.2f} GB"


def group_tags(tags_str):
    categorized = {}
    uncategorized = []
    if not tags_str:
        return categorized, uncategorized
    for tag in tags_str.split(','):
        tag = tag.strip()
        if not tag:
            continue
        if ':' in tag:
            parts = tag.split(':', 1)
            cat = parts[0].strip()
            val = parts[1].strip()
            if cat in categorized:
                categorized[cat].append(val)
            else:
                categorized[cat] = [val]
        else:
            uncategorized.append(tag)
    return categorized, uncategorized
