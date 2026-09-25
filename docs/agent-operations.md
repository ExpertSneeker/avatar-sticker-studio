# Agent 运维与验证交接

本文依据 2026-09-26 的源码与现有文档整理，是操作索引，不是线上状态报告。后续代码变化时应重新核对下列链接。本次实际运行的测试及范围见[交接记录](agent-handoff.md)。

## 1. 接手范围与证据

- 先读 [AGENTS.md](../AGENTS.md)，用 `git status --short` 确认并行改动；不要还原、暂存或提交其他 Agent 的文件。测试、构建和发布应协调端口、工作目录及产物归属。
- 本文仅维护运维与验证知识。功能、权限、入口、状态或恢复行为变化仍须同步 [后台使用说明](../backend/content/staff-guide.json) 的实际章节、版本、日期及维护记录，规则由 AGENTS.md 定义。
- [组织框架发布说明](../deploy/framework-release.md) 是升级、备份和回退的操作入口；[部署说明](../deploy/README.md) 提供运行布局。当前 `deploy/` 只有两个审计 `.py` 和服务/环境模板，**没有 `.sh` 一键发布脚本**。不要猜测脚本名或从历史会话拼装发布脚本。
- [框架验收记录](framework-verification.md)、[图库发布记录](public-library-release.md)、[验证记录](verification.md)、[Agiso 配置记录](agiso-setup.md) 中的日期、提交、测试数量、账号和第三方状态都是历史证据，不能证明当前线上版本、余额、授权、备份或服务健康。
- 报告分别写清：源码核实、隔离本地验证、真实第三方联调、生产部署与公网验收；不要将 mock 成功或历史记录写成已上线接通。

## 2. 依赖、入口与配置名

依赖来源：[根 package.json](../package.json)、[pyproject.toml](../pyproject.toml)、[uv.lock](../uv.lock)、[前端 package.json](../frontend/package.json)、[前端锁文件](../frontend/package-lock.json)。

| 项目 | 当前文件约束与注意点 |
| --- | --- |
| Python | `>=3.12,<3.14`；本地 setup 指定 3.12，部署说明记录服务器使用 3.13，不代表已检查当前服务器。 |
| Node/npm | 可选 Node 22.12+ 的 22.x；锁文件中 Vitest 的 engines 是 `^22.12.0 || ^24.0.0 || >=26.0.0`，并非所有高于 22 的版本都在范围内。需要 npm、uv。 |
| 后端 | FastAPI、Uvicorn、HTTPX、Pillow、NumPy、Pydantic、cryptography；pytest 属于 dev 依赖组。 |
| 前端 | React、Vite、TypeScript、Vitest、Playwright；构建执行 `tsc -b && vite build`。 |
| 字体 | 水印/打印需要支持实际文字的字体；[processing.py](../backend/app/processing.py) 检查字形，缺少中文字体会失败，不能以方框文字验收。 |
| 浏览器 | macOS 检测到 `/Applications/Google Chrome.app` 时默认 Chrome，否则 Chromium；可用 `STUDIO_TEST_BROWSER` 指定已安装通道。安装浏览器需要另行准备，禁止联网时不要自动下载。 |

### 启动器不是沙盒

[scripts/studio.mjs](../scripts/studio.mjs) 在区分模式前就尝试加载根目录 `.env`，子进程继承进程环境；它没有自动清除凭证。

| 命令 | 实际行为 |
| --- | --- |
| `npm run setup` | 加载 `.env` 后执行 `uv sync --python 3.12` 和 `npm ci --prefix frontend`；可能联网安装依赖、改变依赖目录，不启动应用。 |
| `npm start` | 加载 `.env`、构建前端，启动 `backend.app.main:app_factory`；这是可处理真实业务的应用入口，不是 mock 或静态预览。仅监听 loopback，不会因此自动部署到远端。 |
| `npm run dev` | 同一个真实后端，加 Vite `127.0.0.1:5173`；前端代理到后端。没有 Uvicorn `--reload`，改后端需重启。 |
| 直接运行 `app_factory` | 不经过 Node 启动器的 `.env` 加载，但仍读取进程环境、初始化数据库并启动 worker；直接 `uv run` 还应避免继承 `UV_ENV_FILE`。 |
| `npm test` | 顺序执行说明同步检查、`uv run pytest -q`、前端 Vitest；不含构建与 E2E。 |
| `npm run test:e2e` | 使用 [Playwright 配置](../frontend/playwright.config.ts) 启动独立测试后端和 Vite，不走根目录的启动器。 |

