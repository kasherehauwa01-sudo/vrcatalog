"""The final XML full-path component is a product, never a folder."""
FOLDER_PATH_PROPERTY = "ПолныйПуть"
FOLDER_PATH_PROPERTIES = (FOLDER_PATH_PROPERTY, "Полныйпуть")


def folder_path(value: str) -> str | None:
    parts = value.strip().rstrip("|").split("|")
    if len(parts) < 2 or any(not part.strip() for part in parts):
        return None
    return "|".join(parts[:-1])
