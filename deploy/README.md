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

No scheduled backups, off-host backups, backup timers or backup management features are installed, by the owner's instruction.

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
