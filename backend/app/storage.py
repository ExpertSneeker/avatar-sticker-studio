import hashlib
import io
import os
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException
from .db import uid

Image.MAX_IMAGE_PIXELS = 30_000_000
# Generation inputs: templates scale (up or down) to a 1024px long edge; avatars only shrink to a 1024px short edge.
TEMPLATE_EDGE = 1024
AVATAR_SHORT_EDGE = 1024


def fitted_size(width, height, fit=None):
    if fit == 'template':
        scale = TEMPLATE_EDGE / max(width, height)
    elif fit == 'avatar':
        scale = min(1, AVATAR_SHORT_EDGE / min(width, height))
    else:
        return width, height
    return max(1, round(width * scale)), max(1, round(height * scale))


def normalize_image(data, fit=None):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {'PNG', 'JPEG', 'WEBP'} or image.width * image.height > 30_000_000:
                raise ValueError('只支持JPG、PNG、WebP且像素总量不得超过3000万')
            image = ImageOps.exif_transpose(image).convert('RGBA')
            image.load()
            size = fitted_size(*image.size, fit)
            if size != image.size:
                image = image.resize(size, Image.Resampling.LANCZOS)
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
