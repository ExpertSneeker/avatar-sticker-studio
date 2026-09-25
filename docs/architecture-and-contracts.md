# 架构与行为契约

核对基线：2026-09-26，功能源码 `e984fdb`。本文解释当前实现，不是新的功能需求，也不代表已验证当前线上服务。统一维护规则见 [AGENTS.md](../AGENTS.md)，命令见[运维指南](agent-operations.md)。

## 系统与代码地图

浏览器通过同源 `/api` 调用 FastAPI。生产由 FastAPI 同时提供构建后的前端；开发时 Vite 代理 `/api`。SQLite WAL 的事务和持久化记录协调同一主机上的工作进程，不是多主机共享数据库架构。

| 关注点 | 主要文件 |
| --- | --- |
| 启动、环境加载和本地端口 | `scripts/studio.mjs`、`.env.example` |
| API 注册、认证、全局设置、健康和就绪检查 | `backend/app/main.py` |
| 角色、组织、后台会话 | `backend/app/auth.py`、`organizations.py`、`bootstrap.py` |
| 数据模型与自动迁移 | `backend/app/db.py`、`schemas.py` |
| 图库、模板和分类 | `backend/app/library.py`、`categories.py`、`selections.py` |
| 客户订单状态机、配额、访客接口、下载 | `backend/app/customer_orders.py` |
| 任务租约、公平调度、并发和请求恢复 | `backend/app/worker.py`、`providers.py`、`credits.py` |
| 图片入库、预览、水印、拼版、原子发布 | `backend/app/storage.py`、`previews.py`、`guest_media.py`、`processing.py`、`publication.py` |
| Agiso 协议、接口、状态转换和消息队列 | `backend/app/agiso_protocol.py`、`agiso_routes.py`、`agiso_service.py`、`agiso_worker.py` |
| 清理、删除计划和统计 | `backend/app/maintenance.py`、`statistics.py` |
| 后台壳、访客独立入口 | `frontend/src/App.tsx`、`main.tsx`、`pages/Guest.tsx` |
| 工作台与历史订单共用页 | `frontend/src/pages/CustomerOrders.tsx`、`CustomerOrders.css` |
| 后台代操作与访客共用制作界面 | `frontend/src/components/CustomerWorkbench.tsx` |
| API 身份、客户端幂等、交付文件保护 | `frontend/src/lib/api.ts`、`customer-orders.ts`、`delivery.ts`、`sync.ts` |
| 后台说明正文与页面 | `backend/content/staff-guide.json`、`frontend/src/pages/StaffGuide.tsx` |

数据库不是每种业务一张传统关系表：主要记录放在 `records(kind,id,doc)` 的 JSON 文档中，`starts` 用于速率记录。`Database(...)` 会创建目录、修改权限、执行迁移，`transaction()` 使用 `BEGIN IMMEDIATE`，不能作为无副作用只读诊断入口。禁止在真实数据上随意执行初始化代码。

高频查询不要再用 `tx.all(kind)` 全表解析后过滤：`Database` 启动时为 `INDEXED_FIELDS`（`status`、`remote_reserved`、`state`、`workflow_version`、`order_id`、`order_number`、`guest_order_id`、`customer_order_id`）建立 `(kind, json_extract(doc,'$.字段'))` 表达式索引，使用 `tx.where(kind, 字段, 值...)`、`tx.find(kind, (SQL条件, 参数)...)` 和 `tx.count(kind)`。它们按 rowid 返回与 `all()` 相同的顺序；SQL 只做超集预筛，调用处保留原来的 Python 精确判断。索引不改变文档，旧代码会忽略它们。Worker 与 Agiso worker 的调度、访客登录、上传查重、访客媒体授权都依赖这些索引。

只读请求使用 `db.read(fn)`：先以普通 `BEGIN` 读取快照，不等待写锁；`fn` 一旦调用 `put`/`delete` 就抛出 `NeedsWrite`（写入前），随后在原来的 `BEGIN IMMEDIATE` 事务里整体重跑。`fn` 除数据库外不得有副作用，因为它可能执行两次。订单列表/详情、访客订单/图库/媒体、`auth/me`、`auth/status`、图库和分类的 GET 使用它；`dto()` 的 `reconcile` 需要写入时会自动回退。`Database` 另持有一个空闲连接，使每个事务连接关闭时不再触发 checkpoint 和 WAL 删除，因此运行中数据目录会一直存在 `studio.sqlite3-wal`/`-shm`；备份仍须在停服后复制整个数据目录，不能只拷主库文件。

