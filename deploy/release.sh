#!/bin/bash
# Production release with a paired full backup and only a few seconds of downtime.
#
# Run as root on the server:  bash deploy/release.sh /tmp/<commit>.tgz <label>
# The tarball holds one top-level directory named after the commit (git archive + built
# frontend/dist + REVISION). Steps:
#   1. unpack the release next to the current one, keeping the previous build's hashed assets;
#   2. copy the data directory while the service still runs (the slow part, no downtime);
#   3. stop, re-sync only what changed, prove the copy equals the stopped data, switch, start;
#   4. with the service back, hash the static copy, audit it as the baseline, audit live data,
#      then archive the backup to OSS and prune to the newest three snapshots.
# If the new release does not become ready, the previous release is started again. Code-only
# rollback cannot undo a startup migration; see deploy/README.md.
set -euo pipefail

TARBALL=${1:?usage: release.sh <tarball> <label>}
LABEL=${2:?usage: release.sh <tarball> <label>}
R=/opt/avatar-sticker-studio
DATA=/var/lib/avatar-sticker-studio
SERVICE=avatar-sticker-studio
PY=$R/venv/bin/python
AUDIT_MODE=${AUDIT_MODE:---allow-oss-delivery}

step() { printf '[%s] %s\n' "$(date +%T)" "$*"; }
ready() { [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/ready || true)" = 200 ]; }

# The tarball is named <commit>.tgz; REVISION inside it is checked after unpacking.
REV=$(basename "$TARBALL" .tgz)
NEW=$R/releases/$REV
PREV=$(readlink -f $R/current)
B=$R/backups/$LABEL-$(date -u +%Y%m%dT%H%M%SZ)-$REV
[ -n "$REV" ] && [ ! -e "$NEW" ] || { echo "release $REV already present"; exit 1; }

step "unpack $REV (previous $(basename "$PREV"))"
umask 022
tar -xzf "$TARBALL" -C $R/releases --no-same-owner 2>/dev/null
[ "$(cat "$NEW/REVISION")" = "$REV" ]
# Pages still open on the old build lazy-load chunks by hashed name; keep those files available.
cp -n "$PREV"/frontend/dist/assets/* "$NEW"/frontend/dist/assets/
chown -R --reference="$PREV" "$NEW"
chmod --reference="$PREV" "$NEW"

umask 077
mkdir -p "$B"
echo "$PREV" > "$B/previous-release.txt"
cp -a /etc/avatar-sticker-studio.env "$B/production.env"

step "queue before stop"
python3 - "$DATA" <<'PY'
import collections, json, sqlite3, sys
c = sqlite3.connect(f'file:{sys.argv[1]}/studio.sqlite3?mode=ro', uri=True)
busy = collections.Counter()
for kind, doc in c.execute("select kind, doc from records where kind in ('items','agiso_events','agiso_outbox')"):
    d = json.loads(doc); s = d.get('status')
    if kind == 'items' and (s in ('queued', 'running', 'unknown') or d.get('remote_reserved') or d.get('cutout_inflight')): busy[f'items:{s}'] += 1
    if kind == 'agiso_events' and s in ('pending', 'processing'): busy[f'agiso_events:{s}'] += 1
    if kind == 'agiso_outbox' and s in ('pending', 'claimed', 'sending'): busy[f'agiso_outbox:{s}'] += 1
print('busy', dict(busy), '(queued work resumes after restart; FAL request IDs are kept)')
PY

step "copy data while the service runs"
rsync -a --delete "$DATA/" "$B/data/"

step "stop $SERVICE"
START=$(date +%s.%N)
systemctl stop $SERVICE
rsync -a --delete "$DATA/" "$B/data/"
# Same names, sizes and times everywhere, and identical database bytes: the copy is the stopped state.
if [ -n "$(rsync -a --delete --dry-run --itemize-changes "$DATA/" "$B/data/")" ]; then
  echo "backup copy differs from stopped data; starting the previous release again"
  systemctl start $SERVICE; exit 1
fi
for f in "$DATA"/studio.sqlite3*; do
  [ "$(sha256sum < "$f")" = "$(sha256sum < "$B/data/$(basename "$f")")" ] || { echo "database copy mismatch"; systemctl start $SERVICE; exit 1; }
done

ln -sfn "$NEW" $R/current.new && mv -T $R/current.new $R/current
systemctl start $SERVICE
for _ in $(seq 1 90); do ready && break; sleep 1; done
if ! ready; then
  echo "new release not ready; switching back to $PREV"
  ln -sfn "$PREV" $R/current.new && mv -T $R/current.new $R/current
  systemctl restart $SERVICE
  exit 1
fi
step "ready on $REV, downtime $(python3 -c "import time;print(round(time.time()-$START,1))")s"

step "hash the backup copy"
python3 - "$B/data" "$B/data-sha256.json" <<'PY'
import hashlib, json, os, sys
root, out = sys.argv[1:]
manifest = {}
for d, _, files in os.walk(root):
    for name in files:
        path = os.path.join(d, name); h = hashlib.sha256()
        with open(path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b''): h.update(chunk)
        manifest[os.path.relpath(path, root)] = h.hexdigest()
json.dump(manifest, open(out, 'w')); print('files', len(manifest))
PY

step "audit: snapshot baseline, then live data"
cd "$NEW"
$PY deploy/audit_framework.py --data-dir "$B/data" $AUDIT_MODE > "$B/audit-before.json"
$PY deploy/audit_framework.py --data-dir "$DATA" $AUDIT_MODE --baseline "$B/audit-before.json" > "$B/audit-after.json" || true
python3 - "$B/audit-after.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print('failures', d['failures'], 'integrity', d['integrity'], 'inflight', d['inflight'], 'queued', d['queued'])
sys.exit(1 if d['failures'] or d['integrity'] != 'ok' else 0)
PY

step "archive to OSS and keep the newest three snapshots"
set -a; . /etc/avatar-sticker-studio.env; set +a
$PY deploy/backup_archive.py --archive "$B" --verify-readback | grep -E '"key"|"verified"'
$PY deploy/backup_archive.py --prune --apply > /dev/null
ls $R/backups/
step "done: $REV live, backup $(basename "$B")"