“`npm start` 开启生产”应理解为启动真实业务能力；代码没有通过该命令设置一个 `STUDIO_ENV=production` 开关。默认数据目录是仓库 `.data`，如果其中已有正式数据和密钥，启动即可能恢复队列、产生网络请求及费用。

### 配置名与读取位置

只查 [.env.example](../.env.example) 和 [production.env.example](../deploy/production.env.example)，不要 `cat .env`、打印整个进程环境或复制服务器环境文件到聊天。

| 配置名 | 作用与边界 |
| --- | --- |
| `STUDIO_DATA_DIR` | [main.py](../backend/app/main.py) 的私有数据库/文件根目录；未指定时 `.data`。测试使用独立临时目录，部署保留正式数据目录。 |
| `STUDIO_PORT` | 仅本地启动器读取，默认 8000，校验 1024–65535；直接 Uvicorn 和 systemd 的端口由命令行决定。 |
| `STUDIO_API_PROXY` | [vite.config.ts](../frontend/vite.config.ts) 的 `/api` 代理目标，默认 `http://127.0.0.1:8000`；误指正式服务会让页面操作落到真实数据。 |
| `STUDIO_ALLOWED_HOSTS` | 默认 `localhost,127.0.0.1,::1,testserver`；逗号分隔。不要用放开全部主机来掩盖代理错误。 |
| `STUDIO_ALLOWED_ORIGINS` | 默认本机 5173/8000 的 localhost 与 127.0.0.1；修改请求还接受当前受信任请求自身的 origin。字符串拆分没有去除空格。 |
| `STUDIO_SECURE_COOKIE` | 值为 `1` 时要求 HTTPS Cookie；本地 HTTP 测试勿继承生产值。 |
| `STUDIO_ALLOW_SETUP` | `0` 禁止首次管理员设置；测试需允许空库初始化。正式模板为 `0`。 |
| `STUDIO_FONT` | 字体文件路径；未设置时按源码候选检测。 |
| `FAL_KEY` / `YEZI_API_KEY` | 环境优先，其次数据库 `fal_api_key` / `cutout_api_key`。仅 unset 环境变量不能使正式数据库变安全。 |
| `STUDIO_AGISO_APP_ID` / `STUDIO_AGISO_APP_SECRET` / `STUDIO_AGISO_ENCRYPTION_KEY` / `STUDIO_AGISO_PUBLIC_URL` | [agiso_protocol.py](../backend/app/agiso_protocol.py) 读取；public URL 要求 HTTPS 根地址。加密密钥必须随配置安全保留，变更会影响旧凭证解密。 |
| `STUDIO_AGISO_AFTERSALES_VERIFIED` | 仅 `1` 开启售后处理条件；模板为 `0`。不得用旧验收记录认定当前可开启。 |
| `STUDIO_E2E_FRONTEND_PORT` / `STUDIO_E2E_BACKEND_PORT` | Playwright 默认 5174/8001；存在下文所述的部分端口硬编码。 |
| `STUDIO_TEST_BROWSER` | Playwright 浏览器通道，不是模型开关。 |

## 3. 数据隔离与无费用本地命令

### 必须先理解的副作用

[Database](../backend/app/db.py) 构造时会创建目录、改权限、建立表、写默认配置并执行迁移，包括个人积分、共享重试、公共图库、图库状态和组织迁移。`transaction()` 使用 WAL 和 `BEGIN IMMEDIATE`，不是只读事务。

[create_app](../backend/app/main.py) 立即构造 Database；即使 `start_worker=False`，进入 lifespan 时仍执行 [drain_cleanup](../backend/app/maintenance.py)，可能删除已有清理队列中的文件。默认 lifespan 同时启动生成 Worker 和 AgisoWorker。**不要用启动应用、TestClient 或 `Database(正式路径)` 做只读诊断。**

生成 mock 通过 `create_app(..., provider=...)` 注入。生产入口没有 `MOCK=1`、`STUDIO_MOCK` 或通用模型切换环境变量。新请求的 FAL 模型地址写在 [providers.py](../backend/app/providers.py) 中；[模型切换测试](../backend/tests/test_providers.py) 验证旧请求继续使用已保存的队列 URL，不因切换模型重新提交。

