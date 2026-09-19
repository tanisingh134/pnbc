import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ConfidenceCalculator:
    """Documented heuristic scoring system for extracted questions.
    
    NOTE: This score is a heuristic index bounded between 0.0 and 1.0 designed to identify
    extraction anomalies and prioritize human review. It is NOT a calibrated Bayesian probability.
    
    Classification Bands:
        >= 0.80 : High confidence / Successfully extracted
        0.60 - 0.79 : Partial / Medium confidence (may warrant spot checking)
        < 0.60  : Low confidence / Review strictly required (needs_review = True)
    """

    @classmethod
    def calculate(
        cls,
        question_text: str,
        question_number: Optional[str],
        question_type: str,
        options: Optional[Dict[str, str]],
        base_page_confidence: float = 1.0,
        answer_matched: bool = False,
    ) -> float:
        """Calculate weighted heuristic confidence score in range [0.0, 1.0].
        
        Signals evaluated:
        1. OCR / Text extraction fidelity (0.0 - 1.0)
        2. Question numbering validity
        3. Text completeness and character health
        4. Option consistency (for MCQs)
        5. Answer verification bonus
        6. Trailing fragment / truncation penalty
        """
        score = base_page_confidence * 0.35  # Max 0.35 contribution from text/OCR quality

        # Signal 1: Question Numbering (0.15)
        if question_number and question_number.isdigit():
            score += 0.15
        elif question_number:
            score += 0.10
        else:
            score += 0.02

        # Signal 2: Question Text Quality (0.25)
        q_len = len(question_text.strip())
        if q_len >= 20:
            score += 0.20
        elif q_len >= 10:
            score += 0.12
        else:
            score += 0.04

        # Check for unprintable/garbled characters
        weird_chars = len(re.findall(r"[^\w\s\.,\?\!\-\(\)\'\":;%]", question_text))
        if weird_chars > 3:
            score -= 0.10

        # Check for incomplete/truncated ending (e.g., ends in hyphen or lowercase without punctuation)
        if question_text.endswith(("-", "...", "and", "or", "the", "a")):
            score -= 0.12

        # Signal 3: Option Structure Consistency (0.20 for MCQs)
        if question_type == "MCQ":
            if options:
                opt_count = len(options)
                keys = set(options.keys())
                standard_4 = {"A", "B", "C", "D"}
                standard_5 = {"A", "B", "C", "D", "E"}

                if standard_4.issubset(keys) or standard_5.issubset(keys):
                    score += 0.20
                elif opt_count >= 3:
                    score += 0.15
                elif opt_count == 2:
                    score += 0.10
                else:
                    score += 0.03
            else:
                score -= 0.10  # MCQ marked but 0 options parsed!
        else:
            # For non-MCQs (descriptive, short answer), grant baseline option score
            score += 0.15

        # Signal 4: Answer match bonus (0.05)
        if answer_matched:
            score += 0.05

        # Clamp strictly between 0.05 and 1.0
        final_score = max(0.05, min(1.0, score))
        return round(final_score, 2)

    @classmethod
    def evaluate_needs_review(cls, confidence: float, warnings_count: int = 0) -> bool:
        """Determine if question requires human intervention (< 0.60 or multiple warnings)."""
        return confidence < 0.60 or warnings_count > 0
