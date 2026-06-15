"""Telegram notification plugin using Bot API."""

from datetime import datetime
from typing import Optional

import requests

from .base import FlightCheckResult, Notifier
from .email import build_google_flights_url

# Spanish day and month names
DAYS_ES = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]
MONTHS_ES = [
    "", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
    "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"
]


def format_date_spanish(date_input: str | datetime) -> str:
    """Format date as 'Lun 25 May' in Spanish (short version for Telegram)."""
    try:
        if isinstance(date_input, str):
            dt = datetime.strptime(date_input, "%Y-%m-%d")
        else:
            dt = date_input
        day_name = DAYS_ES[dt.weekday()]
        month_name = MONTHS_ES[dt.month]
        return f"{day_name} {dt.day} {month_name}"
    except (ValueError, AttributeError):
        return str(date_input)


def _to_datetime(date_input: str | datetime) -> datetime:
    """Convert string or date to datetime."""
    if isinstance(date_input, str):
        return datetime.strptime(date_input, "%Y-%m-%d")
    if isinstance(date_input, datetime):
        return date_input
    # Handle date object
    return datetime.combine(date_input, datetime.min.time())


def calculate_trip_duration(depart_date: str | datetime, return_date: str | datetime) -> int:
    """Calculate trip duration in days."""
    try:
        depart = _to_datetime(depart_date)
        ret = _to_datetime(return_date)
        return (ret - depart).days
    except (ValueError, AttributeError):
        return 0


def get_price_indicator(price_level: Optional[str], recommended: bool) -> str:
    """Get visual indicator for price level."""
    if recommended:
        return "🟢"
    if price_level == "low":
        return "🟢"
    elif price_level == "typical":
        return "🟡"
    elif price_level == "high":
        return "🔴"
    return "⚪"


