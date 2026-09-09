# dbs-reset 发布验证

## 证据级别

- 设计优势：`check` 与 `consume` 分离；`consume` 必须带 `--confirm`；查询只输出脱敏字段；同一上游请求支持复用幂等键。
- 已验证优势：静态结构、触发边界、密钥扫描、仓库 Marketplace 契约、打包和本机只读查询均通过。
- 待验证假设：本轮没有调用真实 consume，因此 `reset`、`already_redeemed`、`nothing_to_reset` 的线上返回只通过代码路径和模拟数据覆盖，未改变本机额度。

## 校验结果

```text
bash tools/test-dbs-reset.sh                         PASS
validate_skill.py skills/dbs-reset                   PASS
trigger_eval.py skills/dbs-reset                     PASS (9 cases)
secret_scan.sh skills/dbs-reset                      PASS
check-marketplace-scope.py                           PASS
check-skill-metadata.py                              PASS
check-skill-routing-contract.py                      PASS
check-release-versions.py                            PASS (v2.18.43)
check-plugin-update-contract.py --publish             PASS
check-dbs-update-check.sh                            PASS
test-dbs-install-skill.sh                            PASS
test-dbs-install-skill-windows-mock.sh               PASS
build-skills.sh                                      PASS
```

## 本机 Codex 只读验证

使用本机已登录的官方 Codex 状态执行：

```text
python3 skills/dbs-reset/scripts/codex_rate_limit_reset.py check --human
python3 skills/dbs-reset/scripts/codex_rate_limit_reset.py consume --dry-run
```

结果：本机只读查询和 dry-run 均成功；5 小时与 weekly 窗口、可用数量和详情到期时间均可读。动态账户数值不写入仓库；dry-run 能选择最早到期的可用 credit，但只发出 GET，不发出 consume POST。

另执行无确认保护测试：`consume` 未带 `--confirm` 在网络请求前以退出码 2 拒绝，未执行任何实际 reset。

## 隐私复核

- 真实 `check` 与 `consume --dry-run` 输出不包含任何 credit 标识。
- 仓库内没有写入本机动态账户数量、窗口数值、到期时间、access token、account ID 或原始响应。
- 测试只使用明确的 dummy fixture；历史与当前 reset 相关路径均未发现凭证样式字符串、私钥头或带凭证 URL。
- 本轮没有真实消耗 reset credit，没有修改本机 `auth.json`，没有保存 access token、account ID、credit ID 或原始上游响应。
