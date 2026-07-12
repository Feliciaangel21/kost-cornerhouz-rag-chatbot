# app/services/move_in_gate_service.py

import re
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel


class MoveInGateStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    NEED_DATE = "need_date"
    ALLOWED = "allowed"
    TOO_FAR = "too_far"
    PAST_DATE = "past_date"


class MoveInGateResult(BaseModel):
    status: MoveInGateStatus
    allowed_to_forward_admin: bool
    message: Optional[str] = None
    days_until_move_in: Optional[int] = None
    parsed_move_in_date: Optional[date] = None


class MoveInGateService:
    def __init__(self, max_keep_days: int = 15):
        self.max_keep_days = max_keep_days

    def check(
        self,
        requires_admin_forward: bool,
        move_in_date: Optional[date],
        user_message: str = "",
    ) -> MoveInGateResult:
        if not requires_admin_forward:
            return MoveInGateResult(
                status=MoveInGateStatus.NOT_REQUIRED,
                allowed_to_forward_admin=False,
            )

        today = datetime.now(ZoneInfo("Asia/Jakarta")).date()

        # Backend fallback parser if LLM failed to extract date
        if move_in_date is None:
            move_in_date = self._parse_indonesian_date(user_message, today)

        # Vague far date like "bulan depan"
        if move_in_date is None and self._is_vague_too_far_date(user_message):
            return MoveInGateResult(
                status=MoveInGateStatus.TOO_FAR,
                allowed_to_forward_admin=False,
                message=(
                    "Maaf kak, untuk saat ini kami belum bisa keep kamar terlalu lama. "
                    "Kalau rencana masuknya masih bulan depan, kakak bisa tanya lagi "
                    "mendekati tanggal masuk ya, kira-kira 1–2 minggu sebelumnya supaya "
                    "info kamar kosongnya lebih akurat."
                ),
            )

        if move_in_date is None:
            return MoveInGateResult(
                status=MoveInGateStatus.NEED_DATE,
                allowed_to_forward_admin=False,
                message=(
                    "Boleh kak. Rencana mulai masuk tanggal berapa ya? "
                    "Soalnya kami belum bisa keep kamar terlalu lama."
                ),
            )

        days_until = (move_in_date - today).days

        if days_until < 0:
            return MoveInGateResult(
                status=MoveInGateStatus.PAST_DATE,
                allowed_to_forward_admin=False,
                days_until_move_in=days_until,
                parsed_move_in_date=move_in_date,
                message=(
                    "Tanggal masuknya sepertinya sudah lewat ya kak. "
                    "Boleh info ulang rencana mulai masuk tanggal berapa?"
                ),
            )

        if days_until <= self.max_keep_days:
            return MoveInGateResult(
                status=MoveInGateStatus.ALLOWED,
                allowed_to_forward_admin=True,
                days_until_move_in=days_until,
                parsed_move_in_date=move_in_date,
                message=(
                    "Oke kak, bisa kami bantu lanjutkan ke admin ya. "
                    "Karena kamar tidak bisa di-keep terlalu lama, kami prioritaskan "
                    "yang rencana masuknya dalam waktu dekat."
                ),
            )

        return MoveInGateResult(
            status=MoveInGateStatus.TOO_FAR,
            allowed_to_forward_admin=False,
            days_until_move_in=days_until,
            parsed_move_in_date=move_in_date,
            message=(
                "Maaf kak, untuk saat ini kami belum bisa keep kamar terlalu lama. "
                "Kakak bisa tanya lagi mendekati tanggal masuk ya, kira-kira "
                "1–2 minggu sebelumnya supaya info kamar kosongnya lebih akurat."
            ),
        )

    def _is_vague_too_far_date(self, user_message: str) -> bool:
        text = (user_message or "").lower().strip()

        too_far_phrases = [
            "bulan depan",
            "bln depan",
            "bulan dpn",
            "next month",
            "akhir bulan depan",
            "semester depan",
            "tahun depan",
            "masih lama",
        ]

        return any(phrase in text for phrase in too_far_phrases)

    def _parse_indonesian_date(
        self,
        user_message: str,
        today: date,
    ) -> Optional[date]:
        text = (user_message or "").lower().strip()

        if not text:
            return None

        if "hari ini" in text or text in {"today"}:
            return today

        if "besok" in text or text in {"tomorrow"}:
            return today + timedelta(days=1)

        if "lusa" in text:
            return today + timedelta(days=2)

        month_map = {
            "januari": 1,
            "jan": 1,
            "februari": 2,
            "feb": 2,
            "maret": 3,
            "mar": 3,
            "april": 4,
            "apr": 4,
            "mei": 5,
            "juni": 6,
            "jun": 6,
            "juli": 7,
            "jul": 7,
            "agustus": 8,
            "agus": 8,
            "aug": 8,
            "september": 9,
            "sep": 9,
            "oktober": 10,
            "okt": 10,
            "oct": 10,
            "november": 11,
            "nov": 11,
            "desember": 12,
            "des": 12,
            "dec": 12,
        }

        # Examples:
        # "tgl 7 bulan juli"
        # "tanggal 7 juli"
        # "7 juli"
        month_names = "|".join(month_map.keys())

        patterns = [
            rf"(?:tgl|tanggal)?\s*(\d{{1,2}})\s*(?:bulan)?\s*({month_names})",
            rf"({month_names})\s*(\d{{1,2}})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)

            if not match:
                continue

            first = match.group(1)
            second = match.group(2)

            if first.isdigit():
                day = int(first)
                month = month_map.get(second)
            else:
                month = month_map.get(first)
                day = int(second)

            if not month:
                continue

            try:
                parsed = date(today.year, month, day)

                # If date already passed this year, assume next year.
                if parsed < today:
                    parsed = date(today.year + 1, month, day)

                return parsed
            except ValueError:
                return None

        # Numeric date examples:
        # "7/7", "07-07", "7 7"
        numeric_match = re.search(
            r"(?:tgl|tanggal)?\s*(\d{1,2})\s*[\/\-\s]\s*(\d{1,2})",
            text,
        )

        if numeric_match:
            day = int(numeric_match.group(1))
            month = int(numeric_match.group(2))

            try:
                parsed = date(today.year, month, day)

                if parsed < today:
                    parsed = date(today.year + 1, month, day)

                return parsed
            except ValueError:
                return None

        # Only day mentioned:
        # "tgl 7", "tanggal 15"
        day_only_match = re.search(r"(?:tgl|tanggal)\s*(\d{1,2})", text)
        if not day_only_match:
            day_only_match = re.fullmatch(r"(\d{1,2})", text)

        if day_only_match:
            day = int(day_only_match.group(1))

            try:
                parsed = date(today.year, today.month, day)

                if parsed < today:
                    if today.month == 12:
                        parsed = date(today.year + 1, 1, day)
                    else:
                        parsed = date(today.year, today.month + 1, day)

                return parsed
            except ValueError:
                return None

        return None
