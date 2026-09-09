# dbs-reset prior-art 与取舍

## 调研日期 / 查询词

2026-09-09。查询词：`Codex rate limit reset`、`OpenAI usage quota`、`Codex reset credit`。

## 本地与上游证据

- 本地 dbskill 已有 `dbs-update`、`dbs-install-skill` 和 `dbs-skill-maker`，没有覆盖 Codex 上游 reset credit 查询或 consume 的正式 Skill。
- 本机官方 Codex 登录状态可用于只读验证；本轮只调用查询接口，不调用 consume。
- 上游协议采用用户提供的 `/wham/usage`、`/wham/rate-limit-reset-credits` 与 `/consume` 契约；实现以 `available_count` 为权威数量。

## 外部候选

| 候选 | 来源 / 信号 | 决定 | 说明 |
| --- | --- | --- | --- |
| `huajiexiewenfeng/codex-reset-credits` | GitHub，MIT，skills.sh 约 67 installs | adapt | 借鉴本机 auth 读取与过期时间展示；不复制正文，补充 usage、幂等 consume 和安全边界。 |
| `liewcf/agent-skills/codex-reset-credit` | GitHub，skills.sh 约 51 installs，无明确 license 证据 | reject | 只作为触发与只读边界参考，不复制代码或正文。 |
| `sudoHG/codex-reset-credits-skill` | GitHub，MIT，skills.sh 约 14 installs，含脚本与测试 | adapt | 借鉴脱敏输出、错误分类和本地时区；重新实现脚本，加入 `available_count`、窗口 usage 与显式确认门。 |
| 官方 Codex / ChatGPT backend 契约（用户提供） | 一手接口约束 | keep | 作为端点、字段、返回 code 与幂等语义的功能基线。 |

## 原创贡献

- 把“查询 OpenAI 上游 reset”与“清其他系统的本地 cooldown”分成两个动作，避免把本地 routing 恢复误称为额度重置。
- `check` 和 `consume` 分离；`consume` 没有 `--confirm` 时在发起网络请求前退出。
- 查询输出只保留窗口、数量、状态、到期时间和 credit 标识，不输出 token、account ID、完整 credit ID 或原始响应。
- 测试合同明确：真实本机验证最多查询和 dry-run，不调用上游 consume。
