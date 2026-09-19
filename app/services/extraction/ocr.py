import logging
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    import pytesseract
except ImportError:
    pytesseract = None


class OCRService:
    """Optical Character Recognition service wrapping Tesseract OCR with confidence extraction."""

    _configured: bool = False

    @classmethod
    def configure(cls) -> bool:
        """Configure Tesseract executable path if available."""
        if cls._configured:
            return True
        if pytesseract is None:
            logger.warning("pytesseract library is not installed")
            return False

        cmd = settings.resolved_tesseract_cmd
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
            logger.info(f"Configured Tesseract OCR binary: {cmd}")
            cls._configured = True
            return True
        else:
            logger.warning("No Tesseract executable found on system or PATH")
            return False

    @classmethod
    def is_available(cls) -> bool:
        """Check if Tesseract is configured and executable."""
        if pytesseract is None:
            return False
        cls.configure()
        cmd = settings.resolved_tesseract_cmd
        return cmd is not None

    @classmethod
    def extract_text_and_confidence(
        cls,
        image: Image.Image,
        lang: str = "eng",
    ) -> Tuple[str, float, Dict[str, Any]]:
        """Run OCR on a PIL Image and calculate text, average word confidence, and token count.
        
        Returns:
            (text, mean_confidence_0_to_1, metadata_dict)
        """
        if not cls.configure():
            return "", 0.0, {"error": "Tesseract OCR not configured or available"}

        try:
            # Extract structured OCR data including per-word confidence
            data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
            
            words: List[str] = []
            confidences: List[float] = []

            n_boxes = len(data["text"])
            for i in range(n_boxes):
                text_tok = data["text"][i].strip()
                conf_val = float(data["conf"][i])
                if text_tok and conf_val >= 0:
                    words.append(text_tok)
                    confidences.append(conf_val)

            # Also get full layout preserved string
            full_text = pytesseract.image_to_string(image, lang=lang).strip()

            if confidences:
                # Tesseract reports 0-100, scale to 0.0-1.0
                mean_conf = float(sum(confidences) / len(confidences)) / 100.0
            else:
                mean_conf = 0.0 if not full_text else 0.5

            metadata = {
                "word_count": len(words),
                "token_confidences_sample": confidences[:10],
                "raw_confidence_pct": round(mean_conf * 100, 1),
                "lang": lang,
            }

            return full_text, round(mean_conf, 3), metadata

        except Exception as exc:
            logger.warning(f"Tesseract OCR extraction failed: {exc}")
            return "", 0.0, {"error": f"OCR extraction error: {str(exc)}"}
