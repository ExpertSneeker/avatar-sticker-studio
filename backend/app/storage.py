import hashlib
import io
import os
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException
from .db import uid

Image.MAX_IMAGE_PIXELS = 30_000_000


def normalize_image(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {'PNG', 'JPEG', 'WEBP'} or image.width * image.height > 30_000_000:
                raise ValueError('只支持JPG、PNG、WebP且像素总量不得超过3000万')
            image = ImageOps.exif_transpose(image).convert('RGBA')
            image.load()
            out = io.BytesIO()
            image.save(out, 'PNG')
            return out.getvalue()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(400, '图片无法解码或尺寸超限') from exc


def save_asset(db, tx, data, owner, kind='result', order_id=None, organization_id=None):
    id = uid()
    path = db.root / 'assets' / (id + '.png')
    path.parent.mkdir(exist_ok=True, mode=0o700)
    with path.open('xb') as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    os.chmod(path, 0o600)
    doc = {'id': id, 'owner': owner, 'kind': kind, 'file': path.name, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), 'url': '/api/assets/' + id}
    if organization_id is not None:
        doc['organization_id'] = organization_id
    if order_id:
        doc['order_id'] = order_id
    tx.put('assets', doc)
    return doc


def asset_bytes(db, asset):
    return (db.root / 'assets' / asset['file']).read_bytes()
