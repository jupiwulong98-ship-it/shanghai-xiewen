#!/usr/bin/env python3
"""Render each page of a DOCX document to a verified PNG image."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


class PageRenderError(RuntimeError):
    """Raised when a DOCX cannot be converted into a complete page image set."""


def _find_soffice() -> str:
    """Return a usable LibreOffice executable from PATH or the macOS app bundle."""
    from_path = shutil.which("soffice")
    if from_path:
        return from_path

    macos_bundle = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    if macos_bundle.is_file() and os.access(macos_bundle, os.X_OK):
        return str(macos_bundle)
    raise PageRenderError("LibreOffice soffice executable was not found")


def _load_fitz() -> Any:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise PageRenderError("PyMuPDF (fitz) is required to rasterize DOCX pages") from exc
    return fitz


def _validate_png(path: Path) -> None:
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise PageRenderError(f"rendered page is not a decodable PNG: {path.name}") from exc


def _conversion_error(result: subprocess.CompletedProcess[str]) -> PageRenderError:
    detail = (result.stderr or result.stdout or "no converter output").strip()
    return PageRenderError(f"DOCX conversion failed (exit {result.returncode}): {detail}")


def _publish(staged: Path, destination: Path) -> None:
    """Publish a completed PNG without exposing a partially copied destination."""
    handle = tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.stem}-",
        suffix=".png",
        delete=False,
    )
    temporary_destination = Path(handle.name)
    handle.close()
    try:
        shutil.copyfile(staged, temporary_destination)
        _validate_png(temporary_destination)
        temporary_destination.replace(destination)
    except Exception:
        temporary_destination.unlink(missing_ok=True)
        raise


def render_docx_pages(source: Path, target_dir: Path, dpi: int = 160) -> list[Path]:
    """Convert *source* DOCX to PDF, then rasterize every PDF page as ``page-###.png``.

    LibreOffice is run with a temporary writable HOME and user profile so its
    first-run state never touches the caller's profile.  PNGs are staged and
    decoded before they are made visible in ``target_dir``.
    """
    source = Path(source)
    target_dir = Path(target_dir)
    if not source.is_file():
        raise PageRenderError(f"source DOCX does not exist or is not a file: {source}")
    if source.suffix.lower() != ".docx":
        raise PageRenderError(f"source must be a .docx file: {source}")
    if not isinstance(dpi, int) or isinstance(dpi, bool) or dpi <= 0:
        raise PageRenderError(f"dpi must be a positive integer, got {dpi!r}")
    if target_dir.exists() and not target_dir.is_dir():
        raise PageRenderError(f"target directory is not a directory: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)

    soffice = _find_soffice()
    try:
        with tempfile.TemporaryDirectory(prefix="docx-page-render-") as temporary:
            temporary_root = Path(temporary)
            home_dir = temporary_root / "home"
            profile_dir = temporary_root / "libreoffice-profile"
            conversion_dir = temporary_root / "pdf"
            staging_dir = temporary_root / "pages"
            for directory in (home_dir, profile_dir, conversion_dir, staging_dir):
                directory.mkdir()

            environment = os.environ.copy()
            environment["HOME"] = str(home_dir)
            environment["TMPDIR"] = str(temporary_root)
            command = [
                soffice,
                "--headless",
                f"-env:UserInstallation={profile_dir.as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(conversion_dir),
                str(source),
            ]
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=environment,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise PageRenderError(f"DOCX conversion failed to start: {exc}") from exc
            if result.returncode != 0:
                raise _conversion_error(result)

            pdf_path = conversion_dir / f"{source.stem}.pdf"
            if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
                raise PageRenderError("DOCX conversion failed: LibreOffice did not produce a PDF")

            document = None
            try:
                fitz = _load_fitz()
                document = fitz.open(str(pdf_path))
                page_count = document.page_count
                if page_count <= 0:
                    raise PageRenderError("converted PDF has no pages")
                matrix = fitz.Matrix(dpi / 72, dpi / 72)
                staged_pages: list[Path] = []
                for index in range(page_count):
                    page = document.load_page(index)
                    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                    rendered = staging_dir / f"page-{index + 1:03d}.png"
                    pixmap.save(str(rendered))
                    _validate_png(rendered)
                    staged_pages.append(rendered)
            except PageRenderError:
                raise
            except Exception as exc:
                raise PageRenderError(f"failed to rasterize converted PDF: {exc}") from exc
            finally:
                if document is not None:
                    document.close()

            expected_names = [f"page-{index:03d}.png" for index in range(1, page_count + 1)]
            if [path.name for path in staged_pages] != expected_names:
                raise PageRenderError("rendered page sequence is abnormal")

            output_pages = [target_dir / name for name in expected_names]
            for staged, destination in zip(staged_pages, output_pages, strict=True):
                _publish(staged, destination)
            if not all(path.is_file() for path in output_pages):
                raise PageRenderError("rendered page sequence is incomplete")
            return output_pages
    except PageRenderError:
        raise
    except OSError as exc:
        raise PageRenderError(f"failed to prepare rendered pages: {exc}") from exc
