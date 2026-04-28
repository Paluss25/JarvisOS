from pathlib import Path


def test_pdf_imports():
    import pdfplumber
    import PIL.Image
    assert pdfplumber.__version__
    assert PIL.__version__
