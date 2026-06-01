import os
import re
import uuid
import zipfile
import shutil

from app.utils.file_utils import safe_filename, resolve_conflict, get_storage_subdir
from config import COMICS_DIR, NFO_DIR, COVERS_DIR, DOWNLOAD_DIR, IMAGE_EXTENSIONS


class FileOperationService:

    def pack_images_to_zip(self, dir_path, title):
        img_exts = ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp')
        img_files = []
        for root, dirs, files in os.walk(dir_path):
            for fn in sorted(files):
                ext = os.path.splitext(fn)[1].lower().lstrip('.')
                if ext in img_exts and not fn.startswith('.') and not fn.startswith('__MACOSX'):
                    img_files.append(os.path.join(root, fn))
        if not img_files:
            return None
        zip_name = (title or 'unknown') + '.zip'
        zip_path = os.path.join(DOWNLOAD_DIR, re.sub(r'[<>:"/\\|?*]', '_', zip_name))
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for img_path in img_files:
                arc_name = os.path.relpath(img_path, dir_path)
                zf.write(img_path, arc_name)
        return zip_path

    def validate_comic_file(self, file_path):
        ext = os.path.splitext(file_path)[1].lower().lstrip('.')
        if ext in ('zip', 'cbz'):
            return self._validate_zip_file(file_path)
        elif ext in ('rar', 'cbr'):
            return self._validate_rar_file(file_path)
        elif ext in ('7z', 'cb7'):
            return self._validate_7z_file(file_path)
        return True

    def _validate_zip_file(self, file_path):
        try:
            with zipfile.ZipFile(file_path, 'r') as test_zf:
                bad = test_zf.testzip()
                if bad:
                    raise Exception(f'压缩包内损坏的文件: {bad}')
            return True
        except zipfile.BadZipFile as e:
            raise Exception(f'ZIP文件损坏: {e}')
        except Exception as e:
            if '压缩包内损坏' in str(e):
                raise
            raise Exception(f'ZIP验证失败: {e}')

    def _validate_rar_file(self, file_path):
        try:
            import subprocess as _sp
            result = _sp.run(['unrar', 't', file_path], capture_output=True, timeout=30)
            if result.returncode != 0:
                raise Exception('RAR文件损坏或不可读')
            return True
        except FileNotFoundError:
            return True
        except Exception as e:
            if 'RAR文件损坏' in str(e):
                raise
            return True

    def _validate_7z_file(self, file_path):
        try:
            import subprocess as _sp
            result = _sp.run(['7z', 't', file_path], capture_output=True, timeout=30)
            if result.returncode != 0:
                raise Exception('7z文件损坏或不可读')
            return True
        except FileNotFoundError:
            return True
        except Exception as e:
            if '7z文件损坏' in str(e):
                raise
            return True

    def copy_to_comics_dir(self, source_path, source_fname):
        ext = os.path.splitext(source_fname)[1].lower().lstrip('.')
        safe_name = safe_filename(source_fname)
        if not safe_name:
            safe_name = f"{uuid.uuid4().hex}.{ext}"
        storage_subdir = get_storage_subdir(source_fname)
        target_dir = os.path.join(COMICS_DIR, storage_subdir)
        os.makedirs(target_dir, exist_ok=True)
        safe_name = resolve_conflict(target_dir, safe_name)
        dst_path = os.path.join(target_dir, safe_name)

        src_size = os.path.getsize(source_path)
        shutil.copy2(source_path, dst_path)

        if not os.path.exists(dst_path):
            raise Exception(f'文件复制失败，目标文件不存在: {dst_path}')
        dst_size = os.path.getsize(dst_path)
        if dst_size != src_size:
            if os.path.exists(dst_path):
                os.remove(dst_path)
            raise Exception(f'文件复制后大小不一致: 源={src_size}, 目标={dst_size}')

        if ext in ('zip', 'cbz'):
            self._validate_zip_file(dst_path)

        rel_filename = os.path.join(storage_subdir, safe_name).replace('\\', '/')
        return dst_path, rel_filename, dst_size, ext

    def copy_nfo_file(self, nfo_source_path, storage_subdir):
        nfo_name = safe_filename(os.path.basename(nfo_source_path))
        if not nfo_name:
            nfo_name = f"{uuid.uuid4().hex}.nfo"
        nfo_target_dir = os.path.join(NFO_DIR, storage_subdir)
        os.makedirs(nfo_target_dir, exist_ok=True)
        nfo_name = resolve_conflict(nfo_target_dir, nfo_name)
        nfo_dst = os.path.join(nfo_target_dir, nfo_name)
        shutil.copy2(nfo_source_path, nfo_dst)
        if not os.path.exists(nfo_dst) or os.path.getsize(nfo_dst) == 0:
            if os.path.exists(nfo_dst):
                os.remove(nfo_dst)
            return None
        return os.path.join(storage_subdir, nfo_name).replace('\\', '/')

    def generate_cover(self, dst_path, ext, task_id, storage_subdir):
        from app.models import Setting
        auto_cover_enabled = Setting.get('auto_cover', '1') == '1'
        if not auto_cover_enabled:
            return None

        from app.reader import generate_cover_from_archive, generate_cover_from_image

        cover_width = int(Setting.get('cover_width', '300'))
        os.makedirs(COVERS_DIR, exist_ok=True)
        cover_generated = None

        if ext in ('cbz', 'zip'):
            cover_generated = generate_cover_from_archive(dst_path, cover_width)

        if not cover_generated and os.path.exists(dst_path):
            try:
                from PIL import Image
                thumbnail_size = (cover_width, int(cover_width * 1.4))
                if ext in ('rar', 'cbr', '7z', 'cb7'):
                    try:
                        import subprocess as _sp
                        tmp_dir = os.path.join(DOWNLOAD_DIR, f'_cover_tmp_{task_id}')
                        os.makedirs(tmp_dir, exist_ok=True)
                        if ext in ('rar', 'cbr'):
                            _sp.run(['unrar', 'x', '-o+', '-y', dst_path, tmp_dir], capture_output=True, timeout=30)
                        else:
                            _sp.run(['7z', 'x', '-y', f'-o{tmp_dir}', dst_path], capture_output=True, timeout=30)
                        img_files = []
                        for root, dirs2, files in os.walk(tmp_dir):
                            for fn in sorted(files):
                                fn_ext = os.path.splitext(fn)[1].lower()
                                if fn_ext in IMAGE_EXTENSIONS and not fn.startswith('.') and not fn.startswith('__MACOSX'):
                                    img_files.append(os.path.join(root, fn))
                        if img_files:
                            img = Image.open(img_files[0])
                            img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
                            if img.mode in ('RGBA', 'P'):
                                img = img.convert('RGB')
                            cover_name = f"{os.urandom(8).hex()}.jpg"
                            cover_path = os.path.join(COVERS_DIR, cover_name)
                            quality = int(Setting.get('cover_quality', '85'))
                            img.save(cover_path, 'JPEG', quality=quality)
                            cover_generated = cover_name
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    except Exception:
                        shutil.rmtree(os.path.join(DOWNLOAD_DIR, f'_cover_tmp_{task_id}'), ignore_errors=True)
                elif ext in IMAGE_EXTENSIONS:
                    cover_generated = generate_cover_from_image(dst_path, cover_width)
            except Exception:
                pass

        if cover_generated:
            old_cover_path = os.path.join(COVERS_DIR, cover_generated)
            new_cover_dir = os.path.join(COVERS_DIR, storage_subdir)
            os.makedirs(new_cover_dir, exist_ok=True)
            new_cover_path = os.path.join(new_cover_dir, cover_generated)
            if os.path.exists(old_cover_path) and not os.path.exists(new_cover_path):
                shutil.move(old_cover_path, new_cover_path)
            return os.path.join(storage_subdir, cover_generated).replace('\\', '/')

        return None

    def cleanup_temp_files(self, nfo_path=None, torrent_file=None):
        if nfo_path and os.path.exists(nfo_path):
            try:
                os.remove(nfo_path)
            except Exception:
                pass
        if torrent_file:
            try:
                torrent_path = os.path.join(DOWNLOAD_DIR, torrent_file)
                if os.path.exists(torrent_path):
                    os.remove(torrent_path)
            except Exception:
                pass

    def cleanup_download_dir(self, title):
        try:
            download_dir = DOWNLOAD_DIR
            if os.path.isdir(download_dir):
                comic_exts = ('.zip', '.cbz', '.rar', '.cbr', '.7z', '.cb7')
                for fname in os.listdir(download_dir):
                    fpath = os.path.join(download_dir, fname)
                    if not os.path.isfile(fpath):
                        continue
                    ext = os.path.splitext(fname)[1].lower().lstrip('.')
                    if ext in comic_exts and title in fname:
                        os.remove(fpath)
        except Exception:
            pass