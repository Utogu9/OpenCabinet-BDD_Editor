"""Full-cover material maps are linear RGBA data, never lossy artwork."""
from io import BytesIO
from pathlib import Path

from PIL import Image

from editor_common import digest
from i18n import tr

KIND = 'cover_full_material'
POLICY = 'cover-full-material-png-v1'


def lossless_webp(raw):
    """Check the actual RIFF image chunk, including extended/alpha WebP files."""
    if raw[:4] != b'RIFF' or raw[8:12] != b'WEBP':
        return False
    offset = 12
    while offset + 8 <= len(raw):
        chunk = raw[offset:offset + 4]
        size = int.from_bytes(raw[offset + 4:offset + 8], 'little')
        if offset + 8 + size > len(raw):
            return False
        if chunk in (b'VP8 ', b'VP8L'):
            return chunk == b'VP8L'
        offset += 8 + size + (size & 1)
    return False


def encode_material(path):
    """Save 8-bit RGBA as PNG without colour transforms, EXIF rotation or alpha flattening."""
    path = Path(path)
    if path.stat().st_size > 100 * 1024**2:
        raise ValueError(tr('The image exceeds 100 MiB'))
    raw = path.read_bytes()
    with Image.open(BytesIO(raw)) as source:
        if source.format not in {'PNG', 'WEBP'}:
            raise ValueError(tr('Material maps require an 8-bit RGBA PNG or lossless WebP; AVIF and JPEG are not supported.'))
        if getattr(source, 'n_frames', 1) != 1:
            raise ValueError(tr('The image must be static'))
        if source.width * source.height > 40_000_000:
            raise ValueError(tr('The image exceeds 40 megapixels'))
        if source.format == 'PNG' and (source.mode != 'RGBA' or raw[24:26] != bytes((8, 6))):
            raise ValueError(tr('Material PNG files must use RGBA with 8 bits per channel.'))
        if source.format == 'WEBP' and not lossless_webp(raw):
            raise ValueError(tr('Material WebP files must be lossless. Export with lossless and exact enabled to retain hidden RGB values.'))
        image = source.convert('RGBA')
        # Remove colour/EXIF metadata: the channels are independent numeric data.
        image.info.clear()
        buffer = BytesIO()
        image.save(buffer, format='PNG', compress_level=9)
        data = buffer.getvalue()
        with Image.open(BytesIO(data)) as check:
            if check.mode != 'RGBA' or check.size != image.size or check.tobytes() != image.tobytes():
                raise ValueError(tr('Lossless conversion changed the pixels'))
        return {'data': data, 'original': raw, 'filename': path.name,
                'sha256': digest(data), 'source_sha256': digest(raw), 'source_format': source.format,
                'width': image.width, 'height': image.height, 'alpha': True, 'bytes': len(data),
                'format': 'PNG', 'extension': 'png',
                'compression': {'policy': POLICY, 'lossless': True, 'color_space': 'linear-data',
                                'preserve_hidden_rgb': True, 'candidate_bytes': {'png': len(data)}}}
