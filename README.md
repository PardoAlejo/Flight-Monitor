# Flight Monitor

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![UV](https://img.shields.io/badge/uv-package%20manager-blueviolet)](https://github.com/astral-sh/uv)

> Monitor inteligente de precios de vuelos que usa **Google Flights** (via SerpApi) para rastrear precios y recomendarte comprar cuando el precio esta por debajo del rango tipico que Google considera normal para esa ruta.

---

## Caracteristicas

- **Multi-vuelo**: Monitorea multiples rutas simultaneamente con ejecucion concurrente
- **Clasificacion inteligente**: Distingue entre precios LOW (mejores ofertas) y OTHER usando la clasificacion de Google Flights
- **Alertas precisas**: Recomienda comprar cuando el precio esta **por debajo del rango tipico de Google Flights**
- **Notificaciones flexibles**: Soporte para Email (Gmail SMTP) y Telegram Bot (multiples destinatarios)
- **Persistencia**: Almacena todo el historial de precios en SQLite para analisis
- **Optimizado para API limitada**: Disenado para el plan gratuito de SerpApi (100 llamadas/mes)
- **Modo cron/launchd**: Flags `--once` y `--scheduled` (con reintentos automaticos) para tareas programadas

---

## Quick Start

```bash
# 1. Clonar repositorio
git clone https://github.com/aspardog/Flight-Monitor.git
cd Flight-Monitor

# 2. Instalar dependencias (requiere UV)
uv sync

# 3. Configurar credenciales
cp .env.example .env
# Editar .env con tu API key de SerpApi y credenciales de notificacion

# 4. Configurar vuelos a monitorear
# Crea flights.yaml con tus rutas (ver seccion Configuracion > Vuelos)

# 5. Ejecutar
uv run python -m flight_monitor --once
```

---

## Tabla de Contenidos

- [Arquitectura](#arquitectura)
- [Pipeline de Datos](#pipeline-de-datos)
- [Logica de Alertas](#logica-de-alertas)
- [Configuracion](#configuracion)
- [Uso](#uso)
- [Base de Datos](#base-de-datos)
- [Extensibilidad](#extensibilidad)
- [Optimizacion de API](#optimizacion-de-api)

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FLIGHT MONITOR                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌───────────┐ │
│  │   CONFIG    │     │   CLIENT    │     │   STORAGE   │     │ NOTIFIERS │ │
│  │             │     │             │     │             │     │           │ │
│  │ .env        │     │ SerpApi     │     │ SQLite      │     │ Email     │ │
│  │ flights.yaml│     │ (Google     │     │ (Historial) │     │ Telegram  │ │
│  │             │     │  Flights)   │     │             │     │           │ │
│  └──────┬──────┘     └──────┬──────┘     └──────┬──────┘     └─────┬─────┘ │
│         │                   │                   │                   │       │
│         └───────────────────┴───────────────────┴───────────────────┘       │
│                                     │                                       │
│                          ┌──────────▼──────────┐                           │
│                          │      MONITOR        │                           │
│                          │   (Orquestador)     │                           │
│                          │                     │                           │
│                          │ - check_flight()    │                           │
│                          │ - should_alert()    │                           │
│                          │ - run() / run_once()│                           │
│                          └─────────────────────┘                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Estructura del Proyecto

```
flight-monitor/
├── src/
│   └── flight_monitor/
│       ├── __init__.py          # Version del paquete
│       ├── __main__.py          # Punto de entrada CLI
│       ├── config.py            # Carga de configuracion (.env + YAML)
│       ├── monitor.py           # Orquestador principal (async)
│       ├── scheduler.py         # Programador con reintentos (--scheduled)
│       │
│       ├── clients/             # Proveedores de datos de vuelos
│       │   └── serpapi.py       # Cliente Google Flights via SerpApi
│       │
│       ├── storage/             # Backends de persistencia
│       │   └── sqlite.py        # Almacenamiento SQLite
│       │
│       └── notifiers/           # Plugins de notificacion
│           ├── base.py          # Protocolo base y dataclasses
│           ├── email.py         # Notificador Gmail SMTP
│           └── telegram.py      # Notificador Telegram Bot
│
├── .env.example                 # Plantilla de variables de entorno
├── flights.yaml.example         # Plantilla de vuelos a monitorear
├── pyproject.toml               # Configuracion del proyecto (UV/pip)
└── README.md
```

### Patrones de Diseno

| Patron | Implementacion | Beneficio |
|--------|----------------|-----------|
| **Dependency Injection** | Componentes reciben dependencias via constructor | Facilita testing y desacoplamiento |
| **Plugin Architecture** | Notifiers implementan protocolo `Notifier` | Agregar nuevos canales sin modificar core |
| **Protocol (Duck Typing)** | `FlightClient` protocol para proveedores | Intercambiar SerpApi por otro proveedor |
| **Async Concurrency** | `asyncio` + `ThreadPoolExecutor` | Chequeo paralelo de multiples vuelos |

---

## Pipeline de Datos

### Flujo de Chequeo (por vuelo)

```
┌──────────────────┐
│ 1. FETCH PRICE   │     SerpApiClient.fetch_cheapest_offer()
│    (SerpApi)     │     → Consulta Google Flights API
│                  │     → Extrae price_insights: typical_price_range,
│                  │       price_level ("low" / "typical" / "high")
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 2. CATEGORIZE    │     Google Flights clasifica internamente:
│                  │     • best_flights  → price_category = "best" (LOW)
│                  │     • other_flights → price_category = "other"
│                  │     Se toma el vuelo mas barato de ambas listas
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 3. SAVE PRICE    │     SQLiteStorage.insert_price()
│                  │     → Guarda: price, currency, airline,
│                  │       price_category, timestamp
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 4. COMPARE vs    │     FlightMonitor.should_recommend()
│    TYPICAL RANGE │     discount_pct = (typical_low - price) / typical_low × 100
│                  │     recommended = discount_pct > 0
│                  │     (precio < rango tipico → recomienda comprar)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 5. RETURN RESULT │     FlightCheckResult con offer, discount_pct, recommended
└────────┬─────────┘
         │
         ▼ (luego de chequear TODOS los vuelos)
┌──────────────────┐
│ 6. SEND SUMMARY  │     Para cada notifier configurado:
│                  │     • EmailNotifier  → Resumen diario Gmail SMTP
│                  │     • TelegramNotif  → Resumen diario Telegram Bot
└──────────────────┘
```

### Ejecucion Concurrente

Cuando hay multiples vuelos configurados, se ejecutan en paralelo:

```
                    ┌─────────────────────┐
                    │  check_all_flights  │
                    │       _async()      │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  ThreadPoolExecutor │
                    │  (max_workers = N)  │
                    └──────────┬──────────┘
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
           ▼                   ▼                   ▼
    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
    │ check_flight│     │ check_flight│     │ check_flight│
    │ (BOG→MIA)   │     │ (BOG→MAD)   │     │ (BOG→LIM)   │
    └─────────────┘     └─────────────┘     └─────────────┘
           │                   │                   │
           └───────────────────┼───────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   asyncio.gather()  │
                    │   (espera todos)    │
                    └─────────────────────┘
```

---

## Logica de Alertas

### Fuente de Comparacion: Rango Tipico de Google

En lugar de mantener un promedio historico propio, el monitor usa el **rango tipico de precios** que Google Flights publica para cada ruta. Este dato viene en la respuesta de la API como `price_insights`:

| Campo | Significado |
|-------|-------------|
| `typical_price_low` | Limite inferior del rango tipico |
| `typical_price_high` | Limite superior del rango tipico |
| `price_level` | Clasificacion: `"low"`, `"typical"`, o `"high"` |

### Algoritmo de Decision

```python
def should_recommend(self, offer: FlightOffer) -> tuple[bool, float]:
    # 1. Necesita rango tipico de Google para comparar
    if offer.typical_price_low is None:
        return False, 0.0

    # 2. Calcular descuento vs limite inferior del rango tipico
    discount_pct = ((offer.typical_price_low - offer.price) / offer.typical_price_low) * 100

    # 3. Recomendar si el precio esta POR DEBAJO del limite inferior
    recommended = discount_pct > 0

    return recommended, discount_pct
```

### Ejemplo Practico

```
Google Flights para BOG → MIA:
  Rango tipico: USD 430 - USD 550
  Nivel Google: LOW

Precio encontrado: USD 400

Descuento = (430 - 400) / 430 × 100 = 7.0%

7.0% > 0% → RECOMENDADO COMPRAR
```

### Formato de Notificacion (Resumen Diario)

Cada corrida envia un **resumen** de todos los vuelos monitoreados, no alertas individuales:

```
RESUMEN DIARIO DE VUELOS
Fecha: 2026-12-01 14:30
==================================================

VUELO: BOG -> MIA (solo ida)
  Fecha salida:    2026-12-01
  Estado:          OK
  Pasajeros:       1
  Precio total:    USD 400
  Precio/persona:  USD 400
  Aerolinea:       American Airlines
  Escalas:         1
  Rango tipico:    USD 430 - 550
  vs Rango tipico: 7.0% MAS BARATO
  Nivel Google:    BAJO
  >>> RECOMENDADO COMPRAR <<<

--------------------------------------------------

Busca en: https://www.google.com/flights
```

El asunto del email es `[COMPRAR] Resumen vuelos <fecha>` si al menos un vuelo es recomendado.

---

## Configuracion

### Variables de Entorno (`.env`)

```bash
# ═══════════════════════════════════════════════════════════════
# API DE VUELOS (REQUERIDO)
# ═══════════════════════════════════════════════════════════════
SERPAPI_KEY=tu_api_key_aqui          # https://serpapi.com

# ═══════════════════════════════════════════════════════════════
# EMAIL (OPCIONAL) - Gmail SMTP
# ═══════════════════════════════════════════════════════════════
EMAIL_SENDER=tu-correo@example.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx   # App Password (16 chars)
EMAIL_RECEIVER=destino@example.com,otro@example.com  # Multiples separados por coma

# ═══════════════════════════════════════════════════════════════
# TELEGRAM (OPCIONAL)
# ═══════════════════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN=tu_bot_token_aqui
TELEGRAM_CHAT_ID=tu_chat_id_aqui

# ═══════════════════════════════════════════════════════════════
# OPCIONALES
# ═══════════════════════════════════════════════════════════════
DB_PATH=flight_prices.db             # Ruta base de datos SQLite
CHECK_INTERVAL_MINUTES=60            # Intervalo en modo continuo
SCHEDULED_TIMES=10:00,15:30          # Horarios base para modo programado
RETRY_DELAY_MINUTES=60               # Reintento cuando falle una corrida
SCHEDULER_STATE_PATH=.flight_monitor_scheduler.json
```

**Obtener credenciales:**

| Servicio | Como obtener |
|----------|--------------|
| SerpApi | [serpapi.com](https://serpapi.com) - 100 busquedas gratis/mes |
| Gmail App Password | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) |
| Telegram Bot | [@BotFather](https://t.me/botfather) para token, [@userinfobot](https://t.me/userinfobot) para chat_id |

### Vuelos a Monitorear (`flights.yaml`)

```yaml
flights:
  # Vuelo ida y vuelta
  - origin: BOG              # Codigo IATA aeropuerto origen
    destination: MIA         # Codigo IATA aeropuerto destino
    depart_date: "2026-12-01"
    return_date: "2026-12-15"
    adults: 1
    currency: USD

  # Vuelo solo ida
  - origin: BOG
    destination: MAD
    depart_date: "2026-11-20"
    adults: 2
    currency: EUR

  # Vuelo en moneda local
  - origin: BOG
    destination: LIM
    depart_date: "2026-09-07"
    currency: COP
```

---

## Uso

### Modo Unico (Recomendado)

```bash
uv run python -m flight_monitor --once
```

Ejecuta un solo chequeo de todos los vuelos y termina. Ideal para **cron jobs**.

Si falla alguna consulta o el envio del resumen, el proceso termina con codigo de error.

### Modo Programado con Reintentos

```bash
uv run python -m flight_monitor --scheduled
```

Este modo consulta el archivo de estado y solo corre cuando:

- ya llego uno de los horarios configurados en `SCHEDULED_TIMES`
- hay una corrida pendiente porque no se completo
- paso al menos `RETRY_DELAY_MINUTES` desde el ultimo intento fallido

Sirve para recuperarse de dos casos:

- el equipo o `cron` no ejecuto la corrida del horario previsto
- la corrida si arranco pero fallo por red, SerpApi o el notificador

### Modo Continuo

```bash
uv run python -m flight_monitor
```

Ejecuta chequeos en loop segun `CHECK_INTERVAL_MINUTES`.

### Configuracion con Cron

Para habilitar reintentos una hora despues, programa una invocacion **cada hora** y deja
que `--scheduled` decida si hay una corrida pendiente:

```bash
# Editar crontab
crontab -e

# Ejemplo: revisar cada hora y ejecutar solo a las 6:00, 18:00 o sus reintentos
0 * * * * cd /ruta/a/flight-monitor && uv run python -m flight_monitor --scheduled >> monitor.log 2>&1
```

Con `SCHEDULED_TIMES=06:00,18:00`:

- si la corrida de las 06:00 no sucede, la de las 07:00 la recupera
- si la corrida de las 06:00 falla por red, la de las 07:00 la vuelve a intentar
- una vez la corrida termina bien, no se repite hasta el siguiente horario base

### Configuracion con launchd (macOS)

El directorio `launchd/` incluye una plantilla para `launchd` (el equivalente a cron en macOS). Se ejecuta cada hora al minuto 0:

```bash
# Crear una copia local y ajustar la ruta del proyecto
cp launchd/com.flight-monitor.plist.example launchd/com.flight-monitor.plist
vim launchd/com.flight-monitor.plist

# Instalar el agente
cp launchd/com.flight-monitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.flight-monitor.plist

# Ver logs
tail -f monitor.log

# Desinstalar
launchctl unload ~/Library/LaunchAgents/com.flight-monitor.plist
```

### Configuracion con GitHub Actions (Recomendado)

La forma mas confiable de ejecutar el monitor es usando GitHub Actions. No requiere que tu computadora este encendida.

El workflow `.github/workflows/monitor.yml` se ejecuta automaticamente a las 11:00 AM y 4:00 PM hora Colombia (16:00 y 21:00 UTC) todos los dias.

**Configurar secrets en GitHub:**

1. Ve a tu repositorio → Settings → Secrets and variables → Actions
2. Agrega los siguientes secrets:

| Secret | Descripcion | Requerido |
|--------|-------------|-----------|
| `SERPAPI_KEY` | Tu API key de SerpApi | Si |
| `FLIGHTS_YAML` | Contenido completo de tu `flights.yaml` | Si |
| `EMAIL_SENDER` | Correo Gmail para enviar | No |
| `EMAIL_PASSWORD` | App Password de Gmail (16 caracteres) | No |
| `EMAIL_RECEIVER` | Correo(s) destino, separados por coma | No |
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram | No |
| `TELEGRAM_CHAT_ID` | Chat ID de Telegram | No |

**Ejemplo de `FLIGHTS_YAML`:**

```yaml
flights:
  - origin: BOG
    destination: MIA
    depart_date: "2026-12-01"
    return_date: "2026-12-15"
    adults: 1
    currency: USD
```

**Ejecutar manualmente:** Actions → Flight Monitor → Run workflow

### Output de Ejemplo

```
==================================================
  Flight Monitor (SerpApi) - Modo unico
  Chequeando 2 vuelo(s)
  Alerta: cuando precio < rango tipico de Google
==================================================

[DB] Base de datos inicializada: flight_prices.db

==================================================
[2026-12-01 14:30 UTC] Chequeando BOG -> MIA (2026-12-01)
[SerpApi] Categoria de precio: LOW
[SerpApi] Rango tipico Google: USD 430 - 550
[SerpApi] Nivel de precio Google: LOW
[Monitor] Precio encontrado: USD 385 (American Airlines, 1 escala(s)) [LOW]
[DB] Guardado: USD 385 (American Airlines) [LOW]
[Monitor] Precio 10.4% POR DEBAJO del rango tipico
[Monitor] *** RECOMENDADO COMPRAR ***

[Monitor] Chequeo completado.
[Email] Resumen diario enviado a destino@example.com
[Telegram] Resumen enviado.
```

---

## Base de Datos

### Esquema SQLite

```sql
CREATE TABLE prices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    origin          TEXT NOT NULL,     -- Codigo IATA origen
    destination     TEXT NOT NULL,     -- Codigo IATA destino
    depart_date     TEXT NOT NULL,     -- Fecha salida (YYYY-MM-DD)
    return_date     TEXT,              -- Fecha regreso (NULL si solo ida)
    price           REAL NOT NULL,     -- Precio en moneda especificada
    currency        TEXT NOT NULL,     -- Codigo moneda (USD, EUR, COP)
    airline         TEXT,              -- Aerolinea principal
    price_category  TEXT DEFAULT 'other',  -- "best" (LOW) o "other"
    checked_at      TEXT NOT NULL      -- Timestamp ISO 8601
);
```

### Consultas Utiles

```bash
# Abrir base de datos
sqlite3 flight_prices.db

# Ver ultimos 10 precios
SELECT * FROM prices ORDER BY checked_at DESC LIMIT 10;

# Promedio de precios LOW por ruta
SELECT origin, destination, depart_date,
       ROUND(AVG(price), 2) as avg_low,
       COUNT(*) as registros
FROM prices
WHERE price_category = 'best'
GROUP BY origin, destination, depart_date;

# Precio minimo historico por ruta
SELECT origin, destination,
       MIN(price) as min_price,
       currency
FROM prices
GROUP BY origin, destination;

# Evolucion de precios para una ruta
SELECT date(checked_at) as fecha,
       ROUND(AVG(price), 2) as precio_promedio,
       MIN(price) as min,
       MAX(price) as max
FROM prices
WHERE origin = 'BOG' AND destination = 'MIA'
GROUP BY date(checked_at)
ORDER BY fecha;
```

---

## Extensibilidad

### Agregar Nuevo Notificador

1. Crear `src/flight_monitor/notifiers/slack.py`:

```python
from typing import Optional
import requests
from .base import FlightOffer, Notifier, PriceStats

class SlackNotifier(Notifier):
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url

    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    def send(self, offer: FlightOffer, stats: PriceStats, discount_pct: float) -> bool:
        if not self.is_configured():
            return False
        text = self.build_message(offer, stats, discount_pct)
        response = requests.post(self.webhook_url, json={"text": text})
        return response.ok
```

2. Registrar en `__main__.py`:

```python
from .notifiers.slack import SlackNotifier

notifiers = [
    EmailNotifier(...),
    TelegramNotifier(...),
    SlackNotifier(webhook_url=os.getenv("SLACK_WEBHOOK_URL")),
]
```

### Agregar Nuevo Proveedor de Vuelos

1. Crear `src/flight_monitor/clients/amadeus.py`:

```python
from typing import Optional
from ..config import FlightConfig
from ..notifiers.base import FlightOffer

class AmadeusClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def fetch_cheapest_offer(self, flight: FlightConfig) -> Optional[FlightOffer]:
        # Implementar llamada a Amadeus API
        # Retornar FlightOffer o None
        pass
```

2. Intercambiar en `__main__.py`:

```python
from .clients.amadeus import AmadeusClient

client = AmadeusClient(
    api_key=config.amadeus_api_key,
    api_secret=config.amadeus_api_secret
)
```

---

## Optimizacion de API

### Plan Gratuito SerpApi: 100 llamadas/mes

| Vuelos | Chequeos/dia | Llamadas/mes | Status |
|--------|--------------|--------------|--------|
| 1 | 1 | 30 | OK |
| 1 | 2 | 60 | OK |
| 1 | 3 | 90 | OK |
| 2 | 1 | 60 | OK |
| 2 | 2 | 120 | Excede limite |

### Recomendaciones

- **1 vuelo**: Hasta 3 chequeos/dia (90 llamadas/mes)
- **2 vuelos**: Maximo 1 chequeo/dia (60 llamadas/mes)
- **Horarios optimos**: 6 AM y 6 PM suelen tener variaciones de precio

---

## Desarrollo

### Comandos

```bash
# Instalar dependencias (incluyendo dev)
uv sync

# Ejecutar linter
uv run ruff check src/

# Ejecutar type checker
uv run mypy src/

# Ejecutar tests
uv run pytest
```

### Estructura de Tests

```bash
tests/
├── test_monitor.py      # Tests del orquestador
├── test_serpapi.py      # Tests del cliente (mocked)
├── test_storage.py      # Tests de SQLite
└── test_notifiers.py    # Tests de notificadores
```

---

## Seguridad

### Archivos Sensibles

Estos archivos estan en `.gitignore` y **nunca** deben commitearse:

| Archivo | Contenido | Riesgo |
|---------|-----------|--------|
| `.env` | API keys, contrasenas | CRITICO |
| `flights.yaml` | Planes de viaje | MEDIO |
| `*.db` | Historial de busquedas | BAJO |
| `*.log` | Puede contener datos | BAJO |

### Buenas Practicas

1. Usar **repositorio privado** en GitHub
2. Usar **App Passwords** de Gmail (no contrasena principal)
3. Rotar API keys periodicamente
4. No compartir archivos de configuracion

---

## Troubleshooting

### Error: "Falta la API key de SerpApi"

Asegurate de que `.env` existe y contiene `SERPAPI_KEY=tu_key`.

### Error: "No hay vuelos configurados"

Crea `flights.yaml` basado en `flights.yaml.example`.

### No llegan emails

1. Verifica que usas un **App Password** de Gmail, no tu contrasena normal
2. Revisa que `EMAIL_SENDER`, `EMAIL_PASSWORD` y `EMAIL_RECEIVER` esten configurados
3. Revisa la carpeta de spam

### No llegan mensajes de Telegram

1. Inicia una conversacion con tu bot primero
2. Verifica el `TELEGRAM_CHAT_ID` con [@userinfobot](https://t.me/userinfobot)

---

## Licencia

MIT License - Ver archivo [LICENSE](LICENSE) para detalles.

---

## Contribuir

Las contribuciones son bienvenidas. Por favor:

1. Fork el repositorio
2. Crea una rama para tu feature (`git checkout -b feature/nueva-funcionalidad`)
3. Commit tus cambios (`git commit -m 'Agregar nueva funcionalidad'`)
4. Push a la rama (`git push origin feature/nueva-funcionalidad`)
5. Abre un Pull Request

---

<p align="center">
  Desarrollado con la asistencia de <a href="https://claude.ai">Claude Code</a> (Anthropic)
</p>
