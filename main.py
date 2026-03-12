from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Load environment variables from .env
load_dotenv()

APP_NAME = "City ActivityAdvisor"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o").strip()
OPENROUTER_HTTP_REFERER = os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
OPENROUTER_APP_TITLE = os.getenv("OPENROUTER_APP_TITLE", APP_NAME).strip()
OPEN_METEO_GEOCODING_URL = os.getenv(
    "OPEN_METEO_GEOCODING_URL",
    "https://geocoding-api.open-meteo.com/v1/search",
)
OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")

HTTP_TIMEOUT = 10

app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ok(data: Any, message: Optional[str] = None) -> JSONResponse:
    """Build a successful JSON response in the required format."""
    payload: Dict[str, Any] = {"status": "ok", "data": data}
    if message:
        payload["message"] = message
    return JSONResponse(payload)


def err(message: str, status_code: int = 400) -> JSONResponse:
    """Build an error JSON response in the required format."""
    return JSONResponse({"status": "error", "data": {"message": message}}, status_code=status_code)


def parse_date_input(date_input: Optional[str]) -> Optional[date]:
    """Parse a date string into a date object, returning None if invalid or missing."""
    if not date_input:
        return None
    text = date_input.strip().lower()
    if text == "today":
        return datetime.now().date()
    if text == "tomorrow":
        return (datetime.now().date() + timedelta(days=1))
    # Accept YYYY-MM-DD, YYYY/MM/DD, YYYY MM DD, or full ISO datetime
    try:
        if "T" in date_input or ":" in date_input:
            return datetime.fromisoformat(date_input).date()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y %m %d"):
            try:
                return datetime.strptime(date_input, fmt).date()
            except Exception:
                continue
    except Exception:
        return None
    return None


