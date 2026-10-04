# FAL 从 OSS 取图实施与测试方案

日期：2026 年 10 月 5 日。状态：用户已确认做法，待执行；尚未实施、联调或部署。

执行者先读仓库根目录 `AGENTS.md` 及其导航文档。本方案建立在《打印文件迁移OSS完整方案》已上线的基础上（生产 `b8b6a41`，已有 `backend/app/oss_delivery.py`、RAM 角色 `sticker-ecs-oss`、Bucket `coreages-sticker`）。

## 〇 用户已确认的决定（2026-10-05）

| 决定 | 内容 |
| --- | --- |
| 做法 | 生图时不再把模板和头像 base64 塞进 FAL 请求体，改为 ECS 经内网把图片暂存到 OSS，把签名链接交给 FAL，由 FAL 自己去 OSS 取图 |
| 不开传输加速 | 使用 OSS 默认公网域名签名，不启用传输加速、CDN 或自定义域名 |
| 兼容全站 FAL 队列设置 | "最大同时处理数量""同时上传数量""上传超时"、账号并发上限、FAL 429 退避全部保留并继续生效 |
| 测试额度 | 真实 FAL 生图最多 30 张（含失败与异常测试），要测稳定性、速度，并给出更合适的队列上限建议 |

## 一 背景与依据（2026-10-05 实时核对）

- `backend/app/providers.py` 的 `FalProvider.submit` 把模板与头像编码为 `data:image/png;base64,...` 放进 POST 请求体。生产模板中位 1.2MB、头像中位 1.4MB，base64 后每次请求约 3.5MB，全部占用 ECS 3Mbps 出口。
- 之前实测 ECS 到 FAL 单连接上传约 188KB/s，一次提交约 19 秒；两个任务同时上传即可占满出口，拖慢访客页面。
- 云监控近 7 天：每天出网约 640MB，出口占满（≥2.7Mbps）合计 18 分钟，属于突发拥堵；10-04 生图 51 次约占当天出网三成。
- 现有队列设置（`backend/app/worker.py` 的 `claim`）：
  - `max_inflight`：全站同时占用 FAL 的任务数（默认 2，可设 1–40），包含已提交、在 FAL 排队的任务；
  - `max_uploads`：处于"提交中"（还没拿到 `fal_request_id`）的任务数（默认 3）；
  - `fal_upload_timeout`：POST 请求体写入超时（默认 300 秒）；
  - 账号级 `generation_limit` 与 `fal_retry_at`（429 退避）。
- 价格（官网刊例价）：OSS 外网流出忙时 0.50 元/GB、闲时 0.25 元/GB；内网免费；请求次数远低于免费额度。每次生图约 2.6MB，每月 1500 次约 3.9GB，约 2 元/月。

## 二 设计

### 总体流程（OSS 模式）

```text
worker 领取任务（队列设置照旧把关）
  → 计算模板/头像 sha256
  → OSS 内网 HEAD fal-inputs/<UTC日期>/<sha256>.png，不存在才上传（内网、免费）
  → 生成 2 小时有效的 GET 签名链接（公网域名，不带下载头）
  → POST 给 FAL：image_urls=[模板链接, 头像链接]，请求体约 2KB
  → 之后的 poll / result / 未知请求恢复完全沿用现有逻辑
```

### 关键规则

1. **对象路径**：`fal-inputs/<YYYYMMDD UTC>/<sha256>.png`。按天分目录、同一天内同一张图只上传一次（模板会被大量复用）。不含订单号、姓名、组织名。
2. **生命周期**：Bucket 加一条只作用于 `fal-inputs/` 前缀的规则，2 天后删除。临时副本最长存在约 3 天；本地原图不受影响。
3. **签名有效期**：新环境变量 `STUDIO_FAL_INPUT_URL_TTL`，默认 7200 秒，用于覆盖 FAL 排队时间。签名链接不写数据库、不进日志、不回传前端。
4. **提交失败分类不变**：
   - OSS 暂存失败发生在 POST 之前，FAL 必然没收到 → 本次提交**自动改用原来的 base64 方式**继续发送（同一次尝试内，不另外计数），并在 item 上记录 `fal_input='inline'` 与脱敏原因；不得标记为"结果未知"。
   - POST 阶段的错误分类（连接/写入失败 = 未送达、读取超时 = 未知、429 = 退避）保持现状。
   - 已有 `fal_request_id` 的任务恢复时只查原请求，不重新暂存、不重新签名、不重新提交。
