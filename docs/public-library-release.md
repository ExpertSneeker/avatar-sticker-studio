# Public sticker library release

## Behavior

A sticker is one versioned source image. Public template sets contain ordered sticker IDs (1–100), never uploaded images. Library editing is granted per member; administrators always retain access. All authenticated users may use active public resources.

New orders freeze current sticker revisions and template membership. Unique sticker/revision pairs create one generation item and one credit reservation. Ordered export occurrences preserve every selected template member plus directly selected stickers, up to 360 occurrences. PNGs use `order_sticker-code_copy.png`; all occurrences share continuous `order_拼版_page.png` layouts and one overview. Reruns update every occurrence of the unique generation item. Existing orders retain their original grouped publication path and filenames.

## Migration

`public-stickers-v1` preserves template IDs and historical revisions while creating public stickers and granting administrators the edit permission. The marker records migration-created IDs. A1 import uses exact source PNG hashes, stages assets with deterministic IDs, then atomically creates a fresh MB-A collection and archives the old MB-A plus its exclusive migration-created stickers. Other templates and shared stickers survive. Neither migration rewrites orders, generation records, credits, uploads or historical source files.

Run the importer as the service owner from the new release, with production stopped after draining work. Do not start the previous incompatible release after migration. Use `deploy/audit_public_library.py` before and after to verify immutable history, original file hashes and all account state except the intended permission field.

## Verification

- Backend: 128 tests passed; includes 12 generation items / 13 export occurrences, overlap, 360 occurrence limit, shared reruns, source snapshot revisions, account deletion, migration resume, public permissions and legacy publication.
- Frontend unit tests: 36 passed.
- TypeScript/Vite production build passed.
- Browser: all 25 scenarios verified (24 full-run passes plus the corrected permission scenario passing a targeted rerun; production workflow also rerun).
- Browser end-to-end verification uses an isolated temporary database and synthetic provider; no paid generation calls.
- Browser test ports are configurable to avoid interrupting existing local servers.