[browser_app.factory](../backend/tests/browser_app.py) 自行创建 `TemporaryDirectory`，注入输出 1024×1024 RGBA 的 `BrowserTestProvider`，并把测试并发设为 8；它不采用传入环境中的数据目录。mock 生图不等于 mock 全部外部服务：它没有为 Agiso 注入 HTTP transport，必须清空真实 Agiso 配置，且只使用新建的测试库。

### 本地安全环境

以下命令从仓库根目录运行，前提是依赖与测试浏览器已安装。测试会生成临时数据和构建产物。跨机器操作使用实际 checkout 路径，不依赖原作者机器上的绝对目录。

在同一终端定义包装函数，隔离已知业务配置。`STUDIO_AGENT_TMP` 使用本次 `mktemp` 创建的目录；同时检查自定义前端 `.env*` 是否改写 API 代理，测试不能指向真实服务。

```sh
# 在本机实际的仓库根目录执行。
umask 077
STUDIO_AGENT_TMP="$(mktemp -d "${TMPDIR:-/tmp}/sticker-agent-ops.XXXXXX")"
export STUDIO_AGENT_TMP

studio_safe() (
  test -n "${STUDIO_AGENT_TMP:-}" && test -d "$STUDIO_AGENT_TMP" || exit 2
  unset STUDIO_FONT
  unset STUDIO_API_PROXY STUDIO_PORT STUDIO_TEST_BROWSER
  unset STUDIO_E2E_FRONTEND_PORT STUDIO_E2E_BACKEND_PORT
  unset UV_ENV_FILE UV_PROJECT_ENVIRONMENT VIRTUAL_ENV PYTHONPATH NODE_OPTIONS
  export STUDIO_DATA_DIR="$STUDIO_AGENT_TMP/data"
  export STUDIO_ALLOWED_HOSTS='localhost,127.0.0.1,::1,testserver'
  export STUDIO_ALLOWED_ORIGINS='http://127.0.0.1:5174'
  export STUDIO_SECURE_COOKIE=0 STUDIO_ALLOW_SETUP=1
  export UV_NO_ENV_FILE=1
  env -u FAL_KEY -u YEZI_API_KEY \
    -u STUDIO_AGISO_APP_ID -u STUDIO_AGISO_APP_SECRET \
    -u STUDIO_AGISO_ENCRYPTION_KEY -u STUDIO_AGISO_PUBLIC_URL \
    STUDIO_AGISO_AFTERSALES_VERIFIED=0 "$@"
)
```

该函数是清除已知业务配置的操作约束，不是操作系统网络沙盒。无费用依靠下列已核实的测试入口、mock 与全新数据；不要把任意业务命令包进去就声称安全，尤其不要运行会重新加载 `.env` 的 `npm start` / `npm run dev` / `npm run setup`。

依赖缺失时可使用锁文件安装；避免与其他 Agent 对共享依赖目录的更新并行。下面的命令不会启动应用，但可能联网下载依赖。如任务要求离线，分别加 `--offline`，缓存不足时报告缺失项。常规 `npm run setup` 和生产依赖导出见[启动器](../scripts/studio.mjs)与[部署说明](../deploy/README.md)。

```sh
studio_safe uv sync --frozen --python 3.12
studio_safe npm ci --no-audit --no-fund --prefix frontend
```

### 常用本地验证

```sh
studio_safe npm run check:docs
studio_safe .venv/bin/python -B -m pytest -q -p no:cacheprovider backend/tests
studio_safe npm test --prefix frontend
studio_safe npm run build
```

后端测试的 [API 夹具](../backend/tests/test_api.py)、[Worker 夹具](../backend/tests/test_worker.py) 使用 `tmp_path`、显式 provider/clock 和受控 worker；[provider 测试](../backend/tests/test_providers.py) 使用 `httpx.MockTransport`，[Agiso 测试](../backend/tests/test_agiso.py) 使用虚构配置及注入 transport。新增测试应继续遵守，不要让未替换的网络客户端接触真实凭证。

构建会重写 `frontend/dist` 和 TypeScript 增量产物，pytest/浏览器也会产生临时产物；“不改业务数据”不等于“完全不写文件”。仅文档改动通常做说明检查、链接及格式检查即可，不必启动服务。跨提交的说明检查使用实际基础引用：`npm run check:docs -- --base <实际基础提交或分支>`，占位符需替换；该检查只判断文件是否同步修改，不能验证正文语义。

### 浏览器与交互演练

