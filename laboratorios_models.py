from pydantic import BaseModel, Field


class LaboratorioCreateRequest(BaseModel):
    cgeneral: str = Field(min_length=1, max_length=10, pattern=r"^\d+$")
    ngeneral: str = Field(min_length=1, max_length=240)


class LaboratorioPatchRequest(BaseModel):
    ngeneral: str | None = Field(default=None, min_length=1, max_length=240)


class LaboratorioResponse(BaseModel):
    cgeneral: str
    ngeneral: str
