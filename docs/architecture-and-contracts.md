# 架构与行为契约

核对基线：2026-10-05，OSS 交付与单一订单结构。本文解释当前实现，不是新的功能需求，也不代表已验证当前线上服务。统一维护规则见 [AGENTS.md](../AGENTS.md)，命令见[运维指南](agent-operations.md)。

## 系统与代码地图

浏览器通过同源 `/api` 调用 FastAPI。生产由 FastAPI 同时提供构建后的前端；开发时 Vite 代理 `/api`。SQLite WAL 的事务和持久化记录协调同一主机上的工作进程，不是多主机共享数据库架构。

| 关注点 | 主要文件 |
| --- | --- |
| 启动、环境加载和本地端口 | `scripts/studio.mjs`、`.env.example` |
| API 注册、认证、全局设置、健康和就绪检查 | `backend/app/main.py` |
| 角色、组织、后台会话 | `backend/app/auth.py`、`organizations.py`、`bootstrap.py` |
| 数据模型与自动迁移 | `backend/app/db.py`、`schemas.py` |
| 图库、模板和分类 | `backend/app/library.py`、`categories.py`、`customer_orders.py` |
| 客户订单状态机、配额、访客接口、下载 | `backend/app/customer_orders.py` |
| 任务租约、公平调度、并发和请求恢复 | `backend/app/worker.py`、`providers.py`、`request_tracking.py` |
| 图片入库、预览、水印、拼版、原子发布 | `backend/app/storage.py`、`previews.py`、`guest_media.py`、`processing.py`、`publication.py` |
| Agiso 协议、接口、状态转换和消息队列 | `backend/app/agiso_protocol.py`、`agiso_routes.py`、`agiso_service.py`、`agiso_worker.py` |
| 清理、删除计划和统计 | `backend/app/maintenance.py`、`statistics.py` |
| 后台壳、访客独立入口 | `frontend/src/App.tsx`、`main.tsx`、`pages/Guest.tsx` |
| 工作台与全部订单共用页 | `frontend/src/pages/CustomerOrders.tsx`、`CustomerOrders.css` |
| 后台代操作与访客共用制作界面 | `frontend/src/components/CustomerWorkbench.tsx` |
| 视觉设计变量与全局样式 | `frontend/src/styles/tokens.css`、`frontend/src/styles.css`；规范见 `docs/design/design-system.md` |
| API 身份、客户端幂等、交付文件保护 | `frontend/src/lib/api.ts`、`customer-orders.ts`、`delivery.ts`、`sync.ts` |
| 后台说明正文与页面 | `backend/content/staff-guide.json`、`frontend/src/pages/StaffGuide.tsx` |

数据库不是每种业务一张传统关系表：主要记录放在 `records(kind,id,doc)` 的 JSON 文档中，`starts` 用于速率记录。`Database(...)` 会创建目录、修改权限、执行迁移，`transaction()` 使用 `BEGIN IMMEDIATE`，不能作为无副作用只读诊断入口。禁止在真实数据上随意执行初始化代码。

高频查询不要再用 `tx.all(kind)` 全表解析后过滤：`Database` 启动时为 `INDEXED_FIELDS`（`status`、`remote_reserved`、`state`、`order_id`、`order_number`、`guest_order_id`、`customer_order_id`）建立 `(kind, json_extract(doc,'$.字段'))` 表达式索引，使用 `tx.where(kind, 字段, 值...)`、`tx.find(kind, (SQL条件, 参数)...)` 和 `tx.count(kind)`。它们按 rowid 返回与 `all()` 相同的顺序；SQL 只做超集预筛，调用处保留原来的 Python 精确判断。索引不改变文档，旧代码会忽略它们。Worker 与 Agiso worker 的调度、访客登录、上传查重、访客媒体授权都依赖这些索引。

只读请求使用 `db.read(fn)`：先以普通 `BEGIN` 读取快照，不等待写锁；`fn` 一旦调用 `put`/`delete` 就抛出 `NeedsWrite`（写入前），随后在原来的 `BEGIN IMMEDIATE` 事务里整体重跑。`fn` 除数据库外不得有副作用，因为它可能执行两次。订单列表/详情、访客订单/图库/媒体、`auth/me`、`auth/status`、图库和分类的 GET 使用它；`dto()` 的 `reconcile` 需要写入时会自动回退。`Database` 另持有一个空闲连接，使每个事务连接关闭时不再触发 checkpoint 和 WAL 删除，因此运行中数据目录会一直存在 `studio.sqlite3-wal`/`-shm`；备份仍须在停服后复制整个数据目录，不能只拷主库文件。

公开页脚由 `frontend/src/components/IcpFiling.tsx` 统一提供，登录页、后台和客户选图页在底部中央显示 `鲁ICP备20019500号`，备案号与其下方查询入口均链接 `https://beian.miit.gov.cn/`（新标签页，`noopener noreferrer`）。页脚位于正常文档流，不覆盖手机选图操作；公开备案信息不依赖后台说明接口。

## 权限和隐私

