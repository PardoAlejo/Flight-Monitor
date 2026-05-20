"""Telegram notification plugin using Bot API."""

from datetime import datetime
from typing import Optional

import requests

from .base import FlightCheckResult, Notifier


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

    def _sanitize_error(self, error: Exception) -> str:
        """Remove bot token from exception messages before logging them."""
        message = str(error)
        if self.bot_token:
            return message.replace(self.bot_token, "***REDACTED***")
        return message

    def send_summary(self, results: list[FlightCheckResult]) -> bool:
        """Send daily summary via Telegram."""
        if not self.is_configured():
            return False

        assert self.bot_token is not None
        assert self.chat_id is not None

        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "✈️ RESUMEN DE VUELOS",
            f"📅 {today}",
            "",
        ]

        if not results:
            lines.append("No hubo vuelos para resumir en esta ejecucion.")
            lines.append("")

        for result in results:
            route = f"{result.origin} → {result.destination}"

            lines.append(f"🛫 {route}")
            lines.append(f"   Fecha: {result.depart_date}")
            if not result.succeeded or result.offer is None:
                error_detail = result.error_message or "No se pudo consultar el vuelo"
                lines.append("   Estado: ERROR")
                lines.append(f"   Detalle: {error_detail}")
                lines.append("")
                continue

            offer = result.offer
            if offer.adults > 1:
                lines.append(f"   Total: {offer.currency} {offer.price:,.0f}")
                lines.append(f"   Por persona: {offer.currency} {offer.price_per_person:,.0f}")
            else:
                lines.append(f"   Precio: {offer.currency} {offer.price:,.0f}")
            lines.append(f"   Aerolínea: {offer.airline}")

            if result.recommended:
                lines.append("   ✅ RECOMENDADO COMPRAR")
            else:
                lines.append("   ⏳ Esperar mejor precio")
            lines.append("")

        text = "\n".join(lines)
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        try:
            resp = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": text},
                timeout=self.timeout,
            )
            if resp.ok:
                print("[Telegram] Resumen enviado.")
                return True
            else:
                print(f"[Telegram] Error: {resp.text}")
                return False
        except Exception as e:
            print(f"[Telegram] Error de conexion: {self._sanitize_error(e)}")
            return False
