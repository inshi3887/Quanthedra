# P0A 密钥轮换手册（credential encryption key rotation）

适用范围：`CREDENTIAL_ENCRYPTION_KEY` / `CREDENTIAL_ENCRYPTION_KEYS`（broker credential + MFA secret）。
本手册与 JWT/session 的 `SECRET_KEY` 完全独立——两者生成、轮换、备份互不影响（D-009）。

## 原则

1. **在线写路径永远只用 active key**；读取尝试密钥集合中的全部 key（按 key-id 定位）。
2. 轮换 = 把新 key 加入集合 → 重加密 → 收窄集合 → 删除旧 key，四个阶段。
3. 任何阶段失败都可回退：旧密文从未被删除或覆盖（迁移命令逐行 UPDATE + append-only 审计日志）。
4. 全程禁止在日志、审计表、报告中出现明文密钥或明文凭据。

## 阶段 0 — 前置检查

```bash
cd backend_api_python
python -m app.commands.migrate_credentials --dry-run
```

- 输出 `Key inventory` 必须显示 `persistent_key_configured: true`。
- 记录 legacy / re-encrypted / already-current 计数；errors 必须为 0（有错误先解决再继续）。
- 备份数据库（至少 `qd_exchange_credentials`、`qd_user_mfa`、`qd_p0a_migration_log` 三张表）。

## 阶段 1 — 双密钥窗口（新旧并存）

生成新 key，把 **新 key 设为 active**，同时保留旧 key 供读取：

```env
# .env
CREDENTIAL_ENCRYPTION_KEYS=old-1:<旧key>,primary:<新key>
CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID=primary
```

> 说明：`CREDENTIAL_ENCRYPTION_KEY` 兼容变量不再设置（或与集合中 `primary` 一致）。
> 滚动重启全部进程（backend / trading-worker / celery-worker / celery-beat / scheduler-worker），
> 确认 `/api/health` 200、各 worker heartbeat 正常。此窗口内新写入全部用 `primary`，
> 旧数据仍可读。

## 阶段 2 — 重加密

```bash
# 先演练
python -m app.commands.migrate_credentials --dry-run
# 实际执行（幂等、可断点续传；中断后重跑即可）
python -m app.commands.migrate_credentials --batch-size 200
```

验证：

```sql
-- 每个表都应只剩 active key-id 的 envelope
SELECT key_id, count(*) FROM (
  SELECT split_part(encrypted_config, ':', 3) AS key_id
  FROM qd_exchange_credentials WHERE encrypted_config LIKE 'v2:%'
) t GROUP BY key_id;
-- qd_p0a_migration_log 新增行数 == 阶段 0 的 legacy + re-encrypted 计数
SELECT count(*) FROM qd_p0a_migration_log;
```

## 阶段 3 — 跨容器解密 canary

```bash
docker compose exec -T backend    python scripts/decrypt_canary.py
docker compose exec -T trading-worker python scripts/decrypt_canary.py
docker compose exec -T celery-worker   python scripts/decrypt_canary.py
```

脚本对 broker-credential 与 mfa-secret 两个 purpose 各生成、落库（事务回滚）、读取、解密一次
测试密文并输出 `PASS/FAIL`；任一容器 FAIL 停在阶段 1/2 排查，不得收窄密钥集合。

## 阶段 4 — 收窄与清理（观察期后）

观察期（建议 ≥ 7 天，覆盖一次完整业务周期）确认无 `Cannot decrypt` 错误后：

```env
CREDENTIAL_ENCRYPTION_KEYS=primary:<新key>
CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID=primary
```

滚动重启。旧 key 此时才从配置中移除；纸质/密码管理器中的旧 key 按公司密钥保留策略归档。

## 回退

| 阶段 | 回退动作 |
| --- | --- |
| 1 双密钥窗口 | 把 `CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID` 改回 `old-1`，重启 |
| 2 重加密失败/中断 | 直接重跑迁移命令（幂等）；个别行失败时该行保持旧值，仍可读 |
| 3 canary FAIL | 恢复阶段 1 的双密钥配置并重启——密文本身没有被破坏 |
| 4 收窄后发现丢 key | 重新加入旧 key（集合读取按 key-id 定位，密文未损坏即可恢复） |

## 与 D-014 的关系

本手册只轮换**密钥注入方式**；P0A 的安全行为（缺持久化密钥拒绝启动、默认口令拒绝启动、
新凭据禁用 SECRET_KEY 加密、insecure key 禁写真实凭据）不随轮换回退。
