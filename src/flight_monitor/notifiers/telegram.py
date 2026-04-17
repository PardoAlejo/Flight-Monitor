"""Telegram notification plugin using Bot API."""

from typing import Optional

import requests

from .base import FlightOffer, Notifier


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
        discount_pct: float,
    ) -> bool:
        if not self.is_configured():
            return False

        route = f"{offer.origin} -> {offer.destination}"
        lines = [
            "ALERTA DE VUELO BARATO",
            "",
            f"Ruta: {route}",
            f"Fecha: {offer.depart_date}",
            f"Precio: {offer.currency} {offer.price:,.0f}",
            f"Aerolinea: {offer.airline}",
        ]
        if offer.typical_price_low:
            lines.append(f"Rango tipico: {offer.currency} {offer.typical_price_low:,.0f} - {offer.typical_price_high:,.0f}")
            lines.append(f"{discount_pct:.1f}% por debajo del rango")

        text = "\n".join(lines)
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
