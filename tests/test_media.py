import io

from PIL import Image

from asgardian.media import create_thumbnail, image_dimensions


def test_thumbnail_preserves_aspect_ratio_and_bounds_long_edge():
    source = io.BytesIO()
    Image.new("RGB", (1600, 900), color=(24, 48, 96)).save(source, format="PNG")

    thumbnail = create_thumbnail(source.getvalue(), max_edge=768)

    assert image_dimensions(thumbnail) == (768, 432)
    with Image.open(io.BytesIO(thumbnail)) as image:
        assert image.format == "WEBP"
