# OWS 接入页发布更新

社区的「接入 OWS」页展示固定地址 `https://ai.lab.yc345.tv/files/d/ows-release.json` 的 `cli_version`、运行环境和 `release_notes`。页面显示的数据由社区 API 保存到现有 Redis；不会读取或展示 release 文件内的内网服务地址、安装包哈希等字段。

## 一次性配置

在社区 API 的环境文件中设置一个独立的长随机令牌：

```text
OWS_COMMUNITY_OWS_RELEASE_WEBHOOK_TOKEN=<独立随机令牌>
```

重启社区 API 使其读取该变量。将同一个令牌以受限密钥方式交给 OWS release 发布流程。不要写入仓库、release JSON、网页或安装说明。只有发布流程需要该令牌；普通页面访问继续使用社区登录。

## 每次发布

1. 先把新的 release JSON 通过现有 PUT 流程写入固定地址。更新 `release_id`、`cli_version` 和 `release_notes`，并保证第一条日志的 `version` 等于 `cli_version`。
2. PUT 成功后，向社区发送空请求 `POST https://<社区域名>/api/v1/ows-release/webhook`，请求头为 `Authorization: Bearer <令牌>`。
3. 收到 `200` 且响应的 `data.release_id` 为新版本，才视作社区页面已更新。若失败，保留原页面数据，修正发布文件或网络后重试 webhook。

页面打开时读取社区缓存；首次安装且缓存为空时，社区 API 会从固定地址初始化一次。已打开的页面通过同源事件流 `/api/v1/ows-release/events` 接收版本变化并刷新内容。无需定时同步任务。重复触发同一版本是安全的。

可用以下命令在发布流程中调用（令牌由密钥变量提供）：

```sh
curl --fail-with-body --request POST \
  --header "Authorization: Bearer ${OWS_RELEASE_WEBHOOK_TOKEN}" \
  "https://<社区域名>/api/v1/ows-release/webhook"
```
