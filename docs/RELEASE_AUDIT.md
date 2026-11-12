# 部署接入核对记录 · 2026-10-29

## 已修复

- SQLite 提交事务内预占项目名，名称唯一且绑定应用。并发 16 个不同请求编号抢同名仅成功一个，其余返回冲突；失败事务不遗留应用。
- 同请求编号重复提交返回原任务；同编号修改参数拒绝。已受理任务在执行器停止后仍可幂等查询。已有应用的未完成/待恢复任务阻止重复排队。
- 执行可用性改为配置与新鲜心跳共同判断；后台协程失败、正常退出清除就绪状态。
- 前端切换任务取消旧请求，忽略迟到响应；离开页面清理计时器及请求。保留最新应用记录，增加项目名可用性提示。
- 成功任务展示域名；失败展示错误码、原因、字段和处理建议。修正应用快照缺少 active release 导致域名及上线状态遗漏。
- SQLite outbox 同步访问地址与详细错误至飞书，部署记录表已新增“访问地址”。连续状态变化不再清除失败重试的退避时间。
- 提取 DeploymentActivity、DeploymentStatus 组件及通用 BitableWriter。部署页延续既有圆角、色彩与三箭头组件。
- 图片缓冲区显式释放；写图后回收超期可再生成缓存和遗留临时文件。引擎保留容器/镜像归属验证和 cleanup/recovery 检查点，未做全局 Docker prune。
- 增加生产 Dockerfile、compose.server.yaml、server.env.example、启动前检查脚本及宿主机 Worker systemd 配置。API/Worker 身份配置必须一致，生产部署模块初始化失败不再静默忽略。

## 验证

| 检查 | 结果 |
| --- | --- |
| 社区 Python 全量测试 | 166 通过 |
| 部署引擎 worker、权限、域名释放、runtime、存储及下线回收测试 | 184 通过，1 项因本机文件系统不支持 user xattrs 跳过 |
| Vue/JavaScript 测试 | 27 通过 |
| Vue 生产构建 | 通过 |
| 修改的部署模块 Ruff 检查 | 通过 |
| Docker Compose 生产配置解析 | 通过 |
| 本地 SQLite quick_check | ok，未创建真实部署任务 |
| 本地 API /health/ready 与前端登录页 | 均返回 200 |
| Docker 镜像构建 | 两次因 auth.docker.io 连接超时中断，未验证完成 |
| Linux 上真实仓库构建、域名/TLS、XFS 配额、恢复测试 | 未在目标服务器执行 |

原始输出在 var/audit-backend-tests.log、var/audit-engine-tests.log、var/audit-frontend-tests.log、var/audit-frontend-build.log、var/docker-audit-build.log。

当前结论：代码回归与生产配置检查通过；生产镜像及 Linux 自动部署链路尚未验收，不能把当前状态描述为无需配置、直接上线即全部可用。上线步骤和环境条件见 DEPLOYMENT.md。本次未改变原线上自动部署服务，也未迁移其域名或数据。