- `superadmin` 管组织、全站设置与统计；独立超管可以不属于组织，因此不一定有组织工作台。`org_admin` 管本组织成员、图库授权与账号并发；`staff` 在组织内协作。服务器仍需对每个资源校验组织和角色。
- 图库 `scope=public` 是组织内共用。模板由 1–100 个有序且不重复的贴纸 ID 构成；不再是固定 12 张上传图。客户选择同一模板多份仍会产生重复份数。图库编辑需要授权；分类可编辑，不能假定只有男孩/女孩两类。
- 模板和贴纸当前采用删除流程，旧停用接口返回 410。删除、被引用素材和历史快照的保留应按现有服务端流程处理，不能直接删除资产文件。
- 后台使用 `studio_session`，访客使用 `studio_guest`。会话 token 仅保存哈希，Cookie 为 HttpOnly。后台请求携带 `X-Studio-User` 防止其他标签页换号后串操作；常规图片请求仍依赖服务端授权。
- 后台登录保留失败次数限制；访客订单号登录已经取消按 IP/订单号累计失败限制，仍验证订单和组织。不要把旧设计的限制重新加回。
- `/api/staff-guide` 先认证，再读取私有 JSON，响应 `private, no-store` 并区分 Cookie/账号。正文不能通过前端 import、public、构建资源、访客缓存或其他静态路径泄漏。
- `GET /api/admin/fal/balance` 和余额密钥设置仅限网站 `superadmin`。独立 `FAL_ADMIN_KEY` / 私有 `fal_admin_key` 不用于生成，环境变量优先；设置只回传配置状态与来源。余额接口固定调用 FAL 官方账单接口，网络请求在数据库事务之外，返回前再次校验会话、角色和密钥；响应 `private, no-store`，仅返回账号、余额、币种和查询时间。供应商错误转为脱敏中文提示，不回传原始错误或密钥。后台手动查询，不自动刷新或浏览器持久化。
- 访客媒体每次请求（含 304）都按会话、订单归属、订单状态和资产范围现场校验：已取消订单全部拒绝，已提交订单的访客只能看总览，图库贴纸用 `records_image_id` 索引查询是否属于本组织在用贴纸（不再每次读取整个图库）。订单已取消“图片版本号”（`media_version`）：媒体链接为 `/api/guest/media/{order}/{asset}?m=<水印文字指纹>`（后台为 `/api/customer-orders/{order}/media/{asset}?m=…`），不随取消、恢复、提交或解锁改变；`m` 只让打开中的页面在换水印后换图，服务端不据此授权。授权跟随订单实时状态，旧数据中残留的该字段不再读取。需要服务端压平水印；水印媒体使用 `private, no-cache`、`Vary: Cookie` 与按内容计算的 ETag（素材哈希、水印文字、尺寸、渲染管线、是否已带水印），允许浏览器保存但每次复用前仍鉴权，未变化返回 304；换水印后 ETag 改变，浏览器重新下载。尺寸只有 160/320/640/1024 四档（其他请求值向上归档）；160/320 由 640 水印图等比缩小并以 WebP q80 编码。客户选图页用 `srcset`/`sizes` 按显示宽度和屏幕密度选档，`sizes` 与选图网格 CSS 同步维护，由 `customer-picker-responsive-media` E2E 检查；304 不读取原图或重新编码，返回前也再次检查授权。其他访客 API 保持 `no-store`；前端 CSS 遮罩不能代替它。访客图库接口发放的贴纸/模板图片是例外的公开目录图：`/media/catalog/<资产ID>/<水印文字 base64url>/<渲染版本>/<签名>.webp?size=…`，签名为 `HMAC-SHA256(config.settings.media_url_secret, 资产ID+水印+CATALOG_VERSION)`。无需会话；服务端校验签名、渲染版本，并确认资产仍是其所属组织的在用图库贴纸（客户图片、已删除或停用的贴纸返回 404），响应 `public, max-age=31536000, immutable`、无 `Vary: Cookie`，ESA 按地址共享缓存。同一水印下所有订单得到同一地址；换水印或渲染管线即换地址。代价：已发出的目录图地址在订单取消或贴纸下架后仍可取到带水印图片，ESA 节点副本保留到过期。轮换 `media_url_secret` 会使旧地址全部失效、页面刷新后重新发放。访客页的操作引导（`frontend/src/lib/guide.ts`、`components/GuestGuide.tsx`）是唯一写入浏览器存储的访客功能：只在 `localStorage` 存 `guest-guide:<提示ID>=off`（“不再提示”），不存订单号、图片或任何订单数据；“我知道了”只记在页面内存。自动化浏览器（`navigator.webdriver`）默认不显示引导，测试用 `guest-guide:force=1` 打开。所有 GET JSON 接口（后台和访客）附带按响应内容计算的 ETag：前端 `fetchRevalidated` 只在页面内存里记住上次的响应体和 ETag，下次带 `If-None-Match`，内容未变时服务端返回空 304、前端沿用内存中的响应体；接口仍是 `no-store`，处理函数及全部鉴权每次照常执行。后台图库素材（资产 kind 为 `template`）的预览和原图使用 `private, max-age=604800`，浏览器 7 天内不再逐张重新校验；头像、生成结果、总览、打印等客户资产保持 `private, no-cache`/`no-store`。后台工作台用 `GET /api/customer-orders?summary=1&active=1` 只取草稿/待核对订单，历史订单页取全部。提交/取消后的访客 DTO 会省略头像、位置等字段，不得从旧响应回填这些字段。
- 订单号即访客入口凭据。不要把真实编号、预填链接、OAuth code、原始推送或头像放到日志、截图、Git 和交接记录中。

## 客户订单

后台工作台和全部订单统一使用 `/api/customer-orders`。订单只有一种结构，不写入或判断 `workflow_version`，旧 `/api/orders` 接口已移除；框架升级使用明确数据迁移，不保留旧流程兼容层。

| 状态 | 含义和出口 |
| --- | --- |
| `draft` | 待制作，可上传头像并选择；确认生成后冻结并进入 `review` |
| `review` | 选图中，等待任务、重做与版本确认；精确选择 F 个位置后提交 |
| `submitted` | 已锁定，服务端生成水印总览及打印拼图；后台可手动下载、重新排版、解锁或发货 |
| `shipped` | 已发货（归档，2026-10-16）：只读；删除前仍可下载打印文件，可撤销发货（回 `submitted`）、修改快递单号；到 `purge_at` 删除图片 |
| `cancelled` | 取消并保留记录；受规则约束可恢复，退款取消另受售后保护 |

`draft` 订单的工作清单（头像上传记录与各自的模板/贴纸选择）保存在订单的 `draft` 字段，客户与后台通过 `PUT /api/guest/order/draft`、`PUT /api/customer-orders/{id}/draft` 整体覆盖保存，最后一次保存为准。草稿有独立的 `draft.revision`，不增加订单 `version`，不需要 `client_token`，不影响生成/提交的并发检查；完整订单响应（非 `summary`）在 `draft` 状态返回 `draft`。保存时服务端校验：头像数不超过 F、不重复，上传记录已完成且属于本组织；客户只能加入本订单的访客上传，但可保留后台已放入草稿的上传；份数超过 G 时仅允许减少；已下架的模板/贴纸被丢弃。草稿中的头像可通过本订单媒体路由查看；客户生成时可使用后台已放入草稿的头像。开始生成后删除草稿，之后保存返回 409。前端每次添加/移除头像或“应用选择”即保存，网络或服务端错误在下次轮询时自动重试；不在浏览器存储中保存草稿。

