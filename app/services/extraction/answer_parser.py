from dataclasses import dataclass
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ParsedAnswer:
    question_number: str
    answer_text: str
    confidence: float = 1.0
    source_page: Optional[int] = None
    matched: bool = False
    match_uncertain: bool = False
    uncertain_reason: Optional[str] = None


class AnswerKeyParser:
    """Parses answer key sections or documents and matches answers to questions."""

    # Patterns for individual answer entries:
    # 1-A, 1 - A, 1-(A)
    # 1. A, 1. (A), 1. True
    # 1) A, 1) (B)
    # 1: A, 1: (C)
    # 1 A
    # Q1: A, Question 1: B
    ENTRY_PATTERNS = [
        # Match "1-A", "1 - A", "1 - (B)"
        re.compile(
            r"(?:^|(?<=\s))(?:Q\.?|Question)?\s*(\d+|[A-Z])\s*[-–—]\s*(?:\(?([A-Za-z0-9]+)\)?)",
            re.IGNORECASE,
        ),
        # Match "1. A", "1. (A)", "1. True"
        re.compile(
            r"(?:^|(?<=\s))(?:Q\.?|Question)?\s*(\d+|[A-Z])\s*\.\s*(?:\(?([A-Za-z0-9]+)\)?)",
            re.IGNORECASE,
        ),
        # Match "1) A", "1) (A)"
        re.compile(
            r"(?:^|(?<=\s))(?:Q\.?|Question)?\s*(\d+|[A-Z])\s*\)\s*(?:\(?([A-Za-z0-9]+)\)?)",
            re.IGNORECASE,
        ),
        # Match "1: A", "1: (A)", "Q1: A"
        re.compile(
            r"(?:^|(?<=\s))(?:Q\.?|Question)?\s*(\d+|[A-Z])\s*:\s*(?:\(?([A-Za-z0-9]+)\)?)",
            re.IGNORECASE,
        ),
        # Match "1 A", "Q1 A"
        re.compile(
            r"(?:^|(?<=\s))(?:Q\.?|Question)?\s*(\d+|[A-Z])\s+([A-Da-d])(?=\s|$)",
            re.IGNORECASE,
        ),
    ]

    @classmethod
    def normalize_qnum(cls, q_num: str) -> str:
        """Normalize question numbering to comparable standard (e.g. 'Q1' -> '1')."""
        cleaned = re.sub(r"^(?:Q|Que|Ques|Question)\.?\s*", "", q_num.strip(), flags=re.IGNORECASE)
        return cleaned.strip()

    @classmethod
    def parse_answer_key_text(
        cls,
        text: str,
        source_page: Optional[int] = None,
    ) -> List[ParsedAnswer]:
        """Extract structured answers from an answer key string."""
        if not text:
            return []

        raw_answers: List[ParsedAnswer] = []

        for line in text.splitlines():
            line_str = line.strip()
            if not line_str:
                continue

            for pattern in cls.ENTRY_PATTERNS:
                matches = pattern.findall(line_str)
                if matches:
                    for q_raw, ans_raw in matches:
                        norm_q = cls.normalize_qnum(q_raw)
                        clean_ans = ans_raw.strip().upper()
                        raw_answers.append(
                            ParsedAnswer(
                                question_number=norm_q,
                                answer_text=clean_ans,
                                confidence=0.95,
                                source_page=source_page,
                                matched=False,
                            )
                        )
                    break

        # Check for multiple conflicting answer entries for the same question number
        grouped_by_q: Dict[str, List[ParsedAnswer]] = {}
        for a in raw_answers:
            grouped_by_q.setdefault(a.question_number, []).append(a)

        deduped_answers: List[ParsedAnswer] = []
        for q_num, items in grouped_by_q.items():
            distinct_values = {it.answer_text for it in items}
            if len(distinct_values) > 1:
                # Conflicting answers
                first = items[0]
                first.confidence = 0.40
                first.match_uncertain = True
                first.uncertain_reason = f"conflicting_answers: {', '.join(sorted(distinct_values))}"
                deduped_answers.append(first)
            else:
                deduped_answers.append(items[0])

        return deduped_answers

    @classmethod
    def match_answers_to_questions(
        cls,
        answers: List[ParsedAnswer],
        questions: List[Any],  # List[ParsedQuestion] or List[Question]
    ) -> Tuple[List[ParsedAnswer], Dict[str, str]]:
        """Match answers to questions by normalized question number.
        
        Validates option compatibility (e.g. MCQ answer must be in available options).
        Uncertain matches are flagged on the ParsedAnswer object.
        
        Returns:
            (updated_answers, mapping_of_question_number_to_answer)
        """
        # Build lookup table for questions
        q_map: Dict[str, Any] = {}
        for q in questions:
            q_num = getattr(q, "question_number", None)
            if q_num:
                norm = cls.normalize_qnum(q_num)
                q_map[norm] = q

        matched_map: Dict[str, str] = {}

        for ans in answers:
            norm_ans_q = cls.normalize_qnum(ans.question_number)
            if norm_ans_q in q_map:
                target_q = q_map[norm_ans_q]
                ans.matched = True
                matched_map[norm_ans_q] = ans.answer_text

                # Check option compatibility for MCQs
                q_type = getattr(target_q, "question_type", None)
                q_options = getattr(target_q, "options", None)
                if q_type == "MCQ" and isinstance(q_options, dict) and len(q_options) > 0:
                    valid_keys = {str(k).strip().upper() for k in q_options.keys()}
                    clean_ans_key = ans.answer_text.strip().upper()
                    if clean_ans_key not in valid_keys:
                        ans.match_uncertain = True
                        ans.uncertain_reason = f"option_mismatch: {clean_ans_key} not in {sorted(list(valid_keys))}"
                        ans.confidence = min(ans.confidence, 0.50)

                # If question object has attribute 'answer', set it
                if hasattr(target_q, "answer"):
                    target_q.answer = ans.answer_text

        return answers, matched_map

