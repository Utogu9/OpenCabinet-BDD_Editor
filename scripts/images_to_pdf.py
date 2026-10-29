"""Build borderless PDF pages in explicit image order, then compare optimizations."""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps
from editor_common import digest, fit_dimensions
from i18n import tr
from pdf_tools import optimize_pdf_data, pdf_api


MAX_PAGE_IMAGE_SIZE = (3840, 2160)


def page_image_size(size):
    return fit_dimensions(size, MAX_PAGE_IMAGE_SIZE)


def images_to_pdf(paths):
    paths = [Path(path) for path in paths]
    if not 1 <= len(paths) <= 2000:
        raise ValueError(tr('Select between 1 and 2000 images.'))
    _, PdfWriter = pdf_api()
    from pypdf.generic import (ArrayObject, ByteStringObject, DecodedStreamObject,
                               DictionaryObject, EncodedStreamObject, NameObject, NumberObject)
    writer = PdfWriter()
    sources = []
    embedded_bytes = 0

    def stream(data, properties):
        nonlocal embedded_bytes
        obj = DecodedStreamObject()
        obj.set_data(data)
        obj.update({NameObject(key): value for key, value in properties.items()})
        obj = obj.flate_encode(level=9)
        embedded_bytes += len(obj._data)
        return writer._add_object(obj)

    for path in paths:
        if path.stat().st_size > 100*1024**2:
            raise ValueError(tr('The image exceeds 100 MiB'))
        raw = path.read_bytes()
        with Image.open(BytesIO(raw)) as original:
            if original.format not in {'PNG', 'JPEG', 'WEBP'}:
                raise ValueError(tr('PNG, JPG and WebP files are supported'))
            if getattr(original, 'n_frames', 1) != 1:
                raise ValueError(tr('The image must be static'))
            if original.width*original.height > 40_000_000:
                raise ValueError(tr('The image exceeds 40 megapixels'))
            if original.mode not in {'1', 'L', 'LA', 'P', 'RGB', 'RGBA', 'CMYK'}:
                raise ValueError(tr('Use images with 8-bit channels for PDF pages.'))
            image = ImageOps.exif_transpose(original)
            source_width, source_height = image.size
            icc = original.info.get('icc_profile')
            if image.mode == 'CMYK':
                if icc:
                    from PIL import ImageCms
                    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
                    image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(BytesIO(icc)), profile, outputMode='RGB')
                    icc = profile.tobytes()
                else:
                    image = image.convert('RGB')
            size = page_image_size(image.size)
            resized = size != image.size
            if resized:
                if image.mode == 'P':
                    image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')
                elif image.mode == '1':
                    image = image.convert('L')
                image = image.resize(size, Image.Resampling.LANCZOS)
            width, height = image.size
            alpha = image.convert('RGBA').getchannel('A') if ('A' in image.getbands() or 'transparency' in image.info) else None
            gray = image.mode in {'1', 'L', 'LA'}
            base = image.convert('L' if gray else 'RGB') if image.mode != 'P' else image
            colorspace = NameObject('/DeviceGray' if gray else '/DeviceRGB')
            if icc:
                profile = stream(icc, {'/N': NumberObject(1 if gray else 3), '/Alternate': colorspace})
                colorspace = ArrayObject([NameObject('/ICCBased'), profile])
            if base.mode == 'P':
                palette = base.getpalette('RGB')
                if not palette:
                    base = base.convert('RGB')
                else:
                    colorspace = ArrayObject([NameObject('/Indexed'), colorspace, NumberObject(len(palette)//3-1), ByteStringObject(bytes(palette))])
            properties = {'/Type': NameObject('/XObject'), '/Subtype': NameObject('/Image'),
                          '/Width': NumberObject(width), '/Height': NumberObject(height),
                          '/ColorSpace': colorspace, '/BitsPerComponent': NumberObject(8)}
            if alpha is not None and alpha.getextrema() != (255, 255):
                properties['/SMask'] = stream(alpha.tobytes(), {
                    '/Type': NameObject('/XObject'), '/Subtype': NameObject('/Image'),
                    '/Width': NumberObject(width), '/Height': NumberObject(height),
                    '/ColorSpace': NameObject('/DeviceGray'), '/BitsPerComponent': NumberObject(8)})
            if not resized and original.format == 'JPEG' and original.mode in {'RGB', 'L'} and original.getexif().get(274, 1) == 1:
                obj = EncodedStreamObject()
                obj.update({NameObject(key): value for key, value in properties.items()})
                obj[NameObject('/Filter')] = NameObject('/DCTDecode')
                obj._data = raw
                embedded_bytes += len(raw)
                reference = writer._add_object(obj)
            else:
                reference = stream(base.tobytes(), properties)
            if embedded_bytes > 300*1024**2:
                raise ValueError(tr('The PDF exceeds 300 MiB'))
            # One resized image pixel equals one PDF point; never fit to A4 or crop.
            page = writer.add_blank_page(width=width, height=height)
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/PageImage'): reference})})
            page[NameObject('/Contents')] = stream(
                f'q\n{width:.8f} 0 0 {height:.8f} 0 0 cm\n/PageImage Do\nQ\n'.encode('ascii'), {})
            sources.append({'filename': path.name, 'sha256': digest(raw), 'width': width, 'height': height,
                            'source_width': source_width, 'source_height': source_height})
    buffer = BytesIO()
    writer.write(buffer)
    result = optimize_pdf_data(buffer.getvalue())
    result['image_pages'] = sources
    return result
