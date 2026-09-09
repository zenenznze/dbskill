# Codex Reset Credit 接口参考

仅在维护脚本、排查字段或核对上游行为时读取本文件。普通用户查询只需运行
`../scripts/codex_rate_limit_reset.py check`，不要手工复制凭证或直接拼接 POST。

## 接口映射

生产环境使用 ChatGPT backend 的 ChatGPT 风格路径：

```text
GET  https://chatgpt.com/backend-api/wham/usage
GET  https://chatgpt.com/backend-api/wham/rate-limit-reset-credits
POST https://chatgpt.com/backend-api/wham/rate-limit-reset-credits/consume
```

请求头由脚本从本机 Codex 登录状态生成：

```text
Authorization: Bearer <本机登录状态中的 access token>
ChatGPT-Account-ID: <本机登录状态中的 account id>
Accept: application/json
```

access token 和 account id 只能在进程内使用，不能写入仓库、日志、报告或用户回复。

## 查询字段

`/wham/usage` 主要用于窗口和总量摘要：

- `rate_limit.primary_window.used_percent`：5 小时窗口使用率；
- `rate_limit.secondary_window.used_percent`：weekly 窗口使用率；
- 两个窗口的 `reset_at`；
- `rate_limit_reset_credits.available_count`：可用 reset 数量；
- 某些响应还会有 `applicable_available_count`，表示当前窗口适用的数量。

`/wham/rate-limit-reset-credits` 用于详情：

- `available_count`：详情接口声明的权威数量；
- `credits[].id`：服务端选择 credit 所需的内部 ID；
- `status`、`reset_type`、`granted_at`、`expires_at`；
- `title`、`description` 等展示字段可能随上游变化。

后端可能只返回部分详情行，所以 `credits.length` 不能代替 `available_count`。脚本
只向用户展示 ID 尾号，执行时按到期时间排序后在进程内使用完整 ID。

## 消耗字段

```json
{
  "redeem_request_id": "新的 UUID",
  "credit_id": "选中的 credit 内部 ID"
}
```

`redeem_request_id` 是幂等键。若请求已到达上游但响应丢失，重试必须继续使用
同一个键；不能为同一动作重新生成 UUID。脚本把该键输出到结果中，便于用户在
明确授权后重试。

上游结果中：

- `reset`：已消耗 credit，窗口已重置；
- `already_redeemed`：同一幂等键之前已成功，按幂等成功处理；
- `nothing_to_reset`：没有符合条件的窗口需要重置，不能伪报成功；
- `no_credit`：没有可用 credit；
- HTTP 401/403：认证或请求头问题，不等于没有 credit。

## 与代理本地 Reset 的边界

CPA 的 `/v0/management/reset-quota` 以及其他代理的相似接口通常只清理本地
cooldown、quota 缓存或 scheduler 状态。它们不是上游
`/wham/rate-limit-reset-credits/consume`，不能互相替代。上游 reset 后若代理仍排除
账号，需要单独执行该代理记录的 routing recovery 动作。
