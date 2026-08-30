"""站点名 / 域名 / 上传包校验。安全红线集中在此。"""

import re
import tarfile
from pathlib import Path

from fastapi import HTTPException

from .errors import err

SITE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

RESERVED_NAMES = {
    "www",
    "api",
    "cli",
    "free",
    "admin",
    "status",
    "mail",
    "smtp",
    "imap",
    "pop",
    "ns1",
    "ns2",
    "ftp",
    "ssh",
    "vpn",
    "cdn",
    "static",
    "assets",
    "img",
    "images",
    "dashboard",
    "console",
    "panel",
    "root",
    "system",
    "support",
    "help",
    "docs",
    "blog",
    "shop",
    "pay",
    "billing",
    "auth",
    "login",
    "oauth",
    "tt2",
    "hub",
    "lhub",
    "watcha",
    "tokendance",
    "tokenpay",
    "official",
    "security",
    "abuse",
}

# 静态站点白名单扩展名
ALLOWED_EXTENSIONS = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".json",
    ".xml",
    ".txt",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".avif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".mp3",
    ".mp4",
    ".webm",
    ".ogg",
    ".wav",
    ".flac",
    ".m4a",
    ".pdf",
    ".zip",
    ".wasm",
    ".glb",
    ".gltf",
    ".hdr",
    ".csv",
}

MAX_FILES = 2000
MAX_SINGLE_FILE = 20 * 1024 * 1024


def validate_site_name(name: str) -> str:
    if not SITE_NAME_RE.match(name):
        raise HTTPException(
            422,
            detail={
                "error": {
                    "code": "invalid_site_name",
                    "message": "站点名须为 3-32 位小写字母/数字/中划线，且以字母或数字开头",
                    "details": {"name": name},
                }
            },
        )
    if name in RESERVED_NAMES:
        raise err(422, "reserved_name", "该站点名为保留名")
    return name


def validate_domain(domain: str) -> str:
    domain = domain.strip().lower().rstrip(".")
    if not DOMAIN_RE.match(domain):
        raise err(422, "invalid_domain", "域名格式不正确")
    return domain


def safe_extract_tar(archive: Path, dest: Path, max_bytes: int) -> int:
    """安全解压 tar.gz：防路径逃逸、拒绝符号链接/硬链接/设备文件、白名单扩展名、限额。

    返回解压后总字节数。
    """
    total = 0
    count = 0
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            count += 1
            if count > MAX_FILES:
                raise _bad("too_many_files", f"文件数超过上限 {MAX_FILES}")
            # 拒绝非普通文件（符号链接、硬链接、设备等）
            if not member.isreg() and not member.isdir():
                raise _bad("unsafe_entry", f"不允许的条目类型: {member.name}")
            # 防路径逃逸
            target = (dest / member.name).resolve()
            if not str(target).startswith(str(dest.resolve()) + "/") and target != dest.resolve():
                raise _bad("path_escape", f"检测到路径逃逸: {member.name}")
            if member.isreg():
                ext = Path(member.name).suffix.lower()
                if ext not in ALLOWED_EXTENSIONS:
                    raise _bad(
                        "forbidden_extension",
                        f"不允许的文件类型 {ext or '(无扩展名)'}（仅支持静态站点文件）",
                    )
                if member.size > MAX_SINGLE_FILE:
                    raise _bad("file_too_large", f"单文件超过 20MB: {member.name}")
                total += member.size
                if total > max_bytes:
                    raise _bad("package_too_large", "解压后总大小超过限制")
        tf.extractall(dest, filter="data")
    return total


def _bad(code: str, message: str) -> HTTPException:
    return HTTPException(422, detail={"error": {"code": code, "message": message, "details": {}}})
