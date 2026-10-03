# 阿里云网站迁移 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; track steps below.

**Goal:** 全量迁移网站到阿里云，使用 https://sticker.coreages.com，更新阿奇索地址，验证后同步项目与后台说明。

**Architecture:** 保持 React/FastAPI/SQLite WAL 单进程结构。新服务器建立独立目录、Python 环境及 Nginx 虚拟主机；先复制静态文件，停止原服务后迁移一致数据库，检查完整性后只启动新端。DNS 和独立 SSL 证书使用现有账号与官方渠道管理。

**Tech Stack:** Ubuntu 22.04、Python 3.13、uv、systemd、Nginx、Certbot、AliDNS、SQLite、Vite。

**Spec:** 本次用户迁移指令及 [AGENTS.md](../../../AGENTS.md)。目标服务器 8.130.175.250，域名 sticker.coreages.com。

## Global Constraints

- 保留既有主站、Wiki、其他进程和仓库未提交文件；只迁移本应用。
- 不把密钥、订单号、头像、数据库备份或客户消息写入 Git 或报告。
- 数据库与原图完整迁移；不释放未知请求，不重复付费生图，不同时运行两套业务 worker。
- 测试使用隔离数据和 mock；发布验收检查真实公开入口及权限。
- 每次网站行为变化同步私有后台说明；不添加定时备份。

## Review Focus

- 停机到启动之间不会丢失写入或产生两个 worker。
- 域名变化后会话、原链接、OAuth 和消息模板的处理明确。
- 私有媒体、原图和后台说明不能通过 Nginx 或匿名接口泄露。
- Python 版本、字体、媒体缓存和现有网站保持正常。
- DNS、SSL 续期、阿奇索实际保存的地址与当前发布版本一致。

### Task 1: 新端准备与 HTTPS

**Files:** `deploy/avatar-sticker-studio.service`、`deploy/production.env.example`，新建 Nginx 模板。

- [x] 建立独立运行环境；安装锁定依赖和中文字库。
- [x] 记录主站及 Wiki 基线；新增应用虚拟主机并检查 Nginx 配置。
- [x] 添加 sticker A 记录，签发独立证书；验证公网解析、证书和续期。

### Task 2: 数据一致迁移

**Files:** 服务器私有数据目录、环境文件、缓存；不进入 Git。

- [x] 预复制素材、发布文件和缓存。
- [x] 核对在途任务与 Agiso 队列，停止原端；制作单次完整备份并复制最终数据。
- [x] 对比记录数量、SQLite 完整性、全部原图哈希和文件引用。
- [x] 只修改目标域名配置及派生链接；保留历史记录、密钥、订单及额度。
- [x] 启动新端单进程，验证旧端停止及公开服务。

### Task 3: 第三方和客户入口

**Files:** `docs/agiso-setup.md`、`backend/content/staff-guide.json`。

- [x] 开放平台更新应用网址、授权回调、推送网址并验证保存结果。
- [x] 核查自动发货模板中未来发送的选图入口。
- [x] 确认旧入口兼容方案和新域名重新登录行为。

### Task 4: 全量验证

**Files:** 现有后端/前端/E2E 测试及私有部署验收结果。

- [x] 隔离执行 npm test、npm run build、完整浏览器回归。
- [x] 公网验证登录/失效会话、组织隔离、后台说明、访客媒体与拒绝策略。
- [x] 检查真实 FAL 余额查询及生成链路（累计测试不超过 50 张）。
- [x] 检查阿奇索配置及真实外部连通性，明确模拟与真实联调范围。
- [x] 对比主站/Wiki 基线，核对 release、进程、数据与 SSL。

### Task 5: 文档与交付

**Files:** `README.md`、`backend/README.md`、`deploy/README.md`、环境示例、架构/运维文档、阿奇索说明和私有后台说明。

- [x] 按迁移后的实际状态更新说明，清除当前文件中的原入口和原部署描述。
- [x] 更新后台说明版本、日期及维护记录；执行 check:docs 和实际基础提交检查。
- [x] 按文件提交、合并并发布最终版本，验证公网版本和权限。
- [x] 逐项核对用户要求后完成迁移目标。

执行记录：生产切换、主分支合并与推送及公网权限核验已完成。具体验收范围以 [迁移验收](../../aliyun-migration-verification.md) 为准；发布身份以服务器 REVISION 和进程工作目录为准。