工作台仅显示 `draft/review`；全部订单（原“历史订单”）显示全部客户订单，并可筛选已提交、已发货、已取消等。订单详情在弹窗中打开，两处页面共用逻辑。列表轮询使用 `GET /api/customer-orders?summary=1`，响应省略 `avatars`/`slots`（仍对每单执行 `reconcile`）；弹窗单独请求 `GET /api/customer-orders/{id}` 取得完整订单，列表发现版本更新时再刷新详情。不带 `summary` 的列表接口保持完整数据。列表支持关联店铺及无关联店铺筛选。

| 字段 | 必须保持的语义 |
| --- | --- |
| `generation_limit`（G） | 可预览份数上限，按选择出现次数计，不是去重后的付费调用数 |
| `final_count`（F） | 最终必须提交的不同位置数，`1 ≤ F ≤ G ≤ 360` |
| `rerun_limit`（R） | 非负整数，整单共用，已用和在途预留一起计入预算 |
| `version` / `expected_version` | 乐观并发控制，过期操作返回 409 |
| `client_token` | 同一操作的幂等标识；同 token 不同内容拒绝，响应不确定时按原请求重试 |
| `content_version` / `artifact_version` / `delivery_version` | 内容、产物和交付失效各有用途，不要合成一个“刷新”计数；媒体链接已不带版本号，见上文访客媒体 |

开户固定水印和打印参数，空水印使用当时账号显示名，同时保存提示词及版本。生成时固定头像、贴纸版本和选择。首次生图按 `(avatar_id, sticker_id, revision)` 去重；每次选择仍保留独立位置，但同一组位置（`slot_group`）的重做只建一个任务、只在发起位置计一次预留，版本选择同时应用到整组（2026-10-14 起）。

客户自备图（做好的图片，2026-10-15）：上传时 `purpose: 'design'`（访客 `/api/guest/uploads/init` 与后台 `/api/uploads/init` 同一字段，默认 `avatar`；按用途分别去重，只缩不放到长边 2048 并保留透明度）。草稿 `draft.designs = [{upload_id, asset_id, name, cutout}]`，`cutout` 为 `cutout`（不透明时调用抠图）或 `whole`（保留背景，整张矩形印刷）；`Generate`/`DraftSave` 带 `designs`，头像可为 0 但两者不能都空。约束：自备图数 ≤ F，`选择份数 + 自备图数` 在 F 至 G 之间（自备图同时占预览和印刷额度），头像上传不能当自备图用，反之亦然；preflight 返回 `design_count`，`selection_count` 含自备图。生成时每张自备图建一个 `source: 'design'` 的 item：无 generations 记录、不调 FAL，直接以上传图为 `raw_result_id` 进入 `postprocess`（整张印跳过抠图且允许不透明），结果按普通版本进入位置。位置 `source: 'design'`、`sticker_code: '自备图'`、`design_id`、`cutout`，`slot_group` 只含自身；`rerun` 返回 409，改用 `POST …/slots/{slot_id}/replace`（`upload_id` + `cutout`，访客和后台都可用，不占 `rerun_limit`，旧版本保留可选回；处理中不可更换）。访客在 `review` 状态仍可上传 `design` 用途的图片（头像仍只能在 `draft` 上传）。打印不再要求透明（生成结果在后处理时已检查），总览按比例居中放入 256 格。后台 DTO 有 `design_count`，列表标注“含自备图”。

重做成功消耗整单一次机会，保留旧版也不会退回已成功重做次数；明确失败且没有外部占用才释放预留，未知请求继续占用。一次性迁移 `order-shared-rerun-v1` 将存量 v3 订单的 R 设为各自 G；这是历史迁移动作，不是新订单的默认值。

提交要求恰好 F 个不同位置，顺序决定输出；整单所有在途/未知请求、未释放预留和待确认版本都要处理完。顶部“已选 x/y”使用 `selection.length / final_count`，移动端滚动可见；点击可选卡片切换选择，“查看 / 重跑”才打开放大对比。

解锁保留已消耗额度和版本，重新提交前关闭旧交付下载。取消或暂停不等于远端请求结束；继续核对在途请求，但不能继续新生图或发布不该发布的产物。

初始化（2026-10-16，`POST /api/customer-orders/{id}/reset`，仅 `superadmin`/`org_admin`，无访客路由）：`draft`/`review` 订单回到刚开单的 `draft`——清空 `avatars`、`designs`、`slots`、`draft`、`final_entries`、生成/选择计数和产物字段，保留订单号、G/F/R、店铺、水印、打印参数和提示词快照；该订单任何 item 处于 `queued`/`running`/`unknown`、`remote_reserved` 或 `cutout_inflight` 时返回 409，`submitted` 需先解锁。items、generations、资产、上传和审计记录不删除，只是不再被订单引用（媒体授权随之拒绝旧图，访客本人上传的原图仍可访问），统计照旧计入；资产随订单整体按保留天数清理。前端工作台发现订单从非 `draft` 回到 `draft` 时丢弃本页旧选择。

发货与图片删除（2026-10-16）：`POST /api/customer-orders/{id}/ship`（`Ship`：`tracking_number` 可空，≤64，去首尾空白、拒绝控制字符）要求 `submitted` 且 `delivery_ready`，写入 `state='shipped'`、`shipped_at`、`shipped_by`、`tracking_number` 和 `purge_at = shipped_at + config.settings.shipped_retention_days × 86400`（默认 15，1–365，超级管理员在 `PATCH /api/admin/settings` 修改）。`purge_at` 发货时固定，改设置不影响已发货订单。`/unship`（`shipped` 且未删除 → `submitted`，清除 `shipped_at/shipped_by/purge_at`，保留单号）与 `/tracking`（任何已发货订单，含已删除和已取消的）所有后台账号可用，均走 `client_token`/`expected_version`；`tracking` 不受暂停或售后保护限制。`shipped` 不能 `unlock`/`repack`/`reset`。`oss_delivery.active()` 改为 `submitted|shipped` 且 `delivery_ready` 且未 `purged_at`：下载、manifest 和 OSS 同步/保留都按它判断，删除后 OSS 打印副本由对账清理。访客对 `shipped` 与 `submitted` 一样只拿到总览，DTO 另含 `shipped_at`、`tracking_number`、`purge_at`、`purged_at`（后台同样返回）。