先只检查监听端口，不结束任何已有进程；`lsof` 无输出且退出 1 通常表示该端口没有监听者。

```sh
lsof -nP -iTCP:5174 -sTCP:LISTEN
lsof -nP -iTCP:8001 -sTCP:LISTEN
studio_safe npm run test:e2e
```

- 完整回归可用根脚本，但专项参数直接交给前端脚本。主线程实测根目录 `npm run test:e2e -- --grep '…'` 在嵌套 npm 转发时丢失 `--`，Playwright 把值当位置参数后报 `No tests found`。不要把该错误解释成项目没有测试，也不要去掉筛选后无意执行全套。
- 当前 [Playwright 配置](../frontend/playwright.config.ts) 的两个 `reuseExistingServer` **均为 `false`**，Vite 还用 `--strictPort`。端口占用应失败，不要为了通过而改成复用服务器；测试含真实 HTTP 增删操作，例如 [清理场景](../frontend/e2e/studio.spec.ts)，指错服务会删除数据。
- 虽然配置支持改端口，[customer-orders.spec.ts](../frontend/e2e/customer-orders.spec.ts)、[customer-selection-limit.spec.ts](../frontend/e2e/customer-selection-limit.spec.ts) 仍有 `http://127.0.0.1:5174`，browser_app 也把 allowed origin 固定为该地址。全套测试优先保留默认端口；占用时协调使用空闲环境，不能只改变量后假定全套都会跟随。固定 origin 是否导致拒绝还取决于请求自身 origin，不应一概判定改端口必然 403。
- 配置 `workers: 1`，同一轮测试共用一个临时应用库；不要随意加并发。硬编码截图目录 `/tmp/avatar-studio-fal-qa` 也由多轮共享，不宜并行全套运行；历史截图不能当作本轮证据。
- `trace: retain-on-failure` 会保留失败 trace。仅用合成头像/虚构账号；截图、trace、请求体、Cookie 和下载清单都可能包含业务信息，不能把生产浏览器会话接到测试。

专项示例仍经过上面的 `studio_safe`，实际以 `env -u` 去掉 FAL、Yezi 和四个 Agiso 配置，再运行前端脚本：

```sh
studio_safe npm --prefix frontend run test:e2e -- e2e/staff-guide.spec.ts
studio_safe npm --prefix frontend run test:e2e -- --grep '后台可阅读和搜索说明'
```

如只需手动看 mock 页面，先确认默认两端口空闲，再在两个终端中各定义上述包装函数并执行对应命令。后端退出后临时库通常由 atexit 清理；不要把它当持久环境。

```sh
# 终端 A：仅测试工厂，不换成生产 app_factory。
studio_safe .venv/bin/python -B -m uvicorn \
  backend.tests.browser_app:factory --factory \
  --host 127.0.0.1 --port 8001 --no-access-log

# 终端 B：仅指向上面的测试后端。
studio_safe env STUDIO_API_PROXY=http://127.0.0.1:8001 \
  npm run dev --prefix frontend -- --port 5174 --strictPort
```

打开 `http://127.0.0.1:5174`，只用虚构账号和测试素材。该手动服务与 Playwright 不能同时占用端口；结束自己启动的服务后再跑 E2E。

## 4. 按变更选择测试

在上述安全环境中，用 `studio_safe .venv/bin/python -B -m pytest -q <测试文件>`、`studio_safe npm test --prefix frontend -- <测试文件>`、`studio_safe npm --prefix frontend run test:e2e -- <spec 文件>` 选择场景；尖括号占位符需替换为实际相对路径，前端 spec 路径从 frontend 起算。改运行入口、迁移、授权或共享 worker 时，应在定向验证后做完整后端、前端、构建及 E2E；下面是起点，不是穷尽清单。