5. **FAL 取图失败**：FAL 读不到链接时通常表现为任务完成但带错误。沿用现有 `fal_error` → `failed` 路径；测试中要确认 FAL 的实际返回格式和是否计费（见第四节 E1），再决定是否细化中文提示。
6. **队列设置兼容**：
   - `max_inflight`、账号并发、429 退避：语义不变。
   - `max_uploads`："提交中"现在包括"暂存到 OSS + 发送小请求"，仍按没有 `fal_request_id` 的 running 任务计数，代码不用改；含义从"上传到 FAL"变为"提交到 FAL"，界面和说明同步改文字。
   - `fal_upload_timeout`：仍限制 POST 写入（OSS 模式下请求体很小）；OSS 暂存用 SDK 自身超时（现有 `readwrite_timeout=30`、重试 3 次）。
7. **全站开关**：在 `config/settings` 新增 `fal_input_mode`，取值 `oss` / `inline`。超级管理员在"管理设置 → 全站并发"里切换，即时生效、无需发布。迁移默认值为 `inline`（上线后行为不变），测试通过后再切到 `oss`。OSS 未配置时强制 `inline`，界面置灰并说明原因。
8. **计时日志**（保留到测试之后，作为日常排障依据）：每次提交记录一行结构化日志，包含 item ID、`mode`（oss/inline/fallback）、各 OSS 对象是否复用、暂存耗时、POST 耗时、请求体字节数；poll 记录状态变化时间点（IN_QUEUE → IN_PROGRESS → COMPLETED）和 `queue_position`；结果下载耗时。不记录签名链接、密钥、订单号、头像内容。

### 代码改动

| 文件 | 改动 |
| --- | --- |
| `backend/app/oss_delivery.py` | `OSSStore` 新增 `sign_input(key, ttl)`：GET 预签名，不带 `response_content_disposition`；新增 `stage_fal_input(store, data) -> key`（sha256、按天前缀、HEAD 后按需上传、`Content-Type: image/png`） |
| `backend/app/providers.py` | `FalProvider.submit` 增加可选参数 `image_urls`；传入时用链接，否则维持 base64。返回 job 时附带实际使用的 `fal_input` 与计时数据 |
| `backend/app/worker.py` | `execute` 提交前按 `fal_input_mode` 决定是否暂存：在事务外暂存与签名，失败自动回退 inline；写计时日志；`checkpoint` 记录 `fal_input` |
| `backend/app/schemas.py`、`backend/app/main.py` 设置接口 | 新增 `fal_input_mode` 字段及校验，读写权限同现有全站设置（仅超级管理员） |
| `backend/app/db.py` | 迁移：设置中补 `fal_input_mode='inline'` |
| `frontend/src/pages/Settings.tsx`、`frontend/src/lib/types.ts` | 新增"生图图片传输方式"选择；"同时上传数量"改名为"同时提交数量"并改说明文字（字段名不变） |
| `deploy/production.env.example` | 新增 `STUDIO_FAL_INPUT_URL_TTL=7200` |
| `backend/content/staff-guide.json` | 更新"全站管理"相关段落、`version`、`updated_at`、维护记录 |
| `AGENTS.md`、`docs/architecture-and-contracts.md` | 补充契约：OSS 模式下模板与头像以 2 小时签名链接提供给 FAL，临时副本在 `fal-inputs/` 最长约 3 天后自动删除；切换开关不影响未知请求与重试语义 |
| `docs/agent-operations.md`、`deploy/README.md` | RAM 策略、生命周期规则、开关、计时日志字段、排障与回退 |

### 自动化测试（不调用真实 FAL）