Worker 每 300 秒在线程中执行 `maintenance.purge_due(now)`：`purge_at <= now`、未删除、状态为 `shipped` 或发货后被取消（`cancelled`）且没有在途 item 的订单，经 `purge_plan` 计算本单资产（`order_id` 指向本单的资产，以及本单和本单 item 引用的头像、自备图、结果、原图、抠图前图、总览、打印文件，和本单访客上传）减去其他订单/item 引用与图库图片，删除这些 `assets`、对应 `uploads` 记录，并登记文件、`preview-cache`、`media-cache` 到 `cleanup_files` 后立即 `drain_cleanup`。订单写入 `purged_at`，清空 `artifacts`/总览并 `version+1`；订单、items、generations、审计（`action='purge'`, `actor='system'`）全部保留，统计不变。删除后的 DTO `avatars`/`slots` 为空、`preview_url`/`delivery_ready` 为空/假。发布审计 `deploy/audit_framework.py` 的“引用资产必须存在”检查跳过 `purged_at` 订单及其 items 的引用（items 引用的图库模板仍检查）；若清理恰好发生在发布的快照与线上审计之间，比对会报告这些资产缺失，核对为清理所致即可。

### 订单成本（2026-10-16，`backend/app/costs.py`）

`GET /api/costs`（`scope=organization` 需 `org_admin`/`superadmin` 且有组织，`scope=global` 需 `superadmin`；`date_from`/`date_to` 为按 `offset` 时区的订单创建日，另可按 `platform`、`shop_id`）返回每单 `costs`（`packaging`、`shipping`、`material`、`generation`、`cutout`、`agiso`、`oss`、`esa`）、合计与汇总；`PUT /api/costs/rates`（`superadmin`）保存一个费率版本 `{from, packaging, shipping, sheet, per_sheet, cutout, agiso_base, agiso_high, agiso_increment}` 到 `config.settings.cost_rates`，同一 `from` 覆盖。某天的费率取 `from <= 该天` 的最新版本，早于全部版本的天用最早版本；默认版本 `from=1970-01-01`。

- 包装、快递、物料不落库，按订单计算：有 `shipped_at` 时按发货日费率为“实际”，`submitted` 时按今天费率为“预计”，其他为 0。物料张数 = `max(1, ceil(len(final_entries) / per_sheet))`。
- 按次费用写入 `cost_entries`（不受发布审计保护的派生数据，幂等 id）：`{id, source, order_id, organization_id, day, quantity, rate}` 按该天费率计价，或带 `amount_cny`/`amount_usd`（美元按 `fx_rates` 中该天或之前最近的 USD/CNY 换算，无记录时用最早一条，完全没有时用 7.1）。
- 抠图：`sync_cutouts` 为每个 `completed` item 写一条 `cutout:<item_id>`，`cutout_used` 为 1；没有 `cutout_used` 的自动抠图自备图读原图判断是否完全不透明（是则 1，标 `basis='inferred'`）；其余为 0。失败和不确定的抠图不计。
- 汇率：`sync_fx` 每个中国日存一条 `fx_rates/<日期>`，先取中国外汇交易中心 `ccpr.json` 的 USD/CNY 中间价，失败用 `open.er-api.com`；失败后 1 小时内不重试（`cost_sync/fx.attempted_at`）。
- 生图（`sync_fal`，需 FAL ADMIN Key）：按整点窗口（每窗最多一天、每次最多 3 窗、只处理 3 小时前的数据，进度在 `cost_sync/fal.until`）读取 `GET api.fal.ai/v1/models/usage?timeframe=minute` 全部端点的按分钟费用，并用同窗 `timeframe=hour` 合计核对，不一致则不入账；再按端点读取 `requests/by-endpoint`（窗前多取 2 小时），一分钟的费用平分给该分钟内 `ended_at` 落入且 `status_code=200` 的请求（无成功请求时平分给全部），写 `fal:<request_id>`（`amount_usd`）。没有请求的分钟写 `fal-minute:<端点>:<分钟>`，不归属订单。请求编号到 item 的对应来自 `fal_request_id`、新增的 `fal_request_ids`（`request_tracking.progress` 每次追加）、`fal_input_retries[].request_id` 和 `generations.request_id`。
- 阿奇索：`agiso_protocol.on_call`（启动时设置）对每次有应答的网关调用写 `agiso-call:<uuid>`，按 `AGISO_API_TIERS` 定档，带 `tid`/`shop_order_id` 的调用记 `order_number`，否则 `shared`；`sync_agiso` 为每条 `agiso_events` 写 `agiso-push:<事件id>`，数量 = 1 + `agiso_push_repeats` 中的重复次数（重复推送按事件 id 计数，不改事件记录），档位按 `AGISO_PUSH_TIERS`（默认高级），并通过 `agiso_orders.tid/order_number` 或订单号把推送和调用关联到客户订单，对不上的标 `shared`。`sync_agiso_deposit` 每个中国日调用一次 `open/Bankroll/QueryDeposit`（基础档，本身记为共用费用）存 `agiso_deposit/<日期>`；全站报表 `agiso_check` 用相邻两天余额下降额比对两天之间按单价计算的阿奇索费用（余额上升的时段跳过）。
- OSS/ESA（`aliyun_costs.py`，需 `STUDIO_COST_RAM_ROLE_ARN`，ESA 另需 `STUDIO_ESA_SITE_ID`）：ECS 实例角色 `STUDIO_OSS_RAM_ROLE` 经 STS `AssumeRole` 切换到只读角色（`AliyunBSSReadOnlyAccess`、`esa:DescribeSiteLogs/DescribeSiteTimeSeriesData`、`coreages-sticker/oss-access-logs/*` 读和列举），不保存长期密钥。从 2026-10-06 起逐日处理到两天前（进度 `cost_sync/aliyun.day`，每次最多两天；当天账单未出则停）。OSS：`DescribeInstanceBill` 日账单中实例 ID 以本站区域开头的行，“外网流出流量”按访问日志（`oss-access-logs/`，按日志行的 +0800 时间归日）中公网 GET/HEAD 的发送字节分摊：`print/<组织>/<订单>/` 直接归属，`fal-inputs/<UTC日期>/<sha256>.png` 平分给当天（及前一 UTC 日）以该 sha256 资产为模板或头像的 item 所属订单，其余共用；存储、请求等其余金额写 `oss-storage:<日>` 共用。ESA：套餐实付（`dcdn` 预付行，按 `ServicePeriod` 月数平均到天）+ 当天 `dcdn`/`esa` 后付费金额，按 `DescribeSiteLogs` 离线日志中 `sticker.coreages.com` 的 `EdgeResponseBytes` 分摊：订单媒体/详情路径与 `/api/assets/<资产>`（资产的 `order_id`）直接归属；当天只访问过一个订单访客媒体、且未访问后台接口的 IP，其其余请求归该订单；其余共用。每天写 `oss:<日>:<订单>`、`esa:<日>:<订单>`（`amount_cny`）和 `…:shared`，重算时先删同日旧条目。
- 共用费用：`shared` 且无订单的条目按条目所在月份平均分到该月创建、未取消的所有组织订单（`allocated`）；当月没有订单的共用费用和非共用的无主费用在全站报表的 `unattributed` 中列出。
- 成本同步在 `Worker.upkeep` 后台任务中运行，不阻塞生成调度；`costs.STOP` 在 worker 停止时置位，慢接口同步在两次请求之间退出。
- Worker 每 300 秒在线程中执行 `costs.tick`（与发货清理同一节拍），各来源独立失败、下次重试。`Worker.cost_get` 可替换出站 HTTP，浏览器测试注入固定汇率，不访问外网。

