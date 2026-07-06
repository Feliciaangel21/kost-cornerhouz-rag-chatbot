def clean_answer(answer: str) -> str:
    bad_phrases = [
        "sistem akan mengecek data rooms_public terbaru",
        "rooms_public",
        "data rooms_public"
    ]

    cleaned = answer

    for phrase in bad_phrases:
        cleaned = cleaned.replace(phrase, "admin akan cek data ketersediaan kamar")

    return cleaned


def generate_template_reply(action: str, faq: dict | None, user_message: str) -> str:
    if action == "ANSWER":
        answer = clean_answer(faq["answer"])
        return f"{answer} Ada lagi yang mau ditanyakan, kak?"

    if action == "ANSWER_WITH_CAUTION":
        answer = clean_answer(faq["answer"])
        return f"{answer} Untuk info paling pastinya bisa dikonfirmasi lagi dengan admin ya, kak."

    if action == "ASK_CLARIFICATION":
        return (
            "Boleh diperjelas sedikit ya kak? "
            "Kakak mau tanya tentang harga, fasilitas, aturan, atau ketersediaan kamar?"
        )

    if action == "ESCALATE_WITH_CONTEXT":
        if faq:
            answer = clean_answer(faq["answer"])
            return f"{answer} Aku cekkan dulu ke admin untuk info pastinya ya, kak."

    return (
        "Maaf kak, untuk info itu aku perlu cek dulu dengan admin ya. "
        "Boleh tuliskan pertanyaannya lebih detail?"
    )
