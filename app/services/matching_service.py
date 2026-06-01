import re
import threading

from datetime import datetime


def parse_hashes(qb_info_hash):
    if not qb_info_hash:
        return []
    return [h.strip() for h in qb_info_hash.split(',') if h.strip()]


_queue_position_counter = 0
_queue_position_lock = threading.Lock()


def get_next_queue_position():
    global _queue_position_counter
    with _queue_position_lock:
        _queue_position_counter += 1
        return _queue_position_counter


def fuzzy_match_score(query, target):
    if not query or not target:
        return 0
    query_lower = query.lower()
    target_lower = target.lower()
    if query_lower == target_lower:
        return 100
    if query_lower in target_lower:
        return 80
    if target_lower in query_lower:
        return 70
    q_words = re.findall(r'[a-zA-Z0-9\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff]+', query_lower)
    t_words = re.findall(r'[a-zA-Z0-9\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff]+', target_lower)
    if not q_words or not t_words:
        return 0
    matched = 0
    for w in q_words:
        if len(w) < 2:
            continue
        for tw in t_words:
            if w in tw or tw in w:
                matched += 1
                break
    score = int(matched / len(q_words) * 60)
    return score


def normalize_title(title):
    if not title:
        return ''
    t = title.lower()
    t = re.sub(r'\s+', '', t)
    t = re.sub(r'[^\w\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', '', t)
    return t


class MatchingService:

    def match_task_to_torrent(self, task, torrents, used_hashes):

        hash_map = {}
        name_map = {}
        for t in torrents:
            h = t.get('hash', '')
            name = t.get('name', '')
            if h:
                hash_map[h.upper()] = t
            if name:
                name_map[name] = t

        info = None
        matched_hash = None

        if task.qb_info_hash:
            hashes = parse_hashes(task.qb_info_hash)
            for h in hashes:
                info = hash_map.get(h.upper())
                if info:
                    matched_hash = h
                    break

        task_age = (datetime.utcnow() - task.created_at).total_seconds() if task.created_at else 0
        in_hash_phase = task_age < 300

        if not info and in_hash_phase and task.qb_info_hash:
            hashes = parse_hashes(task.qb_info_hash)
            for h in hashes:
                info = hash_map.get(h.upper())
                if info:
                    matched_hash = h
                    break

        if not info and not in_hash_phase and task.title:
            best_score = 0
            best_t = None
            for name, t in name_map.items():
                t_hash = t.get('hash', '').upper()
                if t_hash in used_hashes:
                    continue
                score = fuzzy_match_score(task.title, name)
                added_on = t.get('added_on', 0)
                time_bonus = 0
                if added_on and task.created_at:
                    diff = abs(task.created_at.timestamp() - added_on)
                    if diff < 300:
                        time_bonus = 20
                    elif diff < 3600:
                        time_bonus = 10
                    elif diff < 86400:
                        time_bonus = 3
                total_score = score + time_bonus
                if total_score > best_score:
                    best_score = total_score
                    best_t = t
            if best_score >= 50 and best_t:
                info = best_t
                matched_hash = best_t.get('hash', '')

        return info, matched_hash, in_hash_phase

    def find_comic_in_dir(self, dir_path, task_title, nfo_data):

        import os
        comic_exts_set = ('zip', 'cbz', 'rar', 'cbr', '7z', 'cb7')
        candidates = []
        for fn in sorted(os.listdir(dir_path)):
            fpath = os.path.join(dir_path, fn)
            if not os.path.isfile(fpath):
                continue
            ext = os.path.splitext(fn)[1].lower().lstrip('.')
            if ext not in comic_exts_set:
                continue
            fname_base = os.path.splitext(fn)[0]
            score = 0
            if task_title:
                score = max(score, fuzzy_match_score(task_title, fname_base))
            if nfo_data.get('title'):
                score = max(score, fuzzy_match_score(nfo_data['title'], fname_base))
            if score >= 30:
                candidates.append((fpath, fn, score))
        candidates.sort(key=lambda x: x[2], reverse=True)
        if candidates:
            return candidates[0][0], candidates[0][1]
        return None, None

    def find_comic_in_download_dir(self, download_dir, task_title, nfo_data, qb_info_hash):

        import os
        comic_exts = ('zip', 'cbz', 'rar', 'cbr', '7z', 'cb7')
        candidates = []
        all_comics = []
        for fname in os.listdir(download_dir):
            fpath = os.path.join(download_dir, fname)
            if not os.path.isfile(fpath):
                continue
            ext = os.path.splitext(fname)[1].lower().lstrip('.')
            if ext not in comic_exts:
                continue
            fname_base = os.path.splitext(fname)[0]
            score = 0
            if task_title:
                score = max(score, fuzzy_match_score(task_title, fname_base))
            if nfo_data.get('title'):
                score = max(score, fuzzy_match_score(nfo_data['title'], fname_base))
            if nfo_data.get('title_jp'):
                score = max(score, fuzzy_match_score(nfo_data['title_jp'], fname_base))
            if nfo_data.get('author'):
                score = max(score, fuzzy_match_score(nfo_data['author'], fname_base) // 2)
            fsize = os.path.getsize(fpath)
            if fsize == 0:
                continue
            all_comics.append((fpath, fname, score))
            if qb_info_hash and score < 30:
                continue
            if score >= 30:
                candidates.append((fpath, fname, score))
        if not candidates and len(all_comics) == 1:
            c = all_comics[0]
            return c[0], c[1], max(c[2], 60)
        candidates.sort(key=lambda x: x[2], reverse=True)
        if candidates:
            return candidates[0][0], candidates[0][1], candidates[0][2]
        return None, None, 0