- inline 模式下请求体与现在逐字节一致（回归保护）。
- OSS 模式：同一天同一张图只上传一次；不同日期前缀分开；请求体只含两个链接且不含 base64；签名有效期取自配置。
- 暂存失败自动回退 inline，item 记录 `fal_input='inline'`，状态不是 unknown。
- 已有 `fal_request_id` 的恢复路径不触发暂存与签名。
- `max_uploads`、`max_inflight`、账号并发、429 退避在两种模式下行为一致（复用现有队列测试，参数化两种模式）。
- 设置接口：仅超级管理员可改；OSS 未配置时拒绝设为 `oss`。
- 日志不含签名链接和密钥。
- 基础回归：`npm test`、`npm run build`、`npm run check:docs`。

## 三 阿里云侧配置

1. **RAM 策略**：为 `sticker-oss-access` 新建版本并设为默认，在第一条语句的 Resource 中加入 `acs:oss:*:*:coreages-sticker/fal-inputs/*`（HEAD 属于 GetObject 权限，无需列举权限）。先 `aliyun ram GetPolicy` 读出当前文档，在其基础上增加，不覆盖 `print/`、`backups/`、`selftest/`：

   ```bash
   aliyun ram CreatePolicyVersion --PolicyName sticker-oss-access --SetAsDefault true --PolicyDocument '<在当前文档基础上加入 fal-inputs/* 后的完整 JSON>'
   ```

   策略版本最多 5 个，超出时先删除最旧的非默认版本。
2. **生命周期规则**：先读出现有生命周期配置（PUT 会整体替换，现有规则必须原样保留）。目标规则：

   ```xml
   <LifecycleConfiguration>
     <Rule>
       <ID>fal-inputs-expire-2d</ID>
       <Prefix>fal-inputs/</Prefix>
       <Status>Enabled</Status>
       <Expiration><Days>2</Days></Expiration>
     </Rule>
   </LifecycleConfiguration>
   ```

   确认规则只匹配 `fal-inputs/`，不会影响 `print/` 与 `backups/`。
3. 不启用传输加速、CDN、自定义域名。CORS 不需要改（FAL 是服务端取图，不涉及浏览器跨域）。

## 四 真实测试（最多 30 张 FAL 生图）

### 4.1 测试环境与约束

- 在生产环境进行（只有生产 ECS 能走 OSS 内网，且要测真实出口）。生产现有订单均为测试数据，但测试期间仍可能有访客访问，所以测试订单单独建立并明确命名（如"FAL-OSS 测试 1005"），不动现有订单。
- 头像使用非客户的测试图（例如此前测试用过的合成头像），不要使用真实客户照片；尺寸与生产接近（约 1–2MB PNG）。模板从现有图库中选，至少覆盖 6 种不同模板，同时包含重复模板，用来验证同日复用。
- 记录测试前的全站设置（`max_inflight`、`max_uploads`、`fal_upload_timeout`、`fal_input_mode`）以及测试账号的 `generation_limit`。测试中按需调整，结束后恢复，或改为第五节得出的推荐值（推荐值需用户确认后再落地）。
- **额度账本**：每次向 FAL 发出的新请求都算 1 张，无论成功、失败还是被取消。维护一张逐条记录表，累计达到 30 立即停止。恢复类测试只查询原请求，不计张数。
- 每一批开始前确认 FAL 余额充足（后台余额查询），并确认没有其他在途任务（`deploy/queue_check` 或等价只读检查），避免和客户任务混在一起影响数据。
- 测试期间不改 ECS 配置，不重启无关服务；只有 E2 的重启属于计划内步骤，要事先确认没有访客正在操作。

### 4.2 每批都要采集的数据

| 指标 | 来源 |
| --- | --- |
| 提交阶段：暂存耗时、是否复用、POST 耗时、请求体大小、实际模式 | 计时日志 |
| FAL 阶段：提交 → IN_PROGRESS（排队时间）、IN_PROGRESS → COMPLETED（生成时间）、`queue_position` | 计时日志 |
| 结果下载耗时、总耗时（领取到 `postprocess` 完成） | 计时日志 |
| 成功率；失败原因分类（未送达 / 未知 / FAL 错误 / 取图失败 / 429） | item 状态与日志 |
| ECS 公网出口：每秒采样 | 测试期间在 ECS 上运行只读脚本，每秒读取 `/proc/net/dev` 中 `eth0` 发送字节差，写到临时文件；同时取云监控 `VPC_PublicIP_InternetOutRate` 1 分钟最大值作对照 |
| 访客侧影响 | 测试期间从外部每 2 秒请求一次站点上的一个约 300KB 前端静态文件（`frontend/dist/assets` 中选取），记录耗时。本机测试时确认 `route get 8.130.175.250` 不经过代理 TUN；如经过，在报告中注明 |
| FAL 计费 | 每批前后的 FAL 余额差，确认每张实际扣费，以及失败请求是否扣费 |

