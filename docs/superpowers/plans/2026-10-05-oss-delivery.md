# 打印文件迁移 OSS 实施方案（精简版）

日期：2026 年 10 月 5 日（第二版，取代同名第一版）。状态：用户已确认取舍，待执行；尚未实施、联调或部署。

执行者先读仓库根目录 `AGENTS.md` 及其导航文档。本文的取舍已由用户确认，执行时不要再按第一版的"严格实时鉴权""按版本分目录""任务表租约"等设计扩展范围。

## 〇 用户已确认的决定（2026-10-05）

| 决定 | 内容 |
| --- | --- |
| ECS 不动 | 包年包月实例，固定带宽 3Mbps 出网，不改配置、不改计费方式 |
| 上 OSS | 打印 PNG 走 OSS 私有存储 + 后台签名直链下载，按本文精简设计 |
| 放弃严格实时鉴权 | 接受签名直链在有效期（300 秒）内可被重复使用；签发前仍做完整服务端校验 |
| OSS 只存当前文件 | 每单只保留当前有效打印文件，重新排版后旧对象删除，不按版本分目录、不保留旧版 |
| 抛弃订单流程版本 | 删除 `workflow_version` 字段和旧版 `/api/orders` 批量订单流程，所有订单只有一种结构；以后框架变更直接写迁移脚本转换数据，不保留兼容层 |
| 保留交付版本 | `delivery_version` 保留，它是"下载途中重新排版就中止保存"的防护 |
| 历史订单 | 生产现有订单全部视为测试数据，直接迁入新结构并上传 OSS，用于联调 |
| 备份归档 | 完整备份归档到 OSS；现在及以后只保留最近 3 份备份（本机与 OSS 合计，同一份快照只算一份） |
| 点数下线 | 点数（credits）功能整体下线，随阶段 B 一起删除 |

## 一 实时核对的现状（2026-10-05，只读查询）

| 项目 | 结果 |
| --- | --- |
| ECS | `i-0jld8oj1jlji06zcp3vd`，乌兰察布，PrePaid，PayByBandwidth，出 3Mbps，2027-06-17 到期，未绑定 RAM 角色 |
| Bucket | `coreages-sticker`，`oss-cn-wulanchabu`，私有，标准存储，ZRS，版本控制未开启，空桶 |
| Endpoint | 内网 `oss-cn-wulanchabu-internal.aliyuncs.com`，公网 `oss-cn-wulanchabu.aliyuncs.com` |
| 生产版本 | `6dc72e3`，代码 `/opt/avatar-sticker-studio/current`，数据 `/var/lib/avatar-sticker-studio`（约 2.1G） |
| 订单 | 16 单，全部 `workflow_version=3`（12 cancelled、4 submitted）；items 139 条也全部是 3；旧流程订单 0 单 |
| 打印文件 | 28 个，单页中位 5.8MB、最大 8.6MB；每单中位 2 页、12.5MB，最大 16.8MB |
| 磁盘 | 第 0 步已完成，见第二节；完成后系统盘已用 58%，剩余 16G |
| 点数 | 前端没有任何点数界面；后端有 `credits.py`、4 个接口和 worker 钩子；生产 `credit_ledger` 26 条、`credit_operations` 2 条 |

执行前必须重新实时核对以上状态，以当时结果为准。

## 二 第 0 步：释放磁盘（已完成，执行者不要重做）

2026-10-05 00:52（北京时间）已由 Claude 按用户授权完成：删除下表右列 9 个目录后，`backups/` 只剩左列 3 个（共 6.2G），系统盘从 98%（剩 811MB）降到 58%（剩 16G），服务 `active`，`/api/ready` 返回 200。以下保留原始记录供核对。

| 保留（最近 3 份） | 删除（其余 9 个） |
| --- | --- |
| `order-actions-6dc72e3`（10-05 00:29） | `guest-prompt-1551c3b`、`upload-limit-66f3e77`、`result-zoom-8859d13` |
| `order-actions-60b6956`（10-05 00:15） | `reclassify-test-unknowns`（仅一个 4.3MB 的 sqlite 快照）、`server-draft-40e1a0f`、`preflight-preview-705a990` |
| `remark-sync-2faddfb`（10-04 20:23） | `picker-selected-dddb5a0`、`modal-dvh-fb740b8`、`picker-sticky-a0a10d3` |

步骤：

