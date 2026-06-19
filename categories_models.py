from pydantic import BaseModel, Field, field_validator


def _validate_pct(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    if value < 0 or value > 100:
        raise ValueError(f"{name} must be between 0 and 100")
    if round(value, 2) != value:
        raise ValueError(f"{name} must have at most 2 decimals")
    return value


class CategoriaCreateRequest(BaseModel):
    ccate: str = Field(min_length=1, max_length=10, pattern=r"^\d+$")
    ncate: str = Field(min_length=1, max_length=240)
    pganancia: float | None = None
    pdescu: float | None = None

    _validate_pganancia = field_validator("pganancia")(
        lambda v: _validate_pct("pganancia", v)
    )
    _validate_pdescu = field_validator("pdescu")(lambda v: _validate_pct("pdescu", v))


class CategoriaPatchRequest(BaseModel):
    ncate: str | None = Field(default=None, min_length=1, max_length=240)
    pganancia: float | None = None
    pdescu: float | None = None

    _validate_pganancia = field_validator("pganancia")(
        lambda v: _validate_pct("pganancia", v)
    )
    _validate_pdescu = field_validator("pdescu")(lambda v: _validate_pct("pdescu", v))


class CategoriaResponse(BaseModel):
    ccate: str
    ncate: str
    pganancia: float | None = None
    pdescu: float | None = None
