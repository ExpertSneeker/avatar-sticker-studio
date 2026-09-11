# Avatar Sticker Studio backend

Run from repository root:

```sh
uv sync --python 3.12
uv run uvicorn backend.app.main:app_factory --factory --host 127.0.0.1 --port 8000
```

The FastAPI lifespan starts the durable worker. A built `frontend/dist` is served automatically; during development use the Vite `/api` proxy. Do not start a second standalone worker implementation. Multiple ASGI processes share SQLite transactions and admission records on this single host.

## Configuration

- `STUDIO_DATA_DIR`: private data directory, default `.data` in the working directory. Keep on a local filesystem, not a network share. Contains SQLite WAL database, original upload chunks and immutable PNG assets. Directory mode 0700, DB/assets mode 0600.
- `FAL_KEY`: preferred FAL credential. Alternatively the authenticated administrator can set it in Settings; stored only in the private database and never returned by an API. No Codex credentials are read.
- `YEZI_API_KEY`: optional separate Yezi cutout credential, with the same private admin setting alternative. A paid FAL result is retained before cutout processing.
- `STUDIO_ALLOWED_HOSTS`: comma-separated accepted hostnames; defaults `localhost,127.0.0.1,::1,testserver`.
- `STUDIO_ALLOWED_ORIGINS`: explicit unsafe-request origins; defaults localhost/127.0.0.1 on ports 5173 and 8000. The request's own trusted origin is also accepted.
- `STUDIO_SECURE_COOKIE=1`: require HTTPS cookies when running behind an explicitly configured HTTPS proxy.
- `STUDIO_FONT`: optional path to a Unicode TrueType/OpenType font for watermarks; macOS PingFang/STHeiti Light/Songti and Linux Noto CJK are detected automatically and checked for the actual watermark glyphs. Missing suitable fonts fail clearly instead of producing unreadable replacement boxes.

The initial administrator can only be created from a loopback connection while no users exist. Further registrations require single-use invitations (valid seven days). Passwords use scrypt; sessions are HttpOnly SameSite Strict cookies and only token hashes are stored. Failed login attempts are bounded per client/username. Deactivated accounts cannot log in, fetch assets or start queued work.

## Queue and files

- The only generation admission setting is `max_inflight`, default 2, configurable 1–40. No RPM setting or rolling-minute gate remains. All accounts and worker processes share transactional reservations. This website conservatively counts submitted FAL jobs while waiting in the remote queue as well as running jobs; FAL separately enforces the account's actual `IN_PROGRESS` limit across applications/endpoints.
- Submit to `https://queue.fal.run/openai/gpt-image-2.5/flare/edit` with `Authorization: Key <FAL_KEY>` and JSON `image_urls: [template_data_uri, portrait_data_uri]`, `prompt`, `image_size: {width:1024,height:1024}`, `quality: low`, `num_images: 1`, `background: transparent`, `output_format: png`, `sync_mode: false`. Do not use BYOK or pass an OpenAI credential. New submissions use GPT Image 2.5 Flare. Existing requests continue polling their stored original queue URLs; changing models never resubmits an existing request. Missing FAL credentials leave new jobs queued. The old OpenAI credential is never reused as a FAL key.
- Persist the request ID and validated queue status/result URLs immediately. Poll `IN_QUEUE` / `IN_PROGRESS` / `COMPLETED`, then download the result without an Authorization header. Remote URLs are validated, redirects are not followed blindly, and media size is bounded before image decoding. Production has no simulated provider.
- Known request IDs survive worker leases/restarts. Transient status/download errors retry retrieval of the original request, never a fresh generation. Auth/validation/content failures are shown. A submission with an uncertain outcome and no ID is held as unknown and keeps its reservation until explicitly resolved. FAL handles concurrency waiting in the durable queue; no start deadline is set. HTTP 429 uses backoff/Retry-After.
- Pause affects only unsubmitted jobs. Already submitted jobs continue lookup even if the order is paused or the account is deactivated. Lowering concurrency does not cancel active jobs; no new slots are admitted until the count falls below the new setting. Manual rerun after a terminal outcome clears remote identity for the new attempt, preserving the old good image until success.
- Yezi uses a distinct 2-starts/second, 2-in-flight transactional gate. It is called only for opaque generation results when configured. The sync HTTPS API is implemented from the existing script contract; downloads are restricted to HTTPS Yezi/Alibaba OSS domains.
- Upload chunks are at most 4 MiB; uploads at most 25 MiB. Offset retries must match existing bytes. Completion validates SHA256 and normalizes image orientation. A hash mismatch resets the durable offset to zero for recovery.
- Templates store immutable revisions of exactly twelve images; `image_order` multipart JSON supports mixing retained `{id}` and newly uploaded `{file_index}` references. Existing orders embed selected template and prompt snapshots.
- Print settings default to A4, 85 mm effective-content long edge, 300 DPI, 10 mm margins and gaps. `brightness` and `color_balance` are booleans, both false by default. Enabled presets apply 1.15 brightness and RGB multipliers [1.04, 1.00, 0.97], preserving alpha.
- Printing uses transparent alpha-composite and premultiplied-alpha resizing, never masked paste. Whole sets publish atomically. A4 is 2480×3508 with 300 DPI metadata. Set pages start at 1 and stay in selection order.
- One white full-order overview has 256 px tiles, 4×3 per set, vertically joined, with 45° repeated 25%-opacity account watermark. Repacking/watermark updates do not call image generation.
- Manifests use safe filenames relative to the order directory, immutable authenticated asset URLs, SHA256, byte counts and a monotonic artifact version. Previous artifacts remain available after a rerun or processing failure.

