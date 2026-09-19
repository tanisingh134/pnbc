from dataclasses import dataclass, field
import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image

from app.services.extraction.ocr import OCRService
from app.services.extraction.preprocessor import ImagePreprocessor

logger = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


@dataclass
class PageExtractionResult:
    page_number: int
    text: str
    extraction_method: str  # "direct" or "ocr"
    confidence: float
    has_visual_content: bool = False
    visual_metadata: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class PDFExtractorService:
    """Extracts text, metadata, and visual content from PDF documents and images."""

    MIN_USABLE_TEXT_CHARS: int = 35
    MIN_ALPHANUMERIC_RATIO: float = 0.40

    @classmethod
    def is_text_usable(cls, text: str) -> bool:
        """Heuristic check to determine if direct PDF text extraction is usable or scanned/corrupt."""
        cleaned = text.strip()
        if len(cleaned) < cls.MIN_USABLE_TEXT_CHARS:
            return False

        # Check alphanumeric characters ratio
        alnum_count = sum(1 for c in cleaned if c.isalnum())
        total_non_whitespace = sum(1 for c in cleaned if not c.isspace())
        if total_non_whitespace == 0:
            return False

        ratio = alnum_count / total_non_whitespace
        if ratio < cls.MIN_ALPHANUMERIC_RATIO:
            return False

        # Reject replacement characters or excessive non-printable bytes
        suspicious_chars = cleaned.count("\ufffd") + cleaned.count("")
        if suspicious_chars > 5:
            return False

        return True

    @classmethod
    def extract_from_pdf_bytes(
        cls,
        pdf_bytes: bytes,
        ocr_fallback: bool = True,
    ) -> List[PageExtractionResult]:
        """Inspect and extract each page of a PDF using PyMuPDF and fallback OCR."""
        if fitz is None:
            raise RuntimeError("PyMuPDF (fitz) is not installed")

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_results: List[PageExtractionResult] = []

        try:
            for page_idx in range(len(doc)):
                page_num = page_idx + 1
                page = doc[page_idx]

                # Detect embedded images & drawings on the page
                embedded_images = page.get_images(full=True)
                has_images = len(embedded_images) > 0
                visual_meta = {
                    "embedded_image_count": len(embedded_images),
                    "rect": [round(c, 1) for c in list(page.rect)],
                }

                # Attempt direct selectable text extraction
                raw_direct_text = page.get_text("text").strip()
                usable = cls.is_text_usable(raw_direct_text)

                if usable or not ocr_fallback:
                    page_results.append(
                        PageExtractionResult(
                            page_number=page_num,
                            text=raw_direct_text,
                            extraction_method="direct",
                            confidence=0.98 if usable else 0.50,
                            has_visual_content=has_images,
                            visual_metadata=visual_meta,
                            metadata={
                                "direct_char_count": len(raw_direct_text),
                                "direct_text_usable": usable,
                            },
                        )
                    )
                else:
                    # Page has little or no usable text -> Render to high-res image and OCR
                    logger.info(
                        f"Page {page_num} direct text unusable (chars={len(raw_direct_text)}). "
                        "Rendering page for OCR..."
                    )
                    pix = page.get_pixmap(dpi=200)
                    img_bytes = pix.tobytes("png")
                    pil_img = Image.open(io.BytesIO(img_bytes))

                    # Preprocess rendered page image
                    preprocessed_img, prep_meta = ImagePreprocessor.preprocess_for_ocr(pil_img)

                    # Run OCR
                    ocr_text, ocr_conf, ocr_meta = OCRService.extract_text_and_confidence(preprocessed_img)

                    # Merge direct text if any characters existed
                    final_text = ocr_text if len(ocr_text) >= len(raw_direct_text) else raw_direct_text
                    final_conf = ocr_conf if ocr_text else 0.40

                    page_results.append(
                        PageExtractionResult(
                            page_number=page_num,
                            text=final_text,
                            extraction_method="ocr",
                            confidence=final_conf,
                            has_visual_content=has_images or prep_meta.get("is_low_contrast", False),
                            visual_metadata=visual_meta,
                            metadata={
                                "preprocessing": prep_meta,
                                "ocr_metadata": ocr_meta,
                                "ocr_fallback_triggered": True,
                            },
                        )
                    )

            return page_results

        finally:
            doc.close()

    @classmethod
    def extract_from_image_bytes(
        cls,
        image_bytes: bytes,
    ) -> List[PageExtractionResult]:
        """Extract text from a standalone image document (PNG, JPG, JPEG) using OpenCV & OCR."""
        preprocessed_img, prep_meta = ImagePreprocessor.preprocess_for_ocr(image_bytes)
        ocr_text, ocr_conf, ocr_meta = OCRService.extract_text_and_confidence(preprocessed_img)

        visual_meta = {
            "image_type": "standalone_image",
            "sharpness": prep_meta.get("sharpness"),
            "contrast": prep_meta.get("contrast"),
        }

        return [
            PageExtractionResult(
                page_number=1,
                text=ocr_text,
                extraction_method="ocr",
                confidence=ocr_conf,
                has_visual_content=True,
                visual_metadata=visual_meta,
                metadata={
                    "preprocessing": prep_meta,
                    "ocr_metadata": ocr_meta,
                },
            )
        ]
