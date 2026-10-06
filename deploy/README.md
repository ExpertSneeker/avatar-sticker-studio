# 阿里云生产部署

Production URL: https://sticker.coreages.com

The current organization/guest workflow and migration procedure are documented
in [framework-release.md](framework-release.md). Its tenant roles, credit-free
generation, frozen customer selections and manual print-only downloads supersede
the historical release notes below. Do not use the original local-data transfer
procedure to upgrade an existing production database.

生产服务器为阿里云 ECS `8.130.175.250`（Ubuntu 22.04）。`sticker` 账号运行单个 systemd 管理的 Uvicorn 进程，仅监听 `127.0.0.1:8000`；独立 Nginx 虚拟主机负责 HTTPS 和反向代理。主站和 Wiki 使用自己的虚拟主机，不属于本应用发布范围。不要启动第二个生产 worker。

## DNS、SSL 与入口

自 2026-10-06 起，公网入口经阿里云 ESA（边缘安全加速，基础版）：阿里云 DNS 的 `sticker` 为 CNAME `sticker.coreages.com.a1.initxa.com`，TTL 600 秒，源站仍为 ECS `8.130.175.250`。生产后台为 https://sticker.coreages.com/，客户入口为 https://sticker.coreages.com/guest。前端 API 使用同源 `/api`，不需要把服务器 IP 写入前端代码。ESA 配置见下文“ESA 边缘加速与源站防护”。

- Nginx 模板：[sticker-nginx.conf](sticker-nginx.conf)；生产安装到 `/etc/nginx/sites-available/sticker.coreages.com` 并链接到 `sites-enabled/`。
- 独立 Let's Encrypt 证书位于 `/etc/letsencrypt/live/sticker.coreages.com/`。HTTP 的 `/.well-known/acme-challenge/` 使用 `/var/www/acme`；其他 HTTP 请求以 308 跳转 HTTPS。
- 签发命令：`certbot certonly --webroot -w /var/www/acme -d sticker.coreages.com --non-interactive --agree-tos --reuse-key`（首次使用需按账户状态配置联系邮箱）。
- 现有 `certbot.timer` 管理续期；`/etc/letsencrypt/renewal-hooks/deploy/20-nginx-reload` 在续期后执行 `nginx -t` 并 reload。验证使用 `certbot renew --cert-name sticker.coreages.com --dry-run`。
- Nginx 不直接公开数据目录，也不为受保护 API 设置共享缓存。请求访问日志关闭，错误请求 URL 不落盘；应用诊断通过 systemd journal 的脱敏业务日志查看。
- 历史客户入口 `sticker.magnusma.online` 已于 2026-10-06 停用：用户确认旧链接已无人使用，删除了其 Cloudflare 解析（此前因源站只放行 ESA 已无法到达）。服务器上残留的兼容跳转虚拟主机与证书不再可达，证书续期会失败，可在清理时一并移除。业务、回调和消息只使用 `sticker.coreages.com`。

## ESA 边缘加速与源站防护

ESA 站点 `coreages.com`（SiteId `182026692718828`，CNAME 接入，加速区域仅中国内地，绑定一年期基础版套餐）。阿里云 DNS 仍是权威解析，其他记录不经过 ESA。以下为 2026-10-06 上线时的配置；变更前用 `aliyun esa` 实时查询，不以本文作为当前状态证明。

