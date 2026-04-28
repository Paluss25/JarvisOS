import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_pdf_imports():
    import pdfplumber
    import PIL.Image
    assert pdfplumber.__version__
    assert PIL.__version__


def _minimal_pdf_with_text(text: str) -> bytes:
    import reportlab.pdfgen.canvas as canvas_mod
    import io
    buf = io.BytesIO()
    c = canvas_mod.Canvas(buf)
    c.drawString(72, 720, text)
    c.save()
    buf.seek(0)
    return buf.read()


def test_extract_text_from_pdf_bytes():
    """extract_text_from_bytes should return non-empty string for a valid PDF."""
    from agents.chro.tools import extract_text_from_bytes

    pdf_bytes = _minimal_pdf_with_text("Test cedolino")
    result = extract_text_from_bytes(pdf_bytes, filename="test.pdf")
    assert "Test cedolino" in result