## 图片、队列与打印

- 当前 provider 源码使用 FAL `openai/gpt-image-2.5/flare/edit`；全站提交都带 `enable_safety_checker: false`（FAL 支持确认这是该端点唯一的审核开关，关闭后在上游允许范围内放宽；`model_moderated` 未开放，OpenAI 侧的拒绝仍可能以 422 `content_policy_violation` 返回）；凭证是 `FAL_KEY` 或后台私有设置，环境变量优先。这描述仓库实现，不保证第三方服务未来仍可用。变更 provider 前核对其当时官方契约。
- 点数功能及其接口已下线；实际生图记录、原图、旧请求 ID 和占用继续保留。全站 `max_inflight` 默认 2（1–40）和账号并发同时约束；访客任务计入开户账号。没有旧 RPM 门槛。
- 提交阶段（尚无 request ID，包含 OSS 暂存及发送 FAL 请求）另受全站 `max_uploads`（默认 3，1–40）约束，已拿到 ID 在 FAL 排队的任务不占用；提交 POST 的写超时为全站 `fal_upload_timeout`（默认 300 秒，30–1800），其他 FAL 请求仍为 60 秒。整个 JSON 请求体是一次写入，写超时即上传上限。
- 请求 ID 和队列 URL 持久化；超时或下载失败优先查原请求，不重新提交。提交时连接失败（ConnectError/ConnectTimeout）或请求体未写完（WriteError/WriteTimeout）FAL 不可能接单，记为 `failed` 并释放占用；其余无 ID 的未知提交（如请求体已发出后读响应中断）仍保留占用，人工核对后再确认结束。不要通过清空队列、改状态或重置租约绕过重复计费保护。
- 同组位置（同一 `avatar_id` + 贴纸 `id` + `revision`，`slot_group`）共享生成：`rerun` 要求组内每个位置都空闲且无待确认版本，只新建一个任务并把全组 `active_item_id`/`reservation_item_id` 指向它；只有操作的位置记 `reruns_reserved`/`reruns_used`，其余位置带 `reservation_shared`，`reconcile` 对它们只设 `pending_version_id`/释放占用、不动计数，因此整单只扣一次。`select` 把版本应用到全组（缺该版本的旧分歧位置会补入），组内有进行中的重跑时返回 409。`reprocess` 只对正显示同一任务的组内位置生效。DTO 带 `group_size`。
- 客户订单的首次生成明确失败（`failed`、无占用、无原图、仍是该位置的首次任务）时，DTO 给出 `can_retry`；访客可调用 `POST /api/guest/order/slots/{slot}/retry`，每个位置最多 3 次（`slot.guest_retries`，同一首次任务的重复位置一起计数），后台重试不限且都不占 `rerun_limit`。访客的 `error` 是按状态生成的安全文案，不含供应商原始错误。
- 贴纸（模板）图片按长边缩放到 1024 像素后入库，头像短边超过 1024 像素时缩小（`storage.normalize_image` 的 `fit`）；启动迁移 `template-1024-v1` 为既有非 1024 像素贴纸生成新资产和新修订，旧资产/修订保留给历史订单。
- 原始付费结果先保留，再做可选 Yezi 抠图；抠图有独立凭证和并发/速率控制。Yezi 同步请求只带 `sync`、`output_format`（带 `timeout` 字段会被拒，HTTP 400“timeout不支持”）；结果只接受 `*.aliyuncs.com`、`*.yezisheji.com`、`*.arrowfty.com` 的链接，Yezi 给的 http 链接一律改用 HTTPS 下载。Yezi 已应答（含 HTTP 错误）或根本没连上时，`ProviderFailure.cutout_ended=True`：item 清除 `cutout_inflight`、记 `cutout_failed`，DTO 给 `can_recut`，客户和员工可 `slots/{id}/reprocess` 或整单 `recut` 重抠（客户与首次生成重试共用每位置 3 次）；读超时等中途断开仍按“结果待确认”处理。启动时把旧版存成待确认、但错误里带“抠图失败（HTTP ”的 item 转为可重试。抠图成功的 item 记 `cutout_used`，其版本带 `before_id`（原图），DTO 版本给 `before_url` 做前后对比，媒体授权允许这些原图（同样加水印）。员工 `slots/{id}/recut` 随时重抠：新建 `recut_of`/`force_cutout` 的后处理 item（同原图，强制走抠图），同组位置一起切到新 item 并设为 initial，不占重试额度，统计排除 `recut_of`。存在原图时用“仅重试后处理”，不能误当作重新生图。生产没有 mock 开关，测试通过显式 provider/transport 注入。
- 访客媒体（含后台订单弹窗里的水印预览）以 WebP q90 输出（`guest_media.PIPELINE` 为缓存版本），原图、打印文件、下载和 ZIP 仍为 PNG。
- 水印媒体三层缓存（`guest_media.py`、`media_cache.py`）：每进程 256MB 内存 LRU → 硬盘缓存（`STUDIO_MEDIA_CACHE_DIR`，生产为 `/var/cache/avatar-sticker-studio/media`，默认 `<数据目录>/media-cache`）→ 现场生成。文件按内容命名，相同贴纸 + 水印文字 + 尺寸在所有订单间共用，生成量与订单数无关。`library/<asset>/` 存在用图库贴纸，在贴纸删除、水印不再被在职账号或未完成订单使用、管线变化时清理；`customer/<org>/<asset>/` 存头像/结果/总览，最后访问满组织设置天数（`organizations.media_cache_days`，默认 15，组织管理员 1–365 天，`/api/organization/settings`）后清理。不设容量上限，磁盘剩余低于 512MB 时只跳过写入。`MediaWarmer` 后台线程（nice 19，每 10 分钟）先清理再预生成：在用水印 × 在用贴纸的 160/320/640 三档（一次水印绘制），以及未完成订单在保留期内的头像/结果和已就绪总览的 640。资产删除通过 `cleanup_files` 的 `media-cache/<asset>` 记录持久重试清理。超管存储面板分别统计图库水印图与客户图片。
- 水印分单张预览、访客媒体、已生成总览等路径；水印强度和缓存版本改变要分别核对，避免给已经带水印的总览再次叠加。原图与打印文件不能带预览水印。
- 默认打印 A4、300 DPI、内容长边 85mm、边距/间距 10mm；亮度与色彩预设默认关闭。透明通道、预乘 alpha 缩放和不可变原图需要保留。
- 打印参数 `white_border_px` 默认 7（整数 0–50，0 关闭），随账号默认打印参数在开户时形成订单快照，旧记录缺字段按 7 读取。`white_border_alpha` 默认 128（整数 1–255，旧记录缺字段按 128）：alpha 低于它且与外部相连的像素视为背景，避免抠图残留的低 alpha 雾把外轮廓推到可见边缘之外、或把凹角封成假孔洞。`prepare_sticker` 在原始生成结果尺寸下先清理与该外部背景相邻的向内圆形距离带（背景中 alpha>0 的残留一并刷白；不围绕内部透明孔洞刷白），仅将 RGB 设为 255，保留 alpha；然后裁透明边、预乘 alpha 缩放、做打印色彩调整，清理后的纯白保持中性，最后拼到画布。`repack` 清除发布签名后从保存结果重建，支持修复旧打印文件，原图和单张预览不改，不发起生图；新打印管线签名区分旧缓存。账号默认值变化不影响历史订单，可在重新排版中修改本单宽度。
- 打印标题为订单号加卖家备注（打印最多 60 字）。卖家备注 `platform_remark` 只来自销售平台（目前仅拼多多接入订单查询）、站内不可编辑：开户时取交易推送的 `Remark`；提交（`submit`）时为关联阿奇索的订单置 `remark_sync_pending`，Worker 在排版前经 `before_publish` 钩子调用阿奇索 `Trade/Detail` 读取一次（[remark_sync.py](../backend/app/remark_sync.py)），失败保留原值并记 `remark_sync.status=failed`，不阻塞排版；后台 `POST /api/customer-orders/remarks/sync`（最多 200 单，限本组织）手动读取，备注变化时更新，已提交订单 `delivery_version+1` 并重新排版。买家留言 `buyer_memo` 仍随推送保存，但不再出现在任何 API 响应和界面中。内部备注 `notes` 用于下载目录 `订单号_内部备注`。界面中 `final_count` 统一称“可提交印刷数量”。
- 打印文件整批原子发布，失败保留已有有效结果。后台下载清单和 ZIP 只包含最终打印拼图；仅在用户点击后写目录或下载。目录文件通过哈希、清单和归属保护，不能覆盖未经系统管理的同名文件。