| 项目 | 设置 |
| --- | --- |
| 记录 | `sticker.coreages.com` A/AAAA → `8.130.175.250`，开启代理，业务类型 web |
| 边缘证书 | ESA 免费 Let's Encrypt 证书，ESA 自动续期；源站证书仍由 certbot 管理 |
| 回源规则 | 协议跟随客户端（HTTP 80 / HTTPS 443），Host 与 SNI 均为 `sticker.coreages.com`，校验源站证书，读超时 180 秒，不跟随 302 |
| 缓存 | `/api/` 与 `/.well-known/` 强制绕过缓存；其余遵循源站头。源站只对 `/assets/` 下真实存在的构建文件返回 `public, max-age=31536000, immutable`，HTML、API、水印图均不进共享缓存 |
| 压缩 | ESA 规则 `sticker-compress` 对访客开启 Gzip 与 Brotli；sticker 虚拟主机对 JSON/JS/CSS 开启 gzip（`gzip_proxied any`），源站到 ESA 一段也压缩，节省 3Mbps 出口 |
| 真实 IP | 托管转换添加 `ali-real-client-ip`；Nginx 仅从 ESA 回源地址恢复该头（`/etc/nginx/snippets/esa-origin-ips.conf`），登录限流因此按访客真实 IP 计算 |
| 多级缓存 / 源站防护 | 边缘 + 区域；源站防护开启，`AutoConfirmIPList=off`。基础版不支持回源收敛 |
| WAF | ESA 自动生成的“安全等级低”托管规则对威胁分 26–100 的请求出验证码；白名单规则 `agiso-webhook-callback` 让 `/api/agiso/webhook` 与 `/api/agiso/callback` 跳过全部防护，机器推送不会遇到验证码。两接口仍靠签名、state/nonce 自行校验 |
| 安全组 | `sg-0jlhqi0txhes06ug8wdc` 的 TCP 80–443 只允许前缀列表 `pl-0jlj4dafkh3brxsuzz2b`（ESA 当前回源 IPv4 段）；22 端口未改。ECS 无公网 IPv6 |

只有 22、80、443 在公网监听，因此 80–443 端口范围规则不会额外暴露服务。主站和 Wiki 的解析当前暂停；恢复它们时必须同样经 ESA 代理接入，否则会被安全组拒绝。

### 回源 IP 列表变更

源站防护在 ESA 回源 IP 变化时通知，未确认前 ESA 继续使用旧列表。`deploy/esa_origin_ips.py` 取“当前列表 ∪ 待确认列表”，因此按以下顺序可保证 ESA 用到的地址始终已放行：

```sh
aliyun esa GetOriginProtection --region cn-hangzhou --SiteId 182026692718828 > /tmp/op.json   # NeedUpdate / DiffIPWhitelist
python3 deploy/esa_origin_ips.py ipv4  < /tmp/op.json   # 与前缀列表比对，ModifyPrefixList 只 AddEntry 新增网段
python3 deploy/esa_origin_ips.py nginx < /tmp/op.json   # 覆盖 /etc/nginx/snippets/esa-origin-ips.conf，nginx -t 后 reload
# 在 ESA 确认新列表（UpdateOriginProtectionIpWhiteList），然后重新导出 /tmp/op.json 再运行上面两条：
# 此时只剩确认后的列表，从前缀列表 RemoveEntry 已删除网段并重新生成 Nginx 片段。
```

### 验证与排障

- 本机经 Surge 访问会得到 198.18.x 假 IP；检查 ESA 时用 `dig @223.5.5.5 sticker.coreages.com` 取边缘 IP，再 `curl --resolve sticker.coreages.com:443:<边缘IP>`。响应头 `X-Site-Cache-Status`：HTML/API 应为 `DYNAMIC`/`BYPASS`，构建文件重复请求为 `HIT`。
- 源站直连（含 `curl --resolve ...:8.130.175.250`）现在应超时；从服务器本机 `curl http://127.0.0.1:8000/api/ready` 不受影响。
- Agiso 推送通道探针：对 `/api/agiso/webhook` 发送格式正确、签名错误的 form 请求，应得到应用的 `403 通知签名无效`，不是 ESA 页面或验证码；签名错误不写库。
- 出站（FAL `queue.fal.run`、Agiso API、OSS）不经过 ESA，也不受入方向安全组影响。
- certbot HTTP-01 续期经 ESA 的 HTTP 回源到 `/var/www/acme`；验证 `certbot renew --cert-name sticker.coreages.com --dry-run --no-random-sleep-on-renew`。

