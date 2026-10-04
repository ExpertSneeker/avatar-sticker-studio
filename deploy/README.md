# 阿里云生产部署

Production URL: https://sticker.coreages.com

The current organization/guest workflow and migration procedure are documented
in [framework-release.md](framework-release.md). Its tenant roles, credit-free
generation, frozen customer selections and manual print-only downloads supersede
the historical release notes below. Do not use the original local-data transfer
procedure to upgrade an existing production database.

生产服务器为阿里云 ECS `8.130.175.250`（Ubuntu 22.04）。`sticker` 账号运行单个 systemd 管理的 Uvicorn 进程，仅监听 `127.0.0.1:8000`；独立 Nginx 虚拟主机负责 HTTPS 和反向代理。主站和 Wiki 使用自己的虚拟主机，不属于本应用发布范围。不要启动第二个生产 worker。

## DNS、SSL 与入口

阿里云 DNS 的 `sticker` A 记录指向 `8.130.175.250`，TTL 为 600 秒。生产后台为 https://sticker.coreages.com/，客户入口为 https://sticker.coreages.com/guest。前端 API 使用同源 `/api`，不需要把服务器 IP 写入前端代码。

- Nginx 模板：[sticker-nginx.conf](sticker-nginx.conf)；生产安装到 `/etc/nginx/sites-available/sticker.coreages.com` 并链接到 `sites-enabled/`。
- 独立 Let's Encrypt 证书位于 `/etc/letsencrypt/live/sticker.coreages.com/`。HTTP 的 `/.well-known/acme-challenge/` 使用 `/var/www/acme`；其他 HTTP 请求以 308 跳转 HTTPS。
- 签发命令：`certbot certonly --webroot -w /var/www/acme -d sticker.coreages.com --non-interactive --agree-tos --reuse-key`（首次使用需按账户状态配置联系邮箱）。
- 现有 `certbot.timer` 管理续期；`/etc/letsencrypt/renewal-hooks/deploy/20-nginx-reload` 在续期后执行 `nginx -t` 并 reload。验证使用 `certbot renew --cert-name sticker.coreages.com --dry-run`。
- Nginx 不直接公开数据目录，也不为受保护 API 设置共享缓存。请求访问日志关闭，错误请求 URL 不落盘；应用诊断通过 systemd journal 的脱敏业务日志查看。
- 历史客户入口仅作为服务器端兼容跳转，保留路径和订单号参数；业务、回调和未来消息统一使用新入口。兼容入口也在本服务器续期，不运行另一套业务服务。