| 变更范围 | 后端起点 | 前端/浏览器起点 |
| --- | --- | --- |
| 认证、组织、账号失效、跨标签页 | [test_api.py](../backend/tests/test_api.py)、[test_organizations.py](../backend/tests/test_organizations.py)、[test_account_deletion.py](../backend/tests/test_account_deletion.py) | [z-modal-accounts](../frontend/e2e/z-modal-accounts.spec.ts)、[z-user-deletion](../frontend/e2e/z-user-deletion.spec.ts)、[customer-orders](../frontend/e2e/customer-orders.spec.ts) |
| 使用说明/入口/文档授权 | [test_staff_guide.py](../backend/tests/test_staff_guide.py)、说明同步检查 | [staff-guide](../frontend/e2e/staff-guide.spec.ts)；额外检查产物无私有正文 |
| 访客订单、重试额度、提交/取消/解锁 | [test_customer_orders.py](../backend/tests/test_customer_orders.py)、[test_framework_acceptance.py](../backend/tests/test_framework_acceptance.py) | [customer-orders 单测](../frontend/tests/customer-orders.test.ts)、[customer-orders E2E](../frontend/e2e/customer-orders.spec.ts)、[selection-limit](../frontend/e2e/customer-selection-limit.spec.ts)、[picker-scroll](../frontend/e2e/customer-picker-scroll.spec.ts) |
| 生图、恢复、模型迁移、并发、公平性 | [test_providers.py](../backend/tests/test_providers.py)、[test_worker.py](../backend/tests/test_worker.py)、[test_deployment.py](../backend/tests/test_deployment.py)、[test_account_concurrency.py](../backend/tests/test_account_concurrency.py)、[test_fair_scheduling.py](../backend/tests/test_fair_scheduling.py)、[test_credits.py](../backend/tests/test_credits.py) | [z-user-concurrency](../frontend/e2e/z-user-concurrency.spec.ts)、客户订单 E2E |
| 图库、模板版本、删除/混合选择 | [test_library.py](../backend/tests/test_library.py)、[test_library_management.py](../backend/tests/test_library_management.py)、[test_library_deletion.py](../backend/tests/test_library_deletion.py)、[test_library_status_retirement.py](../backend/tests/test_library_status_retirement.py)、[test_mixed_stickers.py](../backend/tests/test_mixed_stickers.py)、[test_variable_templates.py](../backend/tests/test_variable_templates.py) | [library](../frontend/tests/library.test.tsx)、[templates](../frontend/tests/templates.test.tsx)、[z-library-management](../frontend/e2e/z-library-management.spec.ts)、[z-public-mixed](../frontend/e2e/z-public-mixed.spec.ts)、[z-variable-templates](../frontend/e2e/z-variable-templates.spec.ts) |
| 拼版、水印、预览、导出 | [test_processing.py](../backend/tests/test_processing.py)、[test_previews.py](../backend/tests/test_previews.py)、客户订单/框架验收测试 | [preview](../frontend/tests/preview.test.ts)、[image-preview](../frontend/tests/image-preview.test.tsx)、[sync](../frontend/tests/sync.test.ts)、客户订单 E2E；另做中文/透明边缘/桌面与手机视觉核验 |
| 上传及恢复 | API 测试、客户订单测试 | [image-upload](../frontend/e2e/image-upload.spec.ts)、[orders](../frontend/tests/orders.test.ts) |
| Agiso 授权、推送、套餐、退款、消息 | [test_agiso.py](../backend/tests/test_agiso.py)，确认 transport 已 mock | [agiso 单测](../frontend/tests/agiso.test.ts)、[agiso-entry](../frontend/e2e/agiso-entry.spec.ts)、[agiso-shops](../frontend/e2e/agiso-shops.spec.ts)、[shop-filter](../frontend/e2e/customer-shop-filter.spec.ts) |
| 数据清理、迁移、审计、启动就绪 | [test_cleanup.py](../backend/tests/test_cleanup.py)、[test_library_cleanup.py](../backend/tests/test_library_cleanup.py)、[test_framework_audit.py](../backend/tests/test_framework_audit.py)、[test_library_audit.py](../backend/tests/test_library_audit.py)、[test_import_a1.py](../backend/tests/test_import_a1.py)、[test_deployment.py](../backend/tests/test_deployment.py) | [studio](../frontend/e2e/studio.spec.ts)、[z-user-deletion](../frontend/e2e/z-user-deletion.spec.ts) |
| 统计 | [test_statistics.py](../backend/tests/test_statistics.py) | [zz-statistics](../frontend/e2e/zz-statistics.spec.ts) |

目录选择器测试使用 OPFS 夹具，不能证明真实目录授权、Safari 或打印机输出可用；相关人工验收需单列。`test_credits.py` 等名称含历史术语，不代表当前功能仍实行积分收费。

## 5. 审计脚本怎么用、不能证明什么

