---
name: dbs-reset
description: >-
  当用户需要查询本机 Codex 账户的 rate-limit reset credits、5 小时与 weekly
  配额，进行只读测试、排查 OpenAI reset API 的 401/403 登录问题，或明确要求
  检查、预览或执行 Codex banked reset 时使用；也适用于“Codex 重置次数”、
  “还有几次 reset”“每张什么时候过期”“reset credits”“可用重置次数”、
  “配额恢复”“重置机会”等说法。
---

# dbs-reset：Codex 配额与 Reset Credit

查询官方 Codex 登录账户的使用窗口和 reset credit。默认只读；只有用户明确
确认要消耗一张 reset credit 时，才允许进入变更接口。

## 适用场景

- 用户问当前有几次 Codex reset、banked reset 或 reset credit。
- 用户要查看 5 小时窗口、weekly 窗口、重置时间或 credit 到期时间。
- 用户明确要求预览一次 reset，或在再次确认后实际执行 reset。
- 需要区分 OpenAI 上游 reset 与 CPA/sub2api 本地 cooldown 清理。

## 不适用场景

- 没有本机官方 Codex 登录状态，或用户要求输入、粘贴 access token。
- 仅想清理 CPA、sub2api 或其他代理自己的 quota/cooldown 状态。
- 用户没有明确确认，却要求调用会消耗 credit 的接口。
- 试图修改 `~/.codex/auth.json`、Codex 会话、桌面应用或服务端额度。

## 前置依赖与输入输出

- 需要本机官方 Codex 登录文件：`${CODEX_HOME:-~/.codex}/auth.json`。
- 需要 Python 3.9+；脚本只使用 Python 标准库，不需要安装依赖。
- 可选环境变量：`CODEX_HOME` 指向 Codex 配置目录；`DBS_RESET_TIMEZONE`
  指定展示时区，默认 `Asia/Shanghai`。
- 输入是自然语言请求，以及可选的 `--index` 和幂等键；绝不要求用户提供凭证。
- 只读查询输出使用率、窗口重置时间、权威 `available_count`、可见 credit
  的状态和到期时间，不输出 access token、account ID 或完整 credit ID。

## 标准操作流程

1. 先定位本 Skill 目录，再运行只读查询：

   ```bash
   python3 scripts/codex_rate_limit_reset.py check --human
   ```

2. 同时读取 `/wham/usage` 与 `/wham/rate-limit-reset-credits`。以接口返回的
   `available_count` 为数量依据，不能用 `credits.length` 代替；后端可能只返回
   部分详情。若 `applicable_available_count` 存在，也单独报告当前窗口是否适用。
3. 查询阶段绝不调用 consume。用户要求“测试”时，只做上述查询、脚本自测和
   响应结构校验，不消耗 credit。
4. 只有用户明确说要实际执行 reset，且确认这会消耗一张 credit 后，才运行：

   ```bash
   python3 scripts/codex_rate_limit_reset.py consume --index 1 --confirm
   ```

   默认按 `expires_at` 最早的一张可用 credit 选择。网络错误重试时必须复用输出
   的同一个 `idempotency_key`，不能重新生成 UUID。
5. `reset` 与 `already_redeemed` 都是成功路径；成功后立即重新查询两个只读接口。
   `nothing_to_reset`、`no_credit` 和详情不足不能伪报成功。
6. 本 Skill 不替 CPA/sub2api 清理本地调度器状态；如果它们仍把账号视为 cooldown，
   应把“上游已 reset”和“代理本地恢复 routing”作为两个独立动作报告。

## 常见错误处理

| 错误 | 处理 |
| --- | --- |
| `missing_auth` | 提示用户在本机官方 Codex 登录，不索要凭证。 |
| `invalid_auth_shape` / `missing_access_token` | 说明本地登录文件结构不可用，建议重新登录，不修改 auth 文件。 |
| HTTP 401/403 | 按登录过期、账号头不匹配或上游拒绝处理，不能说成“没有 reset”。 |
| HTTP 429 | 报告限流和 `Retry-After`（如果有），等待后重试只读查询。 |
| 响应不是 JSON 或字段改变 | 保留原始凭证隐私，报告结构变化，不猜测次数。 |
| `available_count` 与详情行数不同 | 以 `available_count` 为准，并说明详情可能被截断。 |
| `nothing_to_reset` / `no_credit` | 不消费或不重复消费，明确报告上游返回 code。 |
| `already_redeemed` | 视为幂等成功，使用原幂等键刷新查询，不生成新键。 |

## 安全边界与反合理化

- 只读查询和实际 consume 是两条不同路径；“我只是测试”不能成为调用 POST 的理由。
- 不打印、保存或提交 auth 文件、access token、account ID、完整 credit ID 或原始响应。
- 不把使用率归零解释成客户端改值；reset 是服务端消耗 credit 并刷新窗口。
- 不把 `/v0/management/reset-quota` 解释成 OpenAI banked reset；那是代理本地状态动作。
- 不因一次 401/403 就结论化为账号没有 reset；先区分认证失败和额度结果。
- 不因“详情列表只有一行”就把可用数量改成一；数量字段优先。

## 示例

```text
/dbs-reset 查询我本机 Codex 还有几次 reset，以及每张什么时候过期。
/dbs-reset 只测试可用 reset 次数，不要真的重置。
/dbs-reset 我确认消耗最早过期的一张 reset，执行前说明会发生什么。
```

实际执行前必须先向用户复述：将消耗哪一张 credit、是否当前窗口需要 reset、
幂等键如何复用；没有这次明确确认时，只执行 `check`。

## 验收标准

- 能从本机 Codex 登录状态完成只读查询，并报告 5 小时、weekly 和 reset credit。
- 数量来自 `available_count`，详情不足时不会误报数量。
- 静态自测不需要真实凭证；本地集成验证最多查询，不调用 consume。
- 所有失败路径都不泄露凭证；实际 consume 只有显式 `--confirm` 才能发出。

## Skill Handoffs

- 新建、修改、评测本 Skill 交给 `joe-make`；安装、暴露或同步交给 `joe`。
- 仓库校验、commit、push 和远端回读交给 `dev`。

完成当前任务后直接结束。只有用户明确询问下一步，且当前环境已经安装 `/dbs` 时，简短提示：「下一步不确定时，可以输入 `/dbs`。」
