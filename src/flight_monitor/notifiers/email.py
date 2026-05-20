"""Email notification plugin using Gmail SMTP."""

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from .base import FlightCheckResult, Notifier


class EmailNotifier(Notifier):
    """Send notifications via Gmail SMTP."""

    def __init__(
        self,
        sender: Optional[str] = None,
        password: Optional[str] = None,
        receiver: Optional[str] = None,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 465,
    ):
        self.sender = sender
        self.password = password
        # Support multiple receivers separated by comma
        self.receivers: list[str] = []
        if receiver:
            self.receivers = [r.strip() for r in receiver.split(",") if r.strip()]
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port

    def is_configured(self) -> bool:
        return bool(self.sender and self.password and self.receivers)

    def send_summary(self, results: list[FlightCheckResult]) -> bool:
        """Send daily summary email with all flight check results."""
        if not self.is_configured():
            return False

        assert self.sender is not None
        assert self.password is not None

        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "RESUMEN DIARIO DE VUELOS",
            f"Fecha: {today}",
            "=" * 50,
            "",
        ]

        any_recommended = False
        if not results:
            lines.append("No hubo vuelos para resumir en esta ejecucion.")
            lines.append("")
        else:
            for result in results:
                route = f"{result.origin} -> {result.destination}"
                ret = (
                    f" (ida/vuelta: {result.return_date})"
                    if result.return_date
                    else " (solo ida)"
                )

                lines.append(f"VUELO: {route}{ret}")
                lines.append(f"  Fecha salida:    {result.depart_date}")

                if not result.succeeded or result.offer is None:
                    error_detail = result.error_message or "No se pudo consultar el vuelo"
                    lines.append("  Estado:          ERROR")
                    lines.append(f"  Detalle:         {error_detail}")
                    lines.append("")
                    lines.append("-" * 50)
                    lines.append("")
                    continue

                offer = result.offer
                lines.append("  Estado:          OK")
                lines.append(f"  Pasajeros:       {offer.adults}")
                lines.append(f"  Precio total:    {offer.currency} {offer.price:,.0f}")
                lines.append(f"  Precio/persona:  {offer.currency} {offer.price_per_person:,.0f}")
                lines.append(f"  Aerolinea:       {offer.airline}")
                lines.append(f"  Escalas:         {offer.stops}")

                # Show Google's typical price range
                if offer.typical_price_low and offer.typical_price_high:
                    low = f"{offer.typical_price_low:,.0f}"
                    high = f"{offer.typical_price_high:,.0f}"
                    lines.append(f"  Rango tipico:    {offer.currency} {low} - {high}")
                    if result.discount_pct > 0:
                        lines.append(f"  vs Rango tipico: {result.discount_pct:.1f}% MAS BARATO")
                    else:
                        lines.append(f"  vs Rango tipico: {abs(result.discount_pct):.1f}% mas caro")
                else:
                    lines.append("  Rango tipico:    No disponible")

                # Show Google's price level assessment
                if offer.price_level:
                    level_map = {"low": "BAJO", "typical": "TIPICO", "high": "ALTO"}
                    level_es = level_map.get(offer.price_level, offer.price_level.upper())
                    lines.append(f"  Nivel Google:    {level_es}")

                if result.recommended:
                    lines.append("  >>> RECOMENDADO COMPRAR <<<")
                    any_recommended = True
                else:
                    lines.append("  Recomendacion:   Esperar mejor precio")

                lines.append("")
                lines.append("-" * 50)
                lines.append("")

        lines.extend([
            "Busca en: https://www.google.com/flights",
            "",
            "---",
            "Flight Monitor - Resumen automatico",
        ])

        body = "\n".join(lines)

        if any_recommended:
            subject = f"[COMPRAR] Resumen vuelos {today}"
        else:
            subject = f"Resumen vuelos {today}"

        msg = MIMEMultipart()
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.receivers)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.receivers, msg.as_string())
            print(f"[Email] Resumen diario enviado a {', '.join(self.receivers)}")
            return True
        except Exception as e:
            print(f"[Email] Error al enviar resumen: {e}")
            return False
