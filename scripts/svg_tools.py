"""Keep SVG originals; render bounded, passive previews for the editor."""
from io import BytesIO
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from PIL import Image
from editor_common import digest
from i18n import tr


def passive_xml(raw):
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError(tr('SVG is too large or contains unsupported entities.'))
    text = raw.decode('utf-8-sig')
    # Adobe exports include namespace/color entities. Expand only these bounded
    # literals in the preview copy; never resolve external DTDs or nested entities.
    declaration = re.search(r'<!DOCTYPE\b[^>\[]*(?:\[[\s\S]*?\]\s*)?>', text, re.IGNORECASE)
    if declaration:
        dtd = declaration[0]
        subset = dtd.split('[', 1)[1].rsplit(']', 1)[0] if '[' in dtd else ''
        pattern = r'<!ENTITY\s+([A-Za-z0-9_]+)\s+[\"\x27]([^<>&\"\x27]{1,256})[\"\x27]\s*>'
        entities = re.findall(pattern, subset)
        header = dtd.split('[', 1)[0]
        urls = re.findall(r'https?://[^\"\x27\s>]+', header)
        if (len(entities) > 32 or re.sub(pattern, '', subset).strip() or
                any(not u.startswith(('http://www.w3.org/', 'https://www.w3.org/')) for u in urls)):
            raise ValueError(tr('SVG is too large or contains unsupported entities.'))
        for name, value in entities:
            namespace = name.startswith('ns_') and re.fullmatch(r'https?://[A-Za-z0-9_./:#-]+', value)
            style = re.fullmatch(r'st[0-9]+', name) and re.fullmatch(
                r'(?:fill|stroke):(?:#[A-Fa-f0-9]{3,8}|none|url\(#[A-Za-z0-9_-]+\));', value)
            if not namespace and not style:
                raise ValueError(tr('SVG is too large or contains unsupported entities.'))
        text = text[:declaration.start()] + text[declaration.end():]
        for name, value in entities:
            text = text.replace('&' + name + ';', value)
    if '<!ENTITY' in text.upper() or '<!DOCTYPE' in text.upper():
        raise ValueError(tr('SVG is too large or contains unsupported entities.'))
    return text


def svg_info(raw):
    root = ET.fromstring(passive_xml(raw))
    if root.tag != '{http://www.w3.org/2000/svg}svg':
        raise ValueError(tr('Expected an SVG image.'))
    for node in root.iter():
        name = node.tag.rsplit('}', 1)[-1].lower()
        if name in {'script', 'foreignobject', 'iframe', 'object', 'embed'}:
            raise ValueError(tr('Active SVG content is not supported.'))
        for key, value in node.attrib.items():
            key = key.rsplit('}', 1)[-1].lower()
            if key.startswith('on'):
                raise ValueError(tr('Active SVG content is not supported.'))
            if key in {'href', 'src'} and name in {'image', 'use', 'feimage'} and not value.startswith(('#', 'data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,')):
                raise ValueError(tr('SVG external resources are not supported.'))
            check_css(value)
        if name == 'style':
            check_css(node.text or '')
    units = {'': 1, 'px': 1, 'pt': 96 / 72, 'pc': 16, 'in': 96, 'cm': 96 / 2.54, 'mm': 96 / 25.4}
    def length(value):
        match = re.fullmatch(r'\s*([0-9.eE+-]+)\s*([a-z]*)\s*', value or '')
        return float(match[1]) * units[match[2]] if match and match[2] in units else None
    width, height = length(root.get('width')), length(root.get('height'))
    if not width or not height:
        box = [float(v) for v in re.split(r'[\s,]+', root.get('viewBox', '').strip()) if v]
        width, height = box[2:] if len(box) == 4 else (300, 150)
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError(tr('Invalid SVG dimensions.'))
    return max(1, round(width)), max(1, round(height))


def check_css(value):
    if '@import' in value.lower():
        raise ValueError(tr('SVG external resources are not supported.'))
    for resource in re.findall(r'url\(\s*[\"\x27]?([^\)\"\x27]+)', value, re.IGNORECASE):
        if not resource.strip().startswith('#'):
            raise ValueError(tr('SVG external resources are not supported.'))


def preview_svg(raw, maximum=1400):
    width, height = svg_info(raw)
    ratio = min(maximum / width, maximum / height)
    import resvg_py
    png = resvg_py.svg_to_bytes(svg_string=passive_xml(raw), dpi=96,
        width=max(1, round(width * ratio)), height=max(1, round(height * ratio)))
    with Image.open(BytesIO(png)) as image:
        return image.convert('RGBA')


def encode_svg(path):
    path = Path(path)
    raw = path.read_bytes()
    width, height = svg_info(raw)
    # Rendering also catches malformed/unrenderable SVG while retaining bytes.
    image = preview_svg(raw)
    return {'data': raw, 'original': raw, 'filename': path.name, 'format': 'SVG', 'extension': 'svg',
            'source_format': 'SVG', 'width': width, 'height': height,
            'alpha': image.getchannel('A').getextrema() != (255, 255), 'bytes': len(raw),
            'sha256': digest(raw), 'source_sha256': digest(raw),
            'compression': {'policy': 'original-svg-v1', 'lossless': True,
                            'candidate_bytes': {'original_svg': len(raw)}}}
