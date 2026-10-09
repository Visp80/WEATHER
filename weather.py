# weather.py
import argparse
import html
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


# ============ ОСНОВНІ КОНФІГУРАЦІЇ ============
if getattr(sys, "frozen", False):
    SCRIPT_DIR = Path(sys.executable).resolve().parent
else:
    SCRIPT_DIR = Path(__file__).resolve().parent

CONFIG_PATH = SCRIPT_DIR / "config.json"
CACHE_PATH = SCRIPT_DIR / "weather_cache.json"
HISTORY_PATH = SCRIPT_DIR / "weather_history.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "latitude": 48.922874,
    "longitude": 24.7116979,
    "forecast_hours": 5,
    "forecast_days": 7,
    "cache_max_age_min": 60,
    "enable_notifications": True,
    "telegram_bot_token": None,
    "telegram_chat_id": None,
    "hazard_thresholds": {
        "wind_ms": 15,
        "rain_mm": 4,
        "snow_cm": 2,
    },
    "hazardous_weather_codes": [56, 57, 66, 67, 75, 82, 86, 95, 96, 99],
}

WEEKDAYS_UK = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
MIN_POP_SHOWN = 10

WMO_WEATHER_CODES = {
    0: "Ясно",
    1: "Переважно ясно",
    2: "Мінлива хмарність",
    3: "Похмуро",
    45: "Туман",
    48: "Паморозевий туман",
    51: "Мряка: слабка",
    53: "Мряка: помірна",
    55: "Мряка: сильна",
    56: "Крижана мряка: слабка",
    57: "Крижана мряка: сильна",
    61: "Дощ: слабкий",
    63: "Дощ: помірний",
    65: "Дощ: сильний",
    66: "Крижаний дощ: слабкий",
    67: "Крижаний дощ: сильний",
    71: "Снігопад: слабкий",
    73: "Снігопад: помірний",
    75: "Снігопад: сильний",
    77: "Снігова крупа",
    80: "Зливи: слабкі",
    81: "Зливи: помірні",
    82: "Зливи: сильні",
    85: "Снігові зливи: слабкі",
    86: "Снігові зливи: сильні",
    95: "Гроза: слабка або помірна",
    96: "Гроза з градом: слабка",
    99: "Гроза з градом: сильна",
}

WMO_WEATHER_EMOJI = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌧️",
    56: "🧊", 57: "🧊",
    61: "🌦️", 63: "🌧️", 65: "🌧️",
    66: "🧊", 67: "🧊",
    71: "🌨️", 73: "🌨️", 75: "❄️", 77: "🌨️",
    80: "🌦️", 81: "🌧️", 82: "🌧️",
    85: "🌨️", 86: "❄️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}


# ============ КОНФІГУРАЦІЯ ============
def deep_copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return deep_copy_json(DEFAULT_CONFIG)

    try:
        user_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"⚠️ Не вдалося прочитати config.json ({exc}), використовую дефолтні значення.")
        return deep_copy_json(DEFAULT_CONFIG)

    if not isinstance(user_config, dict):
        print("⚠️ Config має містити JSON-об'єкт. Використовую дефолтні значення.")
        return deep_copy_json(DEFAULT_CONFIG)

    merged = deep_copy_json(DEFAULT_CONFIG)
    merged.update(user_config)

    if "hazard_thresholds" in user_config and isinstance(user_config["hazard_thresholds"], dict):
        merged["hazard_thresholds"] = {
            **DEFAULT_CONFIG["hazard_thresholds"],
            **user_config["hazard_thresholds"],
        }

    return merged


CONFIG = load_config()


