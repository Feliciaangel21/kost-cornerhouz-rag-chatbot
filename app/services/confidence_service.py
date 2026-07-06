def detect_dynamic_question(message: str) -> bool:
    dynamic_keywords = [
        "kosong",
        "tersedia",
        "available",
        "ready",
        "masih ada",
        "ada kamar",
        "kamar ada",
        "bisa masuk",
        "masuk hari ini",
        "masuk besok",
        "check in",
        "check-in",
        "tanggal masuk",
        "promo",
        "diskon",
        "slot"
    ]

    message_lower = message.lower()
    return any(keyword in message_lower for keyword in dynamic_keywords)


def decide_action(results: list, user_message: str) -> dict:
    if not results:
        return {
            "action": "ESCALATE",
            "reason": "No retrieval result",
            "confidence": 0.0
        }

    top_result = results[0]
    top_score = top_result["score"]
    top_faq = top_result["faq"]

    second_score = results[1]["score"] if len(results) > 1 else 0.0
    score_gap = top_score - second_score

    is_dynamic_question = detect_dynamic_question(user_message)

    # If FAQ explicitly needs admin confirmation
    if top_faq.get("needs_admin_confirmation", False):
        return {
            "action": "ESCALATE_WITH_CONTEXT",
            "reason": "FAQ requires admin confirmation",
            "confidence": top_score
        }

    # If user asks dynamic info and top FAQ is dynamic
    if is_dynamic_question and top_faq.get("is_dynamic", False):
        return {
            "action": "ESCALATE_WITH_CONTEXT",
            "reason": "Dynamic information requires admin confirmation",
            "confidence": top_score
        }

    # Threshold adjusted based on your actual retrieval score
    if top_score >= 0.55:
        return {
            "action": "ANSWER",
            "reason": "High confidence",
            "confidence": top_score
        }

    if top_score >= 0.48 and score_gap >= 0.05:
        return {
            "action": "ANSWER_WITH_CAUTION",
            "reason": "Medium confidence with clear gap",
            "confidence": top_score
        }

    if top_score >= 0.38:
        return {
            "action": "ASK_CLARIFICATION",
            "reason": "Low-medium confidence",
            "confidence": top_score
        }

    return {
        "action": "ESCALATE",
        "reason": "Low confidence",
        "confidence": top_score
    }
