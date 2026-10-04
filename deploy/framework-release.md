# 数据迁移、配对备份与发布

This release adds tenant isolation, a separate guest workflow, immutable customer
result versions, and explicit print-only delivery. Source specification and API
contract: `docs/superpowers/plans/2026-09-11-organization-guest.md`.

## Compatibility and backup boundary

Run the migration audit using the previous deployed release's data schema (the
implementation baseline is `eb627b8`). This section records the historical organization migration. Current Stage B startup rejects orders/items with missing or non-3 workflow versions before mutation. Older data must first be explicitly converted and rehearsed in isolation; never replace production with a local database.

The `organizations-v1` migration adds organization ownership, converts existing
administrators to organization administrators, and preserves catalog revisions,
order snapshots and original asset bytes. It is idempotent. Current customer orders use one structure; legacy order routes have been removed. Old display names are never guest login credentials. Actual generation/request records and unresolved holds remain; website credit ledgers and wallet fields are removed by the explicit Stage B migration.

A code-only rollback to pre-organization releases is not supported: those
releases do not understand the new roles or customer order workflow. If rollback
is needed before accepting new work, stop the service and restore the paired
pre-release database/assets backup and old release link. After accepting new work,
preserve the new data and use a forward fix or an explicitly reviewed data
reconciliation. Never restore an old database over newer customer submissions.

## Read-only rehearsal

The audit emits hashes and counts, not passwords, session tokens, private notes,
provider keys or prompt text. Its SQLite source connection is read-only.

```sh
python deploy/audit_framework.py --data-dir /var/lib/avatar-sticker-studio
python deploy/audit_framework.py --data-dir /var/lib/avatar-sticker-studio --rehearse
```

`--rehearse` uses SQLite's backup API to migrate a temporary database, reads
original assets for integrity checks, and runs migration twice to establish
idempotency. It does not start a worker or submit provider requests. Capture the
normal audit privately before deployment, then compare after migration:

```sh
python deploy/audit_framework.py --data-dir /var/lib/avatar-sticker-studio \
  --baseline /private/path/framework-before.json
```

The command exits nonzero for missing or changed originals, changed historical
snapshots/configuration, missing generation history, duplicate tenant catalog
codes/order numbers, missing tenant ownership, or broken asset references.

## Release sequence

1. Run backend tests, frontend tests/build and full browser acceptance with the
   fake provider. Inspect guest screens at desktop and mobile sizes.
2. Stage immutable source and `frontend/dist` into a new release directory;
   keep private data and existing provider configuration outside the release.
3. Recheck source revision, service health, queued/running/unknown work and
   remote reservations. Stop accepting new requests and stop the sole service.
4. With the service stopped, recheck the queue before migration. If new work
   arrived, restart the old release and drain/reconcile it before proceeding.
5. Make a mode-0700 full data backup on the same private server and capture the
   audit baseline. Verify the backup database and asset hashes, not only its size.
6. Rehearse migration, then initialize the new release's Database on the live
   data directory with no worker. Compare against the baseline. Create the
   separate superadministrator using the supplied bootstrap command with an
   operator-chosen username and a unique password; no default credential exists.
7. Atomically select the new release and start the existing systemd service.
   Check `/api/ready`, organization membership, legacy history, guest entry,
   original asset hashes, logs, and both role-specific login surfaces. Do not use
   a real paid generation as a deployment smoke test.
8. Keep the prior release and paired backup until the new release is accepted.
   Existing authenticated staff sessions are re-authorized on every request, so
   the new organization roles apply immediately.

Create the independent platform administrator from the new release as the service
owner, with an unused username. Interactive invocation asks for the password
twice; it never supplies a default:

```sh
sudo -u sticker /opt/avatar-sticker-studio/venv/bin/python -m backend.app.bootstrap \
  --data-dir /var/lib/avatar-sticker-studio \
  --username siteadmin --display-name '平台管理员'
```

For an unattended release, `--generate-password` generates a unique password.
Redirect its JSON output to a private mode-0600 credential file rather than a
shared deployment log. The account has no organization membership and enters
organization management after login; `magnus` remains the migrated organization
administrator. Existing usernames cannot be overwritten by this command.

## Guest media and operator delivery

Guest sessions cannot authorize backend original or manifest endpoints. Guest
images are flattened and watermarked on the server. Watermarked media allows
private browser storage with `Cache-Control: private, no-cache`, `Vary: Cookie`
and versioned ETags. Every reuse revalidates authorization, including 304
responses; matching validators skip image IO and encoding. Other guest API
responses retain `Cache-Control: no-store`. Never add a CDN rule that caches guest API responses
publicly. Cancellation and watermark revision changes invalidate guest media
links. Do not expose the private assets/cache directories through Nginx or the
Cloudflare tunnel.

Watermark changes use selected-order preview/confirmation and each opener's
current setting. Existing print defaults remain frozen. Preview regeneration
never submits an AI generation.

Saving files requires an explicit backend action. Batch delivery uses the
browser directory picker when available, otherwise ZIP; only print pages appear
in either manifest. Folder names are sanitized from order number and internal
notes. Customers never receive those notes or the original print manifest.


## 2026-10-05 阶段 B 发布闸门

使用新 release 的审计器和实际生产数据路径，先 `--allow-single-order-migration --rehearse`，核对 source/migrated integrity=ok、idempotent=true、failures=[]；该操作仅迁移临时 SQLite 副本、不启动 worker、不复制改写原图。正式发布前生成相同模式基线，发布后用 `--baseline` 对比。模式只允许版本/点数指定字段和点数集合删除及合法 OSS 打印标记变化，generations、原图和业务状态严格保留。

停止服务前后均确认没有正在运行、未知、远端占用或不确定抠图。取消且暂停订单的 queued 记录可能是刻意保留：仅无请求，或已处于 postprocess、FAL COMPLETED 且原图文件哈希核验通过时，才可认定不在途；不修改这些记录来制造空队列。

发布前明确告知：阶段 B 删除字段后，旧代码会看不到订单，回退必须停服并恢复本次配对完整备份及旧 release；仅限尚未产生新业务时。新订单/生成结果产生后向前修复。完成真实 OSS 下载与权限验收后，将新备份归档读回校验，再按最近三份/本机最新一份规则整理。
