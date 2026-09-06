# Avatar Sticker Studio Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Execute continuously, test each subsystem, review integrations before completion.

**Goal:** Fully implement the approved internal avatar sticker production website locally, with initialized Git and no server deployment.

**Architecture:** React + TypeScript + Vite client; FastAPI + SQLite WAL persistent backend and local private asset storage; durable image jobs processed by background workers using transactional global admission control. Browser directory sync is independent from server generation. Production only calls the real OpenAI Images Edit API; test providers are injected only in tests.

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, httpx, Pillow, NumPy; React, TypeScript, Vite, lucide-react. SQLite supports the requested single-host local implementation with transactions shared by worker processes.

**Spec:** ../../../功能实现FINAL.md (authoritative); the document-only delivery paragraph was superseded by the user's instruction to build the complete website.

## Global Constraints

- No deployment, no remote Git push. Preserve the original two requirement documents.
- model=gpt-image-2, quality=low, size=1024x1024, background=transparent, output_format=png, n=1; image order template then avatar; omit input_fidelity.
- 12 independent images per numbered template set; fixed revision snapshots for templates and prompt.
- Default print A4 210×297 mm, effective content long edge 85 mm, 300 DPI, margins and gaps 10 mm; transparent per-set PNG pages named name_code_1.png (numbering starts at 1 for each set).
- One white-background full-order watermark overview: 4×3 tiles per set, each tile 256 px, sets vertically joined, 45° repeated watermark at 25% opacity. Each account has separate watermark.
- Global 5 starts/minute and 2 in flight by default, retries and reruns included. Unknown provider outcomes never automatically resubmitted.
- No secret or customer assets in Git or browser bundles. Local data ignored. All asset routes enforce owner/admin access.
- First-start admin setup is allowed only while no users exist, localhost app defaults bind 127.0.0.1; then invitation-only registration.
- Design: white workspace, narrow light-gray navigation rail, ink text, orange accent; dense but airy table-like order rows. Actual data, meaningful empty states, no fabricated production records.

## Shared HTTP Contract

JSON errors use {detail: string}; session via HttpOnly same-site cookie; unsafe methods verify Origin when present. All paths /api.

- GET /health; GET /auth/status -> {needs_setup:bool,user:User|null}; POST /auth/setup {username,password,display_name}; POST /auth/login {username,password}; POST /auth/logout; POST /auth/register {invite,username,password,display_name}; GET /auth/me.
- User {id,username,display_name,role,watermark,print_defaults}. PATCH /account {display_name?,watermark?,print_defaults?}. Password change {current_password,new_password} at POST /account/password.
- GET /admin/settings -> {rpm,max_inflight,prompt,prompt_version,openai_configured,cutout_configured}; PATCH /admin/settings {rpm?,max_inflight?,prompt?,openai_api_key?,cutout_api_key?}. Never return keys. POST /admin/invites -> {code}; GET /admin/users; PATCH /admin/users/{id} {active?}.
- GET /templates -> list of TemplateSet {id,code,name,category,active,revision,images:[{id,url,position}]}; POST /templates multipart {code,name,category,files[]}; PUT /templates/{id} multipart same fields plus existing_ids JSON for retained/reordered images, optional files[] replacements; PATCH /templates/{id} {active}. Exactly 12 valid independent images per active version; old revisions immutable.
- POST /uploads/init {filename,size,sha256} -> {id,offset,complete}; PUT /uploads/{id} raw bytes with Upload-Offset -> {id,offset,complete}; GET /uploads/{id}; POST /uploads/{id}/complete -> {id,filename,url}; duplicate chunks do not corrupt data. SHA256 validated, EXIF corrected.
- GET /orders -> Order[]; POST /orders {upload_id,name,template_ids,print_settings,client_token} -> Order. Unique per-account normalized name; client token prevents duplicate submissions. PrintSettings {paper_width_mm,paper_height_mm,long_edge_mm,margin_mm,gap_mm,dpi,brightness,color_balance}. Arrays persist set selection order.
- Order {id,name,status,created_at,total,completed,failed,unknown,paused,avatar_url,template_codes,print_settings,artifact_version,items?:Item[],artifacts?:Artifact[]}.
- GET /orders/{id} -> full Order; POST /orders/{id}/pause; POST /orders/{id}/resume; POST /orders/{id}/repack {print_settings}; POST /orders/{id}/watermark; POST /orders/{id}/items/{item_id}/rerun. Archived toggle via POST /orders/{id}/archive.
- Item {id,set_code,position,status,error,result_url,template_url,attempt}. Rerun keeps previous result visible, new attempt publishes only after success.
- GET /orders/{id}/manifest -> {order_id,name,version,complete,files:[Artifact]}; Artifact {id,path,url,sha256,size,kind}; GET /orders/{id}/download.zip; authenticated asset URLs from API; no public directory mount.

