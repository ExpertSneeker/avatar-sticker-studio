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
| 工作台与历史订单共用页 | `frontend/src/pages/CustomerOrders.tsx`、`CustomerOrders.css` |
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
- 访客媒体每次请求（含 304）都按会话、订单归属、订单状态和资产范围现场校验：已取消订单全部拒绝，已提交订单的访客只能看总览，图库贴纸用 `records_image_id` 索引查询是否属于本组织在用贴纸（不再每次读取整个图库）。订单已取消“图片版本号”（`media_version`）：媒体链接为 `/api/guest/media/{order}/{asset}?m=<水印文字指纹>`（后台为 `/api/customer-orders/{order}/media/{asset}?m=…`），不随取消、恢复、提交或解锁改变；`m` 只让打开中的页面在换水印后换图，服务端不据此授权。授权跟随订单实时状态，旧数据中残留的该字段不再读取。需要服务端压平水印；水印媒体使用 `private, no-cache`、`Vary: Cookie` 与按内容计算的 ETag（素材哈希、水印文字、尺寸、渲染管线、是否已带水印），允许浏览器保存但每次复用前仍鉴权，未变化返回 304；换水印后 ETag 改变，浏览器重新下载。尺寸只有 160/320/640/1024 四档（其他请求值向上归档）；160/320 由 640 水印图等比缩小并以 WebP q80 编码。客户选图页用 `srcset`/`sizes` 按显示宽度和屏幕密度选档，`sizes` 与选图网格 CSS 同步维护，由 `customer-picker-responsive-media` E2E 检查；304 不读取原图或重新编码，返回前也再次检查授权。其他访客 API 保持 `no-store`；前端 CSS 遮罩不能代替它。提交/取消后的访客 DTO 会省略头像、位置等字段，不得从旧响应回填这些字段。
- 订单号即访客入口凭据。不要把真实编号、预填链接、OAuth code、原始推送或头像放到日志、截图、Git 和交接记录中。

## 客户订单

后台工作台和历史订单统一使用 `/api/customer-orders`。订单只有一种结构，不写入或判断 `workflow_version`，旧 `/api/orders` 接口已移除；框架升级使用明确数据迁移，不保留旧流程兼容层。

| 状态 | 含义和出口 |
| --- | --- |
| `draft` | 待制作，可上传头像并选择；确认生成后冻结并进入 `review` |
| `review` | 选图中，等待任务、重做与版本确认；精确选择 F 个位置后提交 |
| `submitted` | 已锁定，服务端生成水印总览及打印拼图；后台可手动下载、重新排版或解锁 |
| `cancelled` | 取消并保留记录；受规则约束可恢复，退款取消另受售后保护 |

`draft` 订单的工作清单（头像上传记录与各自的模板/贴纸选择）保存在订单的 `draft` 字段，客户与后台通过 `PUT /api/guest/order/draft`、`PUT /api/customer-orders/{id}/draft` 整体覆盖保存，最后一次保存为准。草稿有独立的 `draft.revision`，不增加订单 `version`，不需要 `client_token`，不影响生成/提交的并发检查；完整订单响应（非 `summary`）在 `draft` 状态返回 `draft`。保存时服务端校验：头像数不超过 F、不重复，上传记录已完成且属于本组织；客户只能加入本订单的访客上传，但可保留后台已放入草稿的上传；份数超过 G 时仅允许减少；已下架的模板/贴纸被丢弃。草稿中的头像可通过本订单媒体路由查看；客户生成时可使用后台已放入草稿的头像。开始生成后删除草稿，之后保存返回 409。前端每次添加/移除头像或“应用选择”即保存，网络或服务端错误在下次轮询时自动重试；不在浏览器存储中保存草稿。

