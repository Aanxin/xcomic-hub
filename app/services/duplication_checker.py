from app import db
from app.models import Comic
from app.services.matching_service import normalize_title


class DuplicationChecker:

    def __init__(self, db_session=None):
        self.db_session = db_session or db.session

    def check_duplicate_by_source_url(self, source_url):
        if not source_url:
            return None
        return Comic.query.filter_by(source_url=source_url).first()

    def check_duplicate_by_title(self, title):
        if not title:
            return None
        return Comic.query.filter(
            db.func.lower(Comic.title) == title.lower()
        ).first()

    def check_duplicate_by_normalized_title(self, title, min_length=4):
        if not title:
            return None
        norm_title = normalize_title(title)
        if not norm_title or len(norm_title) < min_length:
            return None
        all_comics = Comic.query.with_entities(Comic.title, Comic.title_jp).all()
        for c in all_comics:
            for t in [c[0], c[1]]:
                if not t:
                    continue
                norm_db = normalize_title(t)
                if not norm_db:
                    continue
                if norm_title == norm_db or norm_title in norm_db or norm_db in norm_title:
                    return Comic.query.filter_by(title=c[0]).first()
        return None

    def check_duplicate_by_filename(self, filename):
        if not filename:
            return None
        return Comic.query.filter_by(filename=filename).first()

    def check_duplicate(self, title, source_url):
        duplicate = self.check_duplicate_by_source_url(source_url)
        if duplicate:
            return duplicate
        duplicate = self.check_duplicate_by_title(title)
        if duplicate:
            return duplicate
        return self.check_duplicate_by_normalized_title(title)