"""Ordered WebP comic-book manuals and bounded, extraction-free CBZ inspection."""
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
import stat
from zipfile import ZipFile, ZipInfo, ZIP_STORED, BadZipFile

from PIL import Image, ImageOps
from editor_common import digest, fit_dimensions
from i18n import tr

MAX_CBZ_BYTES = 300*1024**2


def images_to_cbz(paths, progress=None):
    paths = [Path(path) for path in paths]
    if not 1 <= len(paths) <= 2000:
        raise ValueError(tr('Select between 1 and 2000 images.'))
    output = BytesIO()
    pages = []
    source_bytes = 0
    with ZipFile(output, 'w', compression=ZIP_STORED) as archive:
        for index, path in enumerate(paths, 1):
            if path.stat().st_size > 100*1024**2:
                raise ValueError(tr('The image exceeds 100 MiB'))
            raw = path.read_bytes()
            source_bytes += len(raw)
            with Image.open(BytesIO(raw)) as original:
                if original.format not in {'PNG', 'JPEG', 'WEBP'}:
                    raise ValueError(tr('PNG, JPG and WebP files are supported'))
                if getattr(original, 'n_frames', 1) != 1:
                    raise ValueError(tr('The image must be static'))
                if original.width*original.height > 40_000_000:
                    raise ValueError(tr('The image exceeds 40 megapixels'))
                if original.mode not in {'1', 'L', 'LA', 'P', 'RGB', 'RGBA', 'CMYK'}:
                    raise ValueError(tr('Use images with 8-bit channels for manual pages.'))
                image = ImageOps.exif_transpose(original)
                source_size = image.size
                icc = original.info.get('icc_profile')
                if image.mode == 'CMYK' and icc:
                    from PIL import ImageCms
                    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
                    image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(BytesIO(icc)), profile, outputMode='RGB')
                    icc = profile.tobytes()
                alpha = 'A' in image.getbands() or 'transparency' in image.info
                image = image.convert('RGBA' if alpha else 'RGB')
                size = fit_dimensions(image.size)
                if size != image.size:
                    image = image.resize(size, Image.Resampling.LANCZOS)
                buffer = BytesIO()
                options = {'format': 'WEBP', 'lossless': False, 'quality': 90, 'method': 4, 'exact': True}
                if icc:
                    options['icc_profile'] = icc
                image.save(buffer, **options)
                data = buffer.getvalue()
                compression = {'policy': 'webp-lossy90-v1', 'lossless': False, 'reason': 'manual_quality90',
                               'quality': 90, 'candidate_bytes': {'lossy90': len(data)}}
                with Image.open(BytesIO(data)) as check:
                    if check.size != size or check.info.get('icc_profile') != icc:
                        raise ValueError(tr('Conversion changed the dimensions or color profile.'))
                    expected = image.convert('RGBA')
                    actual = check.convert('RGBA')
                    if alpha and actual.getchannel('A').tobytes() != expected.getchannel('A').tobytes():
                        raise ValueError(tr('Conversion changed the transparency'))
                name = f'{index:04d}.webp'
                # Fixed ZIP metadata makes repeated builds byte-identical. WebP is
                # already compressed, so archive entries are stored directly.
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_STORED
                archive.writestr(info, data)
                pages.append({'path': name, 'filename': path.name, 'sha256': digest(data),
                    'source_sha256': digest(raw), 'source_width': source_size[0], 'source_height': source_size[1],
                    'width': size[0], 'height': size[1], 'bytes': len(data), 'compression': compression})
            if output.tell() > MAX_CBZ_BYTES:
                raise ValueError(tr('The CBZ exceeds 300 MiB.'))
            if progress:
                progress(index, len(paths))
    data = output.getvalue()
    if len(data) > MAX_CBZ_BYTES:
        raise ValueError(tr('The CBZ exceeds 300 MiB.'))
    return {'data': data, 'original': data, 'filename': 'manual.cbz', 'sha256': digest(data),
            'source_sha256': digest(data), 'source_format': 'CBZ', 'format': 'CBZ', 'extension': 'cbz',
            'pages': len(pages), 'width': None, 'height': None, 'alpha': False, 'bytes': len(data),
            'image_pages': pages, 'compression': {'policy': 'cbz-webp90-pages-v1',
                'lossless': False, 'quality': 90, 'source_bytes': source_bytes,
                'max_image_size': [3840, 2160], 'candidate_bytes': {'stored': len(data)}}}