工作台仅显示 `draft/review`；历史订单显示全部客户订单，并可筛选已提交、已取消等。订单详情在弹窗中打开，两处页面共用逻辑。列表轮询使用 `GET /api/customer-orders?summary=1`，响应省略 `avatars`/`slots`（仍对每单执行 `reconcile`）；弹窗单独请求 `GET /api/customer-orders/{id}` 取得完整订单，列表发现版本更新时再刷新详情。不带 `summary` 的列表接口保持完整数据。列表支持关联店铺及无关联店铺筛选。

| 字段 | 必须保持的语义 |
| --- | --- |
| `generation_limit`（G） | 可预览份数上限，按选择出现次数计，不是去重后的付费调用数 |
| `final_count`（F） | 最终必须提交的不同位置数，`1 ≤ F ≤ G ≤ 360` |
| `rerun_limit`（R） | 非负整数，整单共用，已用和在途预留一起计入预算 |
| `version` / `expected_version` | 乐观并发控制，过期操作返回 409 |
| `client_token` | 同一操作的幂等标识；同 token 不同内容拒绝，响应不确定时按原请求重试 |
| `content_version` / `artifact_version` / `delivery_version` | 内容、产物和交付失效各有用途，不要合成一个“刷新”计数；媒体链接已不带版本号，见上文访客媒体 |

开户固定水印和打印参数，空水印使用当时账号显示名，同时保存提示词及版本。生成时固定头像、贴纸版本和选择。首次生图按 `(avatar_id, sticker_id, revision)` 去重；每次选择仍保留独立位置，重做和版本选择不连带改其他重复位置。

重做成功消耗整单一次机会，保留旧版也不会退回已成功重做次数；明确失败且没有外部占用才释放预留，未知请求继续占用。一次性迁移 `order-shared-rerun-v1` 将存量 v3 订单的 R 设为各自 G；这是历史迁移动作，不是新订单的默认值。

提交要求恰好 F 个不同位置，顺序决定输出；整单所有在途/未知请求、未释放预留和待确认版本都要处理完。顶部“已选 x/y”使用 `selection.length / final_count`，移动端滚动可见；点击可选卡片切换选择，“查看 / 重跑”才打开放大对比。

解锁保留已消耗额度和版本，重新提交前关闭旧交付下载。取消或暂停不等于远端请求结束；继续核对在途请求，但不能继续新生图或发布不该发布的产物。

## 图片、队列与打印

