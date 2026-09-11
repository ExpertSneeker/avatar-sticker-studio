# Organization and guest workflow release

This release adds tenant isolation, a separate guest workflow, immutable customer
result versions, and explicit print-only delivery. Source specification and API
contract: `docs/superpowers/plans/2026-09-11-organization-guest.md`.

## Compatibility and backup boundary

Run the migration audit using the previous deployed release's data schema (the
implementation baseline is `eb627b8`). A much older local database can still run
older application migrations first; those historical migrations intentionally
add fields. Do that normalization on an isolated copy, never by replacing live
production data with a local database.

The `organizations-v1` migration adds organization ownership, converts existing
administrators to organization administrators, and preserves catalog revisions,
order snapshots and original asset bytes. It is idempotent. New customer orders
are separate from legacy backend orders; old display names are never guest login
credentials. New generation requests retain service accounting but no longer
reserve or require credits. Historical ledger rows remain, with positively
ended holds released and unresolved requests retained for review.

A code-only rollback to pre-organization releases is not supported: those
releases do not understand the new roles or customer order workflow. If rollback
is needed before accepting new work, stop the service and restore the paired
pre-release database/assets backup and old release link. After accepting new work,
preserve the new data and use a forward fix or an explicitly reviewed data
reconciliation. Never restore an old database over newer customer submissions.

## Read-only rehearsal

The audit emits hashes and counts, not passwords, session tokens, private notes,
provider keys or prompt text. Its SQLite source connection is read-only.

```sh
python deploy/audit_framework.py --data-dir /var/lib/avatar-sticker-studio
python deploy/audit_framework.py --data-dir /var/lib/avatar-sticker-studio --rehearse
```

`--rehearse` uses SQLite's backup API to migrate a temporary database, reads
original assets for integrity checks, and runs migration twice to establish
idempotency. It does not start a worker or submit provider requests. Capture the
normal audit privately before deployment, then compare after migration:

```sh
python deploy/audit_framework.py --data-dir /var/lib/avatar-sticker-studio \
  --baseline /private/path/framework-before.json
```

The command exits nonzero for missing or changed originals, changed historical
snapshots/configuration, missing generation history, duplicate tenant catalog
codes/order numbers, missing tenant ownership, or broken asset references.

## Release sequence

1. Run backend tests, frontend tests/build and full browser acceptance with the
   fake provider. Inspect guest screens at desktop and mobile sizes.
2. Stage immutable source and `frontend/dist` into a new release directory;
   keep private data and existing provider configuration outside the release.
3. Recheck source revision, service health, queued/running/unknown work and
   remote reservations. Stop accepting new requests and stop the sole service.
4. With the service stopped, recheck the queue before migration. If new work
   arrived, restart the old release and drain/reconcile it before proceeding.
5. Make a mode-0700 full data backup on the same private server and capture the
   audit baseline. Verify the backup database and asset hashes, not only its size.
6. Rehearse migration, then initialize the new release's Database on the live
   data directory with no worker. Compare against the baseline. Create the
   separate superadministrator using the supplied bootstrap command with an
   operator-chosen username and a unique password; no default credential exists.
7. Atomically select the new release and start the existing systemd service.
   Check `/api/ready`, organization membership, legacy history, guest entry,
   original asset hashes, logs, and both role-specific login surfaces. Do not use
   a real paid generation as a deployment smoke test.
8. Keep the prior release and paired backup until the new release is accepted.
   Existing authenticated staff sessions are re-authorized on every request, so
   the new organization roles apply immediately.

## Guest media and operator delivery

Guest sessions cannot authorize backend original or manifest endpoints. Guest
images are flattened and watermarked on the server; guest responses use
`Cache-Control: no-store`. Never add a CDN rule that caches guest API responses
publicly. Cancellation and watermark revision changes invalidate guest media
links. Do not expose the private assets/cache directories through Nginx or the
Cloudflare tunnel.

Watermark changes use selected-order preview/confirmation and each opener's
current setting. Existing print defaults remain frozen. Preview regeneration
never submits an AI generation.

Saving files requires an explicit backend action. Batch delivery uses the
browser directory picker when available, otherwise ZIP; only print pages appear
in either manifest. Folder names are sanitized from order number and internal
notes. Customers never receive those notes or the original print manifest.