| 工具 | 已核实行为及限制 |
| --- | --- |
| [audit_framework.py](../deploy/audit_framework.py) | 必须给 `--data-dir`；SQLite `mode=ro`，输出完整性结果、数量、记录/原图哈希、queued/inflight 与 failures，不启动 worker。还会读取资产文件；只读不等于无隐私接触。 |
| 同脚本 `--rehearse` | 通过 SQLite backup API 复制到临时库，在副本上两次 `Database(...)`，从源 assets 读原图验证；不迁移源数据库，不提交模型任务。不能和 `--baseline` 同用。 |
| 同脚本 `--baseline` | 对比历史记录与资产哈希，只豁免代码中明确列出的组织/用户/生成状态字段。合法的新迁移也可能超出旧豁免范围，失败时审查差异，不删检查或直接认可。 |
| [audit_public_library.py](../deploy/audit_public_library.py) | 历史图库/A1 审计；默认指向 `/var/lib/avatar-sticker-studio`，必须显式给隔离路径。输出还包含模板名/code/ID，并非只有匿名计数。它按全局检查模板 code，且直接访问旧订单 `avatar_id`，不能视为通用组织/多头像订单审计器。 |

两个脚本都不是备份脚本，也不检查远端模型、Agiso 权限/余额、消息送达、代理配置或完整授权矩阵。framework 的 inflight 主要覆盖 items 的 running/unknown、remote_reserved、cutout_inflight；**不会因此证明 Agiso 待处理事件/outbox 已排空**。

`--rehearse` 的输出没有顶层 integrity，当前退出码判断也不会直接检查嵌套的 `source.integrity` / `migrated.integrity`；应人工/受控检查器同时核对它们为 `ok`、`idempotent` 为 true、failures 为空。演练通过不代表全部业务数据的任意迁移都兼容。

以下仅在新建合成库上演示命令结构，不借用客户数据。`Database` 在这里的写入是明确限定到新建临时目录的初始化：

```sh
studio_safe .venv/bin/python -B - <<'PY'
import os
from pathlib import Path
from backend.app.db import Database
root = Path(os.environ['STUDIO_AGENT_TMP']) / 'audit-fixture'
if root.exists():
    raise SystemExit('停止：夹具目录已存在，请创建新的独立临时目录。')
Database(root)
PY
studio_safe .venv/bin/python -B deploy/audit_framework.py \
  --data-dir "$STUDIO_AGENT_TMP/audit-fixture" > "$STUDIO_AGENT_TMP/baseline.json"
studio_safe .venv/bin/python -B deploy/audit_framework.py \
  --data-dir "$STUDIO_AGENT_TMP/audit-fixture" --rehearse
studio_safe .venv/bin/python -B deploy/audit_framework.py \
  --data-dir "$STUDIO_AGENT_TMP/audit-fixture" \
  --baseline "$STUDIO_AGENT_TMP/baseline.json"
```

实际迁移兼容性应使用经授权、私密保管的数据副本；不要启动该副本的生产 worker，副本仍可能带真实密钥、FAL 请求 ID、Agiso 凭证与发送队列。不要把 SQLite `.dump`、完整 records、图片或审计 JSON 粘贴到公共输出。

## 6. 部署前检查、备份、切换与回滚

本节适用于包含生产发布的任务。实际命令使用 [framework-release.md](../deploy/framework-release.md)、[deploy/README.md](../deploy/README.md)、[systemd 单元](../deploy/avatar-sticker-studio.service)，避免维护第二份整段发布脚本。