- 当前 provider 源码使用 FAL `openai/gpt-image-2.5/flare/edit`；凭证是 `FAL_KEY` 或后台私有设置，环境变量优先。这描述仓库实现，不保证第三方服务未来仍可用。变更 provider 前核对其当时官方契约。
- 点数功能及其接口已下线；实际生图记录、原图、旧请求 ID 和占用继续保留。全站 `max_inflight` 默认 2（1–40）和账号并发同时约束；访客任务计入开户账号。没有旧 RPM 门槛。
- 提交阶段（尚无 request ID，包含 OSS 暂存及发送 FAL 请求）另受全站 `max_uploads`（默认 3，1–40）约束，已拿到 ID 在 FAL 排队的任务不占用；提交 POST 的写超时为全站 `fal_upload_timeout`（默认 300 秒，30–1800），其他 FAL 请求仍为 60 秒。整个 JSON 请求体是一次写入，写超时即上传上限。
- 请求 ID 和队列 URL 持久化；超时或下载失败优先查原请求，不重新提交。提交时连接失败（ConnectError/ConnectTimeout）或请求体未写完（WriteError/WriteTimeout）FAL 不可能接单，记为 `failed` 并释放占用；其余无 ID 的未知提交（如请求体已发出后读响应中断）仍保留占用，人工核对后再确认结束。不要通过清空队列、改状态或重置租约绕过重复计费保护。
- 客户订单的首次生成明确失败（`failed`、无占用、无原图、仍是该位置的首次任务）时，DTO 给出 `can_retry`；访客可调用 `POST /api/guest/order/slots/{slot}/retry`，每个位置最多 3 次（`slot.guest_retries`，同一首次任务的重复位置一起计数），后台重试不限且都不占 `rerun_limit`。访客的 `error` 是按状态生成的安全文案，不含供应商原始错误。
- 贴纸（模板）图片按长边缩放到 1024 像素后入库，头像短边超过 1024 像素时缩小（`storage.normalize_image` 的 `fit`）；启动迁移 `template-1024-v1` 为既有非 1024 像素贴纸生成新资产和新修订，旧资产/修订保留给历史订单。
- 原始付费结果先保留，再做可选 Yezi 抠图；抠图有独立凭证和并发/速率控制。存在原图时用“仅重试后处理”，不能误当作重新生图。生产没有 mock 开关，测试通过显式 provider/transport 注入。
- 访客媒体（含后台订单弹窗里的水印预览）以 WebP q90 输出（`guest_media.PIPELINE` 为缓存版本），原图、打印文件、下载和 ZIP 仍为 PNG。
- 水印媒体三层缓存（`guest_media.py`、`media_cache.py`）：每进程 256MB 内存 LRU → 硬盘缓存（`STUDIO_MEDIA_CACHE_DIR`，生产为 `/var/cache/avatar-sticker-studio/media`，默认 `<数据目录>/media-cache`）→ 现场生成。文件按内容命名，相同贴纸 + 水印文字 + 尺寸在所有订单间共用，生成量与订单数无关。`library/<asset>/` 存在用图库贴纸，在贴纸删除、水印不再被在职账号或未完成订单使用、管线变化时清理；`customer/<org>/<asset>/` 存头像/结果/总览，最后访问满组织设置天数（`organizations.media_cache_days`，默认 15，组织管理员 1–365 天，`/api/organization/settings`）后清理。不设容量上限，磁盘剩余低于 512MB 时只跳过写入。`MediaWarmer` 后台线程（nice 19，每 10 分钟）先清理再预生成：在用水印 × 在用贴纸的 160/320/640 三档（一次水印绘制），以及未完成订单在保留期内的头像/结果和已就绪总览的 640。资产删除通过 `cleanup_files` 的 `media-cache/<asset>` 记录持久重试清理。超管存储面板分别统计图库水印图与客户图片。
- 水印分单张预览、访客媒体、已生成总览等路径；水印强度和缓存版本改变要分别核对，避免给已经带水印的总览再次叠加。原图与打印文件不能带预览水印。
- 默认打印 A4、300 DPI、内容长边 85mm、边距/间距 10mm；亮度与色彩预设默认关闭。透明通道、预乘 alpha 缩放和不可变原图需要保留。
- 打印标题为订单号加卖家备注（打印最多 60 字）。卖家备注 `platform_remark` 只来自拼多多、站内不可编辑：开户时取交易推送的 `Remark`；提交（`submit`）时为关联阿奇索的订单置 `remark_sync_pending`，Worker 在排版前经 `before_publish` 钩子调用阿奇索 `Trade/Detail` 读取一次（[remark_sync.py](../backend/app/remark_sync.py)），失败保留原值并记 `remark_sync.status=failed`，不阻塞排版；后台 `POST /api/customer-orders/remarks/sync`（最多 200 单，限本组织）手动读取，备注变化时更新，已提交订单 `delivery_version+1` 并重新排版。买家留言 `buyer_memo` 仍随推送保存，但不再出现在任何 API 响应和界面中。内部备注 `notes` 用于下载目录 `订单号_内部备注`。界面中 `final_count` 统一称“可提交印刷数量”。
- 打印文件整批原子发布，失败保留已有有效结果。后台下载清单和 ZIP 只包含最终打印拼图；仅在用户点击后写目录或下载。目录文件通过哈希、清单和归属保护，不能覆盖未经系统管理的同名文件。

## Agiso 接入边界

代码链路：验签接收 → `agiso_events` 持久化去重 → SKU/店铺/账号校验 → 复用开户函数 → `agiso_orders` 关联 。网站不再创建或消费 `agiso_outbox`，不调用消息接口；仅由阿奇索自动发货平台发送入口。历史发送记录原样保留，新订单消息状态为 disabled，补发接口拒绝请求。网站状态不代表平台消息已送达。

