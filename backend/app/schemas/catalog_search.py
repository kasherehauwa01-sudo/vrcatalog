"""Optional body transport for long code lists; other filters stay in query parameters."""
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CatalogCodeBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=128999)

    @field_validator("code")
    @classmethod
    def validate_codes(cls, value):
        codes = [code for code in re.split(r"[,\s]+", value.strip()) if code]
        if not codes or len(codes) > 1000 or any(len(code) > 128 for code in codes):
            raise ValueError("Укажите до 1000 кодов длиной не более 128 символов")
        return value
