"""Lightweight export links: select primary image URLs without downloading files."""
from urllib.parse import urlencode

from sqlalchemy import and_, func, select
from app.importer.xml_importer import public_image_url
from app.models.catalog import ProductImage

MAX_SHEET_HYPERLINKS = 65530


def primary_image_links(db, product_ids):
    links = {}
    for start in range(0, len(product_ids), 500):
        first = (select(ProductImage.product_id, func.min(ProductImage.image_order).label('image_order'))
                 .where(ProductImage.product_id.in_(product_ids[start:start + 500]))
                 .group_by(ProductImage.product_id).subquery())
        query = select(ProductImage.product_id, ProductImage.image_url).join(first, and_(
            ProductImage.product_id == first.c.product_id,
            ProductImage.image_order == first.c.image_order,
        ))
        for product_id, image_url in db.execute(query):
            links[product_id] = public_image_url(image_url) or ''
    return links


def product_site_link(code):
    # Public code redirect; never fetch products during export.
    return "https://volgorost.ru/link.php?" + urlencode({"code": code})