## 权限和隐私

- `superadmin` 管组织、全站设置与统计；独立超管可以不属于组织，因此不一定有组织工作台。`org_admin` 管本组织成员、图库授权与账号并发；`staff` 在组织内协作。服务器仍需对每个资源校验组织和角色。
- 图库 `scope=public` 是组织内共用。模板由 1–100 个有序且不重复的贴纸 ID 构成；不再是固定 12 张上传图。客户选择同一模板多份仍会产生重复份数。图库编辑需要授权；分类可编辑，不能假定只有男孩/女孩两类。
- 模板和贴纸当前采用删除流程，旧停用接口返回 410。删除、被引用素材和历史快照的保留应按现有服务端流程处理，不能直接删除资产文件。
- 后台使用 `studio_session`，访客使用 `studio_guest`。会话 token 仅保存哈希，Cookie 为 HttpOnly。后台请求携带 `X-Studio-User` 防止其他标签页换号后串操作；常规图片请求仍依赖服务端授权。
- 后台登录保留失败次数限制；访客订单号登录已经取消按 IP/订单号累计失败限制，仍验证订单和组织。不要把旧设计的限制重新加回。
- `/api/staff-guide` 先认证，再读取私有 JSON，响应 `private, no-store` 并区分 Cookie/账号。正文不能通过前端 import、public、构建资源、访客缓存或其他静态路径泄漏。
- 访客媒体按订单、当前媒体版本和状态校验。需要服务端压平水印与 `no-store`；前端 CSS 遮罩不能代替它。提交/取消后的访客 DTO 会省略头像、位置等字段，不得从旧响应回填这些字段。
- 订单号即访客入口凭据。不要把真实编号、预填链接、OAuth code、原始推送或头像放到日志、截图、Git 和交接记录中。

## 客户订单 v3

当前后台工作台和历史订单都使用 `/api/customer-orders`；旧 `/api/orders` 等兼容逻辑仍在后端，不能因为新导航不展示就删除历史数据或兼容处理。

| 状态 | 含义和出口 |
| --- | --- |
| `draft` | 待制作，可上传头像并选择；确认生成后冻结并进入 `review` |
| `review` | 选图中，等待任务、重做与版本确认；精确选择 F 个位置后提交 |
| `submitted` | 已锁定，服务端生成水印总览及打印拼图；后台可手动下载、重新排版或解锁 |
| `cancelled` | 取消并保留记录；受规则约束可恢复，退款取消另受售后保护 |

工作台仅显示 `draft/review`；历史订单显示全部 v3 订单，并可筛选已提交、已取消等。订单详情在弹窗中打开，两处页面共用逻辑。列表轮询使用 `GET /api/customer-orders?summary=1`，响应省略 `avatars`/`slots`（仍对每单执行 `reconcile`）；弹窗单独请求 `GET /api/customer-orders/{id}` 取得完整订单，列表发现版本更新时再刷新详情。不带 `summary` 的列表接口保持完整数据。列表支持关联店铺及无关联店铺筛选。

| 字段 | 必须保持的语义 |
| --- | --- |
| `generation_limit`（G） | 可预览份数上限，按选择出现次数计，不是去重后的付费调用数 |
| `final_count`（F） | 最终必须提交的不同位置数，`1 ≤ F ≤ G ≤ 360` |
| `rerun_limit`（R） | 非负整数，整单共用，已用和在途预留一起计入预算 |
| `version` / `expected_version` | 乐观并发控制，过期操作返回 409 |
| `client_token` | 同一操作的幂等标识；同 token 不同内容拒绝，响应不确定时按原请求重试 |
| `content_version` / `artifact_version` / `delivery_version` / `media_version` | 内容、产物、交付和媒体失效各有用途，不要合成一个“刷新”计数 |

开户固定水印和打印参数，空水印使用当时账号显示名，同时保存提示词及版本。生成时固定头像、贴纸版本和选择。首次生图按 `(avatar_id, sticker_id, revision)` 去重；每次选择仍保留独立位置，重做和版本选择不连带改其他重复位置。

重做成功消耗整单一次机会，保留旧版也不会退回已成功重做次数；明确失败且没有外部占用才释放预留，未知请求继续占用。一次性迁移 `order-shared-rerun-v1` 将存量 v3 订单的 R 设为各自 G；这是历史迁移动作，不是新订单的默认值。

提交要求恰好 F 个不同位置，顺序决定输出；整单所有在途/未知请求、未释放预留和待确认版本都要处理完。顶部“已选 x/y”使用 `selection.length / final_count`，移动端滚动可见；点击可选卡片切换选择，“查看 / 重跑”才打开放大对比。

