import io

from PIL import Image, ImageOps


def image_dimensions(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as image:
        return ImageOps.exif_transpose(image).size


def create_thumbnail(data: bytes, max_edge: int = 768) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        rendered = ImageOps.exif_transpose(image)
        rendered.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        if rendered.mode not in ("RGB", "RGBA"):
            rendered = rendered.convert("RGB")
        output = io.BytesIO()
        rendered.save(output, format="WEBP", quality=86, method=6)
        return output.getvalue()