1. **准备可追溯产物。** 记录候选 revision、实际改动、测试/构建结果、迁移及兼容性结论。使用锁定依赖，源码与 `frontend/dist` 成对进入新 release，私有数据和环境配置不进入发布包。仅 `git rev-parse HEAD` 不能证明包含未提交改动的包对应该提交。
2. **确认目标布局及唯一服务。** 文件描述为 `/opt/avatar-sticker-studio/releases/<commit>`、`current` 链接、独立 venv 和 `/var/lib/avatar-sticker-studio`。unit 以 `sticker` 运行，固定 127.0.0.1:8000、`--workers 1`，从 `/etc/avatar-sticker-studio.env` 读取配置，关闭 access log。这些是配置契约，需在授权部署时核对当前主机；不要新增 worker、公共端口或改动共享 Tunnel。
3. **排空并冻结写入。** 核对 queued/running/unknown、远端预留及不确定抠图，停止接收新请求，按现有流程停止唯一服务，再次检查队列。若窗口内有新任务，返回旧版本排空/核对，不直接迁移。另核对 Agiso pending/claimed/sending/unknown；单停 worker 不等于外部推送停止，不能丢弃或盲目重放通知。
4. **完整且配对的备份。** 在服务停止后，按发布文档保存完整私有数据目录、审计基线及旧 release，备份目录 0700，文件按私密权限管理；验证数据库完整性、资产引用和原图哈希，不能只看大小。SQLite WAL 不能只拷一个运行中的主 DB 文件。环境中的加密密钥属于恢复依赖，单独安全保留，不能进入 Git/日志。
5. **演练与真实迁移分开。** 先审计/副本演练，再由发布操作者按文档在正式目录初始化新 Database；这是写库步骤。不得使用本地数据库覆盖线上。创建独立超管的 [bootstrap.py](../backend/app/bootstrap.py) 也会构造 Database；`--generate-password` 把密码写到 stdout，必须进入私密凭证文件，不能共享终端日志。现有同名账号不能覆盖。
6. **按文档原子切换并启动。** 保留旧 release 与配对备份。A1 导入是单独数据变更，不是每次部署步骤；[import_a1.py](../backend/app/import_a1.py) 的多组织导入需要 `--organization-id`，现有发布文档的旧命令不包含它。每次执行前核实目标组织、原图及碰撞检查。
7. **完成下一节的上线验收后交付。** 不通过真实生图、真实开单或真实发送消息做自动 smoke test。

回滚边界：切换 `current` 并重启只回滚代码，不回滚业务数据。迁移到组织框架后，旧代码不理解新角色和客户订单模型，不支持简单回到框架前版本。尚未接收新业务时，按已有文档停服并恢复配对数据/资产备份与旧 release；一旦接收新订单或产生新结果，应保留新数据，选择向前修复或专门审查的数据对账。不得把旧库覆盖到新客户提交之上。

部署说明记载未配置定时/异地备份；这不是当前主机的实时审计结论，也不授权 Agent 自行安装备份定时任务。不要把已有 release 目录、预览缓存或单次审计报告当作完整备份。

## 7. 上线验证与不收费排障

### 验证项目

- 核对候选 revision、release 内容/构建哈希、`current` 指向和实际进程工作目录/版本证据；不能只看本地 Git 或链接已经切换。
- 核对本机 `/api/ready` 及公网入口；[main.py](../backend/app/main.py) 中 `/api/health` 仅返回常量，不能代表数据库或 worker 正常。ready 检查配置、当前生成 worker 的 loop/lease task 和租约，**不验证 FAL 凭证、Agiso worker/消息或 CDN 行为**。
- 在已授权的受控会话验证后台账号及组织隔离，未登录/访客不能读取后台说明、原图、manifest；账号停用/会话过期后仍要拒绝。不要用隐藏菜单代替接口拒绝测试。
- 核对访客媒体水印、旧媒体链接失效及 `no-store`，后台说明 `private, no-store`；不要把私有资产目录暴露为静态目录或将认证资源放入共享 CDN 缓存。预览的 304 也必须先鉴权，见 [previews.py](../backend/app/previews.py) 与 [预览测试](../backend/tests/test_previews.py)。
- 抽查被授权访问的历史原图哈希与审计基线、既有记录完整性、服务错误和资源约束。公网 UI、原图一致性、第三方送达是不同证据，逐项写结果和未验证项。

下面的 HTTP 示例仅对已经启动的本地合成测试服务，不访问公网、不带订单号或 Cookie：

```sh
curl --noproxy '*' --fail --silent --show-error http://127.0.0.1:8001/api/health
curl --noproxy '*' --fail --silent --show-error http://127.0.0.1:8001/api/ready
```

