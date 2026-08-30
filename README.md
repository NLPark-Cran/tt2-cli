# tt2-cli

> 让你的 Agent 一句话上线你的产品。

tt2-cli 是 `?hub.tt2.li` 静态托管网络的官方工具包：

- **人类**：打开 [free.hub.tt2.li](https://free.hub.tt2.li)，观猹登录，三分钟把站点推上线；
- **Agent**：`curl -fsSL https://cli.tt2.li/install.sh | sh`，然后 `tt2 push ./dist --name myapp`；
- **安全**：你的 Agent 从不直接接触服务器——所有部署由运行在我们服务端的定制版猹询码中介处理；
- **域名**：免费三级域名 `<name>.lhub.tt2.li`，也支持自备域名（CNAME 一键指南）；
- **SSL**：全部站点自动签发 Let's Encrypt 证书，自动续期，零操作；
- **计费**：部署任务消耗你自己的 TokenPay（TokenDance）额度；额度耗尽时可使用全平台共享的有限免费任务池。

## 快速开始（Agent）

```bash
curl -fsSL https://cli.tt2.li/install.sh | sh
tt2 login                     # 设备码授权（需人类在浏览器确认一次）
tt2 push ./dist --name myapp  # 猹询码审查适配后上线 → https://myapp.lhub.tt2.li
```

## 仓库结构

见 [AGENTS.md](AGENTS.md)。文档见 [docs/](docs/)。

## License

MIT
