from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image as PillowImage, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session, load_only, selectinload

from app.importer.xml_importer import public_image_url
from app.models.catalog import Product, ProductImage
from app.services.catalog import catalog_product_query


logger = logging.getLogger(__name__)
MAX_SELECTED_IMAGES = 500
MAX_SOURCE_IMAGE_BYTES = 25 * 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 256 * 1024


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
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Некорректный URL изображения")
    return urlunsplit((
        parts.scheme,
        parts.netloc.encode("idna").decode("ascii"),
        quote(parts.path, safe="/%:@"),
        quote(parts.query, safe="=&%:@/?"),
        "",
    ))


def _download_to_file(url: str, destination: Path) -> None:
    normalized_url = _normalize_image_url(url)
    request = Request(normalized_url, headers={
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "User-Agent": "Mozilla/5.0 (compatible; VRCatalog Photo Report)",
    })
    total = 0
    with urlopen(request, timeout=10) as response, destination.open("wb") as target:
        while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
            total += len(chunk)
            if total > MAX_SOURCE_IMAGE_BYTES:
                raise ValueError("Изображение превышает допустимый размер")
            target.write(chunk)


def _prepare_jpeg(source: Path, destination: Path) -> Path:
    with PillowImage.open(source) as image:
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

    archive_file = tempfile.NamedTemporaryFile(prefix="vrcatalog-photos-", suffix=".zip", delete=False)
    archive_path = Path(archive_file.name)
    archive_file.close()
    added = 0
    try:
        with ZipFile(archive_path, "w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
            for product, image in sorted(valid_rows, key=lambda row: (row[0].id, row[1].image_order, row[1].id)):
                with tempfile.TemporaryDirectory(prefix="vrcatalog-photo-") as directory:
                    source = Path(directory) / "source"
                    converted = Path(directory) / "converted.jpg"
                    try:
                        _download_to_file(image.image_url, source)
                        jpeg = _prepare_jpeg(source, converted)
                        archive.write(jpeg, _safe_archive_name(product, image))
                        added += 1
                    except (OSError, ValueError, UnidentifiedImageError):
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