生产状态和日志入口见 [deploy/README.md 的 Operation](../deploy/README.md#operation)。按任务范围访问目标主机，限定日志时间范围并脱敏；不要输出环境变量、完整请求、Cookie、授权 code、查询参数中的订单号、内部备注、顾客图片或上游返回体。现有 unit/本地正式启动器关闭 access log，不代表代理、浏览器 trace 和手动启动的 Uvicorn 同样安全；手动启动使用 `--no-access-log`。

### 按症状选择下一步

| 症状 | 先检查 | 不要做的“修复” |
| --- | --- | --- |
| ready 503，health 200 | 当前进程的生成 worker/租约、数据库访问、错误日志；[test_deployment.py](../backend/tests/test_deployment.py) 有对应失败场景。 | 反复启动第二个 worker、复制正式库后开生产入口。 |
| 新任务一直 queued | 仅核对是否配置、全站/账号并发、暂停/组织状态、共享退避与已有远端占用；[worker.py](../backend/app/worker.py)。 | 临时填真实密钥做测试、修改 DB 把占用清零。 |
| 有 FAL request ID 的 unknown | 在受控运维流程中恢复对原请求的查询，保留 ID 和队列 URL；这是外部查询，离线任务不执行。 | 清掉 ID 后重新提交或把换模型当重试手段。 |
| 无 ID 的不确定提交、cutout_inflight | 人工核对原服务是否已接单/结束后，使用对应工作流的明确恢复动作。 | 根据超时猜失败、自动 resubmit、直接改状态/额度。 |
| 已有 raw_result，后处理失败 | 优先“重新处理”；不再次 FAL 生图，但原图不透明且配置 Yezi 时仍可能调用付费抠图。 | 宣称所有 reprocess 都完全免费，或直接“重做”一张。 |
| 仅拼版/水印错误 | 从已保存成品恢复排版/水印，检查中文字体和版式；使用 mock 回归验证。 | 为布局故障重跑生图，丢弃旧版本或原图。 |
| Agiso 未配置/授权失败/商品选择失败 | 本地用 [test_agiso.py](../backend/tests/test_agiso.py) 的 MockTransport；真实权限、余额和助手状态交给授权操作者。 | 以“查询商品”当零费用探针：真实 `Goods/List` 是外部调用；也不能重复授权/发消息验证健康。 |
| Agiso message unknown | 保留持久记录，核对真实送达后再决定；[agiso_worker.py](../backend/app/agiso_worker.py) 对不确定发送不自动补发。 | 直接重置 outbox、重放所有 webhook 或点击重试碰运气。 |
| E2E 登录/请求 403/连接失败 | 端口占用、前端代理、硬编码 baseURL、Cookie secure、setup 和 origin，确认仍是独立 mock 库。 | 改 `reuseExistingServer` 为 true、放宽生产权限、结束别人的进程。 |

旧订单的 [main.py 恢复接口](../backend/app/main.py) 与客户订单的 [customer_orders.py](../backend/app/customer_orders.py) 路径、状态限制和幂等参数不同；不要互抄 curl。重新生成/首次失败 retry 可能新增付费请求；resolve 是操作者确认，不会替操作者查询事实。保持 client token 和 expected version 的语义，不能为绕过冲突随意更换 token。

## 8. 当前源码揭示的待复核点

以下是文档交接发现，本文没有修改实现，也没有以真实数据复现：

1. E2E 端口配置与部分 spec 的固定 5174 尚未统一；完整回归仍需协调默认端口和共享截图目录。
2. 旧图库审计对多组织同 code、新客户订单缺少单一 `avatar_id` 的假设不适配；优先使用框架审计，并针对本次迁移核对其比较规则与覆盖范围。
3. framework rehearsal 的嵌套 integrity 与 Agiso 排空状态需额外核对，退出码 0 不能单独作为发布许可。
4. [Agiso 文档](agiso-setup.md) 中旧的“未成团不开户”验收项已随本次交接修正；[test_agiso.py](../backend/tests/test_agiso.py) 的 `test_payment_before_group_without_confirmation_time_still_opens` 覆盖付款通知成交时间为空仍可开户。真实第三方字段与消息送达仍需另验。
5. [后端 README](../backend/README.md) 已修正固定十二图和旧分类说明；部署历史章节仍保留旧积分/角色等阶段性记录。测试选择、恢复操作和默认值以当前源码为准，不把历史记录当作当前线上事实。
6. 2026-09-26 已修正 4 个过期 E2E 断言，完整 E2E 34 项通过：订单详情改为弹窗后需按名称定位选图弹窗、切换导航前先关闭订单弹窗；生成前核对第三项是“可最终提交”，去重后的实际生成数在头像行和提交栏断言；`z-accounts-credits` 改为自建公共模板，不再依赖已删除用例遗留的 `B001`。新增 E2E 应自行准备数据，不依赖其他 spec 的执行顺序。

交付下一位 Agent 时，列出本次实际修改文件、运行过的命令及结果、使用的隔离数据/端口、未验证项，以及是否涉及外部调用或生产变更。不要附私密原始证据；只提供脱敏摘要与受控证据位置。
