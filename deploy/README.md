# DMIT production deployment

Production URL: https://sticker.magnusma.online

The current organization/guest workflow and migration procedure are documented
in [framework-release.md](framework-release.md). Its tenant roles, credit-free
generation, frozen customer selections and manual print-only downloads supersede
the historical release notes below. Do not use the original local-data transfer
procedure to upgrade an existing production database.

The application runs as `sticker` on loopback port 8000, using one systemd-managed Uvicorn process. Cloudflare's existing `sub2api-dmit` tunnel routes this hostname to the application; its other ingress rules and the existing port 443 service are preserved. Do not start another production worker against a copied database.

## Layout

- `/opt/avatar-sticker-studio/releases/<commit>`: source and locally built `frontend/dist`.
- `/opt/avatar-sticker-studio/current`: selected release symlink.
- `/opt/avatar-sticker-studio/venv`: Python 3.13 environment, installed from `uv export --frozen --no-dev`.
- `/var/lib/avatar-sticker-studio`: private database and assets; owned by `sticker`, mode 0700. Reference images are in `reference-assets/` and deployment verification artifacts in `deployment-qa/`, neither publicly served.
- `/etc/avatar-sticker-studio.env`: root-owned mode 0600, based on the supplied example. Existing API keys remain in the private database, never Git.

Install `python3-venv`, `fonts-noto-cjk`, `rsync`, and CA certificates. Build the frontend locally with `npm ci --prefix frontend && npm run build`; export production requirements using `uv export --frozen --no-dev --format requirements-txt`. Install dependencies in the server environment, transfer source/build, and install the supplied unit/environment file. Bootstrap is disabled in production; transfer initialized accounts before starting the service.

## Initial data transfer

Wait for all in-flight jobs to finish and stop the local server before copying its complete data directory. Transfer through SSH, compare file SHA256 values and all records, run SQLite integrity and asset-reference checks, then start the server. Preserve original account credentials and prompt/API configuration. Never overwrite a production database that has received new orders with an earlier local copy.

The domain change requires logging in again and choosing local output directories again. Browser IndexedDB drafts, directory handles and local download ownership do not transfer between origins. Existing downloaded files without their management records remain protected from overwrite; select a new empty output directory when necessary.

## Operation

```sh
systemctl status avatar-sticker-studio
curl --fail http://127.0.0.1:8000/api/ready
journalctl -u avatar-sticker-studio --since '30 minutes ago'
```

Use controlled service restarts, retaining durable FAL request IDs. Unknown cutout requests require explicit manual retry; never automatically resubmit a deployment smoke request. Changing the release symlink and restarting selects another compatible code version; this does not roll back business data.

No scheduled backups, off-host backups, backup timers or backup management features are installed, by the owner's instruction.

## Display image cache

Only display images use `/api/assets/{id}/preview?size=320` or `size=1280`.
Pillow encodes WebP at quality 80 without upscaling; transparency and white
watermark backgrounds are retained. Original URLs, download ZIPs and manifests
continue to serve the original PNG bytes. Modal viewers provide an explicit
original-image toggle for detailed inspection.

Derivatives are generated on demand under `preview-cache/<asset-id>/` in the
private data directory. The 256 MiB encoded-file budget uses least-recently-used
eviction, pruning to approximately 80% when full. Encoding and eviction share a
cross-process lock; only one image is encoded at a time. Incomplete temporary
files are reclaimed on the next cache miss. Below 512 MiB free disk space, or
if persisting a cache entry fails, the compressed response is returned without
storing it. No external service or backup is added.

Every preview request, including cache hits and conditional 304 responses,
checks the authenticated account and asset access. Responses use
`Cache-Control: private, no-cache`, `Vary: Cookie` and versioned ETags. Do not add
Cloudflare rules that force these private endpoints into a shared cache.

Administrator date cleanup includes all cached variants of removed assets,
including historical outputs and variants created after the cleanup preview.
Template/shared surviving assets stay protected. A durable per-asset cache
cleanup entry is retried via the existing cleanup-retry action and on startup.
The storage panel reports cache use and the limit; cached bytes are already
included in the application's total. Cached derivatives are disposable and do
not replace manual retention management of original orders.

## Historical release: personal templates and production credits

The one-time `personal-credits-v1` database migration preserves existing template
IDs, images and versions as public resources. Existing members begin with zero
credits; administrators are exempt. Previously submitted items have no billable
generation record and finish without retroactive charging. New orders and manual
reruns reserve one credit per image for the order owner. A valid 1024 × 1024 raw
result saved on the server settles that reservation; subsequent matting, layout,
watermark and download operations are free. Definitive failures release holds;
unknown provider results remain held for recovery or administrator reconciliation.
Do not clear unknown generations directly in the database.

Account management provides member creation, invitations, activation, password
reset and credit adjustment. Temporary passwords are shown once; password resets
revoke existing sessions. Setting a balance changes available credits only, leaving
frozen credits intact. Adjustments use a wallet version and idempotent client token.
`POST /api/orders/{id}/items/{item_id}/rerun` also requires a JSON `client_token`, retained by clients
until the operation has been confirmed. A retry with the same token never creates
a second generation, even after the first finishes. Manual new reruns use new tokens.

