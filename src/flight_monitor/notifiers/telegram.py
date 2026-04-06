"""Telegram notification plugin using Bot API."""

from typing import Optional

import requests

from .base import FlightOffer, Notifier, PriceStats


class TelegramNotifier(Notifier):
    """Send notifications via Telegram Bot API."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: int = 10,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(
        self,
        offer: FlightOffer,
        stats: PriceStats,
        discount_pct: float,
    ) -> bool:
        if not self.is_configured():
            return False

        text = self.build_message(offer, stats, discount_pct)
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        try:
            resp = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": text},
                timeout=self.timeout,
            )
            if resp.ok:
                print("[Telegram] Alerta enviada.")
                return True
            else:
                print(f"[Telegram] Error: {resp.text}")
                return False
        except Exception as e:
            print(f"[Telegram] Error de conexion: {e}")
            return False
