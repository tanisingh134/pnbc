from dataclasses import dataclass, field
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.extraction.pdf_extractor import PageExtractionResult

logger = logging.getLogger(__name__)


@dataclass
class ParsedQuestion:
    question_number: Optional[str]
    question_text: str
    options: Optional[Dict[str, str]]
    question_type: str  # MCQ, TRUE_FALSE, SHORT_ANSWER, DESCRIPTIVE, UNKNOWN
    source_pages: List[int]
    extraction_metadata: Dict[str, Any] = field(default_factory=dict)
    raw_lines: List[str] = field(default_factory=list)
    has_visual_content: bool = False


class QuestionParser:
    """State-machine and regex based parser for robust question and option extraction across document pages."""

    # Recognize headers that signal start of Answer Key sections
    ANSWER_KEY_SECTION_RE = re.compile(
        r"^(?:[\*#_=-]{0,3}\s*)?"
        r"(?:ANSWER\s*KEYS?|ANSWERS|SOLUTIONS?|CORRECT\s*ANSWERS?|KEYS?)"
        r"(?:\s*[:\-–]?\s*[\*#_=-]{0,3})?\s*$",
        re.IGNORECASE,
    )

    # Regexes for Question Start boundaries:
    # 1. Q1., Q.1, Q 1:, Que 1., Question 1:, Question 1
    # 2. 1., 2., 10.
    # 3. 1), 2), 10)
    # 4. (1), (2), (10)
    # 5. 1:
    QUESTION_START_PATTERNS = [
        re.compile(
            r"^(?:Q|Que|Ques|Question)\.?\s*(\d+|[A-Z])(?:[:.\)-]|\s+)\s*(.*)$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?:Question)\s+(\d+|[A-Z])\s*[:.\)-]?\s*(.*)$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(\d+)\s*[\.]\s+(.*)$"
        ),
        re.compile(
            r"^(\d+)\s*[\)]\s+(.*)$"
        ),
        re.compile(
            r"^\((\d+)\)\s*(.*)$"
        ),
        re.compile(
            r"^(\d+)\s*[:]\s+(.*)$"
        ),
    ]

    # Regex for options on a single line or start of line:
    # A., A), (A), a., a), (a), 1), (i), (ii), etc.
    OPTION_LINE_START_RE = re.compile(
        r"^(?:\(([A-Za-z0-9ivxIVX]+)\)|([A-Za-z0-9ivxIVX]+)\s*[\.\)])\s*(.*)$"
    )

    # Regex for finding inline options embedded across a single line:
    # e.g., "(A) Mumbai   (B) New Delhi   (C) Kolkata   (D) Chennai"
    # or "A. Option 1   B. Option 2   C. Option 3   D. Option 4"
    INLINE_OPTION_RE = re.compile(
        r"(?:^|(?<=\s))(?:(?:\(([A-Za-z0-9ivxIVX]+)\)|([A-Za-z0-9ivxIVX]+)\s*[\.\)]))\s*([^(\n\r]+?)(?=(?:\s+(?:\([A-Za-z0-9ivxIVX]+\)|[A-Za-z0-9ivxIVX]+\s*[\.\)]))|$)"
    )

    @classmethod
    def match_question_start(cls, line: str) -> Optional[Tuple[str, str]]:
        """Check if a line matches any question numbering pattern.
        
        Returns:
            (question_number, remaining_text_on_line) or None
        """
        stripped = line.strip()
        if not stripped:
            return None

        # Filter out common false positives like dates "2026.09", subheadings "1.1", bullet points
        if re.match(r"^\d+\.\d+", stripped):
            return None

        for pattern in cls.QUESTION_START_PATTERNS:
            m = pattern.match(stripped)
            if m:
                q_num = m.group(1)
                rem_text = m.group(2).strip() if len(m.groups()) >= 2 else ""
                return q_num, rem_text

        return None

    @classmethod
    def extract_inline_options(cls, text: str) -> Optional[Dict[str, str]]:
        """Try extracting multiple options from a single line."""
        matches = cls.INLINE_OPTION_RE.findall(text)
        if len(matches) >= 2:
            options: Dict[str, str] = {}
            for g1, g2, opt_text in matches:
                key = (g1 or g2).strip().upper()
                options[key] = opt_text.strip()
            return options
        return None

    @classmethod
    def classify_question_type(cls, question_text: str, options: Optional[Dict[str, str]]) -> str:
        """Classify question into MCQ, TRUE_FALSE, SHORT_ANSWER, DESCRIPTIVE, or UNKNOWN."""
        q_lower = question_text.lower()

        # Check options for True / False
        if options:
            opt_values_lower = [v.lower() for v in options.values()]
            if any(v in ("true", "false") for v in opt_values_lower):
                return "TRUE_FALSE"
            if len(options) >= 2:
                return "MCQ"

        # Check question prompt for True/False
        if "true or false" in q_lower or "state true or false" in q_lower:
            return "TRUE_FALSE"

        # Descriptive indicators
        descriptive_cues = (
            "explain", "describe", "discuss", "elaborate", "prove that",
            "derive", "write a short note", "critically examine", "summarize",
        )
        if any(q_lower.startswith(cue) or f" {cue} " in q_lower for cue in descriptive_cues):
            return "DESCRIPTIVE"

        # Length based classification
        if len(question_text) > 180:
            return "DESCRIPTIVE"

        if "fill in the blank" in q_lower or "____" in question_text:
            return "SHORT_ANSWER"

        if len(question_text) < 100:
            return "SHORT_ANSWER"

        return "DESCRIPTIVE" if len(question_text) > 120 else "UNKNOWN"

    @classmethod
    def parse_pages(
        cls,
        pages: List[PageExtractionResult],
    ) -> Tuple[List[ParsedQuestion], Optional[str]]:
        """Parse structured questions and separate answer key from page extraction results.
        
        Preserves multi-page questions across page boundaries.
        Returns:
            (list_of_parsed_questions, answer_key_text_if_detected)
        """
        # Step 1: Flatten lines with source page and metadata
        flat_lines: List[Tuple[str, int, bool, float]] = []
        for p in pages:
            raw_lines = p.text.splitlines()
            for line in raw_lines:
                flat_lines.append((line, p.page_number, p.has_visual_content, p.confidence))

        # Step 2: Separate Answer Key section if present
        question_lines: List[Tuple[str, int, bool, float]] = []
        answer_key_lines: List[str] = []
        in_answer_key = False

        for line, page_num, has_vis, conf in flat_lines:
            stripped = line.strip()
            if cls.ANSWER_KEY_SECTION_RE.match(stripped):
                in_answer_key = True
                continue

            if in_answer_key:
                answer_key_lines.append(line)
            else:
                question_lines.append((line, page_num, has_vis, conf))

        answer_key_text = "\n".join(answer_key_lines).strip() if answer_key_lines else None

        # Step 3: State machine to group question blocks across pages
        # A question continues across lines (and pages) until a new question start boundary is hit.
        raw_blocks: List[Dict[str, Any]] = []
        current_block: Optional[Dict[str, Any]] = None

        for line, page_num, has_vis, conf in question_lines:
            stripped = line.strip()
            if not stripped:
                continue

            q_match = cls.match_question_start(stripped)
            if q_match:
                q_num, first_line_text = q_match
                # Save previous block
                if current_block is not None:
                    raw_blocks.append(current_block)

                # Initialize new question block
                current_block = {
                    "question_number": q_num,
                    "first_line_text": first_line_text,
                    "body_lines": [first_line_text] if first_line_text else [],
                    "pages": [page_num],
                    "has_visual_content": has_vis,
                    "confidences": [conf],
                }
            else:
                # Continuation line
                if current_block is not None:
                    current_block["body_lines"].append(stripped)
                    if page_num not in current_block["pages"]:
                        current_block["pages"].append(page_num)
                    if has_vis:
                        current_block["has_visual_content"] = True
                    current_block["confidences"].append(conf)
                else:
                    # Header / front matter before first question - ignore or store
                    pass

        if current_block is not None:
            raw_blocks.append(current_block)

        # Step 4: For each raw question block, separate question prompt and options
        parsed_questions: List[ParsedQuestion] = []

        for block in raw_blocks:
            q_num = block["question_number"]
            body_lines = block["body_lines"]
            pages_list = sorted(list(set(block["pages"])))

            prompt_parts: List[str] = []
            options_dict: Dict[str, str] = {}
            current_opt_key: Optional[str] = None

            for line in body_lines:
                # First check if the line contains inline options: (A) ... (B) ...
                inline_opts = cls.extract_inline_options(line)
                if inline_opts:
                    options_dict.update(inline_opts)
                    continue

                # Check if line starts an option: A. Option or (A) Option
                opt_m = cls.OPTION_LINE_START_RE.match(line)
                if opt_m:
                    opt_key = (opt_m.group(1) or opt_m.group(2)).strip().upper()
                    opt_val = opt_m.group(3).strip()
                    options_dict[opt_key] = opt_val
                    current_opt_key = opt_key
                else:
                    if current_opt_key is not None:
                        # Append continuation of current option text
                        options_dict[current_opt_key] += " " + line
                    else:
                        # Continuation of question prompt
                        prompt_parts.append(line)

            question_text = " ".join(prompt_parts).strip()
            # If prompt was empty, use entire body
            if not question_text:
                question_text = " ".join(body_lines).strip()

            q_type = cls.classify_question_type(
                question_text,
                options_dict if options_dict else None,
            )

            avg_page_conf = (
                sum(block["confidences"]) / len(block["confidences"])
                if block["confidences"]
                else 1.0
            )

            extraction_meta = {
                "source_pages": pages_list,
                "multi_page": len(pages_list) > 1,
                "has_visual_content": block["has_visual_content"],
                "avg_page_confidence": round(avg_page_conf, 3),
            }

            parsed_questions.append(
                ParsedQuestion(
                    question_number=str(q_num),
                    question_text=question_text,
                    options=options_dict if options_dict else None,
                    question_type=q_type,
                    source_pages=pages_list,
                    extraction_metadata=extraction_meta,
                    raw_lines=body_lines,
                    has_visual_content=block["has_visual_content"],
                )
            )

        return parsed_questions, answer_key_text
