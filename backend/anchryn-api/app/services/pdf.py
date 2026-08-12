"""Extracting text from a PDF.

Deliberately thin: pypdf does the work, and this adds the failure modes that
matter for a document-grounded bot — an encrypted file, or a scanned one with no
text layer at all. Both are common enough that a generic "upload failed" would
send the user hunting for the wrong problem.
"""

import io
import logging

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)


class PdfExtractionError(Exception):
    """The PDF could not be read. The message is written for the user."""


def extract_pages(data: bytes) -> list[str]:
    """Return one string per page, in order.

    Pages with no extractable text come back as empty strings rather than being
    dropped, so page numbers stay aligned with the actual document — a citation
    saying "page 7" has to mean the seventh page of the PDF.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise PdfExtractionError(f"This file could not be read as a PDF: {exc}") from exc
    except Exception as exc:
        raise PdfExtractionError("This file could not be read as a PDF.") from exc

    if reader.is_encrypted:
        # An empty-password decrypt covers PDFs that are "encrypted" only to
        # restrict printing, which is very common. A real password we cannot help with.
        try:
            if reader.decrypt("") == 0:
                raise PdfExtractionError(
                    "This PDF is password protected. Remove the password and upload it again."
                )
        except PdfExtractionError:
            raise
        except Exception as exc:
            raise PdfExtractionError(
                "This PDF is password protected. Remove the password and upload it again."
            ) from exc

    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001 — one broken page must not lose the rest
            logger.warning("Could not extract text from page %d: %s", index, exc)
            pages.append("")

    if not pages:
        raise PdfExtractionError("This PDF has no pages.")

    if not any(page.strip() for page in pages):
        raise PdfExtractionError(
            "No text could be extracted from this PDF. If it is a scan or a set of images, "
            "it needs OCR first — there is no text layer to read."
        )

    return pages
