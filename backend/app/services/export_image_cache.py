import logging
import os
from pathlib import Path
from threading import Lock

import fcntl

from app.core.config import settings

logger = logging.getLogger(__name__)

_MB = 1024 * 1024
_cleanup_lock = Lock()


def maintain_export_image_cache_safely(job_id: str) -> None:
    """Запускает обслуживание, никогда не прерывая завершение Excel-экспорта."""
    try:
        maintain_export_image_cache()
    except Exception:
        logger.warning("Не удалось обслужить кэш изображений после экспорта %s", job_id, exc_info=True)


def maintain_export_image_cache(cache_dir: Path | None = None) -> None:
    """Ограничивает кэш миниатюр, не ожидая уже запущенную очистку."""
    directory = cache_dir or Path(settings.upload_dir) / "export-image-cache"
    if not _cleanup_lock.acquire(blocking=False):
        return
    lock_file = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        lock_file = (directory / ".cleanup.lock").open("a+b")
        try:
            # flock защищает каталог и при наличии нескольких процессов backend.
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        _cleanup_cache(directory)
    except OSError as exc:
        logger.warning("Не удалось обслужить кэш изображений %s: %s", directory, exc)
    finally:
        if lock_file is not None:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            except OSError as exc:
                logger.warning("Не удалось освободить блокировку кэша изображений: %s", exc)
        _cleanup_lock.release()


def _cleanup_cache(directory: Path) -> None:
    files: list[tuple[float, int, Path]] = []
    total_size = 0
    try:
        entries = list(os.scandir(directory))
    except OSError as exc:
        logger.warning("Не удалось определить размер кэша изображений %s: %s", directory, exc)
        return

    for entry in entries:
        if not entry.name.lower().endswith(".jpg"):
            continue
        try:
            stat = entry.stat(follow_symlinks=False)
            if not entry.is_file(follow_symlinks=False):
                continue
        except OSError as exc:
            logger.warning("Не удалось прочитать файл кэша изображений %s: %s", entry.path, exc)
            continue
        files.append((stat.st_mtime, stat.st_size, Path(entry.path)))
        total_size += stat.st_size

    max_size = settings.export_image_cache_max_mb * _MB
    target_size = settings.export_image_cache_target_mb * _MB
    if total_size <= max_size:
        return

    logger.warning(
        "Кэш изображений превышен: %.0f МБ, начинается очистка до %s МБ",
        total_size / _MB,
        settings.export_image_cache_target_mb,
    )
    initial_size = total_size
    removed_count = 0
    for _mtime, file_size, path in sorted(files, key=lambda item: item[0]):
        if total_size <= target_size:
            break
        try:
            path.unlink()
        except FileNotFoundError:
            # Параллельное удаление не является ошибкой; размер всё равно уменьшился.
            total_size -= file_size
        except OSError as exc:
            logger.warning("Не удалось удалить файл кэша изображений %s: %s", path, exc)
        else:
            total_size -= file_size
            removed_count += 1

    logger.warning(
        "Кэш изображений очищен: удалено %s файлов, освобождено %.0f МБ, текущий размер %.0f МБ",
        removed_count,
        (initial_size - total_size) / _MB,
        total_size / _MB,
    )
