"""SQLAlchemy 模型。"""

import enum
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    watcha_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    avatar_url: Mapped[str] = mapped_column(String(512), default="")
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tokens: Mapped[list["CliToken"]] = relationship(back_populates="user")
    sites: Mapped[list["Site"]] = relationship(back_populates="user")


class CliToken(Base):
    """CLI 访问令牌：只存 SHA-256 哈希。"""

    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="default")
    prefix: Mapped[str] = mapped_column(String(16))  # 便于识别，如 tt2_pat_Ab3x
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="tokens")


class TokenDanceKey(Base):
    """用户 TokenPay 授权获得的 TokenDance API Key（Fernet 加密落库）。"""

    __tablename__ = "tokendance_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key_enc: Mapped[str] = mapped_column(Text)
    key_prefix: Mapped[str] = mapped_column(String(16), default="")
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    ip: Mapped[str] = mapped_column(String(64))
    suffix: Mapped[str] = mapped_column(String(128))  # 例: lhub.tt2.li
    ssh_user: Mapped[str] = mapped_column(String(64), default="deploy")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/draining/disabled


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"))
    name: Mapped[str] = mapped_column(String(32))
    host: Mapped[str] = mapped_column(String(255), unique=True)  # myapp.lhub.tt2.li
    spa: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/deleted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="sites")
    node: Mapped[Node] = relationship()
    domains: Mapped[list["Domain"]] = relationship(back_populates="site")


class Domain(Base):
    """用户自备域名。"""

    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/active
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    site: Mapped[Site] = relationship(back_populates="domains")


class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"
    DONE = "done"
    FAILED = "failed"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)  # ULID 风格
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="push")  # push/assist
    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.QUEUED.value, index=True)
    input_text: Mapped[str] = mapped_column(Text, default="")
    site_name: Mapped[str] = mapped_column(String(32), default="")
    staging_path: Mapped[str] = mapped_column(String(512), default="")
    messages: Mapped[list] = mapped_column(JSON, default=list)  # 猹询码会话
    question: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 结构化反问
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"url": ...}
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    rounds: Mapped[int] = mapped_column(Integer, default=0)
    billing: Mapped[str] = mapped_column(String(16), default="tokenpay")  # tokenpay/free_pool
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DeviceCode(Base):
    __tablename__ = "device_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_code: Mapped[str] = mapped_column(String(16), unique=True)  # 例: ABCD-EFGH
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/approved/denied
    cli_token_id: Mapped[int | None] = mapped_column(ForeignKey("tokens.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