## Verification

```sh
uv run pytest -q
uv run python -m compileall -q backend
uv pip check
```

Tests use temporary directories and explicitly injected providers or HTTP transports. They never make paid generation requests. Real API credentials, provider delivery, printer output and the optional Yezi service require separate operator validation.

## Resume postprocessing without regenerating

`POST /api/orders/{order_id}/items/{item_id}/reprocess` with no body returns the full Order and durably queues only postprocessing of the retained raw image. Items expose `raw_available: boolean` and `processing_stage: "generate" | "postprocess"`. This endpoint requires an existing raw result and rejects already queued/running items with409. It respects the order's paused state. It never calls image generation or increments `attempt` (the number of generation submissions), and works without a FAL key; opaque raw images use the independently limited Yezi API. Failures preserve previous good results/files, and reprocessing remains available across restart. In-progress uncertain cutout outcomes also require explicit operator retry.

Template categories accept Chinese or English inputs and always return canonical `boy` / `girl` values. Display names are trimmed and cannot be whitespace-only.

Authenticated browser API calls should send `X-Studio-User` containing the account ID captured by that tab. If shared cookies switch to another account, a mismatch returns401 (`登录账号已变化，请重新登录`) before mutation. Logout is guarded too when the header is present. Ordinary `<img>` asset requests may omit it and still require owner/admin session authorization.

## FAL contract and settings

`PATCH /api/admin/settings` accepts `fal_api_key`, `max_inflight`, `prompt` and optional `cutout_api_key`; public settings expose only `fal_configured` and `cutout_configured` flags, never keys. `rpm` and `openai_api_key` are rejected. Environment `FAL_KEY` takes precedence over the database value. Migrating an existing database retains accounts, templates, orders, images, prompt versions, print parameters and the chosen concurrency limit.

Official references checked 2026-09-11: [edit schema](https://fal.ai/models/openai/gpt-image-2.5/flare/edit/api), [queue API](https://fal.ai/docs/documentation/model-apis/inference/queue), [concurrency](https://fal.ai/docs/documentation/model-apis/concurrency-limits).

Each detailed item exposes `fal_request_id`, `fal_status`, `queue_position`, `remote_reserved` and `recoverable` without queue URLs. `POST /api/orders/{order_id}/items/{item_id}/recover` resumes lookup for an unknown job with an ID. `POST /api/orders/{order_id}/items/{item_id}/resolve` requires `{"confirmed_ended":true}` and unknown status; it records the operator's assertion that the original job ended/does not exist, releases the reservation, and does not generate. The operator must verify FAL dashboard state before confirming. A later rerun is a separate action. Submission429 also sets a shared cooldown so other workers/orders cannot bypass backoff.
