"""Optimize PDF images without rasterizing pages or embedding unsupported WebP."""
from i18n import tr
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image
from editor_common import ROOT, digest


def pdf_api():
    local = ROOT/'.deps/pdf'
    if local.exists() and str(local) not in sys.path:
        sys.path.insert(0, str(local))
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        raise ValueError(tr('pypdf is missing. Install requirements-editor.txt before importing PDFs.'))
    return PdfReader, PdfWriter


def read_pdf(data):
    PdfReader, _ = pdf_api()
    if len(data) > 300*1024**2:
        raise ValueError(tr('The PDF exceeds 300 MiB'))
    reader = PdfReader(BytesIO(data), strict=True)
    if reader.is_encrypted:
        raise ValueError(tr('Import a PDF without a password or encryption'))
    if not reader.pages or len(reader.pages) > 2000:
        raise ValueError(tr('The PDF must contain between 1 and 2000 pages'))
    return reader


def signature(reader):
    return [(tuple(float(n) for n in page.mediabox), tuple(float(n) for n in page.cropbox),
             page.rotation, page.extract_text() or '') for page in reader.pages]


def optimize_pdf(path):
    path = Path(path)
    if path.stat().st_size > 300*1024**2:
        raise ValueError(tr('The PDF exceeds 300 MiB'))
    raw = path.read_bytes()
    return optimize_pdf_data(raw, path.name)


def optimize_pdf_data(raw, filename='manual.pdf'):
    """Shared optimizer for imported PDFs and image-built manuals."""
    reader = read_pdf(raw)
    PdfReader, PdfWriter = pdf_api()
    from pypdf.generic import NameObject
    fields = reader.get_fields() or {}
    signed = any(field.get('/FT') == '/Sig' and field.get('/V') for field in fields.values())
    original_signature = signature(reader)
    candidates = {'original': raw}
    replaced = 0
    skipped = 0
    if not signed:
        lossless = PdfWriter(clone_from=reader)
        for page in lossless.pages:
            page.compress_content_streams(level=9)
        lossless.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
        buffer = BytesIO()
        lossless.write(buffer)
        lossless_data = buffer.getvalue()
        if signature(read_pdf(lossless_data)) != original_signature:
            raise ValueError(tr('Optimization altered the PDF pages or text'))
        candidates['lossless'] = lossless_data
        writer = PdfWriter(clone_from=PdfReader(BytesIO(lossless_data)))
        seen = set()
        for page in writer.pages:
            for image in page.images:
                reference = image.indirect_reference
                if reference is None or reference.idnum in seen:
                    continue
                seen.add(reference.idnum)
                obj = reference.get_object()
                # JPEG can retain an ICCBased RGB/gray colour space: change only
                # the compressed samples, keeping the original profile reference.
                colorspace = obj.get('/ColorSpace')
                channels = {'/DeviceRGB': 3, '/DeviceGray': 1}.get(str(colorspace))
                if isinstance(colorspace, (list, tuple)) and len(colorspace) == 2 and colorspace[0] == '/ICCBased':
                    profile = colorspace[1].get_object()
                    count = profile.get('/N')
                    if count in {1, 3} and profile.get('/Range', [0, 1]*count) == [0, 1]*count:
                        alternate = '/DeviceRGB' if count == 3 else '/DeviceGray'
                        if profile.get('/Alternate', alternate) == alternate:
                            channels = count
                # Other spaces and non-default sample mappings need conversion,
                # which this optimizer deliberately does not perform.
                if (obj.get('/SMask') or obj.get('/Mask') or obj.get('/ImageMask') or
                        channels is None or obj.get('/BitsPerComponent') != 8 or
                        obj.get('/Decode', [0, 1]*(channels or 0)) != [0, 1]*(channels or 0)):
                    skipped += 1
                    continue
                pil = image.image
                if pil is None or pil.width*pil.height > 40_000_000 or pil.mode != ('RGB' if channels == 3 else 'L'):
                    skipped += 1
                    continue
                jpeg = BytesIO()
                pil.save(jpeg, format='JPEG', quality=90, optimize=False, subsampling=0)
                if len(jpeg.getvalue()) >= len(obj._data):
                    continue
                # image.replace() rebuilds the image dictionary and can discard
                # ICC colour management. Preserve it and all unrelated entries.
                obj._data = jpeg.getvalue()
                obj[NameObject('/Filter')] = NameObject('/DCTDecode')
                obj.pop('/DecodeParms', None)
                obj.decoded_self = None
                replaced += 1
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
        buffer = BytesIO()
        writer.write(buffer)
        data = buffer.getvalue()
        if signature(read_pdf(data)) != original_signature:
            raise ValueError(tr('Optimization altered the PDF pages or text'))
        candidates['jpeg90'] = data
    # Original wins ties. Lossless wins ties against JPEG recompression.
    chosen = min(candidates, key=lambda key: len(candidates[key]))
    result = candidates[chosen]
    return {'data': result, 'original': raw, 'filename': filename, 'sha256': digest(result),
            'source_sha256': digest(raw), 'source_format': 'PDF', 'format': 'PDF', 'extension': 'pdf',
            'pages': len(reader.pages), 'width': None, 'height': None, 'alpha': False, 'bytes': len(result),
            'compression': {'policy': 'pdf-smallest-original-lossless-jpeg90-v2',
                'lossless': chosen != 'jpeg90' or replaced == 0, 'reason': chosen, 'quality': 90 if chosen == 'jpeg90' and replaced else None,
                'candidate_bytes': {key: len(value) for key, value in candidates.items()},
                'recompressed_images': replaced if chosen == 'jpeg90' else 0,
                'skipped_images': skipped, 'signed_original_preserved': bool(signed)}}
