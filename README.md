# OWS Community 源码交接包

打包日期：2026-11-04。此包来自当前本地项目源代码，包含 Vue 3 + Vite + Nuxt UI 前端、FastAPI 后端、社区助手及自动部署引擎。未包含服务器数据备份。

## 本地启动

准备 Python 3.12、uv、Node.js 22.12+ / npm、Docker Compose。在本目录执行：

```sh
cp .env.example .env
uv sync --locked
docker compose up -d redis
uv run python -m app
```

首次启动自动执行 npm ci 和前端构建。前端：http://127.0.0.1:8765/index.html；后端：http://127.0.0.1:8000；API 文档：http://127.0.0.1:8000/docs。

仅启动后端时，先运行 `npm --prefix frontend ci` 和 `npm --prefix frontend run build`，再运行 `uv run python -m app --backend-only`。

页面需要登录。使用真实飞书登录前，在 `.env` 填写自己的 FEISHU_APP_ID、FEISHU_APP_SECRET，配置应用权限、可用范围和回调 `http://127.0.0.1:8765/api/v1/auth/feishu/callback`；详见 docs/FEISHU_LOGIN.md。可选本地开发登录需要设置 DEV_LOGIN_ENABLED=true 和至少 24 字符随机 DEV_LOGIN_KEY，可用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成；仅限本地，不可用于生产。配置项均加 OWS_COMMUNITY_ 前缀。

交接模板默认使用本机 Redis，先关闭未配置的资讯同步、部署台账同步和助手；真实部署执行默认关闭。前后端可以运行，但未接入的外部内容不会凭空生成。不要直接复制原作者的应用 ID、表格 ID 或知识库链接作为自己的配置。

## 功能与配置

- 公共内容：前端请求后端，后端先读 Redis，过期后读飞书。需配置自己的 Base、各表/视图 ID、来源租户及读取权限。Banner 默认缓存 24 小时。
- AI 资讯：配置资讯表、视图及写入权限后，将 NEWS_SYNC_ENABLED=true；默认每 600 秒增量同步，刷新缓存。
- 社区助手：配置 ASSISTANT_AGENT_ID、SOURCE_TENANT、FEEDBACK_BASE/TABLE，并配置 Aily 调用方、对话读写权限、知识库、反馈表及插入提醒，再开启 ASSISTANT_ENABLED。会话按用户隔离，有效期一小时。详见 docs/ASSISTANT.md。
- 自动部署：SQLite 是应用/任务/归属/资源状态的权威数据，Redis 缓存查询，飞书保存异步台账。普通 macOS 本地环境不执行真实部署。Linux 执行器需要 rootless Docker、BuildKit、网关、存储配额、域名及凭据，详见 docs/DEPLOYMENT.md 和 packages/deploy-engine/ops。
- 部署资格可配置 app_visibility：本企业登录＋应用可用范围，不读取受雇信息；continuous 另需员工状态权限。社区拒绝仅 login 的执行配置。
- 被部署项目必须在 main 分支根目录包含 awesome.yaml，app.subdomain 须与提交名称一致。当前包的一键部署接入已完成，但本轮未完成新应用成功构建及 HTTPS 发布的完整验收。
- 被部署项目需要 API Key、登录密码等运行密钥时，在 awesome.yaml 的对应服务中用 `secretRefs` 声明环境变量与引用名，不写实际值。首次部署因缺少配置停止后，社区部署记录会显示填写页；用户保存缺失项并继续部署。已配置的值只显示状态，不回显也不通过此入口覆盖。

所有默认名称、品牌素材、静态说明、业务文档链接及测试样例按源码原样保留；用于其他组织时应按实际业务替换。源码包不携带已配置的飞书服务或自动化权限。

## 生产部署

包含 Dockerfile、compose.server.yaml、deploy/server.env.example、Nginx 和 systemd 示例。先填写生产配置，再按 docs/DEPLOYMENT.md 执行。Compose 可启动社区 API/Redis，真实部署执行器还需独立配置 Linux 宿主机环境，不能只靠填写域名启动。

生产关闭开发登录、使用 HTTPS / Secure Cookie、配置正式飞书回调。上线检查：`python -m scripts.check_server`；执行器检查加 `--executor`。本包不含原服务器路径、密钥或运行台账，不能据此直接接管原线上应用。

## 目录

- frontend/：Vue 页面、复用组件、样式、静态素材、测试和 npm 锁文件。
- app/：FastAPI、飞书/Redis/SQLite 集成、助手、部署任务与同步。
- packages/deploy-engine/：自动部署引擎源码、运维工具与测试（必须保留，uv 使用本地依赖）。
- scripts/、tests/：启动检查、缓存维护脚本及后端测试。
- deploy/、docs/：配置示例和模块说明。部分文档保留历史实现说明；当前运行入口与交接默认值以本 README 和配置模板为准。
- SOURCE_MANIFEST.json：包内每个文件的 SHA-256，便于交接核对。

## 不包含

.env / 正式服务器凭据、SSH 密钥、会话和浏览器记录、SQLite / Redis 数据、图片缓存、日志、node_modules、.venv、dist、旧设计截图和宣传视频。依赖与构建产物按锁文件重新生成。
