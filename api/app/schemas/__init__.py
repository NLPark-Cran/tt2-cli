"""请求/响应 DTO。"""

from datetime import datetime

from pydantic import BaseModel, Field


class TaskCreated(BaseModel):
    task_id: str
    status: str


class TaskOut(BaseModel):
    task_id: str
    status: str
    kind: str
    site_name: str
    question: dict | None = None
    result: dict | None = None
    error: str | None = None
    billing: str
    rounds: int
    created_at: datetime
    updated_at: datetime


class ReplyIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class SiteOut(BaseModel):
    name: str
    host: str
    url: str
    spa: bool
    status: str
    created_at: datetime


class DomainIn(BaseModel):
    site: str = Field(min_length=3, max_length=32)
    domain: str = Field(min_length=4, max_length=253)


class DomainOut(BaseModel):
    domain: str
    status: str
    site: str
    dns_guide: dict


class TokenCreated(BaseModel):
    token: str  # 仅此一次返回明文
    name: str
    prefix: str


class TokenOut(BaseModel):
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None


class DeviceCodeOut(BaseModel):
    device_code: str
    user_code: str
    verification_url: str
    expires_in: int


class MeOut(BaseModel):
    nickname: str
    avatar_url: str
    tokendance_connected: bool
