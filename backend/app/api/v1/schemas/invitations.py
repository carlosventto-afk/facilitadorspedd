from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.db.models import InvitationStatus


class InvitationCreate(BaseModel):
    email: EmailStr
    accounting_firm_id: str


class InvitationRead(BaseModel):
    id: str
    email: str
    accounting_firm_id: str
    status: InvitationStatus
    invited_by: str | None
    accepted_at: datetime | None
    created_user_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvitationAccept(BaseModel):
    token: str
    full_name: str
    password: str
