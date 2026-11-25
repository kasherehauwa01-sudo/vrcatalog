"""Separate XML folder prefixes from product names (which can also contain |)."""
FOLDER_PATH_PROPERTY = "ПолныйПуть"
FOLDER_PATH_PROPERTIES = (FOLDER_PATH_PROPERTY, "Полныйпуть")


def _normalized_part(value: str) -> str:
    return " ".join(value.split()).casefold()


def folder_path(value: str, product_name: str | None = None, *, uppercase_only: bool = False) -> str | None:
    parts = value.strip().rstrip("|").split("|")
    name_parts = (product_name or "").strip().rstrip("|").split("|")
    # The separator is not escaped inside product names, e.g. «х|б ручками».
    # Match the complete name at the end, never an earlier same-named folder.
    name_matches = bool(product_name and product_name.strip()) and len(parts) >= len(name_parts) and all(
        _normalized_part(actual) == _normalized_part(expected)
        for actual, expected in zip(parts[-len(name_parts):], name_parts)
    )
    folders = parts[:-len(name_parts)] if name_matches else parts[:-1]
    # Stop at the first product-like segment, including stale/split product names.
    if any(not part.strip() for part in folders):
        return None
    result = []
    for part in folders:
        first_word = part.strip().split()[0]
        if uppercase_only and not first_word.isupper():
            break
        result.append(part.strip())
    return "|".join(result) or None
