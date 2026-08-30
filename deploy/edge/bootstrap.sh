#!/usr/bin/env bash
# tt2 边缘节点一键入网脚本（Debian 12/13，root 执行）
# 用法: curl -fsSL https://cli.tt2.li/edge-bootstrap.sh | bash -s -- <控制面SSH公钥>
set -euo pipefail

CONTROL_PUBKEY_B64="${1:-}"
if [ -z "$CONTROL_PUBKEY_B64" ]; then
    echo "用法: $0 <控制面SSH公钥(base64)>" >&2
    exit 2
fi
# 公钥含空格，经 ssh 参数传递会被截断，故用 base64 传输
CONTROL_PUBKEY="$(echo "$CONTROL_PUBKEY_B64" | base64 -d)"

echo "==> 安装 Caddy（官方源）"
apt-get update -qq
apt-get install -y -qq curl rsync ufw >/dev/null
if ! command -v caddy >/dev/null; then
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https >/dev/null
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
        -o /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    apt-get install -y -qq caddy >/dev/null
fi

echo "==> 创建 deploy 低权用户与目录"
id deploy &>/dev/null || useradd -m -s /bin/bash deploy
mkdir -p /srv/sites /etc/caddy/sites.d /var/log/caddy /home/deploy/.ssh
chown -R deploy:deploy /srv/sites
chown -R caddy:caddy /var/log/caddy

echo "==> 安装控制面公钥"
touch /home/deploy/.ssh/authorized_keys
grep -qF "$CONTROL_PUBKEY" /home/deploy/.ssh/authorized_keys || \
    echo "$CONTROL_PUBKEY" >> /home/deploy/.ssh/authorized_keys
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh

echo "==> 安装 Caddy 片段管理脚本（sudoers 白名单的唯一提权通道）"
cat > /usr/local/bin/tt2-caddy-install <<'SCRIPT'
#!/usr/bin/env bash
# 由控制面通过 ssh + sudo 调用：tt2-caddy-install <host>，stdin 为 Caddy 片段
set -euo pipefail
HOST="${1:?missing host}"
# host 只能包含域名合法字符，防注入
[[ "$HOST" =~ ^[a-z0-9.,-]+$ ]] || { echo "bad host" >&2; exit 2; }
umask 022
TARGET="/etc/caddy/sites.d/${HOST}.caddy"
cat > "${TARGET}.tmp"
mv "${TARGET}.tmp" "$TARGET"
# 校验失败则回滚，绝不让坏配置进入生产
if ! caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; then
    rm -f "$TARGET"
    echo "caddy 配置校验失败，已回滚" >&2
    exit 1
fi
systemctl reload caddy
SCRIPT
chmod 755 /usr/local/bin/tt2-caddy-install

cat > /usr/local/bin/tt2-caddy-remove <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
HOST="${1:?missing host}"
[[ "$HOST" =~ ^[a-z0-9.,-]+$ ]] || { echo "bad host" >&2; exit 2; }
rm -f "/etc/caddy/sites.d/${HOST}.caddy"
rm -rf "/srv/sites/${HOST}"
systemctl reload caddy
SCRIPT
chmod 755 /usr/local/bin/tt2-caddy-remove

cat > /etc/sudoers.d/tt2-deploy <<'SUDOERS'
deploy ALL=(root) NOPASSWD: /usr/local/bin/tt2-caddy-install, /usr/local/bin/tt2-caddy-remove
SUDOERS
chmod 440 /etc/sudoers.d/tt2-deploy

echo "==> Caddy 全局配置"
cat > /etc/caddy/Caddyfile <<'CADDY'
{
    email admin@tt2.li
}

import /etc/caddy/sites.d/*.caddy
CADDY
# 兜底默认站点（裸 IP 访问返回 404）
cat > /etc/caddy/sites.d/000-default.caddy <<'CADDY'
:80 {
    respond "tt2 edge node" 404
}
CADDY
systemctl enable caddy
systemctl restart caddy

echo "==> 防火墙：仅放行 22/80/443"
ufw --force reset >/dev/null 2>&1
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

echo "==> 完成。节点已就绪：$(curl -s4 ifconfig.me || true)"