Personal templates are editable only by their owner, public templates only by
administrators. Source and preview endpoints enforce access before cache or 304
responses. Set codes remain globally unique. Production statistics filter by order
submission date; credit ledger filters use the transaction's own timestamp.

Date cleanup releases remaining eligible reservations and removes associated
images, preview cache and generation records, preserving the minimal credit ledger.
Orders with unresolved credits must be reconciled before cleanup. No paid provider
requests are needed for regression testing: `uv run pytest backend/tests`,
`npm test --prefix frontend`, `npm run build --prefix frontend` and
`npm run test:e2e --prefix frontend` use isolated data and mock generation services.

## Task previews and repeated names

Task-list preview dialogs open the original watermark overview by default; list
thumbnails remain compressed. Each task has its own download button that selects
a destination and downloads only that task, independently of checked rows.

Order display names may repeat. Within an account, a transactional `output_name`
reserves a distinct folder name (`Name`, `Name (2)`, etc.), including conflicts with
literal numbered names. Manifests and ZIP roots use this name; pre-existing orders
fall back to their original name. Task IDs and submission tokens still provide
identity and retry deduplication. Existing local ownership checks remain in force:
foreign or modified files are never silently overwritten, including files left
behind after an older order was cleaned from the server.

Task names and “查看详情” now open a task-detail dialog above the filtered list.
Nested image, layout and repair dialogs close independently. Without a global
output directory, choosing a draft's location first establishes that global
default. Subsequent choices override only the chosen draft; submitted destination
bindings are unchanged. Cancelled native pickers leave drafts and defaults intact.

## Public sticker library release and A1 replacement

The `public-stickers-v1` startup migration preserves legacy template IDs,
revision records and order snapshots while normalizing the catalog as public
resources (`owner: null`). Only administrators and members explicitly granted
`can_edit_library` may edit it. Account removal and date cleanup protect assets
referenced by current or historical sticker revisions.

Transfer the twelve original `A1-01.png` through `A1-12.png` into a private
staging directory readable by `sticker`. Validate SHA256 against the local files.
After tests and the frontend build pass, deploy the new release, wait for no
running/unknown or remotely reserved items, and stop the service for the switch.
Run from the new release as the service owner:

```sh
sudo -u sticker /opt/avatar-sticker-studio/venv/bin/python -m backend.app.import_a1 \
  --data-dir /var/lib/avatar-sticker-studio \
  --source-dir /var/lib/avatar-sticker-studio/reference-assets/A1
```

The importer validates all twelve PNGs and case-insensitive code collisions
before changing the catalog. It preserves the exact original PNG bytes, stages
public assets durably with deterministic IDs, then creates twelve sticker rows
and a fresh `模板A` / `MB-A` in one SQLite transaction. The previous active MB-A
is archived (`deleted: true`, `active: false`); its IDs, revision rows, assets and
historical order references remain. This is a replacement of the active catalog
entry, not an edit of old order snapshots. Missing/invalid input or collisions
abort without switching the active template. Interrupted staging can be rerun.
A completed repeat with the same sources returns `already_imported: true` and
does not create duplicate records. Changed sources require a separately reviewed
migration rather than silently rerunning this import.

Select the release with an atomic `current` symlink replacement and start the
service. Verify `/api/ready`, SQLite integrity, all twelve sticker source hashes,
exactly one unarchived MB-A, preserved old revision and order records, public
asset access and member editing permissions. Do not overwrite live data with a
local database. Retain the previous release; reverting code alone does not undo
this catalog migration, so check backward compatibility before rollback.

During this replacement, migration-derived members used exclusively by the old
MB-A are archived too. The migration marker records exactly which sticker IDs it
created. Independently uploaded stickers and members referenced by any surviving
template remain active; original sticker revisions and assets are preserved.

`deploy/audit_public_library.py` opens SQLite with `mode=ro` and reports record
hashes and file integrity without printing user credentials or provider settings.
Before switching, capture its stdout privately as a baseline. After migration,
pass `--baseline /path/to/baseline.json`; it checks old order, item, generation,
credit, upload and template-revision hashes plus every old asset file, while
allowing the intentional catalog additions. Run with in-flight work drained.

```sh
python3 deploy/audit_public_library.py --data-dir /var/lib/avatar-sticker-studio
python3 deploy/audit_public_library.py --data-dir /var/lib/avatar-sticker-studio \
  --baseline /private/path/before-public-library.json
```

## Pinduoduo / Agiso integration

See [the shop setup and acceptance guide](../docs/agiso-setup.md). Install the
locked `cryptography` dependency, provision the four `STUDIO_AGISO_*` connection
variables from `production.env.example`, and retain the encryption key alongside
the existing private environment configuration. All shop automation defaults off;
aftersales must remain off until real provider events are verified. The service
unit disables request access logs; inspect any proxy or Cloudflare logging as well
to avoid recording guest order query strings or authorization codes. Production
continues to use its existing Cloudflare tunnel; no additional public port or
Windows software is installed on the Linux website server.