1. `ls -la --time-style=full-iso /opt/avatar-sticker-studio/backups/` 重新确认排序；若期间又有新备份，按新排序重新划分"最近 3 份"，并先向用户报告。
2. 确认 `current` 指向的 release 与要保留的最新备份配对，保留的 3 个目录完整（有 `data/studio.sqlite3`、`bak.sha` 等）。
3. 逐个 `rm -rf` 删除 9 个目录（服务器没有废纸篓，删除不可恢复；用户已按保留规则授权）。只删 `backups/` 下这 9 个具体目录，不用通配符。
4. `df -h /` 确认释放约 17GB。

这 3 份的 OSS 归档在第五节完成后补做。

## 三 阿里云侧配置

### RAM 角色（ECS 实例角色）

不使用长期 AccessKey。用 `aliyun` CLI（本机已登录）创建：

```bash
aliyun ram CreateRole --RoleName sticker-ecs-oss \
  --AssumeRolePolicyDocument '{"Version":"1","Statement":[{"Effect":"Allow","Action":"sts:AssumeRole","Principal":{"Service":["ecs.aliyuncs.com"]}}]}'

aliyun ram CreatePolicy --PolicyName sticker-oss-access --PolicyDocument '{
 "Version":"1","Statement":[
  {"Effect":"Allow",
   "Action":["oss:PutObject","oss:GetObject","oss:DeleteObject","oss:AbortMultipartUpload","oss:ListParts"],
   "Resource":["acs:oss:*:*:coreages-sticker/print/*","acs:oss:*:*:coreages-sticker/backups/*","acs:oss:*:*:coreages-sticker/selftest/*"]},
  {"Effect":"Allow","Action":["oss:ListObjects"],
   "Resource":["acs:oss:*:*:coreages-sticker"],
   "Condition":{"StringLike":{"oss:Prefix":["print/*","backups/*","selftest/*"]}}}]}'

aliyun ram AttachPolicyToRole --PolicyType Custom --PolicyName sticker-oss-access --RoleName sticker-ecs-oss
aliyun ecs AttachInstanceRamRole --RegionId cn-wulanchabu --RamRoleName sticker-ecs-oss --InstanceIds '["i-0jld8oj1jlji06zcp3vd"]'
```

验证：在 ECS 上请求元数据 `ram/security-credentials/` 能看到 `sticker-ecs-oss`（不要打印凭证内容）；用合成文件在 `selftest/` 前缀测试上传、读取、删除成功，对 `coreages-sticker` 其他前缀写入被拒。测试后删除 `selftest/` 对象。

### Bucket

- 保持私有，在控制台确认"阻止公共访问"已开启；不开版本控制；不配置 CDN、传输加速；不配生命周期规则（清理由应用和备份脚本负责）。
- 配置 CORS（文件夹保存用 JavaScript 读取 OSS 响应）：

```xml
<CORSConfiguration>
  <CORSRule>
    <AllowedOrigin>https://sticker.coreages.com</AllowedOrigin>
    <AllowedMethod>GET</AllowedMethod>
    <AllowedMethod>HEAD</AllowedMethod>
    <AllowedHeader>*</AllowedHeader>
    <ExposeHeader>ETag</ExposeHeader>
    <ExposeHeader>Content-Length</ExposeHeader>
    <MaxAgeSeconds>600</MaxAgeSeconds>
  </CORSRule>
</CORSConfiguration>
```

- **默认域名可用性要先测**：用 `selftest/` 合成 PNG 生成签名 URL，分别在本机浏览器 `fetch`（从 `https://sticker.coreages.com` 页面的控制台）和 `curl` 下载，确认中国内地默认域名允许签名下载且 CORS 生效。若默认域名受限，停下来向用户报告，再决定是否绑定自定义域名（需要证书和备案核对），不要自行绑定。

## 四 阶段 A：OSS 打印文件交付（一个提交、一次部署）

### 设计要点

- 不新建任务表、不做租约。worker 主循环里加一个周期性"OSS 同步"步骤，数据库中的订单本身就是唯一状态来源，失败下次循环自然重试。
- 对象路径：`print/<organization_id>/<order_id>/<sha256>.png`，只用内部 ID，不含订单号、姓名或备注。内容寻址，上传幂等。
- OSS 未配置（本地开发、测试）时功能整体关闭，行为与现在完全一致。

### 新模块 `backend/app/oss_delivery.py`

