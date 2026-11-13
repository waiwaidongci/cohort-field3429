from datetime import datetime

from pydantic import BaseModel


class ComparedRun(BaseModel):
    id: int
    name: str
    dataset_id: int
    dataset_name: str
    total: int
    group_count: int
    created_at: datetime


class ComparisonSummary(BaseModel):
    common: int
    retained: int
    migrated: int
    added: int
    left: int
    migration_share_of_common: float
    migration_share_of_a: float
    migration_share_of_b: float
    reconciled: bool


class GroupMatch(BaseModel):
    a_label: int | None
    a_name: str | None
    a_size: int | None
    b_label: int | None
    b_name: str | None
    b_size: int | None
    overlap: int
    share_of_a_group: float
    label_changed: bool
    name_changed: bool


class MatrixCell(BaseModel):
    b_label: int
    b_name: str
    count: int
    share_of_common: float
    share_of_a_group: float
    matched: bool


class MatrixRow(BaseModel):
    a_label: int
    a_name: str
    a_size: int
    cells: list[MatrixCell]


class Migration(BaseModel):
    a_label: int
    a_name: str
    b_label: int
    b_name: str
    count: int
    share_of_common: float
    share_of_a_group: float


class ComparisonResult(BaseModel):
    run_a: ComparedRun
    run_b: ComparedRun
    comparable: bool
    reason: str
    summary: ComparisonSummary
    matches: list[GroupMatch]
    matrix: list[MatrixRow]
    migrations: list[Migration]
    added_codes: list[str]
    left_codes: list[str]
    notes: list[str]