解锁保留已消耗额度和版本，重新提交前关闭旧交付下载。取消或暂停不等于远端请求结束；继续核对在途请求，但不能继续新生图或发布不该发布的产物。

## 图片、队列与打印

- 当前 provider 源码使用 FAL `openai/gpt-image-2.5/flare/edit`；凭证是 `FAL_KEY` 或后台私有设置，环境变量优先。这描述仓库实现，不保证第三方服务未来仍可用。变更 provider 前核对其当时官方契约。
- 新任务免积分门槛，但历史账本、实际生图记录及旧请求占用保留。全站 `max_inflight` 默认 2（1–40）和账号并发同时约束；访客任务计入开户账号。没有旧 RPM 门槛。
- 请求 ID 和队列 URL 持久化；超时或下载失败优先查原请求，不重新提交。无 ID 的未知提交也保留占用，人工核对后再确认结束。不要通过清空队列、改状态或重置租约绕过重复计费保护。
- 原始付费结果先保留，再做可选 Yezi 抠图；抠图有独立凭证和并发/速率控制。存在原图时用“仅重试后处理”，不能误当作重新生图。生产没有 mock 开关，测试通过显式 provider/transport 注入。
- 访客媒体（含后台订单弹窗里的水印预览）以 WebP q90 输出（`guest_media.PIPELINE` 为缓存版本），原图、打印文件、下载和 ZIP 仍为 PNG。
- 水印分单张预览、访客媒体、已生成总览等路径；水印强度和缓存版本改变要分别核对，避免给已经带水印的总览再次叠加。原图与打印文件不能带预览水印。
- 默认打印 A4、300 DPI、内容长边 85mm、边距/间距 10mm；亮度与色彩预设默认关闭。透明通道、预乘 alpha 缩放和不可变原图需要保留。
- v3 打印标题为订单号加卖家备注（打印最多 60 字）。`platform_remark`、买家留言 `buyer_memo`、内部备注 `notes` 各有用途；修改已提交订单的卖家备注会重新排版，下载目录仍按 `订单号_内部备注` 规则。
- 打印文件整批原子发布，失败保留已有有效结果。后台下载清单和 ZIP 只包含最终打印拼图；仅在用户点击后写目录或下载。目录文件通过哈希、清单和归属保护，不能覆盖未经系统管理的同名文件。

## Agiso 接入边界

代码链路：验签接收 → `agiso_events` 持久化去重 → SKU/店铺/账号校验 → 复用开户函数 → `agiso_orders` 关联 → `agiso_outbox` 消息任务。消息发送和开户是不同状态，HTTP 成功不代表买家已经收到消息。

- topic `1` 为交易确认处理路径；付款后通知可接受空 `ConfirmTime`。`8/16/512` 走退款/售后族，`32` 发货通知仅记录，`64` 更新买家备注；未知 topic 会记录而非冒充处理成功。不要把 topic 编号与 operation 混用。
- 全部商品/SKU 必须匹配已启用规则；G/F 按购买数量累加，R 使用匹配规则一致的整单上限，不乘购买数量。未匹配、规则冲突、超额和订单号重复转人工，不能猜套餐或创建重复订单。
- 商品查询不可用时允许人工填写已核实的商品/SKU ID。错误码 17 有专门权限提示，不能把“列表为空”写成“店铺没有商品”。
- 自动开户依赖应用配置、有效店铺授权、开关和有效所属账号/组织。关闭店铺停止未来自动开户和消息，不直接中断已有正常订单制作。
- 售后开关为 `STUDIO_AGISO_AFTERSALES_VERIFIED`；启用后可处理此前因开关关闭而存下的退款。已验签的售后事实不因出站授权过期或店铺关闭而丢弃。
- 全额且类型明确的成功退款取消订单并撤销访客访问；部分、异常或未知类型交人工核对。退款撤回/关闭不能复活已经成功退款的订单；解除售后暂停不能清除原有人工暂停。
- 发送次数有上限；明确可重试失败与超时未知状态分别处理。发送中断后的未知结果不能自动补发，应先核对外部消息记录。
- `STUDIO_AGISO_ENCRYPTION_KEY` 加密店铺凭证，随意更换会导致旧凭证无法解密。账号授权、真实发信、售后和物流均不可用测试模拟冒充验收。

配置和外部条件见 [Agiso 指南](agiso-setup.md)；其中带日期的店铺、余额、服务有效期和助手在线记录均需重新确认。
