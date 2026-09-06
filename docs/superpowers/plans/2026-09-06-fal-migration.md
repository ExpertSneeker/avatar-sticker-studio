# FAL image provider migration

## Authority and constraints

User explicitly requests replacing OpenAI API with FAL and removing image requests/minute configuration, leaving one simultaneous-processing setting. Preserve the existing template/portrait order, 1024×1024, low quality, transparent PNG, per-set print files, account isolation, raw-result recovery, and existing production data. No paid generation, deployment, or external credential changes during verification.

Official sources checked 2026-09-06:
- https://fal.ai/models/openai/gpt-image-2/edit/api
- https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=openai/gpt-image-2/edit
- https://fal.ai/docs/documentation/model-apis/inference/queue
- https://fal.ai/docs/documentation/model-apis/concurrency-limits

Use POST https://queue.fal.run/openai/gpt-image-2/edit with Authorization: Key FAL_KEY, JSON prompt, image_urls ordered [template, portrait] as data URIs, image_size {width:1024,height:1024}, quality low, num_images 1, background transparent, output_format png, sync_mode false. Do not use the BYOK route or send an OpenAI key. Persist returned request_id and validated status/response URLs immediately; GET original job through IN_QUEUE/IN_PROGRESS/COMPLETED and download images[0].url. Validate official queue URL host before sending credentials; media downloads have no Authorization and are bounded. Known request IDs are never automatically submitted again after polling/download failures or restart. An ambiguous submission without ID remains unknown.

FAL limits actual IN_PROGRESS globally per FAL account, including other applications and sometimes individual endpoints. Website max_inflight (default 2, supported 1–40) conservatively counts its outstanding FAL jobs including remote queue waits. All local workers, accounts, retries, and reruns share the same transactional slots. Lowering the limit drains existing jobs without cancelling them. FAL handles overflow through its queue. No RPM limiter or field remains. Transient 429 responses respect Retry-After and backoff; auth/validation/content errors surface clearly. Resume known jobs even while the order is paused (pause only affects not-yet-submitted jobs). Preserve optional cutout service's independent safety controls.

## Task 1: Migrate backend provider and durable concurrency lifecycle

Own backend/app and backend/tests only. Read existing provider, worker, route, database and tests before editing. Add meaningful failing tests first, then implement the FAL contract above. Remove rpm and OpenAI credentials from active settings/schema/public API; use fal_api_key, FAL_KEY and fal_configured, max_inflight 1–40. Migrate existing config without resetting accounts/orders/templates/results/print settings/prompt/concurrency; never reuse old OpenAI key as FAL key.

Persist request identity and remote progress so recovery uses the same FAL request. Preserve remote reservations across worker crashes, transient GET failures, and disabled/paused orders whose calls were already sent. No new POST merely because remote queue wait is long; do not set a queue start deadline. A result known ready but temporarily unavailable should be re-fetched, not regenerated. Keep slot accounting transactional across workers; avoid starvation for postprocessing and recovered jobs. Do not silently release ambiguous remote jobs and refill capacity. Give operator a way to resume lookup for known jobs if classified unknown; explicit reruns cannot forget an active remote job and oversubscribe. Keep terminal failure vs unknown distinction. Expose safe progress fields (fal_status, fal_request_id, queue_position, recoverable if needed) to frontend, no internal URLs/keys. Tell root exact interface after implementation.

Tests cover exact payload and ordered inputs, key isolation, IN_QUEUE→IN_PROGRESS→COMPLETED and media fetch, malformed/hostile responses, 429/auth, uncertain submission, timeout/download retry resumes same job, worker restart with same ID, concurrent workers and removal of minute gating, lowered concurrency, pause/resume, rerun new identity, old-config migration, existing print/recovery/auth regressions. Update browser fixture to concurrency only. Do not touch production .data, .env, frontend, or docs; do not restart servers. No paid calls. Run backend tests and write report.

## Task 2: Frontend and documentation migration

Root owns frontend and documentation. Replace OpenAI settings with FAL API Key and fal_configured. Remove rpm input/types/requests. Single max_inflight 1–40, default 2, help text explains website outstanding jobs and FAL actual account limit. Keep model low 1K transparent. Show remote queue progress and original request recovery actions when backend exposes them. Update isolated e2e for FAL setting and no RPM; keep filesystem/account regression flows. Update .env.example, READMEs and 功能实现FINAL.md; preserve 功能实现.md. Run TypeScript/build/unit/e2e with fake provider, review screenshots. Browser plugin absent; use repository Playwright with installed Chrome.

## Task 3: Integration and independent review

Review full diff against FAL contract and slot/recovery edge cases. Fix all material findings, rerun affected tests. Build and restart only owned local backend after checking no live generation; preserve data. Verify admin settings UI via isolated tests and local health. Report tests and explicitly state no real FAL generation run.
