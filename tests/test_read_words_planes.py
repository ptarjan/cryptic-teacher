"""ocr_clues.read_words holds its upscaled image as planes: the same image, cache name and reading as the
whole RGB image it held before. Synthetic images only; the words cache is a temp dir.

Run: python tests/test_read_words_planes.py (the RapidOCR checks are skipped where it is not installed)."""
import importlib.util
import os
import tempfile

import _path
import ocr_clues

assert _path


def _images():
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(7)
    out = {}
    for name, (w, h) in {"small": (37, 23), "wide": (1501, 61), "tall": (45, 1203), "page": (1211, 1777)}.items():
        colour = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        out[f"{name}-rgb"] = Image.fromarray(colour, "RGB")
        out[f"{name}-L"] = Image.fromarray(colour[:, :, 0].copy(), "L")
        out[f"{name}-grey-rgb"] = Image.fromarray(np.repeat(colour[:, :, :1], 3, axis=2), "RGB")
    out["palette"] = out["small-rgb"].convert("P")
    out["bilevel"] = out["wide-L"].convert("1")
    out["rgba"] = out["small-rgb"].convert("RGBA")
    return out


def _whole(img):
    crop = img.convert("RGB")
    return crop.resize((crop.width * ocr_clues.UPSCALE, crop.height * ocr_clues.UPSCALE))


def test_planes_are_the_upscaled_image():
    for name, img in _images().items():
        planes = ocr_clues.upscaled_planes(img)
        assert len(planes) == (1 if name.endswith(("-L", "-grey-rgb")) or name == "bilevel" else 3), name
        made = ocr_clues.planes_image(planes)
        whole = _whole(img)
        assert (made.mode, made.size) == (whole.mode, whole.size), name
        assert made.tobytes() == whole.tobytes(), name


def test_cache_path_is_the_whole_images():
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get("CT_OCR_WORDS_CACHE")
        os.environ["CT_OCR_WORDS_CACHE"] = tmp
        try:
            for name, img in _images().items():
                assert ocr_clues.planes_cache_path(ocr_clues.upscaled_planes(img), "times") == \
                    ocr_clues.words_cache_path(_whole(img), "times"), name
            os.environ["CT_OCR_WORDS_CACHE"] = "0"
            assert ocr_clues.planes_cache_path(ocr_clues.upscaled_planes(img), "times") is None
        finally:
            if old is None:
                del os.environ["CT_OCR_WORDS_CACHE"]
            else:
                os.environ["CT_OCR_WORDS_CACHE"] = old


def _text_page(mode):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1100, 1500), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=22)
    words = "ACROSS down solution of puzzle crossword No 12,869 clue anagram hidden The Times".split()
    for row in range(40):
        draw.text((40 + 7 * (row % 5), 20 + 36 * row), " ".join(words[(row + k) % len(words)] for k in range(7)),
                  fill=(20, 20, 20) if mode != "colour" else (200, 30, 20 + 5 * row), font=font)
    if mode == "colour":
        noise = np.random.default_rng(3).integers(0, 40, (1500, 1100, 3), dtype=np.uint8)
        img = Image.fromarray(np.asarray(img) - np.minimum(np.asarray(img), noise), "RGB")
    return img.convert("L") if mode == "L" else img


def test_reduction_and_reading_are_rapidocrs():
    if not importlib.util.find_spec("rapidocr_onnxruntime"):
        return "skipped: no rapidocr_onnxruntime"
    import numpy as np
    eng = ocr_clues.engine("ch")
    for name, img in _images().items():  # the reduction RapidOCR reads, of each plane and of the whole
        if ocr_clues.too_thin(img.width * ocr_clues.UPSCALE, img.height * ocr_clues.UPSCALE, "ch"):
            continue
        planes = ocr_clues.upscaled_planes(img)
        parts = [eng.preprocess(np.asarray(p)) for p in planes]
        whole, ratio_h, ratio_w = eng.preprocess(np.asarray(_whole(img)))
        assert all(p[1:] == (ratio_h, ratio_w) for p in parts), name
        assert np.array_equal(np.stack([p[0] for p in parts] * (3 // len(parts)), axis=2), whole), name
    read = 0
    for mode in ("L", "grey", "colour"):
        img = _text_page(mode)
        for band in ((0, 0, 1100, 1500), (0, 0, 1100, 300), (30, 10, 700, 40), (0, 0, 1100, 12)):
            crop = img.crop(band)
            if ocr_clues.too_thin(crop.width * ocr_clues.UPSCALE, crop.height * ocr_clues.UPSCALE, "ch"):
                continue
            want = ocr_clues.raw_words(_whole(crop), "ch")
            assert ocr_clues.planes_words(ocr_clues.upscaled_planes(crop), "ch") == want, (mode, band)
            read += len(want)
    assert read > 50, read  # the pages were read, not found blank
    return f"{read} words the same"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name, fn() or "ok", flush=True)