def inspect_cbz(data):
    if len(data) > MAX_CBZ_BYTES:
        raise ValueError(tr('The CBZ exceeds 300 MiB.'))
    pages = []
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 4000 or sum(entry.file_size for entry in entries) > MAX_CBZ_BYTES:
                raise ValueError(tr('The CBZ exceeds the supported archive limits.'))
            names = set()
            for entry in entries:
                name = entry.orig_filename
                parts = PurePosixPath(name).parts
                if (not parts or name.startswith('/') or any(part in {'.', '..'} for part in parts)
                        or '\\' in name or ':' in name or '\x00' in name or name in names
                        or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1):
                    raise ValueError(tr('Invalid CBZ archive path or entry.'))
                names.add(name)
                if entry.is_dir():
                    continue
                if PurePosixPath(name).name == 'ComicInfo.xml' and entry.file_size <= 1024**2:
                    continue  # Preserve it on import; never interpret XML or extract files.
                if Path(name).suffix.lower() not in {'.webp', '.png', '.jpg', '.jpeg'} or entry.file_size > 100*1024**2:
                    raise ValueError(tr('CBZ manuals must contain static PNG, JPG or WebP pages.'))
                raw = archive.read(entry)
                with Image.open(BytesIO(raw)) as image:
                    if (image.format not in {'PNG', 'JPEG', 'WEBP'} or getattr(image, 'n_frames', 1) != 1
                            or image.width*image.height > 40_000_000):
                        raise ValueError(tr('CBZ manuals must contain static PNG, JPG or WebP pages.'))
                    image.load()
                    pages.append({'path': name, 'sha256': digest(raw), 'bytes': len(raw),
                                  'width': image.width, 'height': image.height})
            if not 1 <= len(pages) <= 2000:
                raise ValueError(tr('Select between 1 and 2000 images.'))
    except (BadZipFile, RuntimeError) as exc:
        raise ValueError(tr('Invalid or encrypted CBZ archive.')) from exc
    return sorted(pages, key=lambda page: [int(part) if part.isdigit() else part.casefold()
                                         for part in re.split(r'(\d+)', page['path'])])


def import_cbz(path):
    path = Path(path)
    if path.stat().st_size > MAX_CBZ_BYTES:
        raise ValueError(tr('The CBZ exceeds 300 MiB.'))
    data = path.read_bytes()
    pages = inspect_cbz(data)
    return {'data': data, 'original': data, 'filename': path.name, 'sha256': digest(data),
            'source_sha256': digest(data), 'source_format': 'CBZ', 'format': 'CBZ', 'extension': 'cbz',
            'pages': len(pages), 'width': None, 'height': None, 'alpha': False, 'bytes': len(data),
            'image_pages': pages, 'compression': {'policy': 'original-cbz-v1', 'lossless': True,
                                               'candidate_bytes': {'original': len(data)}}}


def verify_cbz(data, asset):
    pages = inspect_cbz(data)
    if len(pages) != asset['pages'] or len(data) != asset['bytes']:
        raise ValueError(tr('Invalid manual size'))
    declared = asset.get('image_pages', [])
    if len(pages) != len(declared):
        raise ValueError(tr('Invalid manual provenance'))
    for actual, expected in zip(pages, declared):
        if any(actual[key] != expected.get(key) for key in ('path', 'sha256', 'bytes', 'width', 'height')):
            raise ValueError(tr('Invalid manual provenance'))
        if asset['compression']['policy'] == 'cbz-smallest-webp-pages-v1':
            decision = expected['compression']
            sizes = decision['candidate_bytes']
            if (actual['width'] > 3840 or actual['height'] > 2160 or
                    actual['bytes'] != min(sizes.values()) or
                    decision['lossless'] != (sizes['lossless'] <= sizes['lossy90'])):
                raise ValueError(tr('Invalid manual compression choice'))
        elif asset['compression']['policy'] == 'cbz-webp90-pages-v1':
            decision = expected['compression']
            if (actual['width'] > 3840 or actual['height'] > 2160 or
                    decision.get('policy') != 'webp-lossy90-v1' or decision.get('lossless') is not False or
                    decision.get('quality') != 90 or decision.get('candidate_bytes') != {'lossy90': actual['bytes']} or
                    asset['compression'].get('lossless') is not False or asset['compression'].get('quality') != 90):
                raise ValueError(tr('Invalid manual compression choice'))
