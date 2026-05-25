from pydantic import BaseModel, Field


class CategoriaUpsertRequest(BaseModel):
    ccate: str = Field(min_length=1, max_length=10)
    ncate: str = Field(min_length=1, max_length=240)
    pganancia: float | None = None
    pdescu: float | None = None


class CategoriaResponse(BaseModel):
    ccate: str
    ncate: str
    pganancia: float | None = None
    pdescu: float | None = None
