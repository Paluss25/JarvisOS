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


def test_sanitize_pii_redacts_cf():
    from agents.chro.tools import sanitize_pii
    text = "Il dipendente RSSMRA85M01H703N ha ricevuto il cedolino."
    result = sanitize_pii(text)
    assert "RSSMRA85M01H703N" not in result
    assert "[CF_REDACTED]" in result


def test_sanitize_pii_redacts_iban():
    from agents.chro.tools import sanitize_pii
    text = "Bonifico su IBAN IT60X0542811101000000123456."
    result = sanitize_pii(text)
    assert "IT60X0542811101000000123456" not in result
    assert "[IBAN_REDACTED]" in result


def test_sanitize_pii_preserves_numeric_fields():
    from agents.chro.tools import sanitize_pii
    text = "Retribuzione netta: 2.450,00 EUR"
    result = sanitize_pii(text)
    assert "2.450,00" in result


def test_classify_document_payslip_keywords():
    """classify_document_from_text should classify payslip-like text correctly."""
    from agents.chro.tools import classify_document_from_text

    text = "Retribuzione lorda: 3.000,00 EUR\nIRPEF: 450,00\nFerie residue: 12 gg"
    result = classify_document_from_text(text)
    assert result in ("payslip", "leave_statement", "inps_extract", "expense_report", "unknown")
    assert result == "payslip"