### 回退

1. 恢复安全组 TCP 80、443 对 `0.0.0.0/0` 的放行（`AuthorizeSecurityGroup`）。
2. 将 AliDNS `sticker` 改回 A `8.130.175.250`（RecordId `2106291818949629952`），等待 600 秒 TTL。
3. Nginx real-IP 片段只信任 ESA 地址，直连时无副作用，可保留；应用的静态缓存头对直连同样适用，无需回退代码。

若 ECS 公网 IP 已被黑洞，DNS 改回直连无效，应按云平台黑洞或付费防护流程处理。

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

### 标准发布脚本

`deploy/release.sh` 把下述“停服完整备份 → 切换 → 审计 → 归档 → 保留三份”串成一次执行，停机只剩数秒：服务运行时先把数据目录完整复制到新备份，停服后只补同步变化的文件并核对副本与停服数据一致（rsync 无差异、数据库文件哈希相同），再原子切换并启动；新版本 90 秒内未就绪会自动切回原 release。启动后对静态副本算 `data-sha256.json`、以副本做审计基线并审计线上数据，审计无失败才归档 OSS 并 prune。旧 release 的带哈希前端文件会复制进新 release，打开中的旧页面仍能加载按需模块。

```sh
# 本机：git archive <commit> + frontend/dist + REVISION 打成 <commit>.tgz，上传到服务器 /tmp 并核对 sha256
bash /opt/avatar-sticker-studio/releases/<commit>/deploy/release.sh /tmp/<commit>.tgz <label>   # 首次可先单独解出脚本
```

脚本不处理需要演练的数据迁移（如单一订单迁移），这类发布仍按对应章节手工执行。备份不使用硬链接：归档指纹包含 inode 与 ctime，硬链接会在旧备份删除时改变新备份指纹。

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

## 单一订单结构与点数下线

现有客户订单统一使用 `/api/customer-orders`，不保留旧 `/api/orders` 批量流程和 `workflow_version` 运行分支。`drop-workflow-version-v1` 迁移先拒绝非整数 3 或缺失版本的旧数据，再删除版本字段与索引；`drop-credits-v1` 删除点数记录及指定字段。生成请求记录、原图、未知占用与 FAL 余额查询保留，详细边界见 [架构契约](../docs/architecture-and-contracts.md)。

`personal-credits-v1` 历史迁移标记仅用于幂等保留原有图库 scope/owner 转换，不再创建点数字段或财务记录。账号创建、邀请、停用、密码重置和会话撤销继续有效。客户操作仍要求 `client_token` 与 `expected_version`；响应不确定时重用原 token 和请求体。

阶段 B 发布前以新审计器的 `--allow-single-order-migration --rehearse` 做私密副本演练，再停服完整备份、切换和审计。该迁移不能仅切旧代码回退：尚无新业务时配对恢复备份与旧 release，接收新业务后向前修复。备份仍按本文 OSS 三份保留规则处理。

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

安装依赖前使用 `umask 022`，随后以 `sticker` 服务账号验证依赖导入及 OSS 只读访问。不能只用 root 验证：root 可以读取权限误设为 `0600` 的依赖代码，实际服务账号却不能。仅程序代码需要普通读取权限；环境文件和客户数据仍保持私有。发布前预检可在加载生产 OSS 配置后运行服务账号 Python，导入 `alibabacloud_oss_v2` 与 `alibabacloud_credentials`、构造 `create_store()` 并列举 `selftest/`；不要输出凭证或签名地址。

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
    for chunk in stream.iter_bytes(block_size=1024 * 1024):
        digest.update(chunk)
        out.write(chunk)
