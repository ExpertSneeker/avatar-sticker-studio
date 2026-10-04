"""Customer-order fixtures exercise current HTTP contracts on isolated test apps."""
import asyncio
import hashlib
import io
from uuid import uuid4
from PIL import Image
from fastapi.testclient import TestClient

def png(color=(180, 50, 30, 180), size=(32, 32)):
    image = Image.new('RGBA', size)
    image.paste(color, (4, 4, size[0] - 4, size[1] - 4))
    out = io.BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


def upload(client, data=None):
    data = data or png()
    result = client.post('/api/uploads/init', json={'filename': '头像.png', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}).json()
    assert client.put('/api/uploads/' + result['id'], content=data, headers={'Upload-Offset': '0'}).status_code == 200
    response = client.post('/api/uploads/' + result['id'] + '/complete')
    assert response.status_code == 200, response.text
    return response.json()


def template(client, code='A01'):
    response = client.post('/api/stickers', data={'category': 'boy'}, files=[('files', (f'{code}-{i+1:02}.png', png((i * 10, 50, 20, 200)), 'image/png')) for i in range(12)])
    assert response.status_code == 200, response.text
    response = client.post('/api/templates', json={'code':code, 'name':'测试套装', 'category':'boy', 'sticker_ids':[s['id'] for s in response.json()]})
    assert response.status_code == 200, response.text
    return response.json()



def member(client, app, name='member'):
    response=client.post('/api/admin/users',json={'username':name,'display_name':name})
    assert response.status_code==200,response.text
    account=response.json()
    other=TestClient(app)
    assert other.post('/api/auth/login',json={'username':name,'password':account['temporary_password']}).status_code==200
    return other,account['user']


def create_customer_order(client, name='测试订单', count=12, token=None, **fields):
    body={'order_number':name+'-'+uuid4().hex[:8], 'generation_limit':count, 'final_count':count,
          'rerun_limit':count, 'client_token':token or uuid4().hex, **fields}
    response=client.post('/api/customer-orders',json=body)
    assert response.status_code==200,response.text
    return response.json(),body


def customer_action(client, order, action, **fields):
    value=client.get('/api/customer-orders/'+order['id']).json()
    return client.post('/api/customer-orders/'+order['id']+'/'+action,
                       json={'expected_version':value['version'],'client_token':uuid4().hex,**fields})


def generate_customer_order(client, order, *, template_ids=(), sticker_ids=(), upload_id=None):
    body={'avatars':[{'upload_id':upload_id or upload(client)['id'], 'template_ids':list(template_ids),'sticker_ids':list(sticker_ids)}]}
    response=customer_action(client,order,'generate',**body)
    assert response.status_code==200,response.text
    return response.json()


def order_items(app, order):
    with app.state.db.transaction(readonly=True) as tx:
        return [i for i in tx.all('items') if i['order_id']==order['id']]


def stored_order(app, order):
    with app.state.db.transaction(readonly=True) as tx:
        return tx.get('orders',order['id'])


def slot_for(app, order, item):
    return next(s for s in stored_order(app,order)['slots'] if s['active_item_id']==item['id'])


def submit_and_publish(app, client, order):
    value=client.get('/api/customer-orders/'+order['id']).json()
    response=customer_action(client,order,'submit',slot_ids=[s['id'] for s in value['slots']][:value['final_count']])
    assert response.status_code==200,response.text
    app.state.worker.publish(order['id'])
    return client.get('/api/customer-orders/'+order['id']).json()


def run_all(app):
    while (item:=app.state.worker.claim()) is not None:
        asyncio.run(app.state.worker.execute(item))


def order(client, name='小明', template_ids=None):
    template_ids=template_ids or [template(client)['id']]
    templates={t['id']:t for t in client.get('/api/templates').json()}
    count=sum(len(templates[id]['images']) for id in template_ids)
    value,body=create_customer_order(client,name,count)
    result=generate_customer_order(client,value,template_ids=template_ids)
    return result, {'create':body,'template_ids':template_ids}
