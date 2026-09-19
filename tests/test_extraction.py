import numpy as np
import pytest
from PIL import Image

from app.services.extraction.answer_parser import AnswerKeyParser, ParsedAnswer
from app.services.extraction.confidence import ConfidenceCalculator
from app.services.extraction.pdf_extractor import PageExtractionResult
from app.services.extraction.preprocessor import ImagePreprocessor
from app.services.extraction.question_parser import ParsedQuestion, QuestionParser
from app.services.extraction.warning_service import WarningDetector


# 1. Normal Question Parsing
def test_normal_question_parsing():
    sample_text = """
    1. What is the capital of France?
    A. Berlin
    B. Madrid
    C. Paris
    D. Rome
    
    2. Which planet is known as the Red Planet?
    (A) Venus
    (B) Mars
    (C) Jupiter
    (D) Saturn
    """
    page = PageExtractionResult(page_number=1, text=sample_text, extraction_method="direct", confidence=1.0)
    questions, answer_key = QuestionParser.parse_pages([page])

    assert len(questions) == 2
    assert answer_key is None

    q1 = questions[0]
    assert q1.question_number == "1"
    assert "capital of France" in q1.question_text
    assert q1.question_type == "MCQ"
    assert q1.options == {"A": "Berlin", "B": "Madrid", "C": "Paris", "D": "Rome"}
    assert q1.source_pages == [1]

    q2 = questions[1]
    assert q2.question_number == "2"
    assert "Red Planet" in q2.question_text
    assert q2.question_type == "MCQ"
    assert q2.options == {"A": "Venus", "B": "Mars", "C": "Jupiter", "D": "Saturn"}


# 2. Numbering Format Variants
@pytest.mark.parametrize(
    "header,expected_num",
    [
        ("1. What is gravity?", "1"),
        ("1) What is gravity?", "1"),
        ("Q1. What is gravity?", "1"),
        ("Q.1 What is gravity?", "1"),
        ("Question 1 What is gravity?", "1"),
        ("Question 1: What is gravity?", "1"),
        ("Question 1. What is gravity?", "1"),
        ("(1) What is gravity?", "1"),
        ("1: What is gravity?", "1"),
    ],
)
def test_question_numbering_variants(header, expected_num):
    q_match = QuestionParser.match_question_start(header)
    assert q_match is not None
    q_num, rem_text = q_match
    assert q_num == expected_num
    assert "gravity" in rem_text


# 3. Different Option Formats
def test_option_formats():
    text_with_diff_options = """
    1. Test option formats:
    A. Option A
    B) Option B
    (C) Option C
    d. Option D
    (e) Option E
    (i) Roman Option
    """
    page = PageExtractionResult(page_number=1, text=text_with_diff_options, extraction_method="direct", confidence=1.0)
    questions, _ = QuestionParser.parse_pages([page])
    assert len(questions) == 1
    opts = questions[0].options
    assert opts is not None
    assert opts.get("A") == "Option A"
    assert opts.get("B") == "Option B"
    assert opts.get("C") == "Option C"
    assert opts.get("D") == "Option D"
    assert opts.get("E") == "Option E"
    assert opts.get("I") == "Roman Option"


# 4. Multi-Page Question Continuity
def test_multi_page_question_continuity():
    page1_text = """
    1. Consider a block of mass m placed on an inclined plane of angle theta.
    Assuming the coefficient of kinetic friction is mu_k,
    """
    page2_text = """
    calculate the acceleration of the block as it slides down the incline.
    A. g(sin theta - mu_k cos theta)
    B. g(cos theta - mu_k sin theta)
    C. g sin theta
    D. g mu_k
    
    2. Define inertia.
    """
    p1 = PageExtractionResult(page_number=1, text=page1_text, extraction_method="direct", confidence=0.98)
    p2 = PageExtractionResult(page_number=2, text=page2_text, extraction_method="direct", confidence=0.98)

    questions, _ = QuestionParser.parse_pages([p1, p2])
    assert len(questions) == 2

    q1 = questions[0]
    assert q1.question_number == "1"
    # Verify continuity
    assert "mass m placed on an inclined plane" in q1.question_text
    assert "calculate the acceleration of the block" in q1.question_text
    assert q1.source_pages == [1, 2]
    assert q1.extraction_metadata["multi_page"] is True
    assert q1.options is not None
    assert len(q1.options) == 4

    q2 = questions[1]
    assert q2.question_number == "2"
    assert q2.source_pages == [2]