## 销售平台、店铺与水印

平台定义集中在 [platforms.py](../backend/app/platforms.py)，抖店和小红书的推送分类、字段校验及接口调用在 [agiso_platforms.py](../backend/app/agiso_platforms.py)：`pdd` 拼多多、`douyin` 抖店、`xhs` 小红书，含阿奇索授权域名、推送 `fromPlatform`、接口网关前缀及是否已接入（`connectable`）。协议差异见 [阿奇索资料存档](agiso-reference/README.md)。三个平台都可授权和接收推送。

- 订单 `platform` 必填（`POST /api/customer-orders` 的 `platform`），`shop_id` 可选；店铺必须属于本组织且平台一致，否则 422。阿奇索开户的订单继承来源店铺的平台和店铺，`platform_editable=false`；人工订单可经 `POST /api/customer-orders/{id}/platform`（`client_token` + `expected_version`）修改平台和店铺，水印快照不变。订单号全平台唯一，跨平台撞号开户进入人工处理。
- 店铺（`agiso_shops`）以“平台 + 平台店铺 ID”识别；推送按 `fromPlatform` 定平台后再找店铺。拼多多事件 ID 保持原算法，其他平台加平台前缀去重。
- 水印按店铺设置：`agiso_shops.watermark` 由店铺负责账号或组织管理员经 `PUT /api/agiso/shops/{id}/watermark` 修改。新订单水印 = 所属店铺水印；无店铺的人工订单用开单账号水印（账号水印留空用显示名称）。“批量更新水印”按同一规则取当前值。水印仍是订单快照，改店铺水印不改已有订单。
- 失效 SKU（仅手动触发）：`POST /api/agiso/shops/{id}/rules/check` 逐页读取店铺商品（拼多多 `Goods/List`、抖店 `Product/List`+`Product/Detail`、小红书 `Product/GetList` 在售），短页即末页，最多 100 页；任一页失败返回 409 且不改上次结果。结果存 `agiso_shops.rule_check = {checked_at, missing, offsale, offsale_visible}`，按 `rule_key` 对照（小红书只比 SKU ID）；抖店 status 2 视为已删除。小红书读不到下架商品，`offsale_visible=false`，下架也计入 `missing`。`POST …/rules/prune` 只删除上次检测的 `missing` 规则，删后无启用规则时关闭店铺开关。
- 解绑店铺：`POST /api/agiso/shops/{id}/unbind`（负责账号或组织管理员）。先在事务外尽力调用阿奇索 `Sys/TokenDelete` 撤销授权（失败只记日志，响应 `revoked=false`，前端提示到阿奇索后台确认），再在事务内复核 Token 未被并发重授权：没有任何 `agiso_orders`、`agiso_events`、`orders` 引用的店铺直接删除；其余店铺删除 `token`、`enabled=false`、`expires_at=0`、记 `unbound_at`，保留规则、水印、`push_keys` 和历史。重新授权同一平台同一店铺 ID 时沿用原记录并清除 `unbound_at`。
- `remark_supported` = 阿奇索开户且该平台订单详情含卖家备注（拼多多 `Trade/Detail`、抖店 `seller_words`；小红书没有）；只有此类订单显示和处理“获取卖家备注”。
- 售后按平台验收：`STUDIO_AGISO_AFTERSALES_PLATFORMS`（逗号分隔，如 `pdd,douyin`）列出已用真实退款验收的平台；未设置时沿用旧变量 `STUDIO_AGISO_AFTERSALES_VERIFIED=1`，仅代表拼多多。
- 抖店/小红书推送按平台解释 aopic（抖店 1 付款、2 发起售后、4 售后关闭、8 退款成功；小红书 4 付款、16 申请退款、32 退款成功；其余记录为“已忽略”）。付款推送不含商品，事件先以 `fetch` 入库，Agiso worker 在事务外调用 `Order/Detail`（抖店参数 `shop_order_id`，小红书 `tid`）取规格、实付、卖家备注和订单状态，再与拼多多共用 `open_trade` 开户；未付款/已取消订单记为人工（`order_unpaid`/`order_cancelled`），读取 5 次失败记为 `order_lookup_failed`，授权失效时等待重新授权。抖店按父订单号开户，子订单 SKU 合并计算；小红书订单详情只有 SKU ID，规则按 SKU ID 匹配，赠品（`skuTag=1`）不计额度。
- 授权 Token 同时给出 `ShopId`/`UserId` 时都保存；推送中的店铺 ID 与已知 ID 都不符时事件记为 `unmatched`，worker 用该平台各已授权店铺试读订单，能读到的店铺即归属，并把该店铺 ID 记入 `push_keys`；仍无法匹配记为 `unknown_shop`。
- 退款推送规范化为拼多多同形结构交给 `apply_refund`：钱款退款（抖店售后类型 0/1/2、小红书退货类型 1/3/4/5）参与自动判断，换货等记人工；小红书没有售后关闭推送，撤销的退款需人工处理。新平台退款仅在其平台列入 `STUDIO_AGISO_AFTERSALES_PLATFORMS` 后生效，之前事件保留为 `aftersales_disabled`。
- 迁移 `platform-v1`：所有既有店铺、阿奇索关联、推送事件和订单（含人工订单）标为 `pdd`；阿奇索订单补 `shop_id`；店铺水印取负责账号迁移时的实际水印，订单水印快照不变。