assert digest.hexdigest() == expected, '归档哈希不一致，禁止恢复'
print('归档哈希校验通过')
RESTORE
```

使用 Python 3.13 的 `tarfile` 数据过滤器安全解包至新建目录（`extractall(..., filter='data')`），拒绝越界路径；根据归档根目录检查 `data/studio.sqlite3`、文件哈希清单与配对审计。保持原权限及服务属主，完整恢复数据目录及必要环境配置，原子选择配对旧 release 后启动并验收。SQLite 数据和 release 必须配对，不能只切链接或只恢复主数据库文件。存在新业务时采用向前修复。

OSS 启用后发布审计显式使用 `deploy/audit_framework.py --allow-oss-delivery` 生成基线并执行比对（`--baseline <同模式基线>`）；该模式只忽略打印 artifact 中与组织、订单及 SHA-256 完全匹配的 oss_key 标记，其他业务字段和原图仍严格比对，错误 key 直接失败。基线与结果的比较模式必须相同，不能用旧模式基线冒充同模式检查。


## FAL OSS 输入配置与回退

- 复用 ECS 实例 RAM 角色和同地域内网 OSS 客户端。在当前 `sticker-oss-access` 策略对象资源中追加 `acs:oss:*:*:coreages-sticker/fal-inputs/*`，保留 print/backups/selftest；HEAD 使用 GetObject 权限，无需开放该前缀列举。
- 更新生命周期前先读取并保留现有规则；PUT 会替换整份配置。只增加 ID `fal-inputs-expire-2d`、Prefix `fal-inputs/`、Enabled、Expiration Days=2。读取回验前缀与天数，勿扩展为全桶。OSS 按天扫描和异步执行，2 天过期不等于 48/72 小时必然删除。参见 [阿里云生命周期执行说明](https://help.aliyun.com/zh/oss/user-guide/lifecycle-rules-based-on-the-last-modified-time/)。
- `STUDIO_FAL_INPUT_URL_TTL=7200` 独立于打印链接 TTL；FAL 输入签名不主动设置 attachment 参数；OSS 默认域名可按地域和建桶时间强制返回下载头，不能把签名参数缺省等同于最终响应无 attachment。CORS 不变，不启用传输加速、CDN 或自定义域名。
- 发布默认 `fal_input_mode=inline`。在“管理设置 → 全站并发”切换输入方式无需重启；服务器未配置 OSS 时界面不可用，后端拒绝设置 oss。真实联调与正式开启分开记录。出现问题先切回 inline，已知 request ID 继续原请求恢复；不清除占用或重发未知请求。
- 日常检查脱敏 `fal_submit`（mode、objects_reused、stage_ms、post_ms、request_bytes、outcome）、`fal_poll`（状态变化、queue_position）、`fal_result`（download_ms）及 `fal_postprocess_complete`（postprocess_ms）结构化记录；不要开启会打印 URL/Authorization 的 HTTP 调试日志。fallback 表示本次暂存/签名失败后实际用 inline，并非已经向 FAL 发送两次。
- 带宽验证：`/proc/net/dev` 的网卡发送量包含 OSS 内网流量，不能单独当作公网出口；结合云监控 `VPC_PublicIP_InternetOutRate` 或按公网目的地址过滤的包头计数。恢复旧 release 前排空提交并保留最新数据；此功能新增可忽略设置字段，无须为切回 inline 恢复旧数据库。

2026-10-05 真实联调记录：默认 OSS 域名的首张 FAL 试验返回结果 HTTP 422 / `file_download_error`，网站正确记为可重试失败、无未知占用。普通公网及美国 DMIT 下载成功不能证明 FAL 可取图。已按方案停止后续 OSS 批次并恢复 inline；在定位原因并重新通过真实试验前不要将此配置视为已联通。实测响应有 `Content-Disposition: attachment` / `x-oss-force-download: true`；[阿里云当前规则](https://help.aliyun.com/zh/oss/user-guide/0048-00000114)包含乌兰察布新建 Bucket 的 PNG，但尚未证实该头就是 FAL 失败根因。本次未启用自定义域名、CDN 或传输加速。
