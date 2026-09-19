import io
import logging
from typing import Any, Dict, Optional, Tuple, Union
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

try:
    import cv2
except ImportError:
    cv2 = None  # Handled gracefully if not yet loaded


class ImagePreprocessor:
    """OpenCV and Pillow based image preprocessing pipeline for high-accuracy OCR."""

    @staticmethod
    def to_cv2(image_input: Union[Image.Image, np.ndarray, bytes]) -> np.ndarray:
        """Convert input (PIL Image, bytes, or numpy array) to an OpenCV BGR ndarray."""
        if isinstance(image_input, np.ndarray):
            return image_input.copy()
        elif isinstance(image_input, Image.Image):
            rgb = image_input.convert("RGB")
            arr = np.array(rgb)
            if cv2:
                return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            return arr
        elif isinstance(image_input, (bytes, bytearray)):
            if cv2:
                nparr = np.frombuffer(image_input, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is not None:
                    return img
            # Fallback to PIL
            pil_img = Image.open(io.BytesIO(image_input)).convert("RGB")
            arr = np.array(pil_img)
            if cv2:
                return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            return arr
        else:
            raise ValueError(f"Unsupported image input type: {type(image_input)}")

    @staticmethod
    def to_pil(cv2_image: np.ndarray) -> Image.Image:
        """Convert an OpenCV image (grayscale or BGR) to PIL Image."""
        if len(cv2_image.shape) == 2:
            return Image.fromarray(cv2_image)
        elif len(cv2_image.shape) == 3:
            if cv2:
                rgb = cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB)
                return Image.fromarray(rgb)
            return Image.fromarray(cv2_image)
        raise ValueError("Invalid array dimensions for image conversion")

    @classmethod
    def to_grayscale(cls, img: np.ndarray) -> np.ndarray:
        """Convert image to single-channel grayscale if needed."""
        if len(img.shape) == 2:
            return img
        if cv2:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Fallback luminance formula
        return np.dot(img[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)

    @classmethod
    def assess_quality(cls, gray: np.ndarray) -> Dict[str, float]:
        """Compute objective quality metrics: contrast ratio and Laplacian blur variance."""
        # Dynamic range contrast
        min_val = float(np.min(gray))
        max_val = float(np.max(gray))
        contrast = (max_val - min_val) / 255.0

        # Sharpness / blur measure via Laplacian variance
        sharpness = 100.0
        if cv2:
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            sharpness = float(laplacian.var())

        return {
            "contrast": round(contrast, 3),
            "sharpness": round(sharpness, 2),
            "is_low_contrast": contrast < 0.45,
            "is_blurry": sharpness < 40.0,
        }

    @classmethod
    def enhance_contrast(cls, gray: np.ndarray) -> np.ndarray:
        """Enhance contrast of faint/low-quality scans using CLAHE."""
        if not cv2:
            return gray
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(gray)

    @classmethod
    def denoise(cls, gray: np.ndarray) -> np.ndarray:
        """Remove high-frequency scan noise/speckles without destroying character strokes."""
        if not cv2:
            return gray
        # Gaussian blur with subtle 3x3 kernel
        return cv2.GaussianBlur(gray, (3, 3), 0)

    @classmethod
    def deskew(cls, gray: np.ndarray, max_angle: float = 30.0) -> Tuple[np.ndarray, float]:
        """Detect and correct document skew angle."""
        if not cv2:
            return gray, 0.0

        try:
            # Invert and threshold to get text pixels
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            coords = np.column_stack(np.where(thresh > 0))
            if len(coords) < 50:
                return gray, 0.0

            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = -(90 + angle)
            elif angle > 45:
                angle = 90 - angle
            else:
                angle = -angle

            # Clamp detection to plausible document skew
            if abs(angle) < 0.5 or abs(angle) > max_angle:
                return gray, 0.0

            (h, w) = gray.shape[:2]
            center = (w // 2, h // 2)
            rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(
                gray,
                rot_mat,
                (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            return rotated, round(float(angle), 2)
        except Exception as exc:
            logger.debug(f"Deskew failed: {exc}")
            return gray, 0.0

    @classmethod
    def binarize(cls, gray: np.ndarray) -> np.ndarray:
        """Apply Otsu automatic thresholding for crisp text binarization."""
        if not cv2:
            return gray
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    @classmethod
    def preprocess_for_ocr(
        cls,
        image_input: Union[Image.Image, np.ndarray, bytes],
    ) -> Tuple[Image.Image, Dict[str, Any]]:
        """Complete image preprocessing pipeline for OCR.
        
        Applies:
        1. Grayscale conversion
        2. Quality assessment
        3. Contrast enhancement (if low contrast)
        4. Subtle noise filtering
        5. Deskewing / rotation correction
        6. Otsu binarization
        
        Returns:
            (preprocessed_pil_image, metadata_dict)
        """
        cv_img = cls.to_cv2(image_input)
        gray = cls.to_grayscale(cv_img)
        quality = cls.assess_quality(gray)

        # Enhance contrast if faint
        if quality["is_low_contrast"]:
            gray = cls.enhance_contrast(gray)

        # Denoise
        denoised = cls.denoise(gray)

        # Deskew
        deskewed, skew_angle = cls.deskew(denoised)

        # Binarize for OCR
        binarized = cls.binarize(deskewed)

        pil_result = cls.to_pil(binarized)
        metadata = {
            "skew_angle": skew_angle,
            "contrast": quality["contrast"],
            "sharpness": quality["sharpness"],
            "is_low_contrast": quality["is_low_contrast"],
            "is_blurry": quality["is_blurry"],
        }
        return pil_result, metadata
