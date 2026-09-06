# Avatar Sticker Studio backend

Run from repository root:

```sh
uv sync --python 3.12
uv run uvicorn backend.app.main:app_factory --factory --host 127.0.0.1 --port 8000
```

The FastAPI lifespan starts the durable worker. A built `frontend/dist` is served automatically; during development use the Vite `/api` proxy. Do not start a second standalone worker implementation. Multiple ASGI processes share SQLite transactions and admission records on this single host.

## Configuration

- `STUDIO_DATA_DIR`: private data directory, default `.data` in the working directory. Keep on a local filesystem, not a network share. Contains SQLite WAL database, original upload chunks and immutable PNG assets. Directory mode 0700, DB/assets mode 0600.
- `OPENAI_API_KEY`: preferred OpenAI credential. Alternatively the authenticated administrator can set it in Settings; stored only in the private database and never returned by an API. No Codex credentials are read.
- `YEZI_API_KEY`: optional separate Yezi cutout credential, with the same private admin setting alternative. A paid OpenAI result is retained before cutout processing.
- `STUDIO_ALLOWED_HOSTS`: comma-separated accepted hostnames; defaults `localhost,127.0.0.1,::1,testserver`.
- `STUDIO_ALLOWED_ORIGINS`: explicit unsafe-request origins; defaults localhost/127.0.0.1 on ports 5173 and 8000. The request's own trusted origin is also accepted.
- `STUDIO_SECURE_COOKIE=1`: require HTTPS cookies when running behind an explicitly configured HTTPS proxy.
- `STUDIO_FONT`: optional path to a Unicode TrueType/OpenType font for watermarks; macOS PingFang/STHeiti Light/Songti and Linux Noto CJK are detected automatically and checked for the actual watermark glyphs. Missing suitable fonts fail clearly instead of producing unreadable replacement boxes.

The initial administrator can only be created from a loopback connection while no users exist. Further registrations require single-use invitations (valid seven days). Passwords use scrypt; sessions are HttpOnly SameSite Strict cookies and only token hashes are stored. Failed login attempts are bounded per client/username. Deactivated accounts cannot log in, fetch assets or start queued work.

## Queue and files

- The global default is 5 OpenAI request starts per rolling minute and at most 2 known in-flight requests. Claim, start history and state transition are committed together with `BEGIN IMMEDIATE`.
- All starts including 429 retries and manual reruns pass the same gate. Explicit 429s retry at most three times with exponential backoff and Retry-After. Rejected parameters/auth/content fail visibly. Network/timeout/5xx outcomes become `unknown` and never automatically resubmit.
- Worker leases are refreshed every five seconds; missing/expired leases are classified unknown after 30 seconds. Startup and the running worker recover pending postprocessing. Pause only stops unstarted images. A manual rerun explicitly requeues only that image and preserves the old result until success.
- OpenAI requests always use `gpt-image-2`, `low`, `1024x1024`, `transparent`, `png`, `n=1`, template first and avatar second. `input_fidelity` is omitted. A missing API key leaves jobs queued; there is no simulated production provider.
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

`POST /api/orders/{order_id}/items/{item_id}/reprocess` with no body returns the full Order and durably queues only postprocessing of the retained raw image. Items expose `raw_available: boolean` and `processing_stage: "generate" | "postprocess"`. This endpoint requires an existing raw result and rejects already queued/running items with409. It respects the order's paused state. It never calls OpenAI or increments `attempt` (the number of OpenAI starts), and works without an OpenAI key; opaque raw images use the independently limited Yezi API. Failures preserve previous good results/files, and reprocessing remains available across restart. In-progress uncertain cutout outcomes also require explicit operator retry.

Template categories accept Chinese or English inputs and always return canonical `boy` / `girl` values. Display names are trimmed and cannot be whitespace-only.

Authenticated browser API calls should send `X-Studio-User` containing the account ID captured by that tab. If shared cookies switch to another account, a mismatch returns401 (`登录账号已变化，请重新登录`) before mutation. Logout is guarded too when the header is present. Ordinary `<img>` asset requests may omit it and still require owner/admin session authorization.
