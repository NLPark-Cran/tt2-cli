"""校验器：站点名、域名、tar 包安全解压。"""

import io
import tarfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.validators import safe_extract_tar, validate_domain, validate_site_name


class TestSiteName:
    def test_ok(self):
        assert validate_site_name("my-app1") == "my-app1"

    @pytest.mark.parametrize("name", ["ab", "Aabc", "-abc", "a_b", "www", "api", "x" * 33])
    def test_reject(self, name):
        with pytest.raises(HTTPException):
            validate_site_name(name)


class TestDomain:
    def test_ok(self):
        assert validate_domain("WWW.88sj.COM.") == "www.88sj.com"

    @pytest.mark.parametrize("d", ["not a domain", "-bad.com", "a..com", "x" * 300])
    def test_reject(self, d):
        with pytest.raises(HTTPException):
            validate_domain(d)


def _make_tar(entries: dict[str, bytes | str]) -> Path:
    """entries: name -> bytes 内容，或 'symlink:/target' / 'dir:' 特殊条目。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in entries.items():
            if isinstance(content, str) and content.startswith("symlink:"):
                info = tarfile.TarInfo(name)
                info.type = tarfile.SYMTYPE
                info.linkname = content.removeprefix("symlink:")
                tf.addfile(info)
            elif content == "dir:":
                tf.addfile(tarfile.TarInfo(name))
            else:
                data = content if isinstance(content, bytes) else content.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
    path = Path("/tmp") / f"test_{next(_counter)}.tar.gz"  # noqa: S108
    path.write_bytes(buf.getvalue())
    return path


def _gen():
    i = 0
    while True:
        i += 1
        yield i


_counter = _gen()


class TestSafeExtract:
    def test_normal(self, tmp_path):
        archive = _make_tar({"index.html": "<html></html>", "assets/app.js": "console.log(1)"})
        total = safe_extract_tar(archive, tmp_path, 10 * 1024 * 1024)
        assert total > 0
        assert (tmp_path / "index.html").exists()
        assert (tmp_path / "assets/app.js").exists()

    def test_path_escape(self, tmp_path):
        archive = _make_tar({"../evil.html": b"x"})
        with pytest.raises((HTTPException, tarfile.FilterError, Exception)):
            safe_extract_tar(archive, tmp_path, 10 * 1024 * 1024)
        assert not (tmp_path.parent / "evil.html").exists()

    def test_symlink_rejected(self, tmp_path):
        archive = _make_tar({"link": "symlink:/etc/passwd", "index.html": "x"})
        with pytest.raises(HTTPException):
            safe_extract_tar(archive, tmp_path, 10 * 1024 * 1024)

    def test_forbidden_extension(self, tmp_path):
        archive = _make_tar({"shell.php": b"<?php", "index.html": "x"})
        with pytest.raises(HTTPException):
            safe_extract_tar(archive, tmp_path, 10 * 1024 * 1024)

    def test_size_limit(self, tmp_path):
        archive = _make_tar({"index.html": "x", "big.bin.txt": "y" * 1000})
        with pytest.raises(HTTPException):
            safe_extract_tar(archive, tmp_path, 100)
