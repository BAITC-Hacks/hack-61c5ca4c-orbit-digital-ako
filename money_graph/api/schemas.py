from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

class FileMapping(BaseModel):
    file_id: str
    kind: Literal['transactions', 'edges', 'nodes', 'seeds', 'ignore']
    fields: dict[str, str]
    sheet: str | None = None

class Mapping(BaseModel):
    files: list[FileMapping]
    seeds: list[str] = Field(default_factory=list, max_length=100000)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    collection_threshold: float | None = Field(default=None, ge=0)
    max_depth: int | None = Field(default=None, ge=1, le=1000)
    dayfirst: bool = True
    language: Literal['ru', 'en', 'kk'] = 'ru'
    confirmed: Literal[True]
    expected_start: str | None = None
    expected_end: str | None = None

class PreviewMapping(BaseModel):
    files: list[FileMapping]
    dayfirst: bool = True

class Selection(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=3000)

class Feedback(BaseModel):
    id: str
    verdict: Literal['confirm', 'reject', 'unsure']
    role: str | None = None
    comment: str = Field(default='', max_length=5000)

class Case(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    ids: list[str] = Field(default_factory=list, max_length=3000)
    notes: str = Field(default='', max_length=50000)
    scenarios: list[dict] = Field(default_factory=list, max_length=100)

class ConfigPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    roles: dict[str, float] | None = None
    priority_weights: dict[str, float] | None = None
    threshold_mode: Literal['absolute', 'adaptive'] | None = None
    fast_lag_days: int | None = Field(default=None, ge=0, le=365)