1. **客户端**：使用阿里云官方 Python SDK V2（`alibabacloud-oss-v2`），用 `uv add` 写入 `pyproject.toml` 和 `uv.lock`。两个客户端：上传/删除/列举走内网 Endpoint，签名走公网 Endpoint，域名与签名交给 SDK 处理，不手工替换域名。凭证使用 SDK 支持的 ECS 实例 RAM 角色方式（必要时配合 `alibabacloud-credentials`），以官方文档为准；不读写任何 AccessKey。
2. **配置**（环境变量，写入 `deploy/production.env.example`，不填凭证）：
   - `STUDIO_OSS_BUCKET=coreages-sticker`（为空则功能关闭）
   - `STUDIO_OSS_REGION=cn-wulanchabu`
   - `STUDIO_OSS_INTERNAL_ENDPOINT=oss-cn-wulanchabu-internal.aliyuncs.com`
   - `STUDIO_OSS_PUBLIC_ENDPOINT=oss-cn-wulanchabu.aliyuncs.com`
   - `STUDIO_OSS_RAM_ROLE=sticker-ecs-oss`
   - `STUDIO_OSS_DOWNLOAD=1`（运维开关：设 0 时清单只返回本地地址，上传照常）
   - `STUDIO_OSS_URL_TTL=300`
3. **`sync(db)`**（worker 每 30 秒在线程里调用一次，单线程串行，同一时刻最多上传 1 个文件）：
   - 短事务读取：所有 `state=='submitted' and delivery_ready` 订单中缺少 `oss_key` 的打印文件（`artifacts` 里 `kind=='print'` 的项）。
   - 事务外：读取本地资产，校验 sha256 与记录一致，上传到对应 key（SDK 默认 CRC64 传输校验保持开启），设置 `Content-Type: image/png`、`Cache-Control: private, no-store`。
   - 短事务回写：重新读取订单，只有当前 `artifacts` 里仍存在同一资产 ID 时才写入 `oss_key`；订单已换版则丢弃这次结果，不回写。
   - 对账清理（每 10 分钟一次即可）：列举 `print/` 前缀，删除不属于"当前 submitted 且 delivery_ready 订单的当前打印文件"的对象。这一条同时覆盖重新排版、解锁、取消、订单被清理和账号删除，不必在各删除路径单独接 OSS。
   - 所有 OSS 错误只记脱敏日志并等待下次循环；绝不影响生图任务、计费、未知请求占用或订单状态。
4. **`sign(key)`**：生成 `STUDIO_OSS_URL_TTL` 秒有效的 GET 预签名 URL，响应头带 `Content-Disposition: attachment`。

### 现有代码改动

| 文件 | 改动 |
| --- | --- |
| `backend/app/worker.py` | `run()` 主循环加入节流后的 `await asyncio.to_thread(oss_delivery.sync, db)`；异常与现有调度异常同样处理，不中断循环 |
| `backend/app/publication.py` | 不改。`publish_customer` 每次重新拼版都生成不含 `oss_key` 的新 artifacts，自然触发重新上传 |
| `backend/app/customer_orders.py` manifest | 保留现有校验（后台会话、组织、`submitted`、`delivery_ready`）和 `version: delivery_version`。每个打印文件增加 `local_url`（原 `/api/assets/{id}`）；功能开启且有 `oss_key` 时 `url` 为签名直链，否则 `url` 等于 `local_url`。响应头 `Cache-Control: private, no-store` |
| `backend/app/customer_orders.py` download.zip | 不上 OSS。改为：短事务读出文件清单后退出事务，再在事务外读文件；`ZIP_DEFLATED` 改为 `ZIP_STORED`（PNG 已压缩）；下载文件名改用 `delivery_folder(order)`（RFC 5987 编码）。ZIP 仍走 3Mbps，仅供不支持文件夹选择的浏览器使用 |
| `frontend/src/lib/device.ts` | 见下 |
| `frontend/src/lib/types.ts` | Manifest 文件项加 `local_url` |
| `frontend/src/pages/CustomerOrders.tsx` | 进度提示区分"从 OSS 下载"和"OSS 失败，改从服务器下载（较慢）" |

`device.ts` 的 `syncOrder` 修改：

- 下载每个文件时，使用**最近一次取到的清单**里该路径的 `url`（现在的循环每个文件后都会重新读清单，复用这次结果即可），避免批量下载时早期签名过期。同时要求该文件的 sha256 与初始清单一致，不一致按"结果已更新"中止。
- 跨域地址（`new URL(url, location.href).origin !== location.origin`）使用 `credentials: 'omit'`，同源保持 `same-origin`。
- 远端下载失败（网络错误或非 2xx）时：重新读清单拿新签名重试 1 次；仍失败则对该文件改用 `local_url` 下载，并显示较慢提示。不把 403 无限续签。
- 大小、sha256、写前写后本地哈希、`delivery_version` 比对、Web Locks、冲突检测等现有保护全部保留，不改语义。
- 默认 `manifestPath` 目前指向旧流程 `/orders/...`，阶段 B 改为必填或客户订单路径。

