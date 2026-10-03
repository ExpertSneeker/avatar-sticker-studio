"""Read-only FAL account billing, independent of generation credentials."""
import math
import re
import httpx
from fastapi import HTTPException


def fetch_balance(key):
    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            response = client.get('https://api.fal.ai/v1/account/billing',
                                  params={'expand': 'credits'},
                                  headers={'Authorization': 'Key ' + key})
    except httpx.TimeoutException:
        raise HTTPException(504, 'FAL 余额查询超时，请稍后重试') from None
    except httpx.RequestError:
        raise HTTPException(502, '无法连接 FAL，请稍后重试') from None
    if response.status_code != 200:
        message = {401: 'FAL ADMIN 密钥无效或已撤销，请更换密钥',
                   403: '此 FAL 密钥没有余额查询权限，请使用 ADMIN scope 的密钥',
                   429: 'FAL 查询过于频繁，请稍后重试'}.get(response.status_code, 'FAL 服务暂时不可用，请稍后重试')
        # Never relay upstream errors (which may contain credentials), or turn
        # upstream 401 into a website session-expired response.
        raise HTTPException(502, message)
    try:
        data = response.json()
        credits = data['credits']
        balance, currency, account = credits['current_balance'], credits['currency'], data['username']
        if (type(balance) not in (int, float) or not math.isfinite(balance)
                or not isinstance(currency, str) or not re.fullmatch(r'[A-Z]{3}', currency)
                or not isinstance(account, str) or not 1 <= len(account) <= 200):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise HTTPException(502, 'FAL 返回的余额数据不完整，请稍后重试') from None
    return {'account': account, 'current_balance': balance, 'currency': currency}
