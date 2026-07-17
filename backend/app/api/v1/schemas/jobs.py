from datetime import date, datetime

from pydantic import BaseModel

from app.db.models import JobStatus


class JobCreate(BaseModel):
    period_start: date
    period_end: date


class JobRead(BaseModel):
    id: str
    company_id: str
    status: JobStatus
    period_start: date
    period_end: date
    nfs_found: int | None
    anticipations_matched: int | None
    anticipations_total: int | None
    c197_records_inserted: int | None
    e111_records_inserted: int | None
    e116_records_inserted: int | None
    error_message: str | None
    created_at: datetime
    processing_started_at: datetime | None
    processing_finished_at: datetime | None

    model_config = {"from_attributes": True}


class DownloadUrlResponse(BaseModel):
    url: str
    expires_in_seconds: int = 900