官方运行工具：[uv Python 安装](https://docs.astral.sh/uv/guides/install-python/)、[Certbot webroot](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot)。

## Layout

- `/opt/avatar-sticker-studio/releases/<commit>`: source and locally built `frontend/dist`.
- `/opt/avatar-sticker-studio/current`: selected release symlink.
- `/opt/avatar-sticker-studio/venv`: Python 3.13 environment, installed from `uv export --frozen --no-dev`.
- `/var/lib/avatar-sticker-studio`: private database and assets; owned by `sticker`, mode 0700. Reference images are in `reference-assets/` and deployment verification artifacts in `deployment-qa/`, neither publicly served.
- `/etc/avatar-sticker-studio.env`: root-owned mode 0600, based on the supplied example. Existing API keys remain in the private database, never Git.

Ubuntu 系统 Python 3.10 不满足项目约束。使用官方 uv 在 `/opt/avatar-sticker-studio/python` 安装独立 Python 3.13，并创建 `/opt/avatar-sticker-studio/venv`，不替换系统 Python。安装 `fonts-noto-cjk`、`rsync` 和 CA certificates。生产依赖使用锁文件及其哈希安装；网络较慢时可使用阿里云 PyPI 镜像。 Build the frontend locally with `npm ci --prefix frontend && npm run build`; export production requirements using `uv export --frozen --no-dev --format requirements-txt`. Install dependencies in the server environment, transfer source/build, and install the supplied unit/environment file. Bootstrap is disabled in production; transfer initialized accounts before starting the service.

## 完整迁移与后续发布

迁移前核对所有在途/未知请求、待处理通知及有效 OAuth 会话；等待可安全结束的任务，停止写入端后复制完整数据目录。保留一份受限的一次性迁移备份。新端先比较全部记录、SQLite 完整性和原图哈希，再修改允许主机、来源及 Agiso 公网 URL；只更新已有接入订单中的派生选图链接，历史快照和消息审计不批量替换。确认旧业务 worker 已停止后，只启动新端。 Transfer through SSH, compare file SHA256 values and all records, run SQLite integrity and asset-reference checks, then start the server. Preserve original account credentials and prompt/API configuration. Never overwrite a production database that has received new orders with an earlier local copy.

The domain change requires logging in again and choosing local output directories again. Browser IndexedDB drafts, directory handles and local download ownership do not transfer between origins. Existing downloaded files without their management records remain protected from overwrite; select a new empty output directory when necessary.

## Operation

```sh
systemctl status avatar-sticker-studio
curl --fail http://127.0.0.1:8000/api/ready
journalctl -u avatar-sticker-studio --since '30 minutes ago'
```

Use controlled service restarts, retaining durable FAL request IDs. Unknown cutout requests require explicit manual retry; never automatically resubmit a deployment smoke request. Changing the release symlink and restarting selects another compatible code version; this does not roll back business data.

按用户 2026-10-05 要求，每次发布验收后手动将完整备份归档到私有 OSS；本机与 OSS 合计保留最近 3 份不同快照，同一快照多处存放只计一份。本机保留最新 1 份，另两份经读回校验后仅保留 OSS 归档。不安装定时任务。具体操作见下文。

## Display image cache

Only display images use `/api/assets/{id}/preview?size=320` or `size=1280`.
Pillow encodes WebP at quality 80 without upscaling; transparency and white
watermark backgrounds are retained. Original URLs, download ZIPs and manifests
continue to serve the original PNG bytes. Modal viewers provide an explicit
original-image toggle for detailed inspection.

Derivatives are generated on demand under `preview-cache/<asset-id>/` in the
private data directory. The 256 MiB encoded-file budget uses least-recently-used
eviction, pruning to approximately 80% when full. Encoding and eviction share a
cross-process lock; only one image is encoded at a time. Incomplete temporary
files are reclaimed on the next cache miss. Below 512 MiB free disk space, or
if persisting a cache entry fails, the compressed response is returned without
storing it. No external service or backup is added.

Every preview request, including cache hits and conditional 304 responses,
checks the authenticated account and asset access. Responses use
`Cache-Control: private, no-cache`, `Vary: Cookie` and versioned ETags. Do not add
Cloudflare rules that force these private endpoints into a shared cache.

Administrator date cleanup includes all cached variants of removed assets,
including historical outputs and variants created after the cleanup preview.
Template/shared surviving assets stay protected. A durable per-asset cache
cleanup entry is retried via the existing cleanup-retry action and on startup.
The storage panel reports cache use and the limit; cached bytes are already
included in the application's total. Cached derivatives are disposable and do
not replace manual retention management of original orders.

## Customer watermarked media cache

Customer and staff order media use `Cache-Control: private, no-cache`,
`Vary: Cookie` and a weak content ETag (asset hash, watermark text, size tier,
rendering pipeline). Links carry no order version, only an `m=` watermark
fingerprint so open pages swap images after a watermark change. Browsers may persist the WebP
bytes, but must revalidate before reuse. Authorized unchanged requests return
an empty 304 without reading originals or rendering. Logout, expired sessions,
disabled access, cancellation and the submitted-order view are checked live
before 304. Other guest APIs remain `no-store`. Never force these private
endpoints into a shared CDN cache. Browser storage is best-effort; previously
displayed/saved images cannot be remotely erased.

On the server, renders go through a 256 MiB in-process LRU and a persistent
disk cache at `STUDIO_MEDIA_CACHE_DIR`. The systemd unit sets
`CacheDirectory=avatar-sticker-studio` and points the variable at
`/var/cache/avatar-sticker-studio/media`, outside the data directory, so release
backups do not copy it; losing it only costs re-rendering. There is no size
limit: library watermark files are removed when the sticker is deleted or its
watermark is no longer in use; customer images are removed after each
organization's retention days (default 15) since last use. Writes pause below
512 MiB free disk. A background warmer (lowest CPU priority, every 10 minutes)
pregenerates library tiers 160/320/640 for every in-use watermark and the 640
preview of open-order customer images. When migrating servers, the cache need
not be copied.

## Historical release: personal templates and production credits

The one-time `personal-credits-v1` database migration preserves existing template
IDs, images and versions as public resources. Existing members begin with zero
credits; administrators are exempt. Previously submitted items have no billable
generation record and finish without retroactive charging. New orders and manual
reruns reserve one credit per image for the order owner. A valid 1024 × 1024 raw
result saved on the server settles that reservation; subsequent matting, layout,
watermark and download operations are free. Definitive failures release holds;
unknown provider results remain held for recovery or administrator reconciliation.
Do not clear unknown generations directly in the database.

Account management provides member creation, invitations, activation, password
reset and credit adjustment. Temporary passwords are shown once; password resets
revoke existing sessions. Setting a balance changes available credits only, leaving
frozen credits intact. Adjustments use a wallet version and idempotent client token.
`POST /api/orders/{id}/items/{item_id}/rerun` also requires a JSON `client_token`, retained by clients
until the operation has been confirmed. A retry with the same token never creates
a second generation, even after the first finishes. Manual new reruns use new tokens.

Personal templates are editable only by their owner, public templates only by
administrators. Source and preview endpoints enforce access before cache or 304
responses. Set codes remain globally unique. Production statistics filter by order
submission date; credit ledger filters use the transaction's own timestamp.

Date cleanup releases remaining eligible reservations and removes associated
images, preview cache and generation records, preserving the minimal credit ledger.
Orders with unresolved credits must be reconciled before cleanup. No paid provider
requests are needed for regression testing: `uv run pytest backend/tests`,
`npm test --prefix frontend`, `npm run build --prefix frontend` and
`npm run test:e2e --prefix frontend` use isolated data and mock generation services.

## Task previews and repeated names

Task-list preview dialogs open the original watermark overview by default; list
thumbnails remain compressed. Each task has its own download button that selects
a destination and downloads only that task, independently of checked rows.

Order display names may repeat. Within an account, a transactional `output_name`
reserves a distinct folder name (`Name`, `Name (2)`, etc.), including conflicts with
literal numbered names. Manifests and ZIP roots use this name; pre-existing orders
fall back to their original name. Task IDs and submission tokens still provide
identity and retry deduplication. Existing local ownership checks remain in force:
foreign or modified files are never silently overwritten, including files left
behind after an older order was cleaned from the server.

Task names and “查看详情” now open a task-detail dialog above the filtered list.
Nested image, layout and repair dialogs close independently. Without a global
output directory, choosing a draft's location first establishes that global
default. Subsequent choices override only the chosen draft; submitted destination
bindings are unchanged. Cancelled native pickers leave drafts and defaults intact.

## Public sticker library release and A1 replacement

The `public-stickers-v1` startup migration preserves legacy template IDs,
revision records and order snapshots while normalizing the catalog as public
resources (`owner: null`). Only administrators and members explicitly granted
`can_edit_library` may edit it. Account removal and date cleanup protect assets
referenced by current or historical sticker revisions.

Transfer the twelve original `A1-01.png` through `A1-12.png` into a private
staging directory readable by `sticker`. Validate SHA256 against the local files.
After tests and the frontend build pass, deploy the new release, wait for no
running/unknown or remotely reserved items, and stop the service for the switch.
Run from the new release as the service owner:

```sh
sudo -u sticker /opt/avatar-sticker-studio/venv/bin/python -m backend.app.import_a1 \
  --data-dir /var/lib/avatar-sticker-studio \
  --source-dir /var/lib/avatar-sticker-studio/reference-assets/A1
```

The importer validates all twelve PNGs and case-insensitive code collisions
before changing the catalog. It preserves the exact original PNG bytes, stages
public assets durably with deterministic IDs, then creates twelve sticker rows
and a fresh `模板A` / `MB-A` in one SQLite transaction. The previous active MB-A
is archived (`deleted: true`, `active: false`); its IDs, revision rows, assets and
historical order references remain. This is a replacement of the active catalog
entry, not an edit of old order snapshots. Missing/invalid input or collisions
abort without switching the active template. Interrupted staging can be rerun.
A completed repeat with the same sources returns `already_imported: true` and
does not create duplicate records. Changed sources require a separately reviewed
migration rather than silently rerunning this import.

Select the release with an atomic `current` symlink replacement and start the
service. Verify `/api/ready`, SQLite integrity, all twelve sticker source hashes,
exactly one unarchived MB-A, preserved old revision and order records, public
asset access and member editing permissions. Do not overwrite live data with a
local database. Retain the previous release; reverting code alone does not undo
this catalog migration, so check backward compatibility before rollback.

During this replacement, migration-derived members used exclusively by the old
MB-A are archived too. The migration marker records exactly which sticker IDs it
created. Independently uploaded stickers and members referenced by any surviving
template remain active; original sticker revisions and assets are preserved.

`deploy/audit_public_library.py` opens SQLite with `mode=ro` and reports record
hashes and file integrity without printing user credentials or provider settings.
Before switching, capture its stdout privately as a baseline. After migration,
pass `--baseline /path/to/baseline.json`; it checks old order, item, generation,
credit, upload and template-revision hashes plus every old asset file, while
allowing the intentional catalog additions. Run with in-flight work drained.

```sh
python3 deploy/audit_public_library.py --data-dir /var/lib/avatar-sticker-studio
python3 deploy/audit_public_library.py --data-dir /var/lib/avatar-sticker-studio \
  --baseline /private/path/before-public-library.json
```

## Pinduoduo / Agiso integration

See [the shop setup and acceptance guide](../docs/agiso-setup.md). Install the
locked `cryptography` dependency, provision the four `STUDIO_AGISO_*` connection
variables from `production.env.example`, and retain the encryption key alongside
the existing private environment configuration. All shop automation defaults off;
aftersales must remain off until real provider events are verified. The service
unit disables request access logs; inspect any proxy or Cloudflare logging as well
to avoid recording guest order query strings or authorization codes. Production
continues to use its existing Cloudflare tunnel; no additional public port or
Windows software is installed on the Linux website server.

## OSS 打印交付配置

生产 Bucket 为 `coreages-sticker`，地域 `cn-wulanchabu`，标准 ZRS、私有并阻止公共访问；不开版本控制、生命周期、CDN 或传输加速。ECS 的 `sticker-ecs-oss` 实例 RAM 角色仅允许 `print/`、`backups/`、`selftest/` 前缀的必要对象操作及带前缀条件的列举，不使用长期 AccessKey。

配置项见 [production.env.example](production.env.example)：内网上传/删除/列举 Endpoint 为 `oss-cn-wulanchabu-internal.aliyuncs.com`，公网签名 Endpoint 为 `oss-cn-wulanchabu.aliyuncs.com`。`STUDIO_OSS_BUCKET` 为空时功能关闭；`STUDIO_OSS_DOWNLOAD=0` 仅关闭直链、继续后台上传；`STUDIO_OSS_URL_TTL=300`。修改私密环境文件后受控重启唯一服务，禁止输出整个环境或元数据凭证内容。

CORS 只允许 `https://sticker.coreages.com` 的 GET/HEAD，允许头 `*`，暴露 ETag、Content-Length，预检缓存 600 秒。权限仍由私有对象签名控制，CORS 不代替认证。首次启用先在 `selftest/` 上传合成 PNG，验证内网读回哈希、越权前缀拒绝、生产页面跨域 fetch 及 curl 下载；测试后删除合成对象。默认域名不可用时先向用户报告，不自行绑定域名。

Worker 每 30 秒串行同步当前有效打印 PNG，每 10 分钟清理过时对象；不迁移原图、头像、图库和水印预览。下载失败只影响交付，不能重新生图、释放未知请求或改订单状态。日志只记录脱敏失败类型，不记录完整签名 URL。排障先检查 Bucket/角色、内网网络、当前订单 artifacts 和上传状态，再查看脱敏日志；禁止输出密钥或客户内容。

发布验收需要真实后台下载并确认正文来自 OSS 公网域名，同时观察 ECS 出网。ZIP 和远端失败后的回退仍走 3Mbps；关闭直链可快速恢复原下载路径，但已发链接直到其有效期结束仍可能可用。

## 手动备份归档与三份保留

`deploy/backup_archive.py` 复用应用的内网 OSS 客户端及 ECS RAM 角色。归档输入必须是停服后完成、核验过的完整配对备份目录；不要归档运行中的数据目录。脚本不创建业务备份，也不启动 Database 或 worker。

以 root 读取现有私密环境文件后，从当前 release 运行（不要开启 shell trace）：

```sh
cd /opt/avatar-sticker-studio/current
set -a
. /etc/avatar-sticker-studio.env
set +a
/opt/avatar-sticker-studio/venv/bin/python deploy/backup_archive.py \
  --archive /opt/avatar-sticker-studio/backups/<本次配对备份目录> --verify-readback
/opt/avatar-sticker-studio/venv/bin/python deploy/backup_archive.py --prune
/opt/avatar-sticker-studio/venv/bin/python deploy/backup_archive.py --prune --apply
```

先归档新备份并核验，再读 prune 计划；仅 `--apply` 执行删除。归档为不压缩 tar，临时文件位于 `/var/tmp`，需预留至少一份备份的空间。对象位于 `backups/<快照UTC时间>-<目录名>.tar`，快照时间取源备份时间而非本次上传时间，SHA-256 写入对象元数据；`--verify-readback` 从内网流式读回并校验，完成后删除临时 tar。重复归档按同一快照识别，不应挤占保留名额。

合计保留最近 3 份不同快照；OSS 删除超出的归档，本机保留最新 1 份。位于最近 3 份内但不是最新的本机目录，必须已有匹配且读回校验通过的 OSS 归档才可删除；不在最近 3 份的旧本机目录按用户规则清理。不明目录、符号链接和不符合归档命名的对象先调查，不能按通配符删除。

首次启用时先将已有 3 份备份逐个 `--archive --verify-readback`，再归档本次发布备份，最后执行 prune；目标为 OSS 3 份、本机 1 份，合计 3 个快照。每次后续发布重复“停服完整备份 → 部署验收 → 归档读回 → prune”，不添加 cron 或 systemd timer。

## 从 OSS 归档恢复

先确认所选快照与旧 release 配对，且恢复不会覆盖上线后新业务。停止唯一服务后，通过内网客户端把指定归档下载到受限的临时目录，核对元数据中的 SHA-256，再检查 tar 成员，解到新的暂存目录；不要直接覆盖正式数据。

```sh
umask 077
# OSS_BACKUP_KEY 只填写经核对的 backups/ 下归档 key，不填写签名 URL。
export OSS_BACKUP_KEY='backups/<经核对的快照>.tar'
export OSS_RESTORE_TAR='/var/tmp/sticker-restore.tar'
/opt/avatar-sticker-studio/venv/bin/python - <<'RESTORE'
import hashlib, os
from pathlib import Path
from backend.app.oss_delivery import create_store
store = create_store()
key = os.environ['OSS_BACKUP_KEY']
assert store is not None and key.startswith('backups/') and key.endswith('.tar')
meta = store.head(key)
expected = meta.metadata['sha256']
p = Path(os.environ['OSS_RESTORE_TAR'])
digest = hashlib.sha256()
with p.open('xb') as out, store.read(key) as stream:
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        out.write(chunk)
assert digest.hexdigest() == expected, '归档哈希不一致，禁止恢复'
print('归档哈希校验通过')
RESTORE
```

使用 Python 3.13 的 `tarfile` 数据过滤器安全解包至新建目录（`extractall(..., filter='data')`），拒绝越界路径；根据归档根目录检查 `data/studio.sqlite3`、文件哈希清单与配对审计。保持原权限及服务属主，完整恢复数据目录及必要环境配置，原子选择配对旧 release 后启动并验收。SQLite 数据和 release 必须配对，不能只切链接或只恢复主数据库文件。存在新业务时采用向前修复。

OSS 启用后发布审计显式使用 `deploy/audit_framework.py --allow-oss-delivery` 生成基线并执行比对（`--baseline <同模式基线>`）；该模式只忽略打印 artifact 中与组织、订单及 SHA-256 完全匹配的 oss_key 标记，其他业务字段和原图仍严格比对，错误 key 直接失败。基线与结果的比较模式必须相同，不能用旧模式基线冒充同模式检查。
