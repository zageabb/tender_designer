from types import SimpleNamespace

from services.chat_service import (
    _is_informational_question,
    build_chat_response,
    classify_message_intent,
)


class UnexpectedClassifier:
    def generate_json(self, *_args, **_kwargs):
        raise AssertionError("Informational questions must bypass action classification")


def test_submission_type_question_is_read_only():
    intent, steps = classify_message_intent(
        UnexpectedClassifier(),
        "irrelevant-model",
        "what is the submission type for this tender",
        has_upload=False,
        has_tender_context=True,
    )
    assert intent == "general_answer"
    assert any("Read-only" in step for step in steps)


def test_question_about_questions_is_not_an_update():
    assert _is_informational_question("what questions need to be answered?")
    assert _is_informational_question("can you tell me the submission type?")
    assert not _is_informational_question("can you fill in the answers to the questions?")


def test_even_misclassified_factual_question_does_not_propose_update():
    tender = SimpleNamespace(
        id=61,
        title="Apple iMac Computers",
        tender_number="182",
        customer_name="Test customer",
        status="Open",
        documents=[],
        items=[],
        rfqs=[],
        questions=[SimpleNamespace(answer_status="Unanswered")],
    )
    result = build_chat_response(
        "what is the submission type for this tender",
        {"page": "tender_detail", "tender_id": 61},
        tender,
        intent_hint="answer_questions_from_documents",
    )
    assert result["response_type"] == "answer"
    assert result.get("actions") == []
    assert "fill draft answers" not in result["message"]
