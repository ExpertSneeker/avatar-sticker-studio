# Task 2 report: customer order engine and authorized guest media

Implemented `register_customer_orders(app, db, user)` and all shared-contract customer/guest routes. Organization integration is registered in main by the organization agent.

- Orders open idempotently with globally unique permanent numbers, opener settings snapshots, organization ownership, strict count validation, explicit DTOs, optimistic version checks, durable operation fingerprints and action audit records.
- Guest login uses a separate HTTPOnly cookie and persistent IP/credential failure throttles. Inactive organizations cannot log in. Guest uploads resume with offsets, reject conflicting chunks, verify SHA256 and normalize images. All upload/library/order DTO image URLs are protected derivatives.
- Repeated selections expand into independently selectable slots; initial work deduplicates by avatar upload record + sticker ID + revision. Worker avatar references are per item. Every new generation is recorded as exempt without credits.
- Every rerun creates independent work and immutable history. Success consumes that slot's reservation exactly once and requires version confirmation; definitive failure releases once; uncertain remote/cutout outcomes keep their hold. Recovery after restart does not allocate work or duplicate spending.
- Staff-only slot `/retry`, `/resolve` (confirmed_ended true), and `/reprocess` support free definitive initial retries, explicit uncertain-request resolution, and saved-raw processing without another generation call. DTOs expose staff-only raw_available, needs_resolution and processing_error.
- Exact final slot ordering is transactionally frozen on submit. Only submitted orders enter asynchronous worker publication. New artifacts and delivery manifests include print pages only; overview_id is separate. ZIPs contain one sanitized order_number_notes folder, exposed as manifest.folder_name.
- Cancel pauses new dispatch and revokes existing guest media URLs; remote requests already submitted may reconcile. Restore preserves the previous lifecycle state. Unlock preserves slots/versions/quota while invalidating deliveries. Repack uses existing originals and preserves provider spending.
- Bulk watermark preview/apply checks actor, organization subset, current opener settings and order versions. Applying rotates media versions and snapshots, without new generation or original changes.
- Guest and staff media routes have separate cookie authorities, avoiding simultaneous-session interference. Guest media is flattened RGB, heavily diagonally watermarked, no-store and capped in size. Its bounded cache key includes source digest, opener, watermark content/version, media version, size and pipeline. Authorization runs before cache access and again after rendering to reject cancellation or watermark races; no original fallback exists.

Historical storage references: orders.avatars[].asset_id, orders.slots[].versions[].asset_id, orders.slots[].sticker.image.id, orders.final_entries[].asset_id, orders.overview_id; all generation/rerun task records remain in items. Organization agent excludes v3 orders/history from cleanup and legacy mutation endpoints.

TDD: first test failed with missing customer route (404), then tests were expanded before missing recovery endpoints, inactive organization login, split media authority and ZIP/rerun limit changes. Customer integration tests cover HTTP privacy and authorization, upload scope, duplicate work, multiple avatars, quota reservations, idempotency, concurrent mutations, recovery, publication failures, print-only downloads and cancel/render/publication races. All tests use the local unpaid provider. No production changes or paid provider calls performed.

Validation: first full backend run was 172 passed / 1 importer failure outside this task; root fixed the importer in f76a2a2. Final focused run and commit are reported to root separately. Existing dependency deprecation warnings are unchanged.

Final focused verification: customer + cross-subsystem acceptance + legacy worker tests: 43 passed. After adding Unicode filename acceptance, customer + cross-subsystem tests: 23 passed. Delivery manifest.name and folder_name are the same authoritative safe folder, capped at 220 UTF-8 bytes with a deterministic hash suffix upon truncation; print files use page-001.png naming. Saved-raw reprocessing and unlock/resubmit tests also passed. `git diff --check` passed on owned files.

## Review round 1 corrections

Reproduced both P1 findings from task-2-review.md with failing regression tests before correction. Submission now rejects every outstanding rerun reservation and remote/cutout uncertainty flag, regardless of the item's status label or availability of an older selected version.

Cancellation now stores/reconciles an already submitted generation's raw output and leaves queued saved-raw processing, rather than starting a new cutout. Cancellation checks also cover saved-raw tasks claimed before cancellation and the cutout admission boundary. Root explicitly extended ownership to providers.py for an optional transaction callback checked on every cutout capacity wait/admission. The legacy positional constructor and cutout(data) method remain compatible. A distinct CutoutDeferred signal proves no cutout request was sent, permitting the worker to clear the cutout marker and retain recoverable queued processing; ambiguous paid calls still retain uncertainty holds.

Added regressions for failed+cutout_inflight submission, cancellation during generation followed by restoration, and cancellation while awaiting cutout capacity. Each failed before its fix and all three passed after it. Tests use local mock transports/providers only. The first full backend pass after the two initial fixes was 184 passed; final provider-admission verification is recorded below.

Final review-fix verification: `.venv/bin/python -m pytest backend/tests -q` — 185 passed in 38.18 seconds. Three pre-existing dependency/image-size warnings remain. Owned-file diff whitespace checks passed.