### 历史订单

部署后 worker 会自动把现有 4 张 submitted 订单的打印文件上传到 OSS。逐单核对：对象数量、大小、sha256（从 OSS 读回计算）与本地一致；后台实际下载一次，浏览器网络面板确认文件正文来自 `*.oss-cn-wulanchabu.aliyuncs.com`。

### 测试

- 后端：用假的存储适配器（内存字典）覆盖：首次上传、上传失败后重试、上传期间订单换版不回写、重新排版后旧对象被对账删除、取消/解锁后对象删除、功能关闭时清单与现在一致、清单只在有效后台会话下签名（未登录、访客、跨组织、停用账号、非 submitted 均拒绝）、日志不含完整签名 URL。
- 前端 Vitest：跨域时 `credentials: 'omit'`、签名失败后续签一次再回退本地、sha256 变化时中止。
- 基础回归：`npm test`、`npm run build`、`npm run check:docs`。
- 浏览器：桌面 Chrome 文件夹保存、ZIP 下载、390px 页面布局。
- 真实 OSS：只用 `selftest/` 前缀和合成图片。

### 同步文档（同一提交）

- `backend/content/staff-guide.json`：下载改走 OSS、较慢回退的含义、失败如何重试；更新 `version`、`updated_at` 和维护记录。
- `AGENTS.md` 行为边界：补一条"打印文件经 300 秒签名直链从 OSS 下载；签发前服务端完整校验，已签发链接在有效期内不随状态变化撤销，用户 2026-10-05 确认接受"。
- `docs/architecture-and-contracts.md`：存储与下载契约。
- `docs/agent-operations.md`、`deploy/README.md`：OSS 配置、RAM 角色、开关、排障、回退。

## 五 备份归档（与阶段 A 同一部署落地）

新增 `deploy/backup_archive.py`，用 release 的 venv 运行，复用 `oss_delivery` 的客户端与 RAM 角色。

- `python deploy/backup_archive.py --archive <备份目录>`：把目录打成不压缩的 tar，写到 `/var/tmp`，计算 sha256，上传到 `backups/<UTC 时间戳>-<目录名>.tar`，sha256 写入对象元数据；`--verify-readback` 时从内网下载回来重新计算 sha256 比对。完成后删除临时 tar。
- `python deploy/backup_archive.py --prune`：默认只打印计划；加 `--apply` 才执行。规则：
  1. 以时间戳排序，合计只保留最近 3 份快照（OSS 与本机同名快照算同一份）。
  2. OSS 中超出 3 份的 `.tar` 删除。
  3. 本机只保留最新 1 份备份目录，便于快速回滚；其余本机目录只有在 OSS 已有校验通过的归档时才删除。不在最近 3 份里的本机目录直接删除。
- 不安装定时器。每次发布流程中：停服并完成数据备份 → 部署并验收 → `--archive` 新备份 → `--prune --apply`。

首次执行：阶段 A 部署成功后，对第 0 步保留的 3 个目录逐个 `--archive --verify-readback`，再对本次发布新建的备份执行归档，最后 `--prune --apply`。结果应为 OSS 中 3 份、本机 1 份（为最新快照）。

同步修改 `deploy/README.md` 中"不做异地备份"的表述（改为：按用户 2026-10-05 要求手动归档到 OSS，保留 3 份，无定时任务），以及 `docs/agent-operations.md` 第 6 节发布步骤。回滚时可从内网下载对应 tar 恢复，下载与解包步骤写入运维文档。

## 六 阶段 B：删除 `workflow_version`、旧版批量订单与点数（单独提交、单独部署）

阶段 A 上线并验收后再做，不要与阶段 A 混在一个提交里。

### 范围

