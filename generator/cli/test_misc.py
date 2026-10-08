import fitz
import pytest
from click.testing import CliRunner

from ..cli import cli


@pytest.fixture
def runner():
    return CliRunner()


def _make_pdf(path, pages=2):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)  # A4 in points
        page.insert_text((72, 72), f"Page {i + 1}")
    doc.save(path)
    doc.close()


def test_render_cover_defaults_to_sibling_cover_png(runner, tmp_path):
    pdf = tmp_path / "ukulele-tuesday-songbook-current-2026-10-08.pdf"
    _make_pdf(pdf)

    result = runner.invoke(cli, ["render-cover", str(pdf)])

    assert result.exit_code == 0, result.output
    cover = tmp_path / "ukulele-tuesday-songbook-current-2026-10-08.cover.png"
    assert cover.exists()
    pix = fitz.Pixmap(str(cover))
    # First page only, rendered at the default 150 dpi.
    assert (pix.width, pix.height) == (1240, 1755)


def test_render_cover_honours_output_and_dpi(runner, tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    out = tmp_path / "out.png"

    result = runner.invoke(
        cli, ["render-cover", str(pdf), "--output", str(out), "--dpi", "72"]
    )

    assert result.exit_code == 0, result.output
    pix = fitz.Pixmap(str(out))
    assert (pix.width, pix.height) == (595, 842)


def test_render_cover_fails_on_unreadable_pdf(runner, tmp_path):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"not a pdf")

    result = runner.invoke(cli, ["render-cover", str(pdf)])

    assert result.exit_code == 1
    assert not (tmp_path / "broken.cover.png").exists()
