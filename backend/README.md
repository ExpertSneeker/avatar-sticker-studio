# Avatar Sticker Studio backend

Read [AGENTS.md](../AGENTS.md) first. The current organization/guest workflow is documented in [architecture and contracts](../docs/architecture-and-contracts.md); safe local and production operations are in [the operations guide](../docs/agent-operations.md). Only the current customer-order API remains; the legacy `/api/orders` routes and workflow-version field have been removed.

Customer watermarked media (guest and staff order routes) permits private browser
storage with `private, no-cache`, `Vary: Cookie` and content-based weak ETags.
Each reuse revalidates current authorization before an empty 304; matching
requests skip original-image reads and encoding. Links carry no order version, only an `m=` watermark fingerprint.
Sizes snap up to fixed tiers 160/320/640/1024; the 160/320 thumbnails are
LANCZOS-downscaled from the 640 watermark render (WebP q80). Renders go through
a 256MB in-process LRU, then the disk cache in `app/media_cache.py`
(`STUDIO_MEDIA_CACHE_DIR`), whose background warmer also pregenerates library
tiers and applies per-organization retention. Other guest APIs remain
`no-store`; these images must not enter shared CDN caches or
application-managed IndexedDB.

Run from repository root:

```sh
uv sync --python 3.12
uv run uvicorn backend.app.main:app_factory --factory --host 127.0.0.1 --port 8000 --no-access-log
```

The FastAPI lifespan starts the durable worker. A built `frontend/dist` is served automatically; during development use the Vite `/api` proxy. Do not start a second standalone worker implementation. Multiple ASGI processes share SQLite transactions and admission records on this single host.

The command above starts real generation and Agiso workers; it is not a simulation. Set an isolated `STUDIO_DATA_DIR` for development, never point exploratory startup at business data, and note that `Database(...)` runs migrations even without starting a worker. Direct uvicorn does not load the repository `.env` file. Use the test fixtures for synthetic generation.

## Production

Canonical origin: https://sticker.coreages.com. Aliyun ECS `8.130.175.250` runs one Python 3.13 Uvicorn process behind Nginx; paths, certificates and deployment checks are defined in [deploy/README.md](../deploy/README.md). Frontend API requests remain same-origin. Keep bootstrap disabled, preserve the private encryption key and existing provider request IDs, and never start copied production databases as test services.

## Configuration

- `STUDIO_DATA_DIR`: private data directory, default `.data` in the working directory. Keep on a local filesystem, not a network share. Contains SQLite WAL database, original upload chunks and immutable PNG assets. Directory mode 0700, DB/assets mode 0600.
- `FAL_KEY`: preferred FAL credential. Alternatively the authenticated administrator can set it in Settings; stored only in the private database and never returned by an API. No Codex credentials are read.
- `FAL_ADMIN_KEY`: optional separate Admin-scope credential for balance queries. Takes precedence over the site superadmin's private `fal_admin_key` setting. It is never used for generation or returned to clients. Use the same FAL account as the generation key.
- `YEZI_API_KEY`: optional separate Yezi cutout credential, with the same private admin setting alternative. A paid FAL result is retained before cutout processing.
- `STUDIO_ALLOWED_HOSTS`: comma-separated accepted hostnames; defaults `localhost,127.0.0.1,::1,testserver`.
- `STUDIO_ALLOWED_ORIGINS`: explicit unsafe-request origins; defaults localhost/127.0.0.1 on ports 5173 and 8000. The request's own trusted origin is also accepted.
- `STUDIO_SECURE_COOKIE=1`: require HTTPS cookies when running behind an explicitly configured HTTPS proxy.
- `STUDIO_FONT`: optional path to a Unicode TrueType/OpenType font for watermarks; macOS PingFang/STHeiti Light/Songti and Linux Noto CJK are detected automatically and checked for the actual watermark glyphs. Missing suitable fonts fail clearly instead of producing unreadable replacement boxes.

