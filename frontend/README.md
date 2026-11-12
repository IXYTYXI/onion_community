# OWS Community 前端

Vue 3 + Vite + Nuxt UI 4 + Tailwind CSS 4，使用 Composition API 和单文件组件。保留原有多页面 URL（`index.html`、`cases.html` 等），确保飞书回调、收藏链接与服务端页面鉴权兼容。顶部菜单通过 Vue Router 站内切换，导航和粒子背景常驻，内容区先淡出 130ms、再淡入 220ms；加载较慢时保留当前页并显示细进度条。直接访问和刷新原有 HTML 地址仍经过服务端鉴权。

## 开发

环境：Node.js 22.12+（本机 24）、npm、Python/uv、项目 Redis。

在项目根目录运行 `uv run python -m app`：首次自动安装锁定的 npm 依赖，构建 Vue，启动后端、8765 同源网关及 Vue 构建监听。修改 `.vue`、JS 或 CSS 后自动重新构建，刷新浏览器查看（此模式不提供 HMR）。Ctrl+C 同时停止三个进程。Redis 使用 `docker compose up -d redis` 启动。

- 网站：http://127.0.0.1:8765/index.html
- 接口文档：http://127.0.0.1:8000/docs
- 单独构建：`npm --prefix frontend ci`、`npm --prefix frontend run build`
- 前端验证：`npm --prefix frontend test`

## 结构

- `src/pages/`：首页、案例库、资讯、详情、领航团、个人信息、SkillHub、服务与登录。
- `src/components/`：导航布局、案例卡片、分页、发布表单、人员照片与标签。
- `src/router.js`：页面路由、切换时验证会话、预加载数据和滚动恢复。
- `src/styles/page-transition.css`：内容切换、加载反馈及减少动态效果适配。
- `src/composables/useCatalog.js`：搜索、分类、分页及 URL 状态同步。
- `src/services/auth.js`：会话、Cookie 请求、CSRF、退出登录与安全返回地址。
- `src/services/content.js`：后端案例适配、本机草稿及资讯/Banner 原型存储。
- `src/styles/nuxt-theme.css`：全站主题、布局、响应式断点；原有样式放在 legacy CSS 层中，保留领航团拍立得等特定设计。
- `src/styles/nuxt-login.css`：登录页主题。
- `vite.config.js`：Nuxt UI 的 Vue 插件配置，蓝色主色、Slate 中性色、关闭暗色模式与 Router 集成。按钮、输入框、徽标、头像、提示使用真实 Nuxt UI 组件。
- `public/assets/`：品牌与 Lucide SVG 图标。
- `dist/`：构建产物，不手动编辑；后端只提供该目录中的已知页面和资源。

## 数据与权限

业务数据请求仅访问同源 `/api/v1/`。Redis TTL、飞书查询与图片缓存由 Python 后端负责。首页仍按默认顺序展示前三条可展示案例，只有“暂不公开”的案例被后端过滤。领航团保持组织效能团队优先，title 只参与筛选、不展示在卡片上。SkillHub 在新标签页打开 https://onionhub.yc345.tv/ 。

登录入口单独构建。后端根据 Vite manifest 仅放行登录静态依赖；其他页面与业务资源需会话。源文件、manifest、密钥不会作为网页资源公开。不要将整个前端目录设置成 Nginx 静态根目录。

Banner 改为读取鉴权后端 `/api/v1/banner`，使用共享 24 小时 Redis 缓存和私有封面接口，空封面回退品牌矢量图，空链接不显示按钮。详情见 [Banner](../docs/BANNER.md)。

资讯、个人分享仍保持原有本机预览逻辑，未增加后端写入接口；AI Point 待接入。

## 生产部署

构建后将 `frontend/dist/` 连同 Python 项目部署，再运行 `uv run python -m app --backend-only`，由 Nginx 统一转发。远端可只部署构建产物，无需 Node 常驻；需要部署整个 dist（含 `.vite/manifest.json`）以供后端解析登录依赖。构建产物应整包切换，避免半更新。飞书回调域名及后端配置仍按部署环境设置。

迁移前的 HTML、JS、CSS 本机备份位于项目 `var/frontend-before-vue/`，不参与构建，也不会被服务端提供。

Nuxt UI 改造前的源代码备份位于 `var/frontend-before-nuxt-ui/`。保留多页面入口并接入 Vue Router，未迁移 Nuxt 框架；图标、字体不依赖外部 CDN，无 GSAP 或滚动动画。