# 5. Answer-Key Parsing & Matching
def test_answer_key_parsing():
    sample_key_text = """
    ANSWER KEY
    1-A
    2. B
    3) C
    4: D
    5 A
    Q6: B
    Question 7: C
    """
    answers = AnswerKeyParser.parse_answer_key_text(sample_key_text, source_page=2)
    assert len(answers) == 7

    assert answers[0].question_number == "1"
    assert answers[0].answer_text == "A"
    assert answers[1].question_number == "2"
    assert answers[1].answer_text == "B"
    assert answers[2].question_number == "3"
    assert answers[2].answer_text == "C"
    assert answers[3].question_number == "4"
    assert answers[3].answer_text == "D"
    assert answers[4].question_number == "5"
    assert answers[4].answer_text == "A"
    assert answers[5].question_number == "6"
    assert answers[5].answer_text == "B"
    assert answers[6].question_number == "7"
    assert answers[6].answer_text == "C"


def test_answer_matching():
    q1 = ParsedQuestion(
        question_number="1",
        question_text="Sample Q1",
        options={"A": "opt1"},
        question_type="MCQ",
        source_pages=[1],
    )
    q2 = ParsedQuestion(
        question_number="Q2",
        question_text="Sample Q2",
        options={"B": "opt2"},
        question_type="MCQ",
        source_pages=[1],
    )
    answers = [
        ParsedAnswer(question_number="1", answer_text="A"),
        ParsedAnswer(question_number="2", answer_text="B"),
        ParsedAnswer(question_number="99", answer_text="C"),  # unmatched
    ]

    updated_ans, matched_map = AnswerKeyParser.match_answers_to_questions(answers, [q1, q2])

    assert updated_ans[0].matched is True
    assert updated_ans[1].matched is True
    assert updated_ans[2].matched is False

    assert matched_map["1"] == "A"
    assert matched_map["2"] == "B"


# 6. Confidence Calculation
def test_confidence_calculation():
    # Clean complete question with 4 options and matched answer
    clean_score = ConfidenceCalculator.calculate(
        question_text="What is the chemical symbol for gold in the periodic table?",
        question_number="1",
        question_type="MCQ",
        options={"A": "Au", "B": "Ag", "C": "Fe", "D": "Pb"},
        base_page_confidence=1.0,
        answer_matched=True,
    )
    assert clean_score >= 0.80

    # Truncated question ending in hyphen with missing options
    bad_score = ConfidenceCalculator.calculate(
        question_text="The process of photosyn-",
        question_number=None,
        question_type="MCQ",
        options={"A": "Chlorophyll"},
        base_page_confidence=0.40,
        answer_matched=False,
    )
    assert bad_score < 0.60
    assert ConfidenceCalculator.evaluate_needs_review(bad_score) is True


# 7. Low-Confidence & Warning Generation
def test_low_confidence_and_warnings():
    # Missing number and truncated text
    q_warnings = WarningDetector.inspect_question(
        question_number=None,
        question_text="short...",
        question_type="MCQ",
        options={"A": "only one"},
        confidence=0.45,
        source_pages=[1],
        has_visual_content=True,
    )

    types = [w.warning_type for w in q_warnings]
    assert WarningDetector.MISSING_QUESTION_NUMBER in types
    assert WarningDetector.POSSIBLE_INCOMPLETE_QUESTION in types
    assert WarningDetector.OPTION_PARSE_UNCERTAIN in types
    assert WarningDetector.POSSIBLE_VISUAL_CONTENT in types

    # Unmatched answer warning
    unmatched_w = WarningDetector.inspect_unmatched_answer(
        question_number="10",
        answer_text="D",
        source_page=1,
    )
    assert unmatched_w.warning_type == WarningDetector.ANSWER_UNMATCHED


# 8. Image Preprocessing
def test_image_preprocessing():
    # Create test synthetic image
    img = Image.new("RGB", (200, 100), color=(255, 255, 255))
    preprocessed, meta = ImagePreprocessor.preprocess_for_ocr(img)

    assert isinstance(preprocessed, Image.Image)
    assert "contrast" in meta
    assert "sharpness" in meta
    assert "skew_angle" in meta
