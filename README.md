# Flight Monitor

Monitor de precios de vuelos usando Google Flights (via SerpApi). Te notifica por email o Telegram cuando encuentra ofertas significativamente más baratas que el promedio histórico.

## Características

- Monitorea múltiples vuelos simultáneamente
- Usa Google Flights como fuente de datos (via SerpApi)
- Clasifica precios en categorías LOW/OTHER
- Solo notifica cuando el precio está **10% o más por debajo** del promedio histórico de precios LOW
- Notificaciones por Email (Gmail) y/o Telegram
- Almacena historial de precios en SQLite
- Optimizado para el plan gratuito de SerpApi (100 llamadas/mes)

## Requisitos

- Python 3.10+
- [UV](https://github.com/astral-sh/uv) (gestor de paquetes)
- Cuenta en [SerpApi](https://serpapi.com) (plan gratuito disponible)

## Instalación

```bash
# Clonar repositorio
git clone https://github.com/tu-usuario/flight-monitor.git
cd flight-monitor

# Instalar dependencias con UV
uv sync

# Configurar credenciales
cp .env.example .env
cp flights.yaml.example flights.yaml

# Editar .env con tu API key de SerpApi
# Editar flights.yaml con los vuelos a monitorear
```

## Configuración

### 1. SerpApi (Requerido)

1. Crear cuenta en https://serpapi.com
2. Copiar tu API key
3. Agregar a `.env`:
   ```
   SERPAPI_KEY=tu_api_key
   ```

### 2. Email - Gmail (Opcional)

1. Activar verificación en 2 pasos en tu cuenta de Google
2. Crear App Password: https://myaccount.google.com/apppasswords
3. Agregar a `.env`:
   ```
   EMAIL_SENDER=tu_email@gmail.com
   EMAIL_PASSWORD=tu_app_password
   EMAIL_RECEIVER=destino@gmail.com
   ```

### 3. Telegram (Opcional)

1. Crear bot con @BotFather en Telegram
2. Obtener tu chat_id con @userinfobot
3. Agregar a `.env`:
   ```
   TELEGRAM_BOT_TOKEN=tu_token
   TELEGRAM_CHAT_ID=tu_chat_id
   ```

### 4. Vuelos a Monitorear

Editar `flights.yaml`:

```yaml
flights:
  - origin: BOG
    destination: MIA
    depart_date: "2025-12-01"
    return_date: "2025-12-15"
    adults: 1
    currency: USD
```

## Uso

### Chequeo único (recomendado con cron)

```bash
uv run python -m flight_monitor --once
```

### Modo continuo

```bash
uv run python -m flight_monitor
```

### Configurar con Cron (recomendado)

Para optimizar el uso de API (100 llamadas/mes en plan gratuito):

```bash
# Editar crontab
crontab -e

# Agregar chequeos a las 6 AM y 6 PM
0 6 * * * cd /ruta/a/flight-monitor && uv run python -m flight_monitor --once >> monitor.log 2>&1
0 18 * * * cd /ruta/a/flight-monitor && uv run python -m flight_monitor --once >> monitor.log 2>&1
```

## Arquitectura

```
src/flight_monitor/
├── __main__.py      # Punto de entrada
├── config.py        # Configuración desde .env y flights.yaml
├── monitor.py       # Orquestador principal
├── clients/
│   └── serpapi.py   # Cliente de Google Flights
├── storage/
│   └── sqlite.py    # Persistencia de historial
└── notifiers/
    ├── base.py      # Protocolo de notificadores
    ├── email.py     # Notificador Gmail
    └── telegram.py  # Notificador Telegram
```

## Lógica de Alertas

1. Google Flights clasifica vuelos en `best_flights` (LOW) y `other_flights`
2. El monitor acumula historial de precios LOW
3. Calcula el promedio histórico de precios LOW
4. **Solo envía alerta si el precio actual está 10%+ por debajo del promedio LOW**

## Seguridad

⚠️ **IMPORTANTE**: Los siguientes archivos contienen datos sensibles y **nunca** deben subirse a GitHub:

- `.env` - Credenciales de API y email
- `flights.yaml` - Información de viajes personales
- `*.db` - Historial de precios

Estos archivos están incluidos en `.gitignore` por defecto.

## Licencia

MIT