- topic `1` 为交易确认处理路径；付款后通知可接受空 `ConfirmTime`。`8/16/512` 走退款/售后族，`32` 发货通知仅记录，`64` 更新买家备注；未知 topic 会记录而非冒充处理成功。不要把 topic 编号与 operation 混用。
- 全部商品/SKU 必须匹配已启用规则；G/F 按购买数量累加，R 使用匹配规则一致的整单上限，不乘购买数量。未匹配、规则冲突、超额和订单号重复转人工，不能猜套餐或创建重复订单。
- 商品查询不可用时允许人工填写已核实的商品/SKU ID。错误码 17 有专门权限提示，不能把“列表为空”写成“店铺没有商品”。
- 自动开户依赖应用配置、有效店铺授权、开关和有效所属账号/组织。关闭店铺停止未来自动开户，不直接中断已有正常订单制作。
- 售后开关为 `STUDIO_AGISO_AFTERSALES_VERIFIED`；启用后可处理此前因开关关闭而存下的退款。已验签的售后事实不因出站授权过期或店铺关闭而丢弃。
- 全额且类型明确的成功退款取消订单并撤销访客访问；部分、异常或未知类型交人工核对。退款撤回/关闭不能复活已经成功退款的订单；解除售后暂停不能清除原有人工暂停。
- 网站消息发送及补发已停用；历史待发送、失败、未知记录不会重放，不重写其历史状态。核对第一条消息需查看阿奇索自动发货平台和拼多多聊天记录。
- `STUDIO_AGISO_ENCRYPTION_KEY` 加密店铺凭证，随意更换会导致旧凭证无法解密。账号授权、真实发信、售后和物流均不可用测试模拟冒充验收。

配置和外部条件见 [Agiso 指南](agiso-setup.md)；其中带日期的店铺、余额、服务有效期和助手在线记录均需重新确认。

## 生产入口与运行边界

统一公网来源为 `https://sticker.coreages.com`，部署于阿里云 ECS `8.130.175.250`。Nginx 在独立虚拟主机终止 TLS 并转发到单个 loopback Uvicorn；数据库仍为单机 SQLite WAL。允许主机、修改请求来源、Secure Cookie 及 Agiso 公网来源必须一致；前端 `/api` 使用相对路径。原入口兼容跳转不承载业务 worker，原图和私有说明不通过静态目录暴露。详情见[生产部署](../deploy/README.md)。

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

OSS 模式在数据库事务外计算模板和头像 SHA-256，HEAD 检查 `fal-inputs/<YYYYMMDD UTC>/<sha256>.png`；只有确定 NoSuchKey 才上传，设置 image/png。同日同内容复用，签名由公网 SDK 客户端产生，不带下载附件头。`STUDIO_FAL_INPUT_URL_TTL` 默认 7200 秒；签名只存在提交内存，请求正文不进入数据库、日志或前端。Bucket 的 `fal-inputs-expire-2d` 规则仅清理 `fal-inputs/`，满 2 天后按 OSS 日调度及异步执行，不保证严格 72 小时内完成；打印、备份和本地原图不在此规则内。

OSS 暂存/签名失败发生在 FAL POST 前，同一次尝试回退原 inline 请求；item 记录实际 `fal_input=inline` 和脱敏原因。POST 的写入/连接失败、未知响应、429 退避语义沿用原规则。`max_uploads` 仍统计没有 request ID 的 running 提交任务，包含暂存阶段；全站及账号并发继续共同约束。已知请求 ID 的 poll/result/恢复不再暂存或重新提交。inline 请求体保持原有字节编码。

结构化计时日志只记录 item ID、时间、模式、对象复用标志、stage_ms/post_ms/request_bytes、队列状态及位置、download_ms、postprocess_ms 和脱敏分类，不记录图片、订单号、密钥或签名链接。日志用于排障，不能把未知状态当作供应商未计费的证明。
