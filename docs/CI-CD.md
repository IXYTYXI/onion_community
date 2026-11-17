# GitLab 主仓库与自动发布

`https://gitlab.yc345.tv/fengyang1/owsc.git` 是唯一写入入口。GitHub
`IXYTYXI/onion_communiyt` 是只读镜像；不要直接向 GitHub `main` 提交。
GitLab `main` 的流水线依次测试、打包、推送 GitHub、发布到生产服务器。
发布前还会从 Runner 检查服务器和 GitHub 的 SSH 连接，并核对固定的主机公钥。
GitHub 推送失败时，服务器发布不会开始；推送使用普通快进更新，不强推。
镜像 SSH 连接走 GitHub 提供的 `ssh.github.com:443`，主机公钥固定在
`deploy/ci/github_known_hosts`。

## GitLab 项目变量

下列变量均设为 **Protected**，只供受保护的 `main` 分支使用。私钥设为
**File** 类型。GitLab 的多行 SSH 私钥不能使用 Masked/Hidden 可见性，
因此这两项要选 **Visible**；作业只读取文件路径，不把密钥内容写入日志。
私钥不能加入 Git 仓库或服务器应用配置文件。

| 变量 | 类型 | 用途 |
| --- | --- | --- |
| `GITHUB_MIRROR_SSH_KEY` | File | GitHub 仓库的专用可写 Deploy key 私钥 |
| `OWS_DEPLOY_SSH_KEY` | File | 服务器 `ows-release` 专用 SSH 私钥 |
| `OWS_DEPLOY_KNOWN_HOSTS` | File | 从已认证服务器取得的 SSH 主机公钥记录 |
| `OWS_DEPLOY_HOST` | Variable | 生产服务器主机名或 IP |

GitHub Deploy key 只授予 `IXYTYXI/onion_communiyt` 一个仓库的写权限。
`ows-release` 用户只可把发布包上传到 `/var/spool/ows-community-release`，
并通过 sudo 调用固定的、由 root 拥有的 `activate.sh`。不要把现有 root
私钥或个人 GitHub token 放进 CI。

## 服务器一次性配置

在确认上述访问范围后，在服务器创建 `ows-release` 用户及其授权公钥，
创建仅供该用户写入的发布收件目录；把本仓库的
`deploy/ci/activate.sh`、`deploy/ci/ows-community-slot.service` 和 `scripts/package_release.py` 安装到
`/usr/local/libexec/ows-community/`，由 root 持有、其他用户不可写。
sudoers 只允许 `ows-release` 执行该固定脚本。服务仍读取
`/etc/ows-community/*.env`，部署状态和 SQLite 仍在 `/var/lib/awesome-deploy/`，
均不进入发布包，也不被同步到 GitHub。

`deploy/ci/provision.sh` 将这些一次性配置写在脚本里。运行时把上述
三个文件与专用部署公钥复制到服务器的临时目录，以 root 在该目录执行
`provision.sh`；不要上传私钥。完成后检查 sudoers 语法、目录权限，
并用专用密钥验证 `ows-release` 能登录。部署公钥更换时再次运行脚本。

发布脚本校验构建包的 SHA-256 和提交号，在未接流量的端口构建、启动并
验收新版 API。通过后将原域名的 Nginx 代理从 8000/8001 中的当前端口
切到候选端口，再把唯一的部署 Worker 切到新代码。任一步失败会把网关
和 Worker 指回旧版本；旧 API 保留运行，供回退和现有连接排空。两个 API
使用相同的 `/etc/ows-community/community.env`、Redis 和部署状态目录；
资讯同步由 Redis 租约保证不会并发写入。数据库结构变更必须与旧、新 API
兼容，否则应先制定单独的迁移与回退步骤。数据库定期备份和恢复验证仍需
独立制定计划，不能用代码回滚代替。

## 操作约定

- 开发在 GitLab 分支提交，合并到受保护的 `main` 后自动开始发布。
- 镜像和部署失败时查看 GitLab Pipeline。紧急手动发布仍应使用已提交的
  构建包和同一受限发布脚本，不能直接修改应用源码。
- 同步检查：`git ls-remote` 两个仓库的 `refs/heads/main` 应相同，
  且等于 `/opt/ows-community/.release-commit`。
- 若 GitHub `main` 被直接提交，镜像作业会因非快进更新而停止；先调查差异，
  不要强推覆盖。