- 删除旧流程后端：`backend/app/main.py` 的 `/api/orders` 全部路由（列表、创建、详情、暂停、恢复、归档、重跑、resolve、recover、reprocess、repack、watermark、manifest、download.zip）及其专用辅助函数；`backend/app/publication.py` 的 `publish_selection`。
- 删除所有 `workflow_version` 判断，保留客户订单分支的逻辑：`worker.py`、`customer_orders.py`、`maintenance.py`、`statistics.py`、`media_cache.py`（`tx.where('orders','workflow_version',3)` 改为全部订单）、`remark_sync.py`、`db.py`（`INDEXED_FIELDS` 移除该字段）。
- 新增迁移 `drop-workflow-version-v1`：启动时若发现任何订单或 item 的 `workflow_version` 不是 3，拒绝迁移并报错（生产当前为 0 条）；否则从 orders 与 items 删除该字段。迁移后不再写入该字段。
- `frontend/src/lib/device.ts` 默认 `manifestPath` 不再指向 `/orders/...`。
- 点数（credits）整体下线（用户 2026-10-05 决定）。前端没有点数界面，只涉及后端：
  - 删除 `backend/app/credits.py`；删除 `main.py` 中 `/api/credits`、`/api/admin/users/{id}/credits`（GET/POST）及 settle 接口、`CreditAdjustment`/`CreditSettlement` 等 schema；删除账号停用、组织迁移（`organizations.py`）、清理（`main.py` 的 `cleanup_credits`）、账号删除（`maintenance.py` 的 `frozen_credits`）、worker（`credits.progress`/`credits.settle`）中的点数调用。
  - 新增迁移 `drop-credits-v1`：删除 `credit_ledger`、`credit_operations` 记录，以及 users 的 `credits` 字段、items 的 `credit_exempt`/`billing_legacy` 字段。历史账本保存在发布前的完整备份里（该备份会归档到 OSS）。
  - **不要误删**：`generations` 记录、`remote_reserved`、`fal_request_id`、未知请求占用与恢复逻辑都属于生图请求追踪，不是点数，必须原样保留。`fal_billing.py` 是 FAL 账户余额查询，也不是点数，保留。原来写在 credits 钩子里、但同时承担请求状态推进的逻辑，要先确认职责再拆，不能连带删除。
  - `AGENTS.md` 的"保留原图、旧版本和历史账本"改为不再提账本；`docs/architecture-and-contracts.md` 中 `credits.py` 与"历史账本"的描述同步删除；`staff-guide.json` 若有点数相关描述一并删除。
- 测试：`test_credits.py` 随功能删除；其他大量后端测试（如 `test_worker.py`、`test_api.py`、`test_mixed_stickers.py`、`test_cleanup.py`、`test_account_deletion.py`）用 `/api/orders` 作为生图测试夹具，需改写为通过客户订单创建 items 的辅助函数，覆盖面不能减少。专测旧流程行为的用例随功能一起删除。
- 文档：`AGENTS.md` 中"当前客户订单为 `workflow_version=3`"改为"订单只有一种结构；框架变更直接迁移数据，不保留兼容层"；同步架构文档、运维文档、`staff-guide.json`（若有旧流程描述）。

### 回滚边界

迁移删除字段后，旧版代码会因找不到 `workflow_version==3` 而看不到任何订单，因此阶段 B 不能只切回旧 release。回滚 = 停服 + 恢复本次发布前的配对备份 + 旧 release，仅限上线后尚未产生新订单时；之后只能向前修复。发布前要明确告知用户。

## 七 部署与验收（两阶段各做一次）

按 `docs/agent-operations.md` 第 6 节和 `deploy/framework-release.md` 执行：只读队列检查、审计基线、停服、完整数据备份并核验、原子切换 `current`、启动、`/api/ready`、审计对比。额外检查：

- 阶段 A：生产 env 写入 OSS 配置后启动；服务日志无 OSS 凭证错误；4 张历史订单 OSS 对象核对通过；后台实际下载，网络面板确认正文来自 OSS；下载期间 ECS 出网不再被打满（用阿里云监控或在 ECS 上 `apt install vnstat` 观察）；访客页面、水印图、后台说明可用；备份归档与保留结果符合第五节。
- 阶段 B：迁移后 16 张订单在后台全部可见、状态不变；生图、拼版、下载回归；点数接口返回 404，数据库中不再有点数记录与字段；审计除迁移预期变化外无差异。

汇报时分开说明：计划、已生成、已保存、本地验证、已部署、公网验收。本地 mock 通过不能写成生产 OSS 已接通。

## 八 费用（估算，以账单为准）

按每单 12.5MB、每月 1000 单、每单下载一次估算：OSS 公网流出约 12.5GB/月，存储只保留当前文件，量很小；备份 3 份约 6GB 标准存储。合计预计每月十几元以内。实际单价、ZRS 价差和资源包抵扣以控制台账单为准。

## 九 不做的事

- 不改 ECS 配置或带宽计费方式。
- 不做严格实时鉴权服务、对象版本目录、任务表与租约、OSS 上的 ZIP、单文件断点续传、CDN 或自定义域名（除非第三节测试发现默认域名不可用并经用户同意）。
- 不迁移头像、生成原图、水印预览、图库素材到 OSS。
- 不安装备份定时任务。
