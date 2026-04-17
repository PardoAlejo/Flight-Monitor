"""Email notification plugin using Gmail SMTP."""

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from .base import FlightCheckResult, FlightOffer, Notifier


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

    def send(
        self,
        offer: FlightOffer,
        discount_pct: float,
    ) -> bool:
        """Send alert email for a single flight (legacy method)."""
        if not self.is_configured():
            return False

        route = f"{offer.origin} -> {offer.destination}"
        body_lines = [
            "ALERTA DE VUELO BARATO",
            "",
            f"Ruta: {route}",
            f"Fecha: {offer.depart_date}",
            f"Precio actual: {offer.currency} {offer.price:,.0f}",
            f"Aerolinea: {offer.airline}",
        ]
        if offer.typical_price_low:
            body_lines.append(f"Rango tipico Google: {offer.currency} {offer.typical_price_low:,.0f} - {offer.typical_price_high:,.0f}")
            body_lines.append(f"{discount_pct:.1f}% por debajo del rango tipico")

        body = "\n".join(body_lines)
        subject = (
            f"VUELO BARATO: {offer.origin}->{offer.destination} "
            f"{offer.currency} {offer.price:,.0f}"
        )

        msg = MIMEMultipart()
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.receivers)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.receivers, msg.as_string())
            print(f"[Email] Alerta enviada a {', '.join(self.receivers)}")
            return True
        except Exception as e:
            print(f"[Email] Error al enviar: {e}")
            return False

    def send_summary(self, results: list[FlightCheckResult]) -> bool:
        """Send daily summary email with all flight check results."""
        if not self.is_configured() or not results:
            return False

        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "RESUMEN DIARIO DE VUELOS",
            f"Fecha: {today}",
            "=" * 50,
            "",
        ]

        any_recommended = False
        for result in results:
            offer = result.offer
            route = f"{offer.origin} -> {offer.destination}"
            ret = f" (ida/vuelta: {offer.return_date})" if offer.return_date else " (solo ida)"

            lines.append(f"VUELO: {route}{ret}")
            lines.append(f"  Fecha salida:    {offer.depart_date}")
            lines.append(f"  Precio actual:   {offer.currency} {offer.price:,.0f}")
            lines.append(f"  Aerolinea:       {offer.airline}")
            lines.append(f"  Escalas:         {offer.stops}")

            # Show Google's typical price range
            if offer.typical_price_low and offer.typical_price_high:
                lines.append(f"  Rango tipico:    {offer.currency} {offer.typical_price_low:,.0f} - {offer.typical_price_high:,.0f}")
                if result.discount_pct > 0:
                    lines.append(f"  vs Rango tipico: {result.discount_pct:.1f}% MAS BARATO")
                else:
                    lines.append(f"  vs Rango tipico: {abs(result.discount_pct):.1f}% mas caro")
            else:
                lines.append("  Rango tipico:    No disponible")

            # Show Google's price level assessment
            if offer.price_level:
                level_es = {"low": "BAJO", "typical": "TIPICO", "high": "ALTO"}.get(offer.price_level, offer.price_level.upper())
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
