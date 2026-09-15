"""Strict, fixed-origin Agiso protocol. No provider detail is returned to clients."""
import hashlib
import logging
import os
from decimal import Decimal, InvalidOperation
from datetime import datetime
from urllib.parse import urlsplit
import httpx
from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .schemas import safe_name

MAX_BODY = 256 * 1024
ENV = ('STUDIO_AGISO_APP_ID', 'STUDIO_AGISO_APP_SECRET', 'STUDIO_AGISO_ENCRYPTION_KEY', 'STUDIO_AGISO_PUBLIC_URL')


def settings():
    values = {key: os.environ.get(key, '').strip() for key in ENV}
    missing = [key for key, value in values.items() if not value]
    origin = values[ENV[3]].rstrip('/')
    parsed = urlsplit(origin)
    if origin and (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path):
        missing.append(ENV[3])
    try:
        cipher = Fernet(values[ENV[2]].encode())
    except Exception:
        cipher = None
        if ENV[2] not in missing: missing.append(ENV[2])
    return {'configured':not missing, 'missing':missing, 'origin':origin, 'app_id':values[ENV[0]], 'secret':values[ENV[1]], 'cipher':cipher,
            'aftersales_enabled':os.environ.get('STUDIO_AGISO_AFTERSALES_VERIFIED') == '1'}


def sign(secret, fields):
    return hashlib.md5((secret + ''.join(key + str(fields[key]) for key in sorted(fields)) + secret).encode()).hexdigest()