The initial administrator can only be created from a loopback connection while no users exist. Further registrations require single-use invitations (valid seven days). Passwords use scrypt; sessions are HttpOnly SameSite Strict cookies and only token hashes are stored. Failed login attempts are bounded per client/username. Deactivated accounts cannot log in, fetch assets or start queued work.

## Queue and files

- Generation admission settings: `max_inflight`, default 2, configurable 1–40, and `max_uploads` (default 3, 1–40), which caps only items still submitting to FAL (running without a request ID, i.e. uploading images). `fal_upload_timeout` (default 300 s, 30–1800) is the submit POST write timeout; other FAL calls keep 60 s. No RPM setting or rolling-minute gate remains. All accounts and worker processes share transactional reservations. This website conservatively counts submitted FAL jobs while waiting in the remote queue as well as running jobs; FAL separately enforces the account's actual `IN_PROGRESS` limit across applications/endpoints.
- Submit to `https://queue.fal.run/openai/gpt-image-2.5/flare/edit` with `Authorization: Key <FAL_KEY>` and JSON `image_urls: [template_data_uri, portrait_data_uri]`, `prompt`, `image_size: {width:1024,height:1024}`, `quality: low`, `num_images: 1`, `background: transparent`, `output_format: png`, `sync_mode: false`. Do not use BYOK or pass an OpenAI credential. New submissions use GPT Image 2.5 Flare. Existing requests continue polling their stored original queue URLs; changing models never resubmits an existing request. Missing FAL credentials leave new jobs queued. The old OpenAI credential is never reused as a FAL key.
- Persist the request ID and validated queue status/result URLs immediately. Poll `IN_QUEUE` / `IN_PROGRESS` / `COMPLETED`, then download the result without an Authorization header. Remote URLs are validated, redirects are not followed blindly, and media size is bounded before image decoding. Production has no simulated provider.
- Known request IDs survive worker leases/restarts. Transient status/download errors retry retrieval of the original request, never a fresh generation. Auth/validation/content failures are shown. A submission that failed to connect or to finish writing its body cannot have reached FAL and is marked failed. Any other submission with an uncertain outcome and no ID is held as unknown and keeps its reservation until explicitly resolved. FAL handles concurrency waiting in the durable queue; no start deadline is set. HTTP 429 uses backoff/Retry-After.
- Pause affects only unsubmitted jobs. Already submitted jobs continue lookup even if the order is paused or the account is deactivated. Lowering concurrency does not cancel active jobs; no new slots are admitted until the count falls below the new setting. Manual rerun after a terminal outcome clears remote identity for the new attempt, preserving the old good image until success.
- Yezi uses a distinct 2-starts/second, 2-in-flight transactional gate. It is called only for opaque generation results when configured. The sync HTTPS API is implemented from the existing script contract; downloads are restricted to HTTPS Yezi/Alibaba OSS domains.
- Upload chunks are at most 4 MiB; uploads at most 25 MiB. Offset retries must match existing bytes. Completion validates SHA256 and normalizes image orientation. A hash mismatch resets the durable offset to zero for recovery.
- Current templates contain 1–100 ordered, distinct sticker IDs and belong to an organization. Stickers and templates have immutable revisions; current orders freeze source revisions and prompt snapshots. The original twelve-upload template model is historical, not the current write API.
- Print settings default to A4, 85 mm effective-content long edge, 300 DPI, 10 mm margins and gaps. `brightness` and `color_balance` are booleans, both false by default. Enabled presets apply 1.15 brightness and RGB multipliers [1.04, 1.00, 0.97], preserving alpha.
- Printing uses transparent alpha-composite and premultiplied-alpha resizing, never masked paste. Whole sets publish atomically. A4 is 2480×3508 with 300 DPI metadata. Set pages start at 1 and stay in selection order.
- Customer orders publish the selected final occurrences, a watermarked overview and print pages; see `publication.py` and `guest_media.py`. Single-preview watermark strength and cache versions are independent of already generated overviews. Repacking/watermark updates do not call image generation or change originals.
- Manifests use safe filenames relative to the order directory, private OSS signed URLs with authenticated local fallback, SHA256, byte counts and a monotonic delivery version. Previous artifacts remain available after a rerun or processing failure.

