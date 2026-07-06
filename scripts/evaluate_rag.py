import json

from app.services.retriever_service import RetrieverService
from app.services.confidence_service import decide_action


EVAL_PATH = "data/faq_eval_questions.json"


def main():
    retriever = RetrieverService()

    with open(EVAL_PATH, "r", encoding="utf-8") as f:
        eval_data = json.load(f)

    total = len(eval_data)

    answerable_cases = [
        item for item in eval_data
        if item["expected_faq_id"] is not None
    ]

    no_answer_cases = [
        item for item in eval_data
        if item["expected_faq_id"] is None
    ]

    top1_correct = 0
    top3_correct = 0
    escalation_correct = 0
    no_answer_correct = 0

    failed_cases = []

    for item in eval_data:
        question = item["question"]
        expected_faq_id = item["expected_faq_id"]
        should_escalate = item["should_escalate"]

        results = retriever.search(question, top_k=5)
        decision = decide_action(results, question)

        predicted_top1 = results[0]["faq"]["id"] if results else None
        predicted_top3 = [r["faq"]["id"] for r in results[:3]]

        predicted_escalate = decision["action"] in [
            "ESCALATE",
            "ESCALATE_WITH_CONTEXT"
        ]

        is_escalation_correct = predicted_escalate == should_escalate

        if is_escalation_correct:
            escalation_correct += 1

        # For questions with known FAQ answer
        if expected_faq_id is not None:
            is_top1_correct = predicted_top1 == expected_faq_id
            is_top3_correct = expected_faq_id in predicted_top3

            if is_top1_correct:
                top1_correct += 1

            if is_top3_correct:
                top3_correct += 1

            if not is_top1_correct or not is_escalation_correct:
                failed_cases.append({
                    "question": question,
                    "expected_faq_id": expected_faq_id,
                    "predicted_top1": predicted_top1,
                    "predicted_top3": predicted_top3,
                    "action": decision["action"],
                    "confidence": decision["confidence"],
                    "should_escalate": should_escalate,
                    "predicted_escalate": predicted_escalate
                })

        # For unknown/no-answer questions
        else:
            if predicted_escalate:
                no_answer_correct += 1
            else:
                failed_cases.append({
                    "question": question,
                    "expected_faq_id": expected_faq_id,
                    "predicted_top1": predicted_top1,
                    "predicted_top3": predicted_top3,
                    "action": decision["action"],
                    "confidence": decision["confidence"],
                    "should_escalate": should_escalate,
                    "predicted_escalate": predicted_escalate
                })

        print("-" * 70)
        print("Question:", question)
        print("Expected FAQ:", expected_faq_id)
        print("Top 3:", predicted_top3)
        print("Action:", decision["action"])
        print("Confidence:", round(decision["confidence"], 3))
        print("Escalate:", predicted_escalate)

    print("=" * 70)
    print("TOTAL QUESTIONS:", total)
    print("ANSWERABLE QUESTIONS:", len(answerable_cases))
    print("NO-ANSWER QUESTIONS:", len(no_answer_cases))

    if answerable_cases:
        print("Top-1 Retrieval Accuracy:", round(top1_correct / len(answerable_cases), 3))
        print("Top-3 Retrieval Accuracy:", round(top3_correct / len(answerable_cases), 3))

    print("Escalation Accuracy:", round(escalation_correct / total, 3))

    if no_answer_cases:
        print("No-Answer Escalation Accuracy:", round(no_answer_correct / len(no_answer_cases), 3))

    print("\nFAILED / NEEDS REVIEW:")
    if not failed_cases:
        print("No failed cases. Nice.")
    else:
        for case in failed_cases:
            print("-" * 70)
            print("Question:", case["question"])
            print("Expected:", case["expected_faq_id"])
            print("Predicted:", case["predicted_top1"])
            print("Top 3:", case["predicted_top3"])
            print("Action:", case["action"])
            print("Confidence:", round(case["confidence"], 3))
            print("Should escalate:", case["should_escalate"])
            print("Predicted escalate:", case["predicted_escalate"])


if __name__ == "__main__":
    main()