### Task 1: Backend and image pipeline

Files: backend/app/{main,db,auth,schemas,storage,processing,providers,worker}.py, backend/tests/, pyproject.toml.
Consumes: approved spec and HTTP contract above. Produces: working documented /api routes, persistent DB, worker lifecycle, tests with injectable provider.
- [ ] Add dependency config and test fixtures using temporary data root and injectable clock/provider; test registration isolation, uploads resume/hash, immutable template order.
- [ ] Implement account/session/invite management, owner-scoped assets, strict filenames and print parameter bounds, real multipart OpenAI client and optional Yezi cutout client with independent limiter.
- [ ] Implement durable claims/admission and lease lifecycle. Persist request starts transactionally. Pause affects only unstarted work. Startup classifies abandoned in-flight request as unknown; no unsafe double billing.
- [ ] Implement alpha-safe trim/resize/packing, physical DPI, immutable artifacts and manifest hashes, full-order watermark, optional brightness/color processing. Only publish complete per-set pages; keep good previous versions on failures.
- [ ] Test multiple orders/sets, single rerun and repack without provider calls, global limit across clients, refused/unknown provider errors, queue restart, transparent edges, output names and image dimensions.
- [ ] Run pytest, self-review, report all implemented endpoints and any gaps to root. Do not commit root-owned frontend files.

### Task 2: Designed React application and directory sync

Files: frontend/, package.json, scripts/dev launcher.
Consumes: HTTP contract. Produces: all requested working UI surfaces, first-admin onboarding, browser sync and ZIP fallback.
- [ ] Generate full-workspace concept before coding; save design direction and compare final render.
- [ ] Build API/session hooks, reusable controls, sidebar and separate functional pages for orders, templates, tasks, review, account, admin.
- [ ] Implement batch files + resumable uploads, order naming, per-row and bulk template selection, per-row and bulk print settings, task creation idempotency.
- [ ] Implement real per-item review/rerun, server progress vs device saved distinction, errors, unknown results and pause/resume.
- [ ] Store directory handle and local manifests in IndexedDB; use SHA256 reconciliation and version-checked writes; recover missing/stale files; refuse unowned name collisions; delete obsolete managed pages only after full new-version sync succeeds and old bytes match tracked hash.
- [ ] Test desktop and mobile views, keyboard access, no inert buttons, failures and folder permission loss, account/admin/template full forms, ZIP fallback.

### Task 3: Integration, review and delivery

Files: README.md, .env.example, verification docs; bounded fixes in frontend/backend.
- [ ] Start both servers on loopback, run Python and TypeScript build checks, use real browser UI to set up local admin and import test templates; test full workflow against controlled HTTP provider in isolated test data.
- [ ] Real API smoke test requires user-provided project API key; synthetic test avatar only. Missing credentials must remain an explicit unverified requirement, never fake success.
- [ ] Review security isolation, retries, version consistency, all 8 spec acceptance scenarios. Resolve actionable findings then rerun affected tests.
- [ ] Compare accepted concept and rendered desktop/mobile screenshots. Fix spacing, hierarchy, typography, copy and interaction discrepancies.
- [ ] Document local run/setup, account invite, template import, API configuration, directory sync, backup and known browser limits. Keep servers local; make local Git commits after verified milestones.
- [ ] Finish only with source evidence for complete implementation; distinguish automated verification from real paid API validation and physical print measurement.