## Verification

```sh
uv run pytest -q
uv run python -m compileall -q backend
uv pip check
```

Tests use temporary directories and explicitly injected providers or HTTP transports. They never make paid generation requests. Real API credentials, provider delivery, printer output and the optional Yezi service require separate operator validation.

## Resume postprocessing without regenerating

`POST /api/customer-orders/{id}/slots/{slot_id}/reprocess` 使用 `client_token`、`expected_version`，仅在保留原图且原请求/抠图占用已核对完后恢复后处理。它不重新调用生图、不增加生成 attempt；已有原图和旧结果继续保留，重启后仍可恢复。当前订单状态必须允许操作。

Library categories are editable organization-scoped identities, initially seeded from boy/girl/animal/general. Use returned category IDs rather than assuming only `boy` / `girl`. Display names are trimmed and cannot be whitespace-only. Current sticker/template disable endpoints are retired; use the guarded deletion workflow and retain historical references.

Authenticated browser API calls should send `X-Studio-User` containing the account ID captured by that tab. If shared cookies switch to another account, a mismatch returns401 (`登录账号已变化，请重新登录`) before mutation. Logout is guarded too when the header is present. Ordinary `<img>` asset requests may omit it and still require owner/admin session authorization.

## FAL contract and settings

Only `superadmin` may configure `fal_admin_key` through `PATCH /api/admin/settings` or call `GET /api/admin/fal/balance`. Omit the key to preserve it; an empty value removes the stored balance key. Settings expose only `fal_balance_configured` and `fal_balance_key_source` (`environment`, `settings`, or null). The balance endpoint calls the official account billing endpoint with `expand=credits`, a 10-second HTTP timeout, no redirects and no automatic retries. It returns only account, current balance, currency and query time (`queried_at`, Unix seconds), with `private, no-store`. Network calls occur outside DB transactions; session, role and credential are rechecked after the call. Upstream auth errors become safe Chinese 502 responses, never website 401/logout; timeout is 504, missing/changed key is 409. The UI queries only on click and does not persist balances or keys in browser storage. This is account credit, not an organization's budget. Real integration requires a valid Admin-scope key; synthetic tests do not prove live access.

`PATCH /api/admin/settings` accepts `fal_api_key`, `max_inflight`, `max_uploads`, `fal_upload_timeout`, `prompt` and optional `cutout_api_key`; public settings expose only `fal_configured` and `cutout_configured` flags, never keys. `rpm` and `openai_api_key` are rejected. Environment `FAL_KEY` takes precedence over the database value. Migrating an existing database retains accounts, templates, orders, images, prompt versions, print parameters and the chosen concurrency limit.

Official references checked 2026-09-11: [edit schema](https://fal.ai/models/openai/gpt-image-2.5/flare/edit/api), [queue API](https://fal.ai/docs/documentation/model-apis/inference/queue), [concurrency](https://fal.ai/docs/documentation/model-apis/concurrency-limits).

后台客户订单的任务详情保留 `fal_request_id`、`fal_status`、`queue_position` 和 `remote_reserved`，不暴露队列 URL。Worker 在重启或瞬时错误后继续查询已保存的原请求 ID，不重新提交付费生成。未知结果继续占用；后台 `POST /api/customer-orders/{id}/slots/{slot_id}/resolve` 要求 `confirmed_ended=true`、当前版本和幂等 token，只有人工核对供应商确认原请求结束后才使用。`retry` 仅用于确定失败且没有原图/占用的首次生成，不能替代未知请求查询。429 共享冷却和并发保护继续有效。

点数接口和 `credits.py` 已移除；`request_tracking.py` 只保留实际请求 ID 同步。两项一次性迁移与配对回退要求见架构和发布文档。`generations` 和 FAL 余额查询不是点数记录，不得随点数下线删除。
