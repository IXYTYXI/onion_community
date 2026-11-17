# GitLab 主仓库与自动发布

`https://gitlab.yc345.tv/fengyang1/owsc.git` 是唯一写入入口。GitHub
`IXYTYXI/onion_communiyt` 是只读镜像；不要直接向 GitHub `main` 提交。
GitLab `main` 的流水线依次测试、推送 GitHub、打包、发布到生产服务器。
GitHub 推送失败时，服务器发布不会开始；推送使用普通快进更新，不强推。

## GitLab 项目变量

下列变量均设为 **Protected**，只供受保护的 `main` 分支使用。私钥设为
**File** 类型，不能加入 Git 仓库或服务器应用配置文件。

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
`deploy/ci/activate.sh` 和 `scripts/package_release.py` 安装到
`/usr/local/libexec/ows-community/`，由 root 持有、其他用户不可写。
sudoers 只允许 `ows-release` 执行该固定脚本。服务仍读取
`/etc/ows-community/*.env`，部署状态和 SQLite 仍在 `/var/lib/awesome-deploy/`，
均不进入发布包，也不被同步到 GitHub。

发布脚本校验 GitLab 构建包的 SHA-256 和提交号，先在独立目录构建新虚拟环境，
再暂停 Worker 与 API、切换代码、检查服务和就绪接口；失败时恢复本次发布前
的代码与虚拟环境。临时回滚文件在成功后删除。数据库的定期备份和恢复验证
需要独立制定计划，不能用代码回滚代替。

## 操作约定

- 开发在 GitLab 分支提交，合并到受保护的 `main` 后自动开始发布。
- 镜像和部署失败时查看 GitLab Pipeline；不要在服务器上手工改线上代码。
- 同步检查：`git ls-remote` 两个仓库的 `refs/heads/main` 应相同，
  且等于 `/opt/ows-community/.release-commit`。
- 若 GitHub `main` 被直接提交，镜像作业会因非快进更新而停止；先调查差异，
  不要强推覆盖。
