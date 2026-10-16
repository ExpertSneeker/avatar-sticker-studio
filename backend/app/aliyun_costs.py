"""Daily OSS and ESA charges split over orders by the bytes each order caused.

Read-only: a dedicated RAM role (STUDIO_COST_RAM_ROLE_ARN), assumed from the ECS instance role, reads
the daily bill (BSS), ESA offline access logs and the bucket's OSS access logs. Each China day's actual
amounts are split by bytes; whatever cannot be tied to an order is shared (spread over the month's
orders by the cost report). OSS storage is shared: release backups hold almost all of it.
"""
import base64
import gzip
import hashlib
import hmac
import json
import logging
import os
import re
import shlex
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote
import httpx

log = logging.getLogger(__name__)
CHINA = timezone(timedelta(hours=8))
START_DAY = '2026-10-06'  # sticker.coreages.com moved behind ESA; OSS access logs exist from then on
LOG_PREFIX = 'oss-access-logs/'
ORDER_PATH = re.compile(r'^/api/(?:guest/media|customer-orders)/([0-9a-f]{32})(?:/|$|\?)')
ASSET_PATH = re.compile(r'^/api/assets/([0-9a-f]{32})')
PRINT_KEY = re.compile(r'^print/[^/]+/([0-9a-f]{32})/')
INPUT_KEY = re.compile(r'^fal-inputs/(\d{8})/([0-9a-f]{64})\.png$')


def _enc(value):
    return quote(str(value), safe='-_.~')


