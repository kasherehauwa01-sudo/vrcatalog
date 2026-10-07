from __future__ import annotations

import logging
import ipaddress
import re
import socket
import tempfile
import threading
import warnings
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image as PillowImage, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session, load_only, selectinload

from app.core.config import settings
from app.importer.xml_importer import public_image_url
from app.models.catalog import Product, ProductImage
from app.services.catalog import catalog_product_query


logger = logging.getLogger(__name__)
MAX_SELECTED_IMAGES = 500
MAX_SOURCE_IMAGE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
DOWNLOAD_CHUNK_SIZE = 256 * 1024
_archive_slots = threading.BoundedSemaphore(2)


def photo_report_page(db: Session, params: dict, page: int, page_size: int) -> dict:
    """Возвращает одну порцию товаров из общей отфильтрованной выборки каталога."""
    query = catalog_product_query(db, params, eager_load=False)
    total_items = query.order_by(None).count()
    products = (
        query.options(
            load_only(Product.id, Product.code, Product.article, Product.name),
            selectinload(Product.images).load_only(
                ProductImage.id,
                ProductImage.product_id,
                ProductImage.image_order,
                ProductImage.image_url,
            ),
        )
        .order_by(Product.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    photo_count = sum(len(product.images) for product in products)
    logger.info(
        'Отчет "Скачать фото": найдено товаров=%s, страница=%s, фото на странице=%s',
        total_items,
        page,
        photo_count,
    )
    return {
        "items": [
            {
                "id": product.id,
                "code": product.code,
                "article": product.article,
                "name": product.name,
                "images": [
                    {
                        "id": image.id,
                        "product_id": product.id,
                        "order": image.image_order,
                        "preview_url": public_image_url(image.image_url),
                    }
                    for image in product.images
                ],
            }
            for product in products
        ],
        "page": page,
        "page_size": page_size,
        "total_items": total_items,
        "total_pages": (total_items + page_size - 1) // page_size,
    }


def _safe_archive_name(product: Product, image: ProductImage) -> str:
    code = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", product.code).strip("_") or "product"
    return f"{code}_{product.id}_{image.image_order}_{image.id}.jpg"


def _normalize_image_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Некорректный URL изображения")
    return urlunsplit((
        parts.scheme,
        parts.netloc.encode("idna").decode("ascii"),
        quote(parts.path, safe="/%:@"),
        quote(parts.query, safe="=&%:@/?"),
        "",
    ))


def _validate_public_host(url: str) -> None:
    hostname = urlsplit(url).hostname or ""
    if hostname.casefold() == "localhost" or hostname.casefold().endswith(".localhost"):
        raise ValueError("Недопустимый адрес изображения")
    allowlist = settings.parsed_image_allowed_hosts
    if allowlist and hostname.casefold() not in allowlist:
        raise ValueError("Домен изображения не разрешен")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError("Не удалось определить адрес изображения") from exc
    if not addresses:
        raise ValueError("Не удалось определить адрес изображения")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Недопустимый адрес изображения")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _download_to_file(url: str, destination: Path) -> int:
    normalized_url = _normalize_image_url(url)
    opener = build_opener(_NoRedirect)
    for redirect_count in range(4):
        _validate_public_host(normalized_url)
        request = Request(normalized_url, headers={
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (compatible; VRCatalog Photo Report)",
        })
        try:
            response = opener.open(request, timeout=10)
        except HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308} or redirect_count >= 3:
                raise ValueError("Не удалось получить изображение") from exc
            location = exc.headers.get("Location")
            if not location:
                raise ValueError("Некорректное перенаправление изображения") from exc
            from urllib.parse import urljoin
            normalized_url = _normalize_image_url(urljoin(normalized_url, location))
            continue
        content_type = response.headers.get_content_type()
        try:
            peer_ip = ipaddress.ip_address(response.fp.raw._sock.getpeername()[0])
        except (AttributeError, OSError, ValueError) as exc:
            response.close()
            raise ValueError("Не удалось проверить адрес источника изображения") from exc
        if not peer_ip.is_global:
            response.close()
            raise ValueError("Недопустимый адрес изображения")
        if not content_type.startswith("image/"):
            response.close()
            raise ValueError("Источник не является изображением")
        total = 0
        with response, destination.open("wb") as target:
            while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
                total += len(chunk)
                if total > MAX_SOURCE_IMAGE_BYTES:
                    raise ValueError("Изображение превышает допустимый размер")
                target.write(chunk)
        return total
    raise ValueError("Слишком много перенаправлений")


def _prepare_jpeg(source: Path, destination: Path) -> Path:
    with warnings.catch_warnings():
        warnings.simplefilter("error", PillowImage.DecompressionBombWarning)
        with PillowImage.open(source) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("Слишком большое разрешение изображения")
            image.verify()
            source_format = image.format
    if source_format == "JPEG":
        return source

    with PillowImage.open(source) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
            rgba = image.convert("RGBA")
            prepared = PillowImage.new("RGB", rgba.size, "white")
            prepared.paste(rgba, mask=rgba.getchannel("A"))
        else:
            prepared = image.convert("RGB")
        prepared.save(destination, format="JPEG", quality=90, optimize=True)
    return destination


def create_photo_archive(db: Session, selections) -> tuple[Path, int]:
    """Создаёт ZIP во временном файле, получая URL только из базы данных."""
    requested_pairs = {(item.product_id, item.image_id) for item in selections}
    if len(requested_pairs) > MAX_SELECTED_IMAGES:
        raise ValueError(f"Можно скачать не более {MAX_SELECTED_IMAGES} фотографий")
    rows = (
        db.query(Product, ProductImage)
        .join(ProductImage, ProductImage.product_id == Product.id)
        .filter(ProductImage.id.in_([image_id for _, image_id in requested_pairs]))
        .all()
    )
    valid_rows = [
        (product, image)
        for product, image in rows
        if (product.id, image.id) in requested_pairs
    ]
    if {(product.id, image.id) for product, image in valid_rows} != requested_pairs:
        raise ValueError("Одно или несколько изображений не существуют или не принадлежат товару")

    if not _archive_slots.acquire(blocking=False):
        raise ValueError("Сервис подготовки фотографий занят. Повторите позже")
    archive_file = tempfile.NamedTemporaryFile(prefix="vrcatalog-photos-", suffix=".zip", delete=False)
    archive_path = Path(archive_file.name)
    archive_file.close()
    added = 0
    total_source_bytes = 0
    try:
        with ZipFile(archive_path, "w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
            for product, image in sorted(valid_rows, key=lambda row: (row[0].id, row[1].image_order, row[1].id)):
                with tempfile.TemporaryDirectory(prefix="vrcatalog-photo-") as directory:
                    source = Path(directory) / "source"
                    converted = Path(directory) / "converted.jpg"
                    try:
                        downloaded = _download_to_file(image.image_url, source)
                        total_source_bytes += downloaded if downloaded is not None else source.stat().st_size
                        if total_source_bytes > MAX_TOTAL_SOURCE_BYTES:
                            raise ValueError("Превышен суммарный размер выбранных изображений")
                        jpeg = _prepare_jpeg(source, converted)
                        archive.write(jpeg, _safe_archive_name(product, image))
                        added += 1
                    except (
                        OSError,
                        ValueError,
                        UnidentifiedImageError,
                        PillowImage.DecompressionBombError,
                        PillowImage.DecompressionBombWarning,
                    ):
                        # URL намеренно не пишется в лог: достаточно идентификаторов БД.
                        logger.warning(
                            "Не удалось добавить фотографию в отчет: product_id=%s, image_id=%s",
                            product.id,
                            image.id,
                        )
        if not added:
            archive_path.unlink(missing_ok=True)
            raise ValueError("Не удалось подготовить ни одной выбранной фотографии")
        return archive_path, added
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
    finally:
        _archive_slots.release()