def identifier(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('invalid identifier')
    value = str(value)
    if not value or len(value)>100 or value.strip()!=value or any(ord(c)<32 or c in '/\\' for c in value):
        raise ValueError('invalid identifier')
    return value


class Payload(BaseModel):
    model_config = ConfigDict(extra='ignore')


class Item(Payload):
    goods_id: str
    sku_id: str
    goods_count: int = Field(strict=True, gt=0, le=1000000)
    goods_name: str = Field('', max_length=1000)
    goods_spec: str = Field('', max_length=1000)
    _ids = field_validator('goods_id','sku_id',mode='before')(identifier)


class Trade(Payload):
    MallId: str
    Tid: str
    OrderSn: str
    ConfirmTime: str = Field(min_length=1,max_length=100)
    CreatedTime: str = Field(min_length=1,max_length=100)
    PayAmount: str
    ItemList: list[Item] = Field(min_length=1,max_length=200)
    _ids = field_validator('MallId','Tid','OrderSn',mode='before')(identifier)
    _number = field_validator('OrderSn')(safe_name)

    @field_validator('ConfirmTime','CreatedTime')
    @classmethod
    def confirmed_time(cls,value):
        try:
            parsed=datetime.fromisoformat(value)
            if parsed.year<2000 or len(value)<19: raise ValueError()
        except ValueError:
            raise ValueError('invalid confirmation time')
        return value

    @field_validator('PayAmount',mode='before')
    @classmethod
    def amount(cls,value):
        if isinstance(value,bool): raise ValueError('invalid amount')
        try:
            amount=Decimal(str(value))
            if not amount.is_finite() or amount<0 or amount>1000000000 or amount*100 != (amount*100).to_integral_value():
                raise ValueError('invalid amount')
            return str(amount)
        except InvalidOperation:
            raise ValueError('invalid amount')


class Refund(Payload):
    mall_id: str
    tid: str
    refund_id: str
    bill_type: int = Field(strict=True,ge=1,le=100)
    refund_fee: int = Field(strict=True,ge=0)
    modified: int = Field(strict=True,gt=0)
    operation: int = Field(strict=True,ge=0)
    _ids = field_validator('mall_id','tid','refund_id',mode='before')(identifier)


class Rule(BaseModel):
    model_config = ConfigDict(extra='forbid')
    goods_id: str
    sku_id: str
    goods_name: str = Field('',max_length=1000)
    sku_name: str = Field('',max_length=1000)
    generation_limit: int = Field(strict=True,ge=1,le=360)
    final_count: int = Field(strict=True,ge=1,le=360)
    rerun_limit: int = Field(strict=True,ge=0,le=1000)
    enabled: bool = Field(False,strict=True)
    _ids = field_validator('goods_id','sku_id',mode='before')(identifier)

    @model_validator(mode='after')
    def limits(self):
        if self.final_count>self.generation_limit: raise ValueError('最终数量不能超过生成上限')
        return self


class Rules(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rules: list[Rule] = Field(max_length=1000)

    @model_validator(mode='after')
    def unique(self):
        if len({(r.goods_id,r.sku_id) for r in self.rules})!=len(self.rules): raise ValueError('商品规格不能重复')
        return self


class Enabled(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = Field(strict=True)


class ProtocolError(Exception):
    pass


def token_aliases(data, names):
    if not isinstance(data,dict): raise ProtocolError()
    result=dict(data)
    for name in names:
        alias=name[0].lower()+name[1:]
        if name in data and alias in data:
            if type(data[name]) is not type(data[alias]) or data[name]!=data[alias]: raise ProtocolError()
        if alias in data: result[name]=data[alias]
    return result


async def request_json(method,url,transport=None,token_response=False,**kwargs):
    async with httpx.AsyncClient(transport=transport, timeout=15, follow_redirects=False) as client:
        async with client.stream(method,url,**kwargs) as response:
            response.raise_for_status()
            data=bytearray()
            async for part in response.aiter_bytes():
                data.extend(part)
                if len(data)>1024*1024: raise ProtocolError()
    import json
    result=json.loads(data)
    if token_response:
        if isinstance(result,dict):
            payload=result.get('Data',result.get('data'))
            names=('FromPlatform','ShopId','ShopName','Token','ExpiresIn')
            types={name:type(payload.get(name,payload.get(name[0].lower()+name[1:]))).__name__ for name in names} if isinstance(payload,dict) else {}
            identity=payload.get('UserId',payload.get('userId')) if isinstance(payload,dict) else None
            identity_hash=hashlib.sha256(str(identity).encode()).hexdigest() if type(identity) in (str,int) else 'missing'
            logging.getLogger(__name__).warning('Agiso token UserId digest=%s',identity_hash)
            success=result.get('IsSuccess',result.get('isSuccess'))
            error=result.get('Error_Code',result.get('error_Code'))
            logging.getLogger(__name__).warning('Agiso token schema: success=%s error_code=%s fields=%s',success if type(success) is bool else 'invalid',error if type(error) is int else 'unavailable',types)
        result=token_aliases(result,('IsSuccess','Data'))
    if not isinstance(result,dict) or type(result.get('IsSuccess')) is not bool:
        raise ProtocolError()
    return result


async def exchange(code,config,transport,now):
    fields={'appId':config['app_id'],'code':code}
    result=await request_json('GET','https://aldspdd.agiso.com/auth/token',transport,token_response=True,params={**fields,'sign':sign(config['secret'],fields)})
    data=result.get('Data')
    if isinstance(data,dict):
        data=token_aliases(data,('FromPlatform','ShopId','UserId','ShopName','Token','ExpiresIn'))
    if result['IsSuccess'] is not True or not isinstance(data,dict) or data.get('FromPlatform') not in ('PddAlds','AldsPdd'):
        platform=data.get('FromPlatform') if isinstance(data,dict) else None
        logging.getLogger(__name__).warning('Agiso platform mismatch: %s',platform if isinstance(platform,str) and platform.isalnum() and len(platform)<32 else 'invalid')
        raise ProtocolError()
    shop_id=identifier(data.get('ShopId') if data.get('ShopId') is not None else data.get('UserId'))
    if data.get('ShopId') is not None and data.get('UserId') is not None and identifier(data['UserId'])!=shop_id:
        raise ProtocolError()
    token=data.get('Token');expires=data.get('ExpiresIn');name=data.get('ShopName')
    if not isinstance(token,str) or not token or len(token)>16384 or type(expires) is not int or expires<=0 or not isinstance(name,str) or len(name)>1000:
        raise ProtocolError()
    return {'shop_id':shop_id,'shop_name':name,'token':config['cipher'].encrypt(token.encode()).decode(),'expires_at':now+expires}


async def api(path,fields,shop,config,transport,now):
    fields={**fields,'timestamp':str(int(now))}
    token=config['cipher'].decrypt(shop['token'].encode()).decode()
    return await request_json('POST','https://gw-api.agiso.com/aldsPdd/'+path,transport,
                              data={**fields,'sign':sign(config['secret'],fields)},headers={'Authorization':'Bearer '+token,'ApiVersion':'1'})
