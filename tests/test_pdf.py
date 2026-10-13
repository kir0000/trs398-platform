import pytest

from app import pdf


@pytest.mark.skipif(pdf.find_browser() is None, reason="no Edge/Chrome on this computer")
def test_html_becomes_a_pdf_with_the_installed_browser():
    data = pdf.html_to_pdf("<meta charset=utf-8><h1>Протокол № 2025-0001</h1><p>D<sub>w</sub> = 1,000 Гр</p>")
    assert data.startswith(b"%PDF-") and len(data) > 1000
