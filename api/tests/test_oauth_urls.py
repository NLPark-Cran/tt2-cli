"""OAuth URL 构建与 PKCE。"""

from urllib.parse import parse_qs, urlparse

from app.services import tokendance, watcha


class TestWatchaUrl:
    def test_authorize_url(self):
        url = watcha.build_authorize_url("state123")
        q = parse_qs(urlparse(url).query)
        assert q["response_type"] == ["code"]
        assert q["state"] == ["state123"]
        # client_id 含 + 必须被正确编码
        assert "client_id" in q


class TestTokenDancePkce:
    def test_pkce_pair(self):
        verifier, challenge = tokendance.new_pkce_pair()
        assert 43 <= len(verifier) <= 128
        assert "=" not in challenge and "+" not in challenge and "/" not in challenge

    def test_auth_url(self):
        url = tokendance.build_tokendance_auth_url("st", "ch")
        q = parse_qs(urlparse(url).query)
        assert q["code_challenge"] == ["ch"]
        assert q["code_challenge_method"] == ["S256"]
        assert "callback_url" in q