## Agiso 接入边界

代码链路：验签接收 → `agiso_events` 持久化去重 → SKU/店铺/账号校验 → 复用开户函数 → `agiso_orders` 关联 。网站不再创建或消费 `agiso_outbox`，不调用消息接口；仅由阿奇索自动发货平台发送入口。历史发送记录原样保留，新订单消息状态为 disabled，补发接口拒绝请求。网站状态不代表平台消息已送达。

- topic `1` 为交易确认处理路径；付款后通知可接受空 `ConfirmTime`。`8/16/512` 走退款/售后族，`32` 发货通知仅记录，`64` 更新买家备注；未知 topic 会记录而非冒充处理成功。不要把 topic 编号与 operation 混用。
- 全部商品/SKU 必须匹配已启用规则；G/F 按购买数量累加，R 使用匹配规则一致的整单上限，不乘购买数量。未匹配、规则冲突、超额和订单号重复转人工，不能猜套餐或创建重复订单。
- 新增 SKU 默认启用。前端选择或编辑规格名称时按完整数量加“个/张”从 42/36/30/24/18/12/6/1 降序匹配默认 G/F/R，可继续人工调整；无匹配保留原额度。`sku-spec-defaults-v1` 一次性启动迁移启用所有已有 SKU 并按同规则更新命中额度，仅修改 `agiso_shops.rules`，不打开店铺总开关、不改变已有订单快照；标记存在后不覆盖人工调整。规则见 `backend/app/sku_defaults.py` 和 `frontend/src/lib/agiso.ts`。
- 商品查询不可用时允许人工填写已核实的商品/SKU ID。错误码 17 有专门权限提示，不能把“列表为空”写成“店铺没有商品”。
- 自动开户依赖应用配置、有效店铺授权、开关和有效所属账号/组织。关闭店铺停止未来自动开户，不直接中断已有正常订单制作。
- 售后开关按平台为 `STUDIO_AGISO_AFTERSALES_PLATFORMS`（旧变量 `STUDIO_AGISO_AFTERSALES_VERIFIED=1` 等同仅拼多多）；启用后可处理此前因开关关闭而存下的退款。已验签的售后事实不因出站授权过期或店铺关闭而丢弃。
- 全额且类型明确的成功退款取消订单并撤销访客访问；部分、异常或未知类型交人工核对。退款撤回/关闭不能复活已经成功退款的订单；解除售后暂停不能清除原有人工暂停。
- 网站消息发送及补发已停用；历史待发送、失败、未知记录不会重放，不重写其历史状态。核对第一条消息需查看阿奇索自动发货平台和拼多多聊天记录。
- `STUDIO_AGISO_ENCRYPTION_KEY` 加密店铺凭证，随意更换会导致旧凭证无法解密。账号授权、真实发信、售后和物流均不可用测试模拟冒充验收。

配置和外部条件见 [Agiso 指南](agiso-setup.md)；其中带日期的店铺、余额、服务有效期和助手在线记录均需重新确认。

## 生产入口与运行边界