def get_city_coords(city: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Resolve a city name to latitude/longitude using Open-Meteo Geocoding API."""
    if not city:
        return None, None, "City is required."
    try:
        params = {"name": city, "count": 1, "format": "json"}
        resp = requests.get(OPEN_METEO_GEOCODING_URL, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results") or []
        if not results:
            return None, None, "City not found."
        lat = float(results[0]["latitude"])
        lon = float(results[0]["longitude"])
        return lat, lon, None
    except Exception:
        return None, None, "Failed to geocode city."


def get_current_weather(lat: float, lon: float) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Fetch current temperature from Open-Meteo for given coordinates."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {"latitude": lat, "longitude": lon, "current": "temperature_2m"}
    try:
        resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})
        if "temperature_2m" not in current:
            return None, "Weather data unavailable."
        return {
            "temperature_c": current["temperature_2m"],
            "time": current.get("time"),
        }, None
    except Exception:
        return None, "Failed to fetch weather data."


def get_daily_weather(lat: float, lon: float, target_date: date) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Fetch daily forecast for a specific date from Open-Meteo."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
        "timezone": "auto",
    }
    try:
        resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})
        times = daily.get("time", [])
        if not times:
            return None, "Daily forecast unavailable."
        target_str = target_date.isoformat()
        if target_str not in times:
            return None, "Date is outside the forecast range."
        idx = times.index(target_str)
        return {
            "date": target_str,
            "temp_max_c": daily.get("temperature_2m_max", [None])[idx],
            "temp_min_c": daily.get("temperature_2m_min", [None])[idx],
            "precipitation_probability_max": daily.get("precipitation_probability_max", [None])[idx],
            "weather_code": daily.get("weathercode", [None])[idx],
        }, None
    except Exception:
        return None, "Failed to fetch forecast data."


def map_activity_to_overpass_tags(activity: str) -> List[str]:
    """Map a free-form activity to Overpass tag queries."""
    activity_lc = activity.lower().strip()
    # Simple mapping for common activities
    if "billiard" in activity_lc or "pool" in activity_lc:
        return [
            'leisure="sports_centre"',
            'sport="billiards"',
            'amenity="bar"',
        ]
    if "movie" in activity_lc or "cinema" in activity_lc:
        return ['amenity="cinema"']
    if "museum" in activity_lc:
        return ['tourism="museum"']
    if "restaurant" in activity_lc or "dinner" in activity_lc or "food" in activity_lc:
        return ['amenity="restaurant"']
    if "coffee" in activity_lc or "cafe" in activity_lc:
        return ['amenity="cafe"']
    if "park" in activity_lc or "walk" in activity_lc:
        return ['leisure="park"']
    if "gym" in activity_lc or "workout" in activity_lc:
        return ['leisure="fitness_centre"']
    # Fallback to generic amenities
    return ['amenity~"bar|cafe|restaurant"']


def fetch_places(city: str, activity: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Find places near a city using Overpass API based on activity."""
    lat, lon, geo_error = get_city_coords(city)
    if geo_error or lat is None or lon is None:
        return None, geo_error or "City not found."

    tags = map_activity_to_overpass_tags(activity)
    # 5km radius around city center
    radius_m = 5000

    # Build Overpass QL query
    query_parts = []
    for tag in tags:
        query_parts.append(f"node(around:{radius_m},{lat},{lon})[{tag}];")
        query_parts.append(f"way(around:{radius_m},{lat},{lon})[{tag}];")
        query_parts.append(f"relation(around:{radius_m},{lat},{lon})[{tag}];")

    query = "[out:json][timeout:25];(\n" + "\n".join(query_parts) + "\n);out center 25;"

    try:
        resp = requests.post(OVERPASS_URL, data=query, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        elements = data.get("elements", [])
        places: List[Dict[str, Any]] = []
        for el in elements[:25]:
            tags = el.get("tags", {})
            name = tags.get("name")
            if not name:
                continue
            lat_el = el.get("lat") or (el.get("center") or {}).get("lat")
            lon_el = el.get("lon") or (el.get("center") or {}).get("lon")
            places.append(
                {
                    "name": name,
                    "category": tags.get("amenity") or tags.get("leisure") or tags.get("tourism"),
                    "address": tags.get("addr:street") or tags.get("addr:full") or "",
                    "lat": lat_el,
                    "lon": lon_el,
                    "website": tags.get("website") or "",
                }
            )
        if not places:
            return None, "No places found."
        return places, None
    except Exception:
        return None, "Failed to fetch places."


def build_wear_suggestion(weather: Dict[str, Any]) -> str:
    """Create a simple clothing suggestion based on weather data."""
    # Minimal heuristic for clothing guidance
    temp = weather.get("temperature_c")
    temp_max = weather.get("temp_max_c")
    temp_min = weather.get("temp_min_c")

    ref_temp = temp if temp is not None else (temp_max if temp_max is not None else temp_min)
    if ref_temp is None:
        return "Dress comfortably for the season."
    if ref_temp <= 5:
        return "Wear a warm coat, gloves, and a hat."
    if ref_temp <= 12:
        return "A jacket or layered outfit is recommended."
    if ref_temp <= 20:
        return "Light jacket or sweater should be enough."
    return "T-shirt and light layers are fine."


def generate_recommendation(
    activity: str,
    city: str,
    when_text: Optional[str],
    weather: Dict[str, Any],
    places: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str]]:
    """Generate a personalized recommendation using the OpenRouter API."""
    if not OPENROUTER_API_KEY:
        return None, "OpenRouter API key not configured."

    places_text = "\n".join([f"- {p['name']} ({p.get('category', 'place')})" for p in places[:5]])
    weather_text = ", ".join([f"{k}: {v}" for k, v in weather.items()])

    system_prompt = (
        "You are City ActivityAdvisor. Use only the provided weather and places. "
        "Return a concise, friendly recommendation with a clear pick and a brief rationale."
    )

    user_prompt = (
        f"Activity: {activity}\n"
        f"City: {city}\n"
        f"When: {when_text or 'not specified'}\n"
        f"Weather: {weather_text}\n"
        f"Places:\n{places_text}\n"
        "Return: 1) top pick, 2) short reason, 3) what to wear."
    )

    try:
        url = f"{OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        if OPENROUTER_HTTP_REFERER:
            headers["HTTP-Referer"] = OPENROUTER_HTTP_REFERER
        if OPENROUTER_APP_TITLE:
            headers["X-Title"] = OPENROUTER_APP_TITLE

        payload = {
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 300,
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            return None, f"Failed to generate recommendation: {resp.status_code} {resp.text}"
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return None, "Failed to generate recommendation: empty response."
        message = choices[0].get("message", {})
        text = message.get("content", "").strip()
        if not text:
            return None, "Failed to generate recommendation: empty content."
        return text, None
    except Exception as exc:
        return None, f"Failed to generate recommendation: {exc}"


@app.get("/health")
def health() -> JSONResponse:
    """Health check endpoint."""
    # Simple liveness response
    return ok({"message": "Server running"}, message="Server running")


@app.get("/weather")
def weather(city: str = Query(default="")) -> JSONResponse:
    """Get current temperature for a city."""
    try:
        city = city.strip()
        if not city:
            return err("City is required.")

        lat, lon, geo_error = get_city_coords(city)
        if geo_error or lat is None or lon is None:
            return err(geo_error or "City not found.")

        data, weather_error = get_current_weather(lat, lon)
        if weather_error or data is None:
            return err(weather_error or "Weather unavailable.")

        return ok({"city": city, "weather": data})
    except Exception:
        return err("Unexpected error.", status_code=500)


@app.get("/places")
def places(activity: str = Query(default=""), city: str = Query(default="")) -> JSONResponse:
    """Find places based on activity and city."""
    try:
        activity = activity.strip()
        city = city.strip()
        if not activity or not city:
            return err("Activity and city are required.")

        results, places_error = fetch_places(city=city, activity=activity)
        if places_error or results is None:
            return err(places_error or "Places unavailable.")

        return ok({"city": city, "activity": activity, "places": results})
    except Exception:
        return err("Unexpected error.", status_code=500)


@app.post("/advisor")
def advisor(
    activity_form: Optional[str] = Form(default=None),
    city_form: Optional[str] = Form(default=None),
    date_form: Optional[str] = Form(default=None),
    datetime_form: Optional[str] = Form(default=None),
) -> JSONResponse:
    """Return personalized activity advice using weather, places, and OpenAI."""
    try:
        activity = str(activity_form or "").strip()
        city = str(city_form or "").strip()
        when_text = str(date_form or datetime_form or "").strip() or None

        if not activity or not city:
            return err("Activity and city are required.")

        target_date = parse_date_input(when_text)
        lat, lon, geo_error = get_city_coords(city)
        if geo_error or lat is None or lon is None:
            return err(geo_error or "City not found.")

        # Weather: daily forecast if a valid date is provided, else current weather
        if target_date:
            weather_data, weather_error = get_daily_weather(lat, lon, target_date)
        else:
            weather_data, weather_error = get_current_weather(lat, lon)

        if weather_error or weather_data is None:
            return err(weather_error or "Weather unavailable.")

        places_data, places_error = fetch_places(city=city, activity=activity)
        if places_error or places_data is None:
            return err(places_error or "Places unavailable.")

        wear_text = build_wear_suggestion(weather_data)

        recommendation, rec_error = generate_recommendation(
            activity=activity,
            city=city,
            when_text=when_text,
            weather=weather_data,
            places=places_data,
        )
        if rec_error or recommendation is None:
            return err(rec_error or "Recommendation unavailable.")

        return ok(
            {
                "activity": activity,
                "city": city,
                "datetime": when_text,
                "weather": weather_data,
                "places": places_data,
                "wear": wear_text,
                "recommendation": recommendation,
            }
        )
    except Exception:
        return err("Unexpected error.", status_code=500)