def save_config() -> None:
    try:
        CONFIG_PATH.write_text(
            json.dumps(CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"⚠️ Не вдалося зберегти конфіг: {exc}")


# ============ ФОРМАТУВАННЯ ============
def fmt(value: Any, spec: str = ".1f", unit: str = "", na: str = "н/д") -> str:
    if value is None:
        return na
    try:
        return f"{value:{spec}}{unit}"
    except (TypeError, ValueError):
        return f"{value}{unit}"


def fmt_pop(pop: Any) -> str:
    if pop is None:
        return "—"
    try:
        pop_value = float(pop)
    except (TypeError, ValueError):
        return "—"
    if pop_value < MIN_POP_SHOWN:
        return "—"
    return f"{pop_value:.0f}%"


def daily_header() -> str:
    return f"{'День':<8}  {'Мін.':>7}  {'Макс.':>7}  {'Вітер':>5}  Умови"


def format_daily_line(day: dict) -> str:
    date_str = day.get("date")
    if not date_str:
        return "н/д"

    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return date_str

    date = f"{WEEKDAYS_UK[d.weekday()]} {d.strftime('%d.%m')}"
    return (
        f"{date:<8}  {fmt(day.get('temp_min'), '.1f', '°C'):>7}  "
        f"{fmt(day.get('temp_max'), '.1f', '°C'):>7}  "
        f"{fmt(day.get('wind_max'), '.1f'):>5}  "
        f"{describe_with_emoji(day.get('weather_code'))}"
    )


def hourly_header() -> str:
    return (
        f"{'Час':<5}  {'Темп.':>7}  {'Волог.':>6}  {'Вітер':>5}  "
        f"{'Опади':>5}  Умови"
    )


def format_hourly_row(h: dict) -> str:
    return (
        f"{h.get('time', '—'):<5}  {fmt(h.get('temp'), '.1f', '°C'):>7}  "
        f"{fmt(h.get('humidity'), '.0f', '%'):>6}  "
        f"{fmt(h.get('wind'), '.1f'):>5}  {fmt_pop(h.get('pop')):>5}  "
        f"{describe_with_emoji(h.get('weather_code'))}"
    )


def _at(seq, index: int, default=None):
    if seq is None or index >= len(seq):
        return default
    return seq[index]


# ============ ОСНОВНІ ФУНКЦІЇ ПОГОДИ ============
class WeatherFetchError(RuntimeError):
    pass


def fetch_weather_data() -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    timeout = int(CONFIG.get("curl_timeout_sec", 10))
    days = max(1, min(int(CONFIG.get("forecast_days", 7)), 16))

    params = {
        "latitude": CONFIG["latitude"],
        "longitude": CONFIG["longitude"],
        "current": "temperature_2m,wind_speed_10m,rain,showers,snowfall,weather_code,relative_humidity_2m",
        "hourly": "temperature_2m,precipitation_probability,weather_code,relative_humidity_2m,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_sum,weather_code,wind_speed_10m_max",
        "wind_speed_unit": "ms",
        "timezone": "auto",
        "forecast_days": days,
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=timeout,
            headers={"User-Agent": "weather-script/1.0"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise WeatherFetchError(f"Не вдалося отримати дані про погоду: {exc}") from exc

    text = response.text.strip()
    if not text:
        raise WeatherFetchError("Сервер повернув порожню відповідь.")

    if "<html" in response.text.lower():
        raise WeatherFetchError("Сервер повернув HTML замість JSON.")

    try:
        data = response.json()
    except ValueError as exc:
        raise WeatherFetchError(f"Некоректна JSON-відповідь від сервера: {exc}") from exc

    if not isinstance(data, dict):
        raise WeatherFetchError("Формат відповіді API не є об'єктом JSON.")

    if "error" in data:
        reason = data.get("reason", data)
        raise WeatherFetchError(f"API повернуло помилку: {reason}")

    if not data.get("current") or not data.get("hourly") or not data.get("daily"):
        raise WeatherFetchError("API повернуло неповний набір даних (відсутні current/hourly/daily).")

    return parse_weather_data(data)


def pick_day_code(hour_codes: List[Tuple[int, Optional[int]]], fallback):
    valid_hour_codes = [code for hour, code in hour_codes if 9 <= hour <= 21 and code is not None]
    if not valid_hour_codes:
        return fallback

    storm = [code for code in valid_hour_codes if code in (95, 96, 99)]
    if storm:
        return Counter(storm).most_common(1)[0][0]

    precip = [code for code in valid_hour_codes if code >= 51]
    if len(precip) >= 3:
        return Counter(precip).most_common(1)[0][0]

    dry = [code for code in valid_hour_codes if code < 51]
    return Counter(dry or valid_hour_codes).most_common(1)[0][0]


def parse_weather_data(data: dict) -> dict:
    current = data.get("current") or {}
    hourly = data.get("hourly") or {}
    daily = data.get("daily") or {}

    api_timezone = data.get("timezone", "н/д")

    current_time_str = current.get("time")
    if current_time_str:
        try:
            now_obj = datetime.strptime(current_time_str, "%Y-%m-%dT%H:%M").replace(minute=0, second=0, microsecond=0)
        except ValueError:
            now_obj = datetime.now().replace(minute=0, second=0, microsecond=0)
    else:
        now_obj = datetime.now().replace(minute=0, second=0, microsecond=0)

    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    precip_probs = hourly.get("precipitation_probability") or []
    weather_codes = hourly.get("weather_code") or []
    humidities = hourly.get("relative_humidity_2m") or []
    winds = hourly.get("wind_speed_10m") or []

    codes_by_date: Dict[str, List[Tuple[int, Optional[int]]]] = {}
    for index, time_str in enumerate(times):
        date_key, _, time_part = time_str.partition("T")
        try:
            hour = int(time_part[:2])
        except (TypeError, ValueError):
            hour = 0
        codes_by_date.setdefault(date_key, []).append((hour, _at(weather_codes, index)))

    hourly_forecast: List[dict] = []
    count = min(len(times), len(temps))
    for i in range(count):
        time_str = times[i]
        try:
            time_obj = datetime.strptime(time_str, "%Y-%m-%dT%H:%M")
        except ValueError:
            continue

        if time_obj >= now_obj:
            hourly_forecast.append(
                {
                    "time": time_obj.strftime("%H:%M"),
                    "datetime": time_obj.isoformat(),
                    "temp": _at(temps, i),
                    "pop": _at(precip_probs, i, 0),
                    "weather_code": _at(weather_codes, i),
                    "humidity": _at(humidities, i),
                    "wind": _at(winds, i),
                }
            )

        if len(hourly_forecast) >= int(CONFIG.get("forecast_hours", 5)) * 2:
            break

    daily_forecast: List[dict] = []
    daily_times = daily.get("time") or []
    for i, date in enumerate(daily_times):
        if i >= int(CONFIG.get("forecast_days", 7)):
            break

        daily_code = _at(daily.get("weather_code"), i)
        daily_forecast.append(
            {
                "date": date,
                "temp_max": _at(daily.get("temperature_2m_max"), i),
                "temp_min": _at(daily.get("temperature_2m_min"), i),
                "sunrise": _at(daily.get("sunrise"), i),
                "sunset": _at(daily.get("sunset"), i),
                "precipitation_sum": _at(daily.get("precipitation_sum"), i, 0),
                "weather_code": pick_day_code(codes_by_date.get(date, []), daily_code),
                "wind_max": _at(daily.get("wind_speed_10m_max"), i),
            }
        )

    return {
        "temp": current.get("temperature_2m"),
        "wind": current.get("wind_speed_10m"),
        "rain": current.get("rain", 0) or current.get("showers", 0),
        "snow": current.get("snowfall", 0),
        "humidity": current.get("relative_humidity_2m"),
        "weather_code": current.get("weather_code"),
        "hourly_forecast": hourly_forecast,
        "daily_forecast": daily_forecast,
        "timezone": api_timezone,
        "source": "Open-Meteo",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


# ============ РЕКОМЕНДАЦІЇ ============
def get_weather_recommendations(
    temp: Optional[float],
    wind: Optional[float],
    rain: Optional[float],
    snow: Optional[float],
    humidity: Optional[float],
    weather_code: Optional[int],
) -> List[str]:
    recommendations: List[str] = []

    if temp is not None:
        if temp < -10:
            recommendations.append("🧥 Дуже холодно! Одягніть термобілизну, пуховик, шапку, шарф та рукавиці")
        elif temp < 0:
            recommendations.append("🧥 Холодно. Потрібна тепла куртка, шапка та рукавиці")
        elif temp < 10:
            recommendations.append("🧥 Прохолодно. Візьміть куртку або пальто")
        elif temp < 18:
            recommendations.append("🧥 Комфортно. Легка куртка або светр")
        elif temp < 25:
            recommendations.append("👕 Тепло. Легкий одяг підійде")
        else:
            recommendations.append("☀️ Дуже тепло! Легкий одяг, капелюх та сонцезахисний крем")

    if rain and float(rain) > 0:
        if float(rain) > 10:
            recommendations.append("☂️ Сильний дощ! Візьміть парасольку та водонепроникне взуття")
        elif float(rain) > 3:
            recommendations.append("☂️ Очікується дощ. Візьміть парасольку")

    if snow and float(snow) > 0:
        if float(snow) > 5:
            recommendations.append("❄️ Сильний снігопад! Будьте обережні на дорогах")
        else:
            recommendations.append("❄️ Очікується сніг. Одягніться тепліше")

    if wind is not None:
        if wind > 20:
            recommendations.append("🌪️ Ураганний вітер! Залишайтеся вдома")
        elif wind > 15:
            recommendations.append("🌬️ Дуже сильний вітер. Будьте обережні, можливі повалені дерева")
        elif wind > 10:
            recommendations.append("🌬️ Сильний вітер. Застебніть куртку")

    if humidity is not None:
        if humidity > 80:
            recommendations.append("💧 Висока вологість. Може бути душно")
        elif humidity < 30:
            recommendations.append("💧 Низька вологість. Пийте більше води")

    if weather_code in [95, 96, 99]:
        recommendations.append("⛈️ Гроза! Залишайтеся в приміщенні, уникайте металевих предметів")
    elif weather_code in [56, 57, 66, 67]:
        recommendations.append("⚠️ Крижаний дощ! Дуже слизько, будьте обережні")
    elif weather_code == 45:
        recommendations.append("🌫️ Туман. Обмежена видимість, будьте обережні за кермом")

    hour = datetime.now().hour
    if 6 <= hour <= 8:
        recommendations.append("🌅 Ранок. Перевірте, чи немає ожеледиці")
    elif 20 <= hour <= 22:
        recommendations.append("🌙 Вечір. Температура може впасти")

    return recommendations


# ============ СПОВІЩЕННЯ (Telegram) ============
class NotificationManager:
    @staticmethod
    def telegram_configured() -> bool:
        return bool(CONFIG.get("telegram_bot_token") and CONFIG.get("telegram_chat_id"))

    def send_telegram(self, message: str, html_mode: bool = False) -> bool:
        if not self.telegram_configured():
            return False

        token = str(CONFIG["telegram_bot_token"])
        payload = {"chat_id": CONFIG["telegram_chat_id"], "text": message}
        if html_mode:
            payload["parse_mode"] = "HTML"

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            if response.ok and data.get("ok"):
                return True
            print(f"⚠️ Telegram відхилив повідомлення: {data.get('description', response.status_code)}")
        except (requests.RequestException, ValueError) as exc:
            print(f"⚠️ Не вдалося відправити Telegram сповіщення: {exc}")
        return False

    @staticmethod
    def build_messages(weather_data: dict) -> List[Tuple[str, bool]]:
        temp = weather_data.get("temp")
        wind = weather_data.get("wind")
        rain = weather_data.get("rain", 0)
        snow = weather_data.get("snow", 0)
        humidity = weather_data.get("humidity")
        code = weather_data.get("weather_code")

        current_lines = [
            f"📊 ПОТОЧНІ ПОКАЗНИКИ ({datetime.now().strftime('%d.%m.%Y %H:%M')})",
            "",
            f"🌡️ Температура: {fmt(temp, '.1f', '°C')}",
            f"💨 Вітер: {fmt(wind, '.1f', ' м/с')}",
            f"💧 Вологість: {fmt(humidity, '.0f', '%')}",
            f"☔ Опади: {fmt(rain, '.1f', ' мм')}",
            f"❄️ Сніг: {fmt(snow, '.1f', ' см')}",
            f"{weather_emoji(code)} Умови: {describe_weather_code(code)}",
        ]

        recommendations = get_weather_recommendations(temp, wind, rain, snow, humidity, code)
        if recommendations:
            current_lines += ["", "💡 РЕКОМЕНДАЦІЇ:"] + [f"• {rec}" for rec in recommendations]

        is_safe, warnings = check_weather_hazard(wind, rain, snow, code)
        current_lines += ["", "⚠️ МОНІТОР НЕГОДИ:"]
        if is_safe:
            current_lines.append("✅ Погодні умови безпечні")
        else:
            current_lines += [f"⚠️ {warning}" for warning in warnings]

        messages: List[Tuple[str, bool]] = [("\n".join(current_lines), False)]

        hourly = weather_data.get("hourly_forecast", [])
        if hourly:
            table = "\n".join([hourly_header()] + [format_hourly_row(h) for h in hourly])
            text = (
                f"🕐 ПОГОДИННИЙ ПРОГНОЗ (найближчі {len(hourly)} год):\n\n"
                f"<pre>{html.escape(table)}</pre>"
            )
            messages.append((text, True))

        daily = weather_data.get("daily_forecast", [])
        if daily:
            days = daily[: int(CONFIG.get("forecast_days", 7))]
            table = "\n".join([daily_header()] + [format_daily_line(d) for d in days])
            text = (
                f"📅 ПРОГНОЗ НА {len(days)} ДНІВ:\n\n"
                f"<pre>{html.escape(table)}</pre>"
            )
            messages.append((text, True))

        return messages

    def send_weather_report(self, weather_data: dict):
        if not CONFIG.get("enable_notifications", True):
            return
        if not self.telegram_configured():
            print("\nℹ️ Telegram не налаштовано, звіт не надіслано.")
            return

        messages = self.build_messages(weather_data)
        for text, html_mode in messages:
            if not self.send_telegram(text, html_mode):
                print("❌ Відправку звіту в Telegram перервано.")
                return
        print(f"\n📨 Надіслано в Telegram: {len(messages)} повідомлення")


# ============ ДОПОМІЖНІ ФУНКЦІЇ ============
def describe_weather_code(code):
    if code is None:
        return "н/д"
    return WMO_WEATHER_CODES.get(code, f"Невідомий код ({code})")


def weather_emoji(code) -> str:
    return WMO_WEATHER_EMOJI.get(code, "❔")


def describe_with_emoji(code) -> str:
    if code is None:
        return "н/д"
    return f"{weather_emoji(code)} {describe_weather_code(code)}"


def check_weather_hazard(wind, rain, snow, weather_code=None):
    thresholds = CONFIG["hazard_thresholds"]
    warnings = []

    if wind is not None and wind >= thresholds["wind_ms"]:
        warnings.append(f"Сильний вітер: {wind} м/с")
    if rain is not None and rain >= thresholds["rain_mm"]:
        warnings.append(f"Сильна злива: {rain} мм")
    if snow is not None and snow >= thresholds["snow_cm"]:
        warnings.append(f"Значний снігопад: {snow} см")
    if weather_code in CONFIG["hazardous_weather_codes"]:
        warnings.append(f"Небезпечне явище: {describe_weather_code(weather_code)}")

    return (len(warnings) == 0, warnings)


def save_cache(result: dict) -> None:
    try:
        CACHE_PATH.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"⚠️ Не вдалося зберегти кеш: {exc}")


def load_cache() -> Tuple[Optional[dict], Optional[float]]:
    if not CACHE_PATH.exists():
        return None, None

    try:
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
    except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
        return None, None

    age_minutes = (datetime.now() - fetched_at).total_seconds() / 60
    if age_minutes > CONFIG["cache_max_age_min"]:
        return None, None

    return cached, age_minutes


def save_history(weather_data: dict) -> None:
    try:
        history: List[dict] = []

        if HISTORY_PATH.exists():
            try:
                history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                history = []

        if not isinstance(history, list):
            history = []

        history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "temp": weather_data.get("temp"),
                "wind": weather_data.get("wind"),
                "rain": weather_data.get("rain"),
                "snow": weather_data.get("snow"),
                "humidity": weather_data.get("humidity"),
                "weather_code": weather_data.get("weather_code"),
            }
        )

        cutoff = datetime.now() - timedelta(days=30)
        filtered = []

        for item in history:
            try:
                item_timestamp = item.get("timestamp")
                if item_timestamp and datetime.fromisoformat(item_timestamp) > cutoff:
                    filtered.append(item)
            except (TypeError, ValueError):
                pass

        HISTORY_PATH.write_text(
            json.dumps(filtered, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        print(f"⚠️ Не вдалося зберегти історію: {exc}")


# ============ ГЕОКОДУВАННЯ (ПОШУК МІСТА) ============
def geocode_city(city: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Пошук координат міста за назвою через Nominatim.
    Повертає (latitude, longitude, display_name) або (None, None, None) при помилці.
    """
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": city, "format": "json", "limit": 1},
            headers={"User-Agent": "weather-script/1.0"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if not data:
            return None, None, None

        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        display_name = data[0].get("display_name", f"{lat}, {lon}")
        return lat, lon, display_name
    except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
        print(f"⚠️ Помилка пошуку міста: {exc}")
        return None, None, None


# ============ ВІДОБРАЖЕННЯ ============
def display_weather(weather_data: dict, show_hourly: bool = True, show_daily: bool = True):
    """Відображення погоди в консолі."""
    print("\n" + "=" * 70)
    print(f"🌤️  ПОГОДА НА {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print("=" * 70)

    temp = weather_data.get("temp")
    wind = weather_data.get("wind")
    rain = weather_data.get("rain", 0)
    snow = weather_data.get("snow", 0)
    humidity = weather_data.get("humidity")
    weather_code = weather_data.get("weather_code")

    print("\n📊 ПОТОЧНІ ПОКАЗНИКИ:")
    print(f"  🌡️  Температура:     {fmt(temp, '.1f', '°C')}")
    print(f"  💨  Вітер:           {fmt(wind, '.1f', ' м/с')}")
    print(f"  💧  Вологість:       {fmt(humidity, '.0f', '%')}")
    print(f"  ☔  Опади:           {fmt(rain, '.1f', ' мм')}")
    print(f"  ❄️  Сніг:            {fmt(snow, '.1f', ' см')}")
    print(f"  {weather_emoji(weather_code)}  Умови:           {describe_weather_code(weather_code)}")
    print(f"  🕐  Часовий пояс:    {weather_data.get('timezone', 'н/д')}")

    recommendations = get_weather_recommendations(temp, wind, rain, snow, humidity, weather_code)
    if recommendations:
        print("\n💡 РЕКОМЕНДАЦІЇ:")
        for rec in recommendations:
            print(f"  {rec}")

    is_safe, warnings = check_weather_hazard(wind, rain, snow, weather_code)
    print("\n⚠️  МОНІТОР НЕГОДИ:")
    if is_safe:
        print("  ✅ Погодні умови безпечні")
    else:
        print("  ⚠️ Виявлено небезпечні умови:")
        for warning in warnings:
            print(f"    - {warning}")

    if show_hourly:
        hourly = weather_data.get("hourly_forecast", [])
        if hourly:
            print(f"\n🕐 ПОГОДИННИЙ ПРОГНОЗ (найближчі {len(hourly)} год):")
            print("  " + "-" * 80)
            print("  " + hourly_header())
            for h in hourly:
                print("  " + format_hourly_row(h))

    if show_daily:
        daily = weather_data.get("daily_forecast", [])
        if daily:
            days = daily[: int(CONFIG.get("forecast_days", 7))]
            print(f"\n📅 ПРОГНОЗ НА {len(days)} ДНІВ:")
            print("  " + "-" * 70)
            print("  " + daily_header())
            for day in days:
                print("  " + format_daily_line(day))

    print("\n" + "=" * 70)
    print(f"📡 Джерело: {weather_data.get('source', 'н/д')}")
    print(f"🔄 Оновлено: {weather_data.get('fetched_at', 'н/д')}")
    print("=" * 70)

    if not str(weather_data.get("source", "")).startswith("Кеш"):
        save_history(weather_data)


# ============ ОСНОВНА ПРОГРАМА ============
def fetch_weather(use_cache: bool = True) -> Optional[dict]:
    """
    Отримує погоду з API; при помилці повертає дані з кешу або None.
    
    Args:
        use_cache: Чи можна використовувати кеш при помилці
    """
    try:
        print("🔄 Отримання даних про погоду...")
        result = fetch_weather_data()
        save_cache(result)
        print("✅ Дані отримано успішно!")
        return result
    except WeatherFetchError as exc:
        print(f"⚠️ Помилка виконання: {exc}")
        
        if not use_cache:
            print("❌ Кеш вимкнено. Програма завершується.")
            return None
        
        cached_result, cache_age_min = load_cache()
        if cached_result is None:
            print("❌ Придатного кешу немає. Програма завершується.")
            return None

        cached_result["source"] = (
            f"Кеш ({cached_result.get('source', 'Open-Meteo')}, "
            f"застарів на {cache_age_min:.0f} хв)"
        )
        print("✅ Використовую кешовані дані")
        return cached_result


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Програма для отримання прогнозу погоди з Open-Meteo API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Приклади використання:
  python weather.py                           # Використати координати з config.json
  python weather.py --city Київ               # Змінити місто на Київ
  python weather.py --city "New York"         # Міста з пробілами потрібно в лапках
  python weather.py --no-notify                # Вимкнути Telegram сповіщення
  python weather.py --no-hourly                # Не показувати погодинний прогноз
  python weather.py --no-daily                 # Не показувати денний прогноз
  python weather.py --no-cache                 # Не використовувати кеш
  python weather.py --quiet                    # Мінімальний вивід (тільки поточна погода)
  python weather.py --json                     # Вивести дані в форматі JSON
  python weather.py --city Львів --no-notify   # Комбінування аргументів
        """
    )

    parser.add_argument(
        "--city",
        type=str,
        help="Назва міста для поточної погоди (без збереження в config.json)",
    )

    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Вимкнути Telegram сповіщення для цього запуску",
    )

    parser.add_argument(
        "--no-hourly",
        action="store_true",
        help="Не показувати погодинний прогноз",
    )

    parser.add_argument(
        "--no-daily",
        action="store_true",
        help="Не показувати денний прогноз",
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Не використовувати кеш при помилці",
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Мінімальний вивід: тільки поточна погода",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Вивести результат у форматі JSON",
    )

    parser.add_argument(
        "--config",
        type=str,
        help="Шлях до файлу конфіг (за замовчуванням config.json)",
    )

    return parser


def main():
    parser = create_argument_parser()
    args = parser.parse_args()

    # Якщо передано інший config
    if args.config:
        global CONFIG_PATH, CONFIG
        CONFIG_PATH = Path(args.config)
        CONFIG = load_config()

    # Якщо передано місто, тимчасово змінити координати
    if args.city:
        lat, lon, display_name = geocode_city(args.city)
        if lat is None or lon is None:
            print(f"❌ Не вдалося знайти місто '{args.city}'. Використовую конфіг.")
            return
        print(f"✅ Знайдено: {display_name}")
        CONFIG["latitude"] = lat
        CONFIG["longitude"] = lon

    # Отримати погоду
    result = fetch_weather(use_cache=not args.no_cache)
    if result is None:
        return

    # Вивести результат
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        show_hourly = not (args.quiet or args.no_hourly)
        show_daily = not (args.quiet or args.no_daily)
        display_weather(result, show_hourly=show_hourly, show_daily=show_daily)

    # Надіслати Telegram
    if not args.no_notify:
        notifier = NotificationManager()
        notifier.send_weather_report(result)


if __name__ == "__main__":
    main()