#!/usr/bin/env python3
"""Render each page of a DOCX document to a verified PNG image."""

from __future__ import annotations

import os
import re
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


def _find_pdftoppm() -> str | None:
    """Return Poppler's PDF rasterizer when it is installed."""
    return shutil.which("pdftoppm")


def _validate_png(path: Path) -> None:
    try:
        with Image.open(path) as image:
            image.verify()
            if image.format != "PNG":
                raise PageRenderError(f"rendered page is not a decodable PNG: {path.name}")
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise PageRenderError(f"rendered page is not a decodable PNG: {path.name}") from exc


def _conversion_error(result: subprocess.CompletedProcess[str]) -> PageRenderError:
    detail = (result.stderr or result.stdout or "no converter output").strip()
    return PageRenderError(f"DOCX conversion failed (exit {result.returncode}): {detail}")


def _set_png_permissions(path: Path) -> None:
    """Set predictable, readable permissions before an image is published."""
    try:
        path.chmod(0o644)
    except OSError as exc:
        raise PageRenderError(f"failed to set rendered page permissions: {path.name}") from exc


def _assert_continuous_pages(paths: list[Path], staging_dir: Path) -> None:
    expected_names = [f"page-{index:03d}.png" for index in range(1, len(paths) + 1)]
    if [path.name for path in paths] != expected_names:
        raise PageRenderError("rendered page sequence is abnormal")
    try:
        actual_names = sorted(path.name for path in staging_dir.iterdir())
    except OSError as exc:
        raise PageRenderError(f"failed to inspect rendered page sequence: {exc}") from exc
    if actual_names != expected_names:
        raise PageRenderError("rendered page sequence is abnormal")


def _rasterize_with_fitz(fitz: Any, pdf_path: Path, staging_dir: Path, dpi: int) -> list[Path]:
    document = None
    try:
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
            _set_png_permissions(rendered)
            staged_pages.append(rendered)
        return staged_pages
    except PageRenderError:
        raise
    except Exception as exc:
        raise PageRenderError(f"failed to rasterize converted PDF: {exc}") from exc
    finally:
        if document is not None:
            document.close()


def _rasterize_with_pdftoppm(pdftoppm: str, pdf_path: Path, staging_dir: Path, dpi: int) -> list[Path]:
    prefix = staging_dir / "page"
    try:
        result = subprocess.run(
            [pdftoppm, "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PageRenderError(f"PDF rasterization failed to start: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no rasterizer output").strip()
        raise PageRenderError(f"PDF rasterization failed (exit {result.returncode}): {detail}")

    numbered_pages: list[tuple[int, Path]] = []
    for path in staging_dir.glob("page-*.png"):
        match = re.fullmatch(r"page-(\d+)\.png", path.name)
        if match is None:
            raise PageRenderError("rendered page sequence is abnormal")
        numbered_pages.append((int(match.group(1)), path))
    numbered_pages.sort()
    if not numbered_pages:
        raise PageRenderError("converted PDF has no pages")
    if [number for number, _ in numbered_pages] != list(range(1, len(numbered_pages) + 1)):
        raise PageRenderError("rendered page sequence is abnormal")

    staged_pages: list[Path] = []
    for index, (_, source_page) in enumerate(numbered_pages, start=1):
        rendered = staging_dir / f"page-{index:03d}.png"
        if source_page != rendered:
            source_page.replace(rendered)
        _validate_png(rendered)
        _set_png_permissions(rendered)
        staged_pages.append(rendered)
    return staged_pages


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
    try:
        target_parent = target_dir.parent
        target_parent.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            raise PageRenderError(f"target directory already exists: {target_dir}")
    except PageRenderError:
        raise
    except OSError as exc:
        raise PageRenderError(f"failed to prepare target directory: {exc}") from exc

    soffice = _find_soffice()
    try:
        with tempfile.TemporaryDirectory(prefix=f".{target_dir.name}-", dir=target_parent) as output_temporary:
            staging_dir = Path(output_temporary)
            with tempfile.TemporaryDirectory(prefix="docx-page-render-") as temporary:
                temporary_root = Path(temporary)
                home_dir = temporary_root / "home"
                profile_dir = temporary_root / "libreoffice-profile"
                conversion_dir = temporary_root / "pdf"
                for directory in (home_dir, profile_dir, conversion_dir):
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

                fitz_error = None
                try:
                    fitz = _load_fitz()
                except PageRenderError as exc:
                    fitz_error = exc
                    fitz = None
                if fitz is not None:
                    staged_pages = _rasterize_with_fitz(fitz, pdf_path, staging_dir, dpi)
                else:
                    pdftoppm = _find_pdftoppm()
                    if pdftoppm is None:
                        raise PageRenderError(
                            "PyMuPDF (fitz) or the pdftoppm command is required to rasterize DOCX pages"
                        ) from fitz_error
                    staged_pages = _rasterize_with_pdftoppm(pdftoppm, pdf_path, staging_dir, dpi)

            _assert_continuous_pages(staged_pages, staging_dir)
            expected_names = [path.name for path in staged_pages]
            if target_dir.exists():
                raise PageRenderError(f"target directory already exists: {target_dir}")
            staging_dir.rename(target_dir)
            output_pages = [target_dir / name for name in expected_names]
            if not all(path.is_file() for path in output_pages):
                raise PageRenderError("rendered page sequence is incomplete")
            return output_pages
    except PageRenderError:
        raise
    except OSError as exc:
        raise PageRenderError(f"failed to prepare rendered pages: {exc}") from exc