统一公网来源为 `https://sticker.coreages.com`，经阿里云 ESA 回源到 ECS `8.130.175.250`；ESA 只缓存带内容哈希的 `/assets/` 构建文件，`/api/` 一律绕过缓存，访客真实 IP 经 `ali-real-client-ip` 由 Nginx 仅从 ESA 地址恢复。Nginx 在独立虚拟主机终止 TLS 并转发到单个 loopback Uvicorn；数据库仍为单机 SQLite WAL。允许主机、修改请求来源、Secure Cookie 及 Agiso 公网来源必须一致；前端 `/api` 使用相对路径。原入口 `sticker.magnusma.online` 已于 2026-10-06 停用解析；原图和私有说明不通过静态目录暴露。详情见[生产部署](../deploy/README.md)。

## OSS 打印文件交付

配置 `STUDIO_OSS_BUCKET` 后，`oss_delivery.py` 使用官方 Python SDK V2 和 ECS 实例 RAM 角色；不保存长期 AccessKey。Worker 每 30 秒在线程中串行同步 submitted 且 delivery_ready 的当前打印 PNG，事务外经同地域内网上传，校验本地 SHA-256 并保留 SDK CRC64 校验；回写前复查订单及资产。对象路径为 `print/<组织内部ID>/<订单内部ID>/<sha256>.png`，不含客户订单号。每 10 分钟对账清理当前有效打印文件之外的对象；删除失效对象前先清除对应 oss_key，使取消后恢复的订单能重新上传。没有新增任务表、租约或版本目录。

后台 manifest 保留完整会话、组织及 submitted/delivery_ready 检查，返回 `local_url` 和当前可用下载 `url`，响应 `private, no-store`。启用 OSS 下载且文件已同步时签发默认 300 秒 GET 链接；客户端跨域使用 `credentials: omit`，最近清单用于下一文件，远端失败刷新一次再回退 local_url。哈希、目录归属、Web Locks 和 delivery_version 检查仍有效。用户 2026-10-05 明确接受已发链接在有效期内可重复使用且不会随账号或订单状态即时撤销，停止新签发不等于撤销旧链接。

ZIP 不上传 OSS：短事务取得授权文件快照后在事务外读取并用 ZIP_STORED 打包，下载文件名按订单目录名用 RFC 5987 编码。ZIP 和 PNG 回退仍经过 ECS 公网出口。OSS 只存当前文件，本地原图及历史版本语义不变；空 Bucket 配置完全关闭同步，`STUDIO_OSS_DOWNLOAD=0` 只关闭直链、继续上传。


## 单一订单与点数下线迁移

`drop-workflow-version-v1` 首次执行前只读核对全部 orders/items：每条记录的 `workflow_version` 必须是整数 3，缺失或其他值立即拒绝，不先修改业务记录。通过后删除该字段及 `records_workflow_version` 索引，并记录迁移标记；重复启动不重复转换。

`drop-credits-v1` 删除 `credit_ledger`、`credit_operations` 记录，及 users.credits、items.credit_exempt/billing_legacy。`generations`、请求 ID、远端占用、未知状态、原图及历史版本保留；`request_tracking.progress` 只同步供应商请求 ID，不再执行点数状态结算。FAL 账户余额查询 `fal_billing.py` 保留。

已有客户订单历史仍阻止账号永久删除；只能停用。常规订单清理不删除客户订单历史。统计继续按现有客户订单和任务汇总，旧流程的 template_codes 统计来源随旧流程删除；未添加客户订单模板来源追溯。

迁移审计必须显式使用 `--allow-single-order-migration`，只容许上述删除和合法打印 OSS 标记变化，其余受保护记录、生成请求与资产哈希保持严格比对。阶段 B 回退必须恢复发布前配对数据与旧 release，不能只切回代码；接收新业务后仅向前修复。


## FAL 从 OSS 取生图输入

全站 `config/settings.fal_input_mode` 的迁移默认值为 `inline`，有效值只有 `inline` / `oss`。仅超级管理员可读取、修改全站设置；响应中的 `fal_input_oss_available` 只读派生于服务器 OSS 配置。配置不可用时有效模式为 inline，拒绝设置 oss，不泄露凭证。设置即时作用于后续新提交，不改变已有请求的恢复路径。

OSS 模式在数据库事务外计算模板和头像 SHA-256，HEAD 检查 `fal-inputs/<YYYYMMDD UTC>/<sha256>.png`；只有确定 NoSuchKey 才上传，设置 image/png。同日同内容复用，签名由公网 SDK 客户端产生，不主动设置 `response-content-disposition`；OSS 默认域名仍可能强制返回 attachment，不能保证最终响应没有下载头。`STUDIO_FAL_INPUT_URL_TTL` 默认 7200 秒；签名只存在提交内存，请求正文不进入数据库、日志或前端。Bucket 的 `fal-inputs-expire-2d` 规则仅清理 `fal-inputs/`，满 2 天后按 OSS 日调度及异步执行，不保证严格 72 小时内完成；打印、备份和本地原图不在此规则内。

OSS 暂存/签名失败发生在 FAL POST 前，同一次尝试回退原 inline 请求；item 记录实际 `fal_input=inline` 和脱敏原因。POST 的写入/连接失败、未知响应、429 退避语义沿用原规则。`max_uploads` 仍统计没有 request ID 的 running 提交任务，包含暂存阶段；全站及账号并发继续共同约束。已知请求 ID 的 poll/result/恢复不再暂存或重新提交。inline 请求体保持原有字节编码。

OSS 输入请求若明确以 `file_download_error` 结束（状态接口 `error_type` 或结果接口 422 `detail[].type`），该请求已结束且无输出、FAL 不计费：worker 把原 request ID 记入 item 的 `fal_input_retries`，清除该请求的状态字段并以 `fal_force_inline=True` 重新排队，下一次领取照常经过 `max_inflight`、`max_uploads`、账号并发与 429 退避，提交改用 inline（`fal_input_fallback_reason=fal_download_retry`）。每个 item 最多一次；inline 请求或已自动重试过的请求出现同类错误按普通失败处理。该重提交不改变客户重试次数和整单 `rerun_limit`，`attempt` 记录实际请求数。

结构化计时日志只记录 item ID、时间、模式、对象复用标志、stage_ms/post_ms/request_bytes、队列状态及位置、download_ms、postprocess_ms 和脱敏分类，不记录图片、订单号、密钥或签名链接。日志用于排障，不能把未知状态当作供应商未计费的证明。
