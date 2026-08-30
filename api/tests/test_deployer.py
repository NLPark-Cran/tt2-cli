"""Caddy 片段渲染与 DNS 指南。"""

from app.routers.domains import dns_guide
from app.services.deployer import render_caddy_snippet


class TestCaddySnippet:
    def test_static(self):
        out = render_caddy_snippet("myapp.lhub.tt2.li", [], spa=False)
        assert "myapp.lhub.tt2.li {" in out
        assert "root * /srv/sites/myapp.lhub.tt2.li" in out
        assert "file_server" in out
        assert "rewrite" not in out

    def test_spa_and_domains(self):
        out = render_caddy_snippet("myapp.lhub.tt2.li", ["www.88sj.com"], spa=True)
        assert "myapp.lhub.tt2.li, www.88sj.com {" in out
        assert "rewrite @spa_not_found /index.html" in out


class TestDnsGuide:
    def test_guide(self):
        g = dns_guide("www.88sj.com", "myapp.lhub.tt2.li", "38.76.172.131")
        assert g["recommended"]["type"] == "CNAME"
        assert "myapp.lhub.tt2.li" in g["recommended"]["value"]
        assert g["alternative"]["value"] == "38.76.172.131"
        assert "阿里云" in g["providers"]