class TelegramNotifier(Notifier):
    """Send notifications via Telegram Bot API."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: int = 10,
    ):
        self.bot_token = bot_token
        self.chat_ids: list[str] = []
        if chat_id:
            self.chat_ids = [c.strip() for c in chat_id.split(",") if c.strip()]
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_ids)

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

        now = datetime.now()
        today_formatted = format_date_spanish(now.strftime("%Y-%m-%d"))
        time_str = now.strftime("%H:%M")

        # Check if any flight is recommended
        any_recommended = any(r.recommended for r in results if r.succeeded)

        lines = [
            f"✈️ *VUELOS — {today_formatted} {time_str}*",
        ]

        if not results:
            lines.append("")
            lines.append("No hubo vuelos para resumir.")
        else:
            for result in results:
                route = f"{result.origin} → {result.destination}"

                if not result.succeeded or result.offer is None:
                    lines.append("")
                    lines.append(f"⚠️ *{route}* — Error")
                    error_detail = result.error_message or "No se pudo consultar"
                    lines.append(error_detail)
                    continue

                offer = result.offer
                indicator = get_price_indicator(
                    offer.price_level, result.recommended
                )

                # ── Header ──
                lines.append("")
                lines.append(f"{indicator} *{route}*")
                lines.append("─────────────────────")

                # ── Best flight details ──
                # Route path: BOG → MIA → LHR
                airport_ids: list[str] = []
                for seg in offer.segments:
                    parts = seg.split(" -> ")
                    if parts and not airport_ids:
                        airport_ids.append(parts[0].strip().split(" ")[0])
                    if len(parts) > 1:
                        arr_part = parts[1].strip().split(" ")[0]
                        airport_ids.append(arr_part)
                if airport_ids:
                    route_path = " → ".join(airport_ids)
                    lines.append(f"🛫 {offer.airline} | {route_path}")

                # Timing
                time_parts = []
                if offer.departure_time and offer.arrival_time:
                    time_parts.append(f"{offer.departure_time} → {offer.arrival_time}")
                if offer.duration_formatted:
                    time_parts.append(offer.duration_formatted)
                if time_parts:
                    lines.append(f"🕐 {' | '.join(time_parts)}")

                # Layovers
                if offer.layovers:
                    lines.append(f"🔄 Escalas: {', '.join(offer.layovers)}")

                lines.append("")

                # ── Price ──
                if offer.adults > 1:
                    lines.append(
                        f"💰 *{offer.currency} {offer.price:,.0f}* total"
                        f" ({offer.currency} {offer.price_per_person:,.0f}/persona)"
                    )
                else:
                    lines.append(f"💰 *{offer.currency} {offer.price:,.0f}*")

                # vs typical
                if offer.typical_price_low and offer.typical_price_high:
                    low = f"{offer.typical_price_low:,.0f}"
                    high = f"{offer.typical_price_high:,.0f}"
                    if result.discount_pct > 0:
                        lines.append(
                            f"📉 {result.discount_pct:.0f}% bajo típico"
                            f" ({offer.currency} {low}–{high})"
                        )
                    else:
                        lines.append(
                            f"📈 {abs(result.discount_pct):.0f}% sobre típico"
                            f" ({offer.currency} {low}–{high})"
                        )

                # Trend
                if result.trend and result.trend.record_count > 0:
                    trend_parts = []
                    if (
                        result.trend.price_change is not None
                        and result.trend.price_change != 0
                    ):
                        if result.trend.price_change < 0:
                            trend_parts.append(
                                f"↓ {offer.currency}"
                                f" {abs(result.trend.price_change):,.0f}"
                            )
                        else:
                            trend_parts.append(
                                f"↑ {offer.currency}"
                                f" {result.trend.price_change:,.0f}"
                            )
                    if result.trend.is_all_time_low:
                        trend_parts.append("🏆 MÍNIMO HISTÓRICO")
                    if trend_parts:
                        lines.append(f"📊 {' | '.join(trend_parts)}")

                lines.append("")

                # ── Dates ──
                depart_fmt = format_date_spanish(result.depart_date)
                if result.return_date:
                    return_fmt = format_date_spanish(result.return_date)
                    duration = calculate_trip_duration(
                        result.depart_date, result.return_date
                    )
                    lines.append(f"📅 {depart_fmt} → {return_fmt} ({duration}d)")
                else:
                    lines.append(f"📅 {depart_fmt} (solo ida)")

                # Date alternatives table
                if result.date_alternatives:
                    lines.append("")
                    lines.append("*Precios por fecha:*")
                    for alt in result.date_alternatives:
                        date_fmt = format_date_spanish(alt.depart_date)
                        if alt.is_cheapest:
                            lines.append(
                                f"  ▸ {date_fmt}  *{alt.currency} {alt.price:,.0f}* ◀"
                            )
                        else:
                            lines.append(
                                f"    {date_fmt}  {alt.currency} {alt.price:,.0f}"
                            )

                lines.append("")

                # ── Recommendation + Link ──
                if result.recommended:
                    lines.append("✅ *COMPRAR AHORA*")
                else:
                    lines.append("⏳ Esperar mejor precio")

                gf_url = build_google_flights_url(
                    result.origin,
                    result.destination,
                    result.depart_date,
                    result.return_date,
                )
                lines.append(f"🔗 [Ver en Google Flights]({gf_url})")

        # Footer
        if any_recommended:
            lines.append("")
            lines.append("─────────────────────")
            lines.append("🔔 *¡Hay vuelos recomendados!*")

        text = "\n".join(lines)
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        all_ok = True
        for chat_id in self.chat_ids:
            try:
                resp = requests.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                    },
                    timeout=self.timeout,
                )
                if resp.ok:
                    print(f"[Telegram] Resumen enviado a {chat_id}.")
                else:
                    print(f"[Telegram] Error ({chat_id}): {resp.text}")
                    all_ok = False
            except Exception as e:
                print(f"[Telegram] Error de conexion ({chat_id}): {self._sanitize_error(e)}")
                all_ok = False
        return all_ok