### 4.3 零成本预测试（不消耗生图额度）

| 编号 | 内容 | 通过标准 |
| --- | --- | --- |
| P1 | 在 ECS 上用新代码的暂存函数上传 20 张不同模板到 `fal-inputs/`，记录每张耗时；再次暂存同样 20 张，确认全部复用 | 内网上传 p95 < 2 秒；第二轮 0 次上传 |
| P2 | 对 P1 的对象生成签名链接，从本机和美国 DMIT 服务器各 `curl` 20 次（覆盖多个不同对象），记录耗时与速度（`-w` 输出连接、TLS、首字节、总耗时、平均速度）。DMIT：洛杉矶，`ssh -i ~/.ssh/DMIT-FYHzdVfT6I_id_rsa.pem root@179.253.232.80`，2026-10-05 已确认可登录、能连通 OSS 默认域名。只在 DMIT 上执行 `curl` 并把下载写到 `/dev/null`，不安装软件、不改配置，不碰 Xray、Cloudflare Tunnel 及其他服务；签名链接通过命令参数临时传入，不写入 DMIT 上的文件或 shell 历史（如用 `HISTFILE=/dev/null`）。不要使用 Vultr 服务器 | 全部 200；记录海外中位/p95 下载时间，作为 FAL 取图耗时的参考 |
| P2b | 在 DMIT 上用 4 个并发连接同时下载 P1 的不同对象，重复 5 轮 | 全部 200；记录并发时单连接速度是否明显下降，用于判断 C1/C2 批高并发时 FAL 取图是否会变慢 |
| P3 | 签名有效期：生成 60 秒链接，到期后访问 | 返回 403 |
| P4 | 未签名访问对象、访问 `print/` 下对象 | 均被拒绝 |
| P5 | 生命周期规则读回 | 只有 `fal-inputs/` 规则，其他前缀不受影响 |

### 4.4 生图测试批次（合计 30 张）

批次之间间隔至少 5 分钟，让出口曲线回落，便于区分。

| 批次 | 模式 | `max_inflight` / `max_uploads` | 张数 | 目的 |
| --- | --- | --- | --- | --- |
| A 基线 | inline | 2 / 3（现值） | 6 | 记录现状：提交耗时、出口占满时长、访客侧延迟 |
| B 对照 | oss | 2 / 3 | 6 | 与 A 同条件对比；第 1 张单独先跑，确认 FAL 能从 OSS 取图后再放其余 5 张 |
| C1 加压 | oss | 4 / 4 | 6 | 观察更高并发下 FAL 排队时间、429 与出口 |
| C2 加压 | oss | 8 / 8 | 8 | 找 FAL 账号并发上限：出现 429 或排队时间明显增长即为上限信号；出现 429 立即停止该批剩余提交（未发出的不计张数） |
| E1 取图失败 | oss | 1 / 1 | 1 | 用已过期的签名链接提交（测试专用开关或脚本，生产代码不保留该后门），记录 FAL 的返回格式、任务状态、是否扣费，确认网站显示为可重试的失败，不是"结果未知" |
| E2 重启恢复 | oss | 2 / 2 | 2 | 两张提交后、FAL 尚在排队或生成时重启服务；确认重启后用原 `fal_request_id` 取回结果，没有重复提交，额度账本不增加 |
| 预留 | — | — | 1 | 任一批出现需要复测的偶发问题时使用；不用则不发 |
| **合计** | | | **30** | |

每批同时上传若干头像、选不同模板，确保一批内有并发；B 批和 C 批里至少有 2 张使用同一模板，以验证同日复用。

如果 B 批第 1 张取图失败：停止全部 OSS 批次，`fal_input_mode` 切回 `inline`，整理 FAL 返回信息向用户报告，不要自行启用传输加速或换域名。

