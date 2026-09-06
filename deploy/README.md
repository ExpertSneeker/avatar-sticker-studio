# DMIT production deployment

Production URL: https://sticker.magnusma.online

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
