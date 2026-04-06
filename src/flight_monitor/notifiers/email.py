"""Email notification plugin using Gmail SMTP."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from .base import FlightOffer, Notifier, PriceStats


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
        self.receiver = receiver
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port

    def is_configured(self) -> bool:
        return bool(self.sender and self.password and self.receiver)

    def send(
        self,
        offer: FlightOffer,
        stats: PriceStats,
        discount_pct: float,
    ) -> bool:
        if not self.is_configured():
            return False

        body = self.build_message(offer, stats, discount_pct)
        subject = (
            f"VUELO {discount_pct:.0f}% BARATO: {offer.origin}->{offer.destination} "
            f"{offer.currency} {offer.price:,.0f}"
        )

        msg = MIMEMultipart()
        msg["From"] = self.sender
        msg["To"] = self.receiver
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.receiver, msg.as_string())
            print(f"[Email] Alerta enviada a {self.receiver}")
            return True
        except Exception as e:
            print(f"[Email] Error al enviar: {e}")
            return False