### 4.5 通过标准

- OSS 模式成功率 100%（E1 是预期失败除外）；不出现因暂存导致的 unknown；回退 inline 的次数和原因全部有记录。
- 提交阶段（领取到拿到 `fal_request_id`）中位耗时比 A 批明显下降（预期从十几秒降到 2 秒以内）。
- 总耗时中位不劣于 A 批；若 FAL 取图让排队或生成时间变长，要在报告中量化。
- OSS 模式下生图期间 ECS 出口不再出现持续数秒的满载平台；访客侧静态文件耗时没有 A 批那样的尖峰。
- E2 无重复提交、无额外扣费；E1 显示为可重试的失败。
- 每张扣费与 inline 一致（OSS 取图不应改变 FAL 计费）。

## 五 队列上限建议的得出方法

根据 B、C1、C2 的数据给出推荐值，交用户确认后再在"管理设置"中修改：

1. **`max_inflight`**：取没有出现 429、成功率 100%、单张总耗时中位不超过 B 批 1.5 倍的最高档。若 C2 出现 429，推荐值取 C1 档或"429 出现时的在途数减 1"中较小者，并在报告中写明 FAL 账号的实际并发上限证据。
2. **`max_uploads`（同时提交数量）**：OSS 模式下提交很轻，建议等于 `max_inflight`；若数据表明暂存或 POST 有排队，再取较小值。
3. **`fal_upload_timeout`**：OSS 模式下请求体很小，若 POST 耗时 p99 远小于 30 秒，可建议调到 60 秒，让真正的网络故障更早被判为未送达；inline 回退时仍要足够长，因此不低于"3.5MB ÷ 实测最差上传速度"的 2 倍。两者冲突时保持 300 秒。
4. **账号并发 `generation_limit`**：报告当前各账号的值；若低于推荐的 `max_inflight`，说明全站上限实际被账号上限截断，由用户决定是否调整。
5. **`STUDIO_FAL_INPUT_URL_TTL`**：若 C2 中最长排队时间超过 TTL 的一半，建议加长；否则保持 7200 秒。

## 六 报告格式

测试结束后在本目录新建 `FAL从OSS取图测试报告.md`，包含：

- 测试环境、提交版本、测试前后的设置值；
- 额度账本（逐条：批次、模式、模板、开始时间、结果、是否扣费），总计不超过 30；
- 每批的指标表（中位 / p95 / 最大值）与 ECS 出口曲线摘要（满载秒数、峰值）；
- A 与 B 的对比结论；C1、C2 的并发结论；E1、E2 的结论；
- 第五节的推荐设置值及依据；
- 未验证项与风险。

报告中不得出现签名链接、密钥、订单号、头像图片或客户信息。

## 七 部署与回退

1. 按 `docs/agent-operations.md` 第 6 节发布：只读队列检查、审计基线、停服、完整备份并核验、原子切换、启动、`/api/ready`、审计对比；发布后执行备份归档与保留 3 份清理。
2. 上线时 `fal_input_mode=inline`，先确认行为与上线前一致（可以合并到 A 批基线）。
3. 完成第三节阿里云配置与 4.3 预测试后，再按 4.4 测试。
4. 全部通过且用户确认后，`fal_input_mode` 设为 `oss`，并按用户确认的推荐值调整队列设置。
5. 回退：出现问题时在"管理设置"切回 `inline` 即可，不需要发布；已提交的任务按原 `fal_request_id` 继续，不受影响。只有代码本身有问题时才回滚 release。

汇报时分开说明：计划、已生成、已保存、本地验证、已部署、公网验收、真实 FAL 测试结果。本地 mock 通过不能写成 FAL 已能从 OSS 取图。

## 八 不做的事

- 不启用 OSS 传输加速、CDN、自定义域名。
- 不改 ECS 配置。
- 海外测试只用 DMIT，且只运行 `curl`；不使用 Vultr 服务器。
- 不改变未知请求占用、重试次数、整单重试上限等既有语义。
- 不把签名链接写入数据库、日志、前端或报告。
- 不超过 30 张真实生图；不使用真实客户头像测试。
- 不在未经用户确认时把推荐队列值写入生产设置（测试期间的临时调整除外，测试后恢复）。