class Aliyun:
    """Minimal signed RPC (signature v1) plus OSS log access with temporary credentials."""
    def __init__(self, role_arn, source_role, region, bucket, endpoint, site_id):
        self.role_arn, self.source_role, self.region, self.bucket, self.endpoint, self.site_id = role_arn, source_role, region, bucket, endpoint, site_id
        self.creds = None

    @classmethod
    def from_env(cls):
        role = os.environ.get('STUDIO_COST_RAM_ROLE_ARN', '').strip()
        bucket = os.environ.get('STUDIO_OSS_BUCKET', '').strip()
        if not role or not bucket:
            return None
        return cls(role, os.environ.get('STUDIO_OSS_RAM_ROLE', 'sticker-ecs-oss'), os.environ.get('STUDIO_OSS_REGION', 'cn-wulanchabu'), bucket,
                   os.environ.get('STUDIO_OSS_INTERNAL_ENDPOINT', 'oss-cn-wulanchabu-internal.aliyuncs.com'), os.environ.get('STUDIO_ESA_SITE_ID', '').strip())

    def rpc(self, host, version, action, creds, **params):
        ak, sk, token = creds
        p = {'Format': 'JSON', 'Version': version, 'AccessKeyId': ak, 'SignatureMethod': 'HMAC-SHA1', 'SignatureVersion': '1.0',
             'SignatureNonce': uuid.uuid4().hex, 'Timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'Action': action, **params}
        if token:
            p['SecurityToken'] = token
        query = '&'.join(f'{_enc(k)}={_enc(p[k])}' for k in sorted(p))
        signature = base64.b64encode(hmac.new((sk + '&').encode(), ('GET&%2F&' + _enc(query)).encode(), hashlib.sha1).digest()).decode()
        response = httpx.get(f'https://{host}/?{query}&Signature={_enc(signature)}', timeout=30)
        data = response.json()
        if response.status_code != 200:
            # Error bodies carry only a code and request id; never credentials.
            raise RuntimeError(f"{action} {response.status_code} {data.get('Code')}")
        return data

    def credentials(self):
        if self.creds and self.creds[1] > time.time() + 300:
            return self.creds[0]
        from alibabacloud_credentials.client import Client as CredentialsClient
        from alibabacloud_credentials.models import Config as CredentialsConfig
        source = CredentialsClient(CredentialsConfig(type='ecs_ram_role', role_name=self.source_role, disable_imds_v1=True,
                                                     timeout=3000, connect_timeout=3000)).get_credential()
        data = self.rpc(f'sts.{self.region}.aliyuncs.com', '2015-04-01', 'AssumeRole',
                        (source.access_key_id, source.access_key_secret, source.security_token),
                        RoleArn=self.role_arn, RoleSessionName='sticker-costs', DurationSeconds=3600)['Credentials']
        self.creds = ((data['AccessKeyId'], data['AccessKeySecret'], data['SecurityToken']), time.time() + 3500)
        return self.creds[0]

    def bill(self, day, product):
        """Daily bill lines of one product: [(InstanceID, BillingItem, SubscriptionType, PretaxAmount)]."""
        lines, token = [], None
        while True:
            params = dict(BillingCycle=day[:7], BillingDate=day, Granularity='DAILY', ProductCode=product, IsBillingItem='true', MaxResults=300)
            if token:
                params['NextToken'] = token
            data = self.rpc('business.aliyuncs.com', '2017-12-14', 'DescribeInstanceBill', self.credentials(), **params)['Data']
            lines += [(i.get('InstanceID') or '', i.get('BillingItem') or '', i.get('SubscriptionType') or '', float(i.get('PretaxAmount') or 0))
                      for i in data.get('Items', [])]
            token = data.get('NextToken')
            if not token:
                return lines

    def subscriptions(self, cycle, product):
        """Prepaid lines of a month: [(amount, months)] — the ESA plan fee."""
        data = self.rpc('business.aliyuncs.com', '2017-12-14', 'DescribeInstanceBill', self.credentials(),
                        BillingCycle=cycle, ProductCode=product, IsBillingItem='true', MaxResults=300)['Data']
        return [(float(i.get('PretaxAmount') or 0), int(i.get('ServicePeriod') or 0) if i.get('ServicePeriodUnit') == '月' else 0)
                for i in data.get('Items', []) if i.get('SubscriptionType') == 'Subscription']

    def esa_rows(self, day):
        """Every ESA access log row of one China day."""
        start = datetime.fromisoformat(day).replace(tzinfo=CHINA).astimezone(timezone.utc)
        params = dict(SiteId=self.site_id, StartTime=start.strftime('%Y-%m-%dT%H:%M:%SZ'),
                      EndTime=(start + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ'), PageSize=100)
        files, page = [], 1
        while True:
            data = self.rpc('esa.cn-hangzhou.aliyuncs.com', '2024-09-10', 'DescribeSiteLogs', self.credentials(), PageNumber=page, **params)
            batch = [l['LogPath'] for s in data.get('SiteLogDetails', []) for l in s.get('LogInfos', [])]
            files += batch
            if len(batch) < 100:
                break
            page += 1
        for path in files:
            content = httpx.get('https://' + path, timeout=60).content
            for line in gzip.decompress(content).decode('utf-8', 'replace').splitlines():
                try:
                    yield json.loads(line)
                except ValueError:
                    continue

    def oss_lines(self, day):
        """Raw OSS access log lines from files that may hold requests of this China day."""
        import alibabacloud_oss_v2 as oss
        ak, sk, token = self.credentials()
        client = oss.Client(oss.Config(region=self.region, endpoint=self.endpoint,
                                       credentials_provider=oss.credentials.StaticCredentialsProvider(ak, sk, token)))
        names = {(datetime.fromisoformat(day) + timedelta(days=d)).strftime('%Y-%m-%d') for d in (-1, 0, 1)}
        token_ = None
        while True:
            result = client.list_objects_v2(oss.ListObjectsV2Request(bucket=self.bucket, prefix=LOG_PREFIX, continuation_token=token_, max_keys=1000))
            for item in result.contents or []:
                if any(self.bucket + name in item.key for name in names):
                    body = client.get_object(oss.GetObjectRequest(bucket=self.bucket, key=item.key)).body.read()
                    yield from body.decode('utf-8', 'replace').splitlines()
            if not result.is_truncated:
                return
            token_ = result.next_continuation_token


def oss_requests(lines, day):
    """(key, bytes) of public-network GET/HEAD downloads on the China day; internal traffic is free."""
    for line in lines:
        try:
            p = shlex.split(line)
            when = datetime.strptime(p[3].lstrip('[') + ' ' + p[4].rstrip(']'), '%d/%b/%Y:%H:%M:%S %z')
            method, path = p[5].split(' ')[:2]
            sent = int(p[7]) if p[7].isdigit() else 0
        except (ValueError, IndexError):
            continue
        if when.astimezone(CHINA).date().isoformat() != day or '-internal' in p[11] or method not in ('GET', 'HEAD') or not sent:
            continue
        yield unquote(path.split('?')[0].lstrip('/')), sent


def split_oss(requests, input_users):
    """Bytes per order (None = shared). Print files carry the order id; an FAL input is shared by the
    items that used that image on that day."""
    shares = {}
    for key, sent in requests:
        match = PRINT_KEY.match(key)
        if match:
            shares[match.group(1)] = shares.get(match.group(1), 0) + sent
            continue
        match = INPUT_KEY.match(key)
        users = input_users.get((match.group(1), match.group(2))) if match else None
        if users:
            for order_id in users:
                shares[order_id] = shares.get(order_id, 0) + sent / len(users)
        else:
            shares[None] = shares.get(None, 0) + sent
    return shares


def input_users(tx, days):
    """(UTC yyyymmdd, sha256) -> order ids, one per item that sent that image to FAL that day."""
    sha = {a['id']: a.get('sha256') for a in tx.all('assets') if a.get('sha256')}
    users = {}
    for item in tx.all('items'):
        if not item.get('started_at') or item.get('source') == 'design':
            continue
        date = datetime.fromtimestamp(item['started_at'], timezone.utc).strftime('%Y%m%d')
        if date not in days:
            continue
        for asset in (item.get('template_id'), item.get('avatar_id')):
            if sha.get(asset):
                users.setdefault((date, sha[asset]), []).append(item['order_id'])
    return users


def split_esa(rows, assets):
    """Bytes per order (None = shared) for the sticker site. Order media paths and order assets are
    direct; other requests of a visitor IP that opened exactly one order's media that day (catalog
    images, pages, guest API) go to that order; the rest is shared (library work, polling, static)."""
    rows = [r for r in rows if r.get('ClientRequestHost') == 'sticker.coreages.com']
    owner, guest_ips, staff_ips = {}, {}, set()
    for r in rows:
        uri = r.get('ClientRequestURI', '')
        if uri.startswith('/api/guest/media/') and ORDER_PATH.match(uri):
            guest_ips.setdefault(r.get('ClientIP'), set()).add(ORDER_PATH.match(uri).group(1))
        elif uri.startswith('/api/') and not uri.startswith('/api/guest/') and not uri.startswith('/api/ready'):
            staff_ips.add(r.get('ClientIP'))
    for ip, orders in guest_ips.items():
        if len(orders) == 1 and ip not in staff_ips:
            owner[ip] = next(iter(orders))
    shares = {}
    for r in rows:
        sent = int(r.get('EdgeResponseBytes') or 0)
        uri = r.get('ClientRequestURI', '')
        match = ORDER_PATH.match(uri)
        order_id = match.group(1) if match else None
        if not order_id and (match := ASSET_PATH.match(uri)):
            order_id = assets.get(match.group(1))
        if not order_id:
            order_id = owner.get(r.get('ClientIP'))
        shares[order_id] = shares.get(order_id, 0) + sent
    return shares


def entries_for(day, source, amount, shares, orders):
    """Split one day's amount by bytes; unknown or deleted orders fall to the shared entry."""
    total = sum(shares.values())
    result, shared = [], amount
    for order_id, sent in shares.items():
        if order_id is None or order_id not in orders or not total:
            continue
        part = amount * sent / total
        shared -= part
        result.append({'id': f'{source}:{day}:{order_id}', 'source': source, 'order_id': order_id, 'organization_id': orders[order_id],
                       'day': day, 'quantity': round(sent), 'amount_cny': round(part, 6), 'basis': 'split'})
    result.append({'id': f'{source}:{day}:shared', 'source': source, 'order_id': None, 'day': day, 'shared': True,
                   'quantity': round(shares.get(None, 0)), 'amount_cny': round(max(shared, 0.0), 6), 'basis': 'split'})
    return result


def esa_plan_daily(db, client, day):
    """The prepaid ESA plan spread evenly over its service days (cached once found)."""
    with db.transaction(readonly=True) as tx:
        plan = tx.get('cost_sync', 'esa-plan')
    if not plan:
        found = []
        for cycle in sorted({day[:7], START_DAY[:7]}):
            found += client.subscriptions(cycle, 'dcdn')
        found = [(amount, months) for amount, months in found if amount and months]
        if not found:
            return 0.0
        amount, months = found[0]
        plan = {'id': 'esa-plan', 'amount': amount, 'months': months}
        with db.transaction() as tx:
            tx.put('cost_sync', plan)
    return plan['amount'] / (plan['months'] * 365 / 12)


def sync_day(db, client, day):
    oss_bill = [(i, item, kind, amount) for i, item, kind, amount in client.bill(day, 'oss') if i.startswith(client.region)]
    if not oss_bill:
        return False  # the day's bill is not out yet
    traffic = sum(a for _, item, _, a in oss_bill if '流出' in item)
    rest = sum(a for _, item, _, a in oss_bill if '流出' not in item)
    esa_payg = sum(a for product in ('dcdn', 'esa') for _, _, kind, a in client.bill(day, product) if kind != 'Subscription')
    esa_cost = esa_plan_daily(db, client, day) + esa_payg
    with db.transaction(readonly=True) as tx:
        orders = {o['id']: o.get('organization_id') for o in tx.all('orders')}
        assets = {a['id']: a['order_id'] for a in tx.all('assets') if a.get('order_id')}
        days = {(datetime.fromisoformat(day) + timedelta(days=d)).strftime('%Y%m%d') for d in (-1, 0)}
        users = input_users(tx, days)
    oss_shares = split_oss(oss_requests(client.oss_lines(day), day), users)
    esa_shares = split_esa(client.esa_rows(day), assets) if client.site_id else {}
    entries = entries_for(day, 'oss', traffic, oss_shares, orders)
    entries.append({'id': f'oss-storage:{day}', 'source': 'oss', 'order_id': None, 'day': day, 'shared': True,
                    'quantity': 0, 'amount_cny': round(rest, 6), 'basis': 'bill'})
    entries += entries_for(day, 'esa', esa_cost, esa_shares, orders)
    with db.transaction() as tx:
        for entry in tx.find('cost_entries', ("json_extract(doc,'$.day')=? AND json_extract(doc,'$.source') IN ('oss','esa')", (day,))):
            tx.delete('cost_entries', entry['id'])
        for entry in entries:
            tx.put('cost_entries', entry)
        tx.put('cost_sync', {'id': 'aliyun', 'day': day})
    return True


def sync_aliyun(db, now, client=None, *, max_days=2):
    """Days whose bill is final (two days back), oldest first, from START_DAY."""
    client = client or Aliyun.from_env()
    if client is None:
        return 0
    with db.transaction(readonly=True) as tx:
        last = (tx.get('cost_sync', 'aliyun') or {}).get('day')
    day = (datetime.fromisoformat(last) + timedelta(days=1)).date().isoformat() if last else START_DAY
    final = datetime.fromtimestamp(now, CHINA).date() - timedelta(days=2)
    done = 0
    while done < max_days and datetime.fromisoformat(day).date() <= final:
        if not sync_day(db, client, day):
            break
        done += 1
        day = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    return done
