#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("TALARIA_ROOT", Path(__file__).resolve().parent))
USER_CONFIG_DIR = Path.home() / "Library" / "Application Support" / "Talaria"
CONFIG_PATH = USER_CONFIG_DIR / "intervals_config.json"
BUNDLED_CONFIG_PATH = ROOT / "intervals_config.json"
LEGACY_CONFIG_PATH = ROOT / ".intervals_gui_config.json"
WORKOUT_DIR = ROOT / "inputs" / "intervals_workouts"
REPORT_DIR = ROOT / "reports"
API_BASE = "https://intervals.icu/api/v1"


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if BUNDLED_CONFIG_PATH.exists():
        config = json.loads(BUNDLED_CONFIG_PATH.read_text(encoding="utf-8"))
        if config.get("api_key"):
            save_config(config)
        return config
    if LEGACY_CONFIG_PATH.exists():
        return json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"))
    return {"athlete_id": "0", "api_key": ""}


def save_config(config: dict[str, Any]) -> None:
    existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    merged = {**existing, **config}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def workout_name(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return fallback


def infer_workout_type(filename_slug: str, name: str, description: str) -> str:
    text = f"{filename_slug} {name} {description}".lower()
    rules = [
        ("WeightTraining", ("strength", "weights", "weight training", "gym", "lift", "lifting", "s&c", "conditioning")),
        ("Swim", ("swim", "pool", "open water", "css", "freestyle", "breaststroke", "backstroke")),
        ("Run", ("run", "jog", "brick run", "tempo run", "long run", "interval run")),
        ("Ride", ("bike", "ride", "cycle", "cycling", "turbo", "trainer", "zwift", "brick bike")),
        ("Walk", ("walk", "hike", "hiking")),
        ("Yoga", ("yoga", "mobility", "stretch")),
        ("Rowing", ("row", "rowing", "erg rower")),
    ]
    for workout_type, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return workout_type
    return "Other"


WORKOUT_EXTENSIONS = {".txt", ".md"}
DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")


def workout_slug_from_path(path: Path, workout_date: str) -> str:
    stem = path.stem
    stem = re.sub(rf"^{re.escape(workout_date)}[_\-\s]*", "", stem)
    return slugify(stem) or "workout"


def dated_sections(text: str) -> list[tuple[str, str, str]]:
    sections: list[tuple[str, str, str]] = []
    starts: list[tuple[int, str, str]] = []
    for match in re.finditer(r"(?m)^(?:#{1,6}\s*)?(?P<date>\d{4}-\d{2}-\d{2})[\s:_-]*(?P<title>[^\n]*)$", text):
        starts.append((match.start(), match.group("date"), match.group("title").strip(" #-_") or "Workout"))
    for index, (start, workout_date, title) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append((workout_date, title, body + "\n"))
    return sections


def workout_record(path: Path, workout_date: str, slug: str, description: str, title_hint: str | None = None) -> dict[str, Any]:
    name = title_hint.strip() if title_hint else workout_name(description, slug.replace("-", " ").title())
    workout_type = infer_workout_type(slug, name, description)
    relative = path.relative_to(WORKOUT_DIR).as_posix() if path.is_relative_to(WORKOUT_DIR) else path.name
    stable_source = slugify(relative)
    return {
        "id": f"{workout_date}-{workout_type.lower()}-{slug}-{stable_source}",
        "date": workout_date,
        "type": workout_type,
        "name": name,
        "filename": relative,
        "path": str(path),
        "description": description,
        "external_id": f"talaria-{workout_date}-{workout_type.lower()}-{slugify(name)}-{stable_source}",
    }


def workout_files() -> list[dict[str, Any]]:
    workouts: list[dict[str, Any]] = []
    if not WORKOUT_DIR.exists():
        return workouts
    for path in sorted(item for item in WORKOUT_DIR.rglob("*") if item.is_file() and item.suffix.lower() in WORKOUT_EXTENSIONS):
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            raw = path.read_text(encoding="utf-8-sig", errors="replace").strip()
        if not raw:
            continue
        filename_date = DATE_PATTERN.search(path.stem)
        if filename_date:
            workout_date = filename_date.group(1)
            slug = workout_slug_from_path(path, workout_date)
            workouts.append(workout_record(path, workout_date, slug, raw + "\n"))
            continue
        sections = dated_sections(raw)
        for section_index, (workout_date, title, description) in enumerate(sections, start=1):
            slug = slugify(title) or f"{path.stem}-{section_index}"
            workouts.append(workout_record(path, workout_date, slug, description, title))
    return sorted(workouts, key=lambda item: (item["date"], item["type"], item["name"], item["filename"]))


def auth_header(api_key: str) -> str:
    token = base64.b64encode(f"API_KEY:{api_key}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def intervals_request(
    method: str,
    path: str,
    api_key: str,
    body: Any | None = None,
    query: dict[str, str] | None = None,
) -> Any:
    if not api_key:
        raise ValueError("Missing Intervals.icu API key.")
    url = f"{API_BASE}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None
    headers = {
        "Authorization": auth_header(api_key),
        "Accept": "application/json",
        "User-Agent": "IntervalsPlannerGui/1.0",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Intervals.icu returned HTTP {exc.code}: {detail[:800]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Intervals.icu: {exc.reason}") from exc


def activity_identifier(activity: dict[str, Any]) -> str | None:
    value = first_value(activity, ("id", "activity_id", "icu_activity_id"))
    return str(value) if value is not None else None


def recent_activities(activities: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    return sorted(
        activities,
        key=lambda a: a.get("start_date_local") or a.get("start_date") or "",
        reverse=True,
    )[:limit]


def fetch_activity_enrichment(
    activities: list[dict[str, Any]],
    api_key: str,
    limit: int | None = None,
    stream_limit: int | None = None,
) -> dict[str, dict[str, Any]]:
    enriched: dict[str, dict[str, Any]] = {}
    selected_activities = recent_activities(activities, limit) if limit is not None else recent_activities(activities, len(activities))
    for index, activity in enumerate(selected_activities):
        activity_id = activity_identifier(activity)
        if not activity_id:
            continue
        data: dict[str, Any] = {}
        requests: tuple[tuple[str, str, dict[str, str] | None], ...] = (
            ("detail", f"/activity/{activity_id}", {"intervals": "true"}),
            ("intervals", f"/activity/{activity_id}/intervals", None),
            ("interval_stats", f"/activity/{activity_id}/interval-stats", None),
            ("hr_histogram", f"/activity/{activity_id}/hr-histogram", {"bucketSize": "5"}),
            ("time_at_hr", f"/activity/{activity_id}/time-at-hr", None),
            ("hr_load_model", f"/activity/{activity_id}/hr-load-model", None),
            ("power_vs_hr", f"/activity/{activity_id}/power-vs-hr.json", None),
            ("power_histogram", f"/activity/{activity_id}/power-histogram", {"bucketSize": "25"}),
            ("pace_histogram", f"/activity/{activity_id}/pace-histogram", None),
            ("weather", f"/activity/{activity_id}/weather-summary", None),
        )
        for key, path, query in requests:
            try:
                data[key] = intervals_request("GET", path, api_key, query=query) or {}
            except Exception as exc:
                data[f"{key}_error"] = str(exc)
        if stream_limit is None or index < stream_limit:
            try:
                data["streams"] = intervals_request(
                    "GET",
                    f"/activity/{activity_id}/streams.json",
                    api_key,
                    query={"types": "heartrate,watts,cadence,velocity,altitude,grade,temperature", "includeDefaults": "true"},
                ) or []
            except Exception as exc:
                data["streams_error"] = str(exc)
        for stream, query in {
            "best_hr_5m": {"stream": "heartrate", "duration": "300", "count": "3"},
            "best_power_5m": {"stream": "watts", "duration": "300", "count": "3"},
            "best_power_20m": {"stream": "watts", "duration": "1200", "count": "2"},
            "best_pace_1k": {"stream": "velocity", "distance": "1000", "count": "3"},
            "best_pace_5k": {"stream": "velocity", "distance": "5000", "count": "2"},
        }.items():
            try:
                data[stream] = intervals_request("GET", f"/activity/{activity_id}/best-efforts", api_key, query=query) or {}
            except Exception:
                pass
        enriched[activity_id] = data
    return enriched


def fetch_fitness_model_events(athlete_id: str, api_key: str) -> list[dict[str, Any]]:
    try:
        return intervals_request("GET", f"/athlete/{athlete_id}/fitness-model-events", api_key) or []
    except Exception:
        return []


def fetch_athlete_curve_context(athlete_id: str, api_key: str, oldest: str, newest: str) -> dict[str, Any]:
    context: dict[str, Any] = {}
    requests: tuple[tuple[str, str, dict[str, str]], ...] = (
        ("range_hr_bests", f"/athlete/{athlete_id}/activity-hr-curves.json", {"oldest": oldest, "newest": newest, "secs": "60,300,1200"}),
        ("range_power_bests", f"/athlete/{athlete_id}/activity-power-curves.json", {"oldest": oldest, "newest": newest, "secs": "5,60,300,1200"}),
        ("range_pace_bests", f"/athlete/{athlete_id}/activity-pace-curves.json", {"oldest": oldest, "newest": newest, "distances": "1000,5000,10000"}),
        ("power_hr_curve", f"/athlete/{athlete_id}/power-hr-curve", {"start": oldest, "end": newest}),
    )
    for key, path, query in requests:
        try:
            context[key] = intervals_request("GET", path, api_key, query=query) or {}
        except Exception as exc:
            context[f"{key}_error"] = str(exc)
    return context


def selected_events(selected_ids: list[str]) -> list[dict[str, Any]]:
    selected = set(selected_ids)
    events = []
    for workout in workout_files():
        if selected and workout["id"] not in selected:
            continue
        events.append(
            {
                "category": "WORKOUT",
                "start_date_local": f"{workout['date']}T00:00:00",
                "type": workout["type"],
                "name": workout["name"],
                "description": workout["description"],
                "external_id": workout["external_id"],
            }
        )
    return events


def delete_workout_files(selected_ids: list[str]) -> list[str]:
    selected = set(selected_ids)
    removed: list[str] = []
    paths: dict[str, Path] = {}
    for workout in workout_files():
        if workout["id"] in selected:
            paths[workout["filename"]] = Path(workout["path"])
    for label, path in sorted(paths.items()):
        if path.exists() and path.is_file() and path.suffix.lower() in WORKOUT_EXTENSIONS:
            path.unlink()
            removed.append(label)
    return removed


def date_range_for_events(events: list[dict[str, Any]]) -> tuple[str, str]:
    dates = sorted(str(event.get("start_date_local", ""))[:10] for event in events if event.get("start_date_local"))
    if not dates:
        today = date.today().isoformat()
        return today, today
    return dates[0], dates[-1]


def delete_event(athlete_id: str, api_key: str, event_id: str) -> Any:
    return intervals_request("DELETE", f"/athlete/{athlete_id}/events/{event_id}", api_key)


def safe_num(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def minutes_to_hm(minutes: float) -> str:
    hours = int(minutes // 60)
    mins = int(round(minutes % 60))
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def activity_minutes(activity: dict[str, Any]) -> float:
    for key in ("moving_time", "elapsed_time", "icu_moving_time"):
        value = safe_num(activity.get(key))
        if value:
            return value / 60.0
    return 0.0


def first_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return None


def first_number(data: dict[str, Any], keys: tuple[str, ...]) -> float:
    value = first_value(data, keys)
    return safe_num(value)


def fmt_number(value: Any, digits: int = 1, suffix: str = "") -> str | None:
    if not isinstance(value, (int, float)):
        return None
    if value == 0:
        rendered = "0"
    elif digits == 0:
        rendered = str(int(round(value)))
    else:
        rendered = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return f"{rendered}{suffix}"


def fmt_optional(data: dict[str, Any], keys: tuple[str, ...], label: str, digits: int = 1, suffix: str = "") -> str | None:
    value = first_value(data, keys)
    if isinstance(value, (int, float)):
        rendered = fmt_number(value, digits, suffix)
        return f"{label} {rendered}" if rendered is not None else None
    if value is not None and value != "":
        return f"{label} {value}"
    return None


def fmt_distance_meters(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    if value >= 1000:
        return f"distance {value / 1000:.1f}km"
    return f"distance {value:.0f}m"


def seconds_to_hm(seconds: Any) -> str | None:
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return None
    return minutes_to_hm(seconds / 60.0)


def average(values: list[float]) -> float | None:
    useful = [value for value in values if value]
    if not useful:
        return None
    return sum(useful) / len(useful)


def wellness_date(wellness_item: dict[str, Any]) -> str:
    return str(
        wellness_item.get("id")
        or wellness_item.get("date")
        or wellness_item.get("day")
        or wellness_item.get("start_date_local")
        or ""
    )


def interval_list(interval_payload: Any) -> list[dict[str, Any]]:
    if isinstance(interval_payload, list):
        return [item for item in interval_payload if isinstance(item, dict)]
    if isinstance(interval_payload, dict):
        for key in ("intervals", "items", "data"):
            value = interval_payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def summarize_intervals(interval_payload: Any) -> str | None:
    intervals = interval_list(interval_payload)
    meaningful = [
        item for item in intervals
        if item.get("type") not in {"WORK", "RECOVERY"} or item.get("name") or safe_num(item.get("moving_time") or item.get("elapsed_time"))
    ]
    if not meaningful:
        return None
    parts = [f"{len(meaningful)} intervals"]
    named = [item for item in meaningful if item.get("name")][:5]
    if named:
        parts.append("named " + ", ".join(str(item.get("name")) for item in named))
    load = sum(first_number(item, ("icu_training_load", "training_load", "load")) for item in meaningful)
    if load:
        parts.append(f"interval load {load:.0f}")
    hard = [
        item for item in meaningful
        if first_number(item, ("average_heartrate", "avg_hr")) >= 150
        or first_number(item, ("average_watts", "avg_watts")) > 0
        or first_number(item, ("icu_intensity", "intensity")) >= 0.8
    ]
    if hard:
        parts.append(f"{len(hard)} notable/hard segments")
    return "; ".join(parts)


def summarize_weather(weather: Any) -> str | None:
    if not isinstance(weather, dict) or not weather:
        return None
    bits = []
    for item in [
        fmt_optional(weather, ("average_temp", "average_weather_temp", "temp", "temperature", "air_temp"), "temp", 1, "C"),
        fmt_optional(weather, ("average_feels_like",), "feels like", 1, "C"),
        fmt_optional(weather, ("humidity",), "humidity", 0, "%"),
        fmt_optional(weather, ("average_wind_speed", "wind_speed", "windSpeed"), "wind", 1, "m/s"),
        fmt_optional(weather, ("average_wind_gust", "wind_gust", "windGust"), "gust", 1, "m/s"),
        fmt_optional(weather, ("headwind_percent",), "headwind", 0, "%"),
        fmt_optional(weather, ("tailwind_percent",), "tailwind", 0, "%"),
        fmt_optional(weather, ("max_rain",), "rain", 1, "mm"),
        fmt_optional(weather, ("description", "weather", "summary"), "conditions", 1),
    ]:
        if item:
            bits.append(item)
    return ", ".join(bits) if bits else None


def seconds_text(seconds: Any) -> str | None:
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return None
    if seconds < 90:
        return f"{int(round(seconds))}s"
    return minutes_to_hm(seconds / 60.0)


def numeric_series(values: Any) -> list[float]:
    if isinstance(values, dict):
        iterable = values.values()
    elif isinstance(values, list):
        iterable = values
    else:
        return []
    series: list[float] = []
    for value in iterable:
        if isinstance(value, (int, float)):
            series.append(float(value))
        elif isinstance(value, list) and value and isinstance(value[-1], (int, float)):
            series.append(float(value[-1]))
    return series


def summarize_series(label: str, values: list[float], digits: int = 0, suffix: str = "") -> str | None:
    values = [value for value in values if value is not None]
    if not values:
        return None
    avg = sum(values) / len(values)
    first = values[: max(1, len(values) // 2)]
    second = values[max(1, len(values) // 2):]
    bits = [
        f"{label} samples {len(values)}",
        f"avg {fmt_number(avg, digits, suffix)}",
        f"min {fmt_number(min(values), digits, suffix)}",
        f"max {fmt_number(max(values), digits, suffix)}",
    ]
    if second:
        drift = (sum(second) / len(second)) - (sum(first) / len(first))
        if abs(drift) >= 1:
            bits.append(f"2nd-half drift {fmt_number(drift, digits, suffix)}")
    return ", ".join(bits)


def find_stream(streams: Any, names: tuple[str, ...]) -> list[float]:
    if not isinstance(streams, list):
        return []
    wanted = {name.lower() for name in names}
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        stream_type = str(stream.get("type") or stream.get("name") or "").lower()
        if stream_type in wanted:
            return numeric_series(stream.get("data") or stream.get("values") or stream.get("data2"))
    return []


def summarize_streams(streams: Any) -> list[str]:
    summaries = []
    for names, label, digits, suffix in [
        (("heartrate", "hr", "heart_rate"), "HR stream", 0, "bpm"),
        (("watts", "power", "fixed_watts", "raw_watts"), "power stream", 0, "w"),
        (("cadence",), "cadence stream", 0, "rpm"),
        (("velocity", "speed"), "speed stream", 2, "m/s"),
        (("altitude",), "altitude stream", 0, "m"),
        (("temperature", "temp"), "temperature stream", 1, "C"),
    ]:
        summary = summarize_series(label, find_stream(streams, names), digits, suffix)
        if summary:
            summaries.append(summary)
    return summaries


def summarize_zone_seconds(values: Any, label: str) -> str | None:
    if not isinstance(values, list) or not values:
        return None
    zone_bits = []
    for index, value in enumerate(values, start=1):
        secs = value.get("secs") if isinstance(value, dict) else value
        text = seconds_text(secs)
        if text:
            zone_id = value.get("id") if isinstance(value, dict) else f"Z{index}"
            zone_bits.append(f"{zone_id} {text}")
    return f"{label}: " + ", ".join(zone_bits[:8]) if zone_bits else None


def summarize_histogram(histogram: Any, label: str, value_key: str) -> str | None:
    if not isinstance(histogram, list) or not histogram:
        return None
    buckets = [bucket for bucket in histogram if isinstance(bucket, dict) and safe_num(bucket.get("secs") or bucket.get("movingSecs"))]
    if not buckets:
        return None
    buckets.sort(key=lambda item: safe_num(item.get("secs") or item.get("movingSecs")), reverse=True)
    bits = []
    for bucket in buckets[:4]:
        start = first_value(bucket, ("start", value_key))
        secs = seconds_text(bucket.get("secs") or bucket.get("movingSecs"))
        if start is not None and secs:
            bits.append(f"{start}: {secs}")
    return f"{label}: " + ", ".join(bits) if bits else None


def summarize_time_at_hr(plot: Any) -> str | None:
    if not isinstance(plot, dict) or not plot:
        return None
    bits = []
    for item in [
        fmt_optional(plot, ("min_bpm",), "min", 0, "bpm"),
        fmt_optional(plot, ("max_bpm",), "max", 0, "bpm"),
    ]:
        if item:
            bits.append(item)
    secs = plot.get("secs")
    cumulative = plot.get("cumulative_secs")
    if isinstance(secs, list) and secs:
        max_bucket = max(safe_num(value) for value in secs)
        text = seconds_text(max_bucket)
        if text:
            bits.append(f"largest HR bucket {text}")
    if isinstance(cumulative, list) and cumulative:
        high = seconds_text(cumulative[-1])
        if high:
            bits.append(f"cumulative high-HR tail {high}")
    return ", ".join(bits) if bits else None


def summarize_power_vs_hr(plot: Any) -> str | None:
    if not isinstance(plot, dict) or not plot:
        return None
    bits = []
    for item in [
        fmt_optional(plot, ("decoupling",), "decoupling", 1, "%"),
        fmt_optional(plot, ("powerHr",), "power/HR", 2),
        fmt_optional(plot, ("powerHrFirst",), "first half power/HR", 2),
        fmt_optional(plot, ("powerHrSecond",), "second half power/HR", 2),
        fmt_optional(plot, ("powerHrZ2",), "Z2 power/HR", 2),
        fmt_optional(plot, ("avgCadenceZ2",), "Z2 cadence", 0, "rpm"),
        fmt_optional(plot, ("hrZ2BucketCount",), "Z2 buckets", 0),
    ]:
        if item:
            bits.append(item)
    return ", ".join(bits) if bits else None


def summarize_hr_load_model(model: Any) -> str | None:
    if not isinstance(model, dict) or not model:
        return None
    bits = []
    for item in [
        fmt_optional(model, ("type",), "type", 0),
        fmt_optional(model, ("icu_training_load", "training_load"), "HR load", 0),
        fmt_optional(model, ("trainingDataCount",), "training data points", 0),
    ]:
        if item:
            bits.append(item)
    return ", ".join(bits) if bits else None


def effort_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        value = payload.get("efforts") or payload.get("items") or payload.get("data")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def summarize_best_efforts(enrichment: dict[str, Any]) -> list[str]:
    summaries = []
    labels = {
        "best_hr_5m": ("best 5m HR", 0, "bpm"),
        "best_power_5m": ("best 5m power", 0, "w"),
        "best_power_20m": ("best 20m power", 0, "w"),
        "best_pace_1k": ("best 1km speed", 2, "m/s"),
        "best_pace_5k": ("best 5km speed", 2, "m/s"),
    }
    for key, (label, digits, suffix) in labels.items():
        efforts = effort_list(enrichment.get(key))
        if efforts:
            value = first_value(efforts[0], ("average", "value"))
            rendered = fmt_number(value, digits, suffix) if isinstance(value, (int, float)) else None
            if rendered:
                summaries.append(f"{label} {rendered}")
    return summaries


def summarize_curve_payload(payload: Any, label: str, value_suffix: str = "") -> str | None:
    curves = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    bits = []
    for curve in curves[:3]:
        if not isinstance(curve, dict):
            continue
        curve_label = curve.get("label") or curve.get("type") or label
        values = numeric_series(curve.get("values"))
        if values:
            bits.append(f"{curve_label}: best {fmt_number(max(values), 1, value_suffix)}")
        for model_key in ("powerModels", "paceModels"):
            models = curve.get(model_key)
            if isinstance(models, list) and models:
                model = models[-1]
                if isinstance(model, dict):
                    model_bits = []
                    for item in [
                        fmt_optional(model, ("cp", "criticalPower"), "CP", 0, "w"),
                        fmt_optional(model, ("ftp",), "FTP", 0, "w"),
                        fmt_optional(model, ("criticalSpeed",), "critical speed", 2, "m/s"),
                        fmt_optional(model, ("wPrime", "w_prime"), "W'", 0, "J"),
                        fmt_optional(model, ("dPrime",), "D'", 0, "m"),
                        fmt_optional(model, ("r2",), "model r2", 2),
                    ]:
                        if item:
                            model_bits.append(item)
                    if model_bits:
                        bits.append(f"{curve_label} model " + ", ".join(model_bits))
    return f"{label}: " + "; ".join(bits[:6]) if bits else None


def summarize_curve_context(curve_context: dict[str, Any]) -> list[str]:
    summaries = []
    for payload, label, suffix in [
        (curve_context.get("range_hr_bests"), "range HR bests", "bpm"),
        (curve_context.get("range_power_bests"), "range power bests", "w"),
        (curve_context.get("range_pace_bests"), "range pace/speed bests", "m/s"),
    ]:
        summary = summarize_curve_payload(payload, label, suffix)
        if summary:
            summaries.append(summary)
    power_hr = summarize_power_vs_hr(curve_context.get("power_hr_curve"))
    if power_hr:
        summaries.append("range power-vs-HR: " + power_hr)
    return summaries


def compact_json_value(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return f"{len(value)} items"
    if isinstance(value, dict):
        return f"{len(value)} fields"
    return str(value)


def summarize_additional_fields(data: dict[str, Any], known_keys: set[str]) -> str | None:
    extras = []
    for key in sorted(data):
        if key in known_keys or key.startswith("_"):
            continue
        rendered = compact_json_value(data.get(key))
        if rendered:
            extras.append(f"{key}: {rendered}")
    return "; ".join(extras) if extras else None


def save_markdown_report(summary: str, oldest: str, newest: str) -> Path:
    report_dir = REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"talaria_progress_{oldest}_to_{newest}.md"
    path.write_text(summary, encoding="utf-8")
    return path


def open_reports_folder() -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(["open", str(REPORT_DIR)], check=False)
    return REPORT_DIR


def open_workout_folder() -> Path:
    WORKOUT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(["open", str(WORKOUT_DIR)], check=False)
    return WORKOUT_DIR


def build_progress_summary(
    activities: list[dict[str, Any]],
    events: list[dict[str, Any]],
    wellness: list[dict[str, Any]],
    oldest: str,
    newest: str,
    activity_enrichment: dict[str, dict[str, Any]] | None = None,
    fitness_events: list[dict[str, Any]] | None = None,
    curve_context: dict[str, Any] | None = None,
) -> str:
    activity_enrichment = activity_enrichment or {}
    fitness_events = fitness_events or []
    curve_context = curve_context or {}
    completed_by_type: dict[str, dict[str, float]] = {}
    for activity in activities:
        sport = activity.get("type") or "Other"
        bucket = completed_by_type.setdefault(
            sport,
            {
                "count": 0,
                "minutes": 0,
                "load": 0,
                "distance": 0,
                "elevation": 0,
                "work": 0,
                "calories": 0,
            },
        )
        bucket["count"] += 1
        bucket["minutes"] += activity_minutes(activity)
        bucket["load"] += safe_num(activity.get("icu_training_load") or activity.get("training_load"))
        bucket["distance"] += first_number(activity, ("distance", "icu_distance"))
        bucket["elevation"] += first_number(activity, ("total_elevation_gain", "elevation_gain", "icu_elevation"))
        bucket["work"] += first_number(activity, ("work", "total_work"))
        bucket["calories"] += first_number(activity, ("calories", "kilojoules"))

    lines = [
        f"Completed training and recovery summary for {oldest} to {newest}",
        "Use this as context for conservative coaching decisions. Prioritise completed work, recent load, HR response, sleep/recovery, injury risk, and whether the next 7 days should be progressed, held, or reduced.",
        "",
        "Completed activities by sport:",
    ]
    if completed_by_type:
        for sport, data in sorted(completed_by_type.items()):
            load = int(round(data["load"]))
            duration = minutes_to_hm(data["minutes"])
            details = [f"{int(data['count'])} sessions", duration, f"load {load}"]
            if data["distance"]:
                details.append(f"distance {data['distance'] / 1000:.1f}km")
            if data["elevation"]:
                details.append(f"elevation {int(round(data['elevation']))}m")
            if data["work"]:
                details.append(f"work {int(round(data['work']))}kJ")
            if data["calories"]:
                details.append(f"energy {int(round(data['calories']))}")
            lines.append(f"- {sport}: " + ", ".join(details))
    else:
        lines.append("- No completed activities found in this date range.")

    curve_summaries = summarize_curve_context(curve_context)
    if curve_summaries:
        lines.extend(["", "Best-effort and athlete curve context:"])
        for summary in curve_summaries:
            lines.append(f"- {summary}")

    all_activities = recent_activities(activities, len(activities))
    lines.extend(["", "All activity detail:"])
    if all_activities:
        known_activity_keys = {
            "id", "activity_id", "icu_activity_id", "start_date_local", "start_date", "type", "name", "moving_time",
            "elapsed_time", "icu_moving_time", "icu_training_load", "training_load", "distance", "icu_distance",
            "total_elevation_gain", "elevation_gain", "icu_elevation", "average_heartrate", "avg_hr",
            "icu_average_heartrate", "max_heartrate", "max_hr", "athlete_max_hr", "lthr", "average_watts",
            "avg_watts", "icu_average_watts", "weighted_average_watts", "normalized_power",
            "icu_weighted_average_watts", "icu_weighted_avg_watts", "icu_ftp", "icu_pm_ftp", "icu_rolling_ftp",
            "average_speed", "avg_speed", "pace", "gap", "average_cadence", "avg_cadence", "perceived_exertion",
            "rpe", "feel", "session_rpe", "icu_rpe", "icu_intensity", "intensity", "trimp", "power_load",
            "icu_power_load", "hr_load", "icu_hr_load", "pace_load", "icu_pace_load", "decoupling",
            "icu_decoupling", "icu_efficiency_factor", "icu_variability_index", "polarization_index",
            "strain_score", "icu_power_hr", "icu_power_hr_z2", "icu_cadence_z2", "icu_joules_above_ftp",
            "icu_max_wbal_depletion", "carbs_used", "carbs_ingested", "average_stride", "lengths",
            "pool_length", "kg_lifted", "compliance", "icu_hr_zone_times", "icu_zone_times",
            "pace_zone_times", "gap_zone_times", "work", "total_work", "calories", "kilojoules",
        }
        for activity in all_activities:
            enrichment = activity_enrichment.get(activity_identifier(activity) or "", {})
            detail = enrichment.get("detail") if isinstance(enrichment.get("detail"), dict) else {}
            combined = {**activity, **detail}
            when = (activity.get("start_date_local") or activity.get("start_date") or "")[:10]
            name = combined.get("name") or activity.get("name") or activity.get("type") or "Activity"
            sport = combined.get("type") or activity.get("type") or "Other"
            duration = minutes_to_hm(activity_minutes(combined) or activity_minutes(activity))
            load = int(round(safe_num(combined.get("icu_training_load") or combined.get("training_load"))))
            details = [duration, f"load {load}"]
            distance = fmt_distance_meters(first_number(combined, ("distance", "icu_distance")))
            if distance:
                details.append(distance)
            for item in [
                fmt_optional(combined, ("total_elevation_gain", "elevation_gain", "icu_elevation"), "elevation", 0, "m"),
                fmt_optional(combined, ("average_heartrate", "avg_hr", "icu_average_heartrate"), "avg HR", 0, "bpm"),
                fmt_optional(combined, ("max_heartrate", "max_hr"), "max HR", 0, "bpm"),
                fmt_optional(combined, ("athlete_max_hr",), "athlete max HR setting", 0, "bpm"),
                fmt_optional(combined, ("lthr",), "LTHR", 0, "bpm"),
                fmt_optional(combined, ("average_watts", "avg_watts", "icu_average_watts"), "avg power", 0, "w"),
                fmt_optional(combined, ("weighted_average_watts", "normalized_power", "icu_weighted_average_watts", "icu_weighted_avg_watts"), "weighted power", 0, "w"),
                fmt_optional(combined, ("icu_ftp", "icu_pm_ftp", "icu_rolling_ftp"), "FTP", 0, "w"),
                fmt_optional(combined, ("average_speed", "avg_speed"), "avg speed", 2, "m/s"),
                fmt_optional(combined, ("pace",), "pace", 2, "m/s"),
                fmt_optional(combined, ("gap",), "GAP", 2, "m/s"),
                fmt_optional(combined, ("average_cadence", "avg_cadence"), "cadence", 0, "rpm"),
                fmt_optional(combined, ("perceived_exertion", "rpe"), "RPE", 1),
                fmt_optional(combined, ("feel",), "feel", 0),
                fmt_optional(combined, ("session_rpe", "icu_rpe"), "session RPE", 0),
                fmt_optional(combined, ("icu_intensity", "intensity"), "intensity", 2),
                fmt_optional(combined, ("trimp",), "TRIMP", 0),
                fmt_optional(combined, ("power_load", "icu_power_load"), "power load", 0),
                fmt_optional(combined, ("hr_load", "icu_hr_load"), "HR load", 0),
                fmt_optional(combined, ("pace_load", "icu_pace_load"), "pace load", 0),
                fmt_optional(combined, ("decoupling", "icu_decoupling"), "decoupling", 1, "%"),
                fmt_optional(combined, ("icu_efficiency_factor",), "efficiency factor", 2),
                fmt_optional(combined, ("icu_variability_index",), "variability index", 2),
                fmt_optional(combined, ("polarization_index",), "polarization", 2),
                fmt_optional(combined, ("strain_score",), "strain", 1),
                fmt_optional(combined, ("icu_power_hr",), "power/HR", 2),
                fmt_optional(combined, ("icu_power_hr_z2",), "Z2 power/HR", 2),
                fmt_optional(combined, ("icu_cadence_z2",), "Z2 cadence", 0, "rpm"),
                fmt_optional(combined, ("icu_joules_above_ftp",), "work above FTP", 0, "J"),
                fmt_optional(combined, ("icu_max_wbal_depletion",), "max W' depletion", 0, "J"),
                fmt_optional(combined, ("carbs_used",), "carbs used", 0, "g"),
                fmt_optional(combined, ("carbs_ingested",), "carbs ingested", 0, "g"),
                fmt_optional(combined, ("average_stride",), "stride", 2, "m"),
                fmt_optional(combined, ("lengths",), "swim lengths", 0),
                fmt_optional(combined, ("pool_length",), "pool", 0, "m"),
                fmt_optional(combined, ("kg_lifted",), "kg lifted", 0, "kg"),
                fmt_optional(combined, ("compliance",), "workout compliance", 0, "%"),
            ]:
                if item:
                    details.append(item)
            for zone_summary in [
                summarize_zone_seconds(combined.get("icu_hr_zone_times"), "HR zones"),
                summarize_zone_seconds(combined.get("icu_zone_times"), "power zones"),
                summarize_zone_seconds(combined.get("pace_zone_times"), "pace zones"),
                summarize_zone_seconds(combined.get("gap_zone_times"), "GAP zones"),
            ]:
                if zone_summary:
                    details.append(zone_summary)
            lines.append(f"- {when}: {sport} - {name}; " + "; ".join(details))
            interval_summary = summarize_intervals(enrichment.get("intervals") or detail)
            if interval_summary:
                lines.append(f"  intervals: {interval_summary}")
            interval_stats = summarize_intervals(enrichment.get("interval_stats"))
            if interval_stats and interval_stats != interval_summary:
                lines.append(f"  interval stats: {interval_stats}")
            hr_load = summarize_hr_load_model(enrichment.get("hr_load_model"))
            if hr_load:
                lines.append(f"  HR load model: {hr_load}")
            time_at_hr = summarize_time_at_hr(enrichment.get("time_at_hr"))
            if time_at_hr:
                lines.append(f"  time at HR: {time_at_hr}")
            for histogram in [
                summarize_histogram(enrichment.get("hr_histogram"), "HR histogram dominant buckets", "hr"),
                summarize_histogram(enrichment.get("power_histogram"), "power histogram dominant buckets", "watts"),
                summarize_histogram(enrichment.get("pace_histogram"), "pace histogram dominant buckets", "start"),
            ]:
                if histogram:
                    lines.append(f"  {histogram}")
            power_vs_hr = summarize_power_vs_hr(enrichment.get("power_vs_hr"))
            if power_vs_hr:
                lines.append(f"  power-vs-HR: {power_vs_hr}")
            best_efforts = summarize_best_efforts(enrichment)
            if best_efforts:
                lines.append("  best efforts: " + ", ".join(best_efforts))
            for stream_summary in summarize_streams(enrichment.get("streams")):
                lines.append(f"  stream: {stream_summary}")
            weather_summary = summarize_weather(enrichment.get("weather"))
            if weather_summary:
                lines.append(f"  weather: {weather_summary}")
            fetch_errors = [f"{key}: {value}" for key, value in sorted(enrichment.items()) if key.endswith("_error")]
            if fetch_errors:
                lines.append("  unavailable API detail: " + "; ".join(fetch_errors))
            extra_fields = summarize_additional_fields(combined, known_activity_keys)
            if extra_fields:
                lines.append(f"  additional activity fields: {extra_fields}")
    else:
        lines.append("- None.")

    if fitness_events:
        lines.extend(["", "Fitness/load model events:"])
        for event in sorted(fitness_events, key=lambda e: e.get("start_date_local") or e.get("start_date") or e.get("date") or ""):
            when = (event.get("start_date_local") or event.get("start_date") or event.get("date") or "")[:10]
            label = event.get("name") or event.get("type") or event.get("category") or "fitness event"
            bits = []
            for item in [
                fmt_optional(event, ("icu_training_load", "training_load", "load"), "load", 0),
                fmt_optional(event, ("ctl", "fitness"), "fitness/CTL", 1),
                fmt_optional(event, ("atl",), "acute load/ATL", 1),
                fmt_optional(event, ("form", "tsb"), "form/TSB", 1),
            ]:
                if item:
                    bits.append(item)
            lines.append(f"- {when}: {label}" + (f"; {'; '.join(bits)}" if bits else ""))

    if wellness:
        sorted_wellness = sorted(wellness, key=wellness_date)
        latest = sorted_wellness[-1]
        wellness_bits = []
        for keys, label, digits, suffix in [
            (("weight",), "weight", 1, "kg"),
            (("restingHR", "resting_hr", "restingHeartRate"), "resting HR", 0, "bpm"),
            (("hrv", "hrv_rmssd", "rmssd"), "HRV", 1, "ms"),
            (("hrvSDNN",), "HRV SDNN", 1, "ms"),
            (("sleep_secs", "sleepSeconds"), "sleep", 0, ""),
            (("sleepSecs",), "sleep", 0, ""),
            (("sleep_score", "sleepScore"), "sleep score", 0, ""),
            (("sleepQuality",), "sleep quality", 0, ""),
            (("avgSleepingHR",), "sleeping HR", 0, "bpm"),
            (("fatigue",), "fatigue", 1, ""),
            (("form",), "form", 1, ""),
            (("ctl", "fitness"), "fitness/CTL", 1, ""),
            (("atl",), "acute load/ATL", 1, ""),
            (("rampRate",), "ramp rate", 1, ""),
            (("readiness",), "readiness", 1, ""),
            (("mood",), "mood", 1, ""),
            (("motivation",), "motivation", 1, ""),
            (("soreness",), "soreness", 1, ""),
            (("stress",), "stress", 1, ""),
            (("injury",), "injury", 1, ""),
            (("spO2", "spo2"), "SpO2", 1, "%"),
            (("respiration",), "respiration", 1, ""),
            (("steps",), "steps", 0, ""),
            (("hydration",), "hydration", 0, ""),
            (("kcalConsumed",), "kcal consumed", 0, ""),
            (("carbohydrates",), "carbs", 0, "g"),
            (("protein",), "protein", 0, "g"),
            (("fatTotal",), "fat", 0, "g"),
            (("vo2max",), "VO2max", 1, ""),
            (("bodyBattery", "body_battery"), "body battery", 0, ""),
        ]:
            value = first_value(latest, keys)
            if keys[0] in {"sleep_secs", "sleepSeconds", "sleepSecs"}:
                sleep = seconds_to_hm(value)
                if sleep:
                    wellness_bits.append(f"{label}: {sleep}")
            else:
                item = fmt_optional(latest, keys, label, digits, suffix)
                if item:
                    wellness_bits.append(item)
        if wellness_bits:
            lines.extend(["", f"Latest wellness/recovery ({wellness_date(latest) or 'unknown date'}): " + ", ".join(wellness_bits)])

        hrv_avg = average([first_number(w, ("hrv", "hrv_rmssd", "rmssd")) for w in sorted_wellness])
        rhr_avg = average([first_number(w, ("restingHR", "resting_hr", "restingHeartRate")) for w in sorted_wellness])
        sleep_avg = average([first_number(w, ("sleep_secs", "sleepSeconds", "sleepSecs")) / 3600.0 for w in sorted_wellness])
        sleep_score_avg = average([first_number(w, ("sleep_score", "sleepScore")) for w in sorted_wellness])
        readiness_avg = average([first_number(w, ("readiness",)) for w in sorted_wellness])
        fatigue_avg = average([first_number(w, ("fatigue",)) for w in sorted_wellness])
        stress_avg = average([first_number(w, ("stress",)) for w in sorted_wellness])
        trend_bits = []
        if hrv_avg:
            trend_bits.append(f"avg HRV {hrv_avg:.1f}ms")
        if rhr_avg:
            trend_bits.append(f"avg resting HR {rhr_avg:.0f}bpm")
        if sleep_avg:
            trend_bits.append(f"avg sleep {sleep_avg:.1f}h")
        if sleep_score_avg:
            trend_bits.append(f"avg sleep score {sleep_score_avg:.0f}")
        if readiness_avg:
            trend_bits.append(f"avg readiness {readiness_avg:.1f}")
        if fatigue_avg:
            trend_bits.append(f"avg fatigue {fatigue_avg:.1f}")
        if stress_avg:
            trend_bits.append(f"avg stress {stress_avg:.1f}")
        if trend_bits:
            lines.append("Wellness range averages: " + ", ".join(trend_bits))

        lines.extend(["", "Recent wellness/recovery detail:"])
        for item in sorted_wellness[-7:]:
            bits = []
            for keys, label, digits, suffix in [
                (("hrv", "hrv_rmssd", "rmssd"), "HRV", 1, "ms"),
                (("hrvSDNN",), "SDNN", 1, "ms"),
                (("restingHR", "resting_hr", "restingHeartRate"), "RHR", 0, "bpm"),
                (("sleep_secs", "sleepSeconds", "sleepSecs"), "sleep", 0, ""),
                (("sleep_score", "sleepScore"), "sleep score", 0, ""),
                (("readiness",), "readiness", 1, ""),
                (("fatigue",), "fatigue", 1, ""),
                (("mood",), "mood", 1, ""),
                (("soreness",), "soreness", 1, ""),
                (("stress",), "stress", 1, ""),
                (("injury",), "injury", 1, ""),
            ]:
                value = first_value(item, keys)
                if keys[0] in {"sleep_secs", "sleepSeconds", "sleepSecs"}:
                    sleep = seconds_to_hm(value)
                    if sleep:
                        bits.append(f"{label} {sleep}")
                else:
                    rendered = fmt_optional(item, keys, label, digits, suffix)
                    if rendered:
                        bits.append(rendered)
            if bits:
                lines.append(f"- {wellness_date(item) or 'unknown date'}: " + ", ".join(bits))

        known_wellness_keys = {
            "id", "date", "day", "start_date_local", "weight", "restingHR", "resting_hr", "restingHeartRate",
            "hrv", "hrv_rmssd", "rmssd", "hrvSDNN", "sleep_secs", "sleepSeconds", "sleepSecs", "sleep_score", "sleepScore", "sleepQuality", "avgSleepingHR",
            "fatigue", "form", "ctl", "fitness", "atl", "mood", "motivation", "soreness", "stress",
            "injury", "spO2", "spo2", "bodyBattery", "body_battery", "readiness", "rampRate", "respiration",
            "steps", "hydration", "kcalConsumed", "carbohydrates", "protein", "fatTotal", "vo2max",
        }
        extra = []
        for key, value in latest.items():
            if key not in known_wellness_keys and value not in (None, "", [], {}):
                extra.append(f"{key}: {value}")
        if extra:
            lines.extend(["", "Additional latest wellness fields from Intervals.icu:", "- " + "; ".join(extra[:24])])
    else:
        lines.extend(["", "Wellness/recovery: no wellness records returned for this date range or API key permissions."])

    lines.extend(
        [
            "",
            "Prompt for an AI coach:",
            "Given the completed training, HR response, intensity distribution, best-effort context, fitness/load trend, and recovery data above, identify fatigue risk, likely limiters, signs of improving or worsening fitness, and the most sensible changes for the next 7 days. Keep recommendations conservative, flag missing data, and explain assumptions.",
        ]
    )
    return "\n".join(lines)


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Talaria</title>
  <style>
    :root {
      --bg: #f7f7f4;
      --ink: #20211f;
      --muted: #62665f;
      --line: #deded6;
      --panel: #ffffff;
      --accent: #206f67;
      --accent-2: #bb5a35;
      --danger: #a33b2f;
      --ok: #2d6e46;
      --shadow: 0 18px 44px rgba(32, 33, 31, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background: var(--bg);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    button, input, textarea, select { font: inherit; }
    .app { display: grid; grid-template-columns: 280px 1fr; min-height: 100vh; }
    aside {
      border-right: 1px solid var(--line);
      background: #fcfcfa;
      padding: 28px 22px;
      position: sticky;
      top: 0;
      height: 100vh;
    }
    .brand { display: flex; align-items: center; gap: 12px; margin-bottom: 28px; }
    .mark {
      width: 42px; height: 42px; display: grid; place-items: center;
    }
    .mark img { width: 42px; height: 42px; object-fit: contain; display: block; }
    .brand h1 { font-size: 18px; line-height: 1.2; margin: 0; font-weight: 750; }
    .brand p { margin: 3px 0 0; color: var(--muted); font-size: 13px; }
    nav { display: grid; gap: 8px; }
    .nav-btn {
      border: 1px solid transparent; background: transparent; color: var(--muted);
      border-radius: 8px; padding: 11px 12px; text-align: left; cursor: pointer;
      display: flex; align-items: center; gap: 10px;
    }
    .nav-btn.active { background: #edf3f1; border-color: #c8dbd7; color: var(--accent); }
    .nav-btn svg, .icon-btn svg { width: 18px; height: 18px; stroke-width: 2; }
    main { padding: 32px; max-width: 1180px; width: 100%; }
    section { display: none; }
    section.active { display: block; }
    .topline { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 22px; }
    h2 { margin: 0; font-size: 28px; line-height: 1.15; }
    .lede { color: var(--muted); margin: 8px 0 0; max-width: 760px; line-height: 1.55; }
    .grid { display: grid; gap: 16px; }
    .two { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
    .panel {
      background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
      box-shadow: var(--shadow); padding: 20px;
    }
    label { display: block; font-size: 13px; font-weight: 700; margin-bottom: 7px; }
    input, textarea {
      width: 100%; border: 1px solid #cfcfc7; border-radius: 8px; padding: 11px 12px;
      background: #fff; color: var(--ink); outline: none;
    }
    input:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(32, 111, 103, 0.12); }
    textarea { min-height: 280px; resize: vertical; line-height: 1.45; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
    .row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .spaced { justify-content: space-between; }
    .btn {
      border: 1px solid var(--accent); background: var(--accent); color: white; border-radius: 8px;
      padding: 10px 13px; cursor: pointer; display: inline-flex; align-items: center; gap: 8px;
      font-weight: 700;
    }
    .btn.secondary { background: white; color: var(--accent); }
    .btn.warn { border-color: var(--accent-2); background: var(--accent-2); }
    .btn:disabled { opacity: 0.55; cursor: wait; }
    .status {
      border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px;
      background: #fbfbf8; color: var(--muted); white-space: pre-wrap; line-height: 1.45;
    }
    .status.ok { border-color: #b7d5c1; color: var(--ok); background: #f2faf5; }
    .status.err { border-color: #e3b7af; color: var(--danger); background: #fff6f4; }
    .workouts { display: grid; gap: 9px; max-height: 540px; overflow: auto; padding-right: 4px; }
    .workout {
      display: grid; grid-template-columns: auto 96px 58px 1fr; gap: 12px; align-items: center;
      padding: 11px 12px; border: 1px solid var(--line); border-radius: 8px; background: #fff;
    }
    .workout small { color: var(--muted); }
    .pill { border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; font-size: 12px; color: var(--muted); width: fit-content; }
    .date-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .copy-area { position: relative; }
    .copy-area .copy-btn { position: absolute; top: 10px; right: 10px; }
    .copy-area .reports-btn { position: absolute; right: 10px; bottom: 10px; }
    .note { color: var(--muted); font-size: 13px; line-height: 1.45; }
    @media (max-width: 820px) {
      .app { grid-template-columns: 1fr; }
      aside { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--line); }
      main { padding: 22px; }
      .two { grid-template-columns: 1fr; }
      .workout { grid-template-columns: auto 76px 50px 1fr; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand">
        <div class="mark" aria-hidden="true">
          <img src="/assets/talaria-logo.png" alt="" />
        </div>
        <div>
          <h1>Talaria</h1>
          <p>Upload and read training</p>
        </div>
      </div>
      <nav>
        <button class="nav-btn active" data-view="setup"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.03.03a2 2 0 1 1-2.83 2.83l-.03-.03A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6V20a2 2 0 1 1-4 0v-.04a1.7 1.7 0 0 0-1-.56 1.7 1.7 0 0 0-1.87.34l-.03.03a2 2 0 1 1-2.83-2.83l.03-.03A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1H4a2 2 0 1 1 0-4h.04a1.7 1.7 0 0 0 .56-1 1.7 1.7 0 0 0-.34-1.87l-.03-.03A2 2 0 1 1 7.06 4.27l.03.03A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6V4a2 2 0 1 1 4 0v.04a1.7 1.7 0 0 0 1 .56 1.7 1.7 0 0 0 1.87-.34l.03-.03a2 2 0 1 1 2.83 2.83l-.03.03A1.7 1.7 0 0 0 19.4 9c.22.34.42.68.6 1H20a2 2 0 1 1 0 4h-.04c-.16.35-.35.68-.56 1Z"/></svg>Setup</button>
        <button class="nav-btn" data-view="upload"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M20 16v4H4v-4"/></svg>Upload workouts</button>
        <button class="nav-btn" data-view="progress"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 16v-5"/><path d="M12 16V8"/><path d="M16 16v-9"/></svg>Progress read</button>
      </nav>
    </aside>
    <main>
      <section id="setup" class="active">
        <div class="topline">
          <div>
            <h2>Setup</h2>
            <p class="lede">Paste your Intervals.icu API key. Athlete id can usually stay as 0.</p>
          </div>
        </div>
        <div class="grid two">
          <div class="panel grid">
            <div>
              <label for="apiKey">Intervals.icu API key</label>
              <input id="apiKey" type="text" autocomplete="off" placeholder="Paste API key" />
            </div>
            <div>
              <label for="athleteId">Athlete id</label>
              <input id="athleteId" value="0" />
            </div>
            <div class="row">
              <button class="btn" id="saveConfig"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/></svg>Save</button>
              <button class="btn secondary" id="testKey"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18"><path d="M20 6 9 17l-5-5"/></svg>Test key</button>
            </div>
            <div id="setupStatus" class="status">No API call made yet.</div>
          </div>
          <div class="panel">
            <h3>Where the key lives</h3>
            <p class="note">The app stores settings in <code>~/Library/Application Support/Talaria</code>, so auth stays saved when Talaria moves.</p>
            <p class="note">Required permissions: calendar write for uploads, activity read for progress, wellness read only if you want recovery data included.</p>
          </div>
        </div>
      </section>
      <section id="upload">
        <div class="topline">
          <div>
            <h2>Upload Workouts</h2>
            <p class="lede">Select workouts and upload them as planned workouts. Re-running is safe because each event uses an external id and the API call uses upsert.</p>
          </div>
          <button class="btn warn" id="uploadSelected"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18"><path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M20 16v4H4v-4"/></svg>Upload selected</button>
        </div>
        <div class="panel grid">
          <div class="row spaced">
            <div class="row">
              <button class="btn secondary" id="selectAll">Select all</button>
              <button class="btn secondary" id="selectFuture">Future only</button>
              <button class="btn secondary" id="clearSelection">Clear</button>
              <button class="btn secondary" id="openWorkoutFolder">Open workout folder</button>
            </div>
            <span class="pill" id="workoutCount">0 workouts</span>
          </div>
          <div class="workouts" id="workoutList"></div>
          <div id="uploadStatus" class="status">Ready.</div>
        </div>
      </section>
      <section id="progress">
        <div class="topline">
          <div>
            <h2>Progress Read</h2>
            <p class="lede">Fetch completed activities, HR response, load trends, and optional wellness, then copy the summary into whichever AI coach you want.</p>
          </div>
          <button class="btn" id="fetchProgress"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg>Fetch summary</button>
        </div>
        <div class="grid two">
          <div class="panel grid">
            <div class="date-fields">
              <div>
                <label for="oldest">Oldest</label>
                <input id="oldest" type="date" />
              </div>
              <div>
                <label for="newest">Newest</label>
                <input id="newest" type="date" />
              </div>
            </div>
            <div id="progressStatus" class="status">Ready.</div>
          </div>
          <div class="copy-area">
            <button class="btn secondary copy-btn" id="copySummary">Copy</button>
            <button class="btn secondary reports-btn" id="viewReports">View reports</button>
            <textarea id="summary" placeholder="Progress summary will appear here."></textarea>
          </div>
        </div>
      </section>
    </main>
  </div>
  <script>
    const $ = (id) => document.getElementById(id);
    const state = { workouts: [] };
    const icons = {};

    function setStatus(id, message, kind = "") {
      const el = $(id);
      el.className = "status" + (kind ? " " + kind : "");
      el.textContent = message;
    }

    async function api(path, options = {}) {
      const res = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      const body = await res.json();
      if (!res.ok || body.ok === false) throw new Error(body.error || "Request failed");
      return body;
    }

    function switchView(view) {
      document.querySelectorAll("section").forEach(s => s.classList.toggle("active", s.id === view));
      document.querySelectorAll(".nav-btn").forEach(b => b.classList.toggle("active", b.dataset.view === view));
    }

    function renderWorkouts() {
      $("workoutCount").textContent = `${state.workouts.length} workouts`;
      $("workoutList").innerHTML = state.workouts.map(w => `
        <label class="workout">
          <input type="checkbox" class="workoutCheck" value="${w.id}" checked />
          <small>${w.date}</small>
          <span class="pill">${w.type}</span>
          <span>${w.name}</span>
        </label>
      `).join("");
    }

    function selectedWorkoutIds() {
      return [...document.querySelectorAll(".workoutCheck:checked")].map(el => el.value);
    }

    async function loadInitial() {
      const config = await api("/api/config");
      $("athleteId").value = config.athlete_id || "0";
      $("apiKey").value = config.api_key || "";
      $("apiKey").placeholder = config.has_api_key ? "Saved API key present" : "Paste API key";
      state.workouts = (await api("/api/workouts")).workouts;
      renderWorkouts();
      const today = new Date();
      const oldest = new Date(today.getTime() - 7 * 86400000);
      const newest = today;
      $("oldest").value = oldest.toISOString().slice(0, 10);
      $("newest").value = newest.toISOString().slice(0, 10);
    }

    document.querySelectorAll(".nav-btn").forEach(btn => btn.addEventListener("click", () => switchView(btn.dataset.view)));

    $("saveConfig").addEventListener("click", async () => {
      try {
        await api("/api/config", {
          method: "POST",
          body: JSON.stringify({ api_key: $("apiKey").value, athlete_id: $("athleteId").value || "0" }),
        });
        $("apiKey").placeholder = "Saved API key present";
        setStatus("setupStatus", "Saved locally.", "ok");
      } catch (err) {
        setStatus("setupStatus", err.message, "err");
      }
    });

    $("testKey").addEventListener("click", async () => {
      try {
        setStatus("setupStatus", "Testing API key...");
        const result = await api("/api/test", { method: "POST" });
        setStatus("setupStatus", result.message, "ok");
      } catch (err) {
        setStatus("setupStatus", err.message, "err");
      }
    });

    $("selectAll").addEventListener("click", () => document.querySelectorAll(".workoutCheck").forEach(c => c.checked = true));
    $("clearSelection").addEventListener("click", () => document.querySelectorAll(".workoutCheck").forEach(c => c.checked = false));
    $("openWorkoutFolder").addEventListener("click", async () => {
      try {
        const result = await api("/api/open-workout-folder", { method: "POST" });
        setStatus("uploadStatus", result.message, "ok");
      } catch (err) {
        setStatus("uploadStatus", err.message, "err");
      }
    });
    $("selectFuture").addEventListener("click", () => {
      const today = new Date().toISOString().slice(0, 10);
      document.querySelectorAll(".workoutCheck").forEach(c => {
        const workout = state.workouts.find(w => w.id === c.value);
        c.checked = workout && workout.date >= today;
      });
    });

    $("uploadSelected").addEventListener("click", async () => {
      try {
        const ids = selectedWorkoutIds();
        if (!ids.length) throw new Error("Select at least one workout.");
        setStatus("uploadStatus", `Uploading ${ids.length} workouts...`);
        const result = await api("/api/upload", { method: "POST", body: JSON.stringify({ ids }) });
        setStatus("uploadStatus", result.message, "ok");
      } catch (err) {
        setStatus("uploadStatus", err.message, "err");
      }
    });

    $("fetchProgress").addEventListener("click", async () => {
      try {
        setStatus("progressStatus", "Fetching Intervals.icu data...");
        const params = new URLSearchParams({ oldest: $("oldest").value, newest: $("newest").value });
        const result = await api("/api/progress?" + params.toString());
        $("summary").value = result.summary;
        let message = result.message;
        if (result.needs_markdown_choice) {
          const shouldSave = window.confirm(
            `Talaria fetched ${result.activity_count} completed activities. Do you want to also save the full summary as a Markdown file?`
          );
          if (shouldSave) {
            const saved = await api("/api/save-report", {
              method: "POST",
              body: JSON.stringify({ summary: result.summary, oldest: $("oldest").value, newest: $("newest").value }),
            });
            message += " " + saved.message;
          } else {
            message += " Markdown save skipped; the text summary is still shown here.";
          }
        }
        setStatus("progressStatus", message, "ok");
      } catch (err) {
        setStatus("progressStatus", err.message, "err");
      }
    });

    $("copySummary").addEventListener("click", async () => {
      await navigator.clipboard.writeText($("summary").value);
      setStatus("progressStatus", "Copied summary to clipboard.", "ok");
    });

    $("viewReports").addEventListener("click", async () => {
      try {
        const result = await api("/api/open-reports", { method: "POST" });
        setStatus("progressStatus", result.message, "ok");
      } catch (err) {
        setStatus("progressStatus", err.message, "err");
      }
    });

    loadInitial().catch(err => setStatus("setupStatus", err.message, "err"));
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                raw = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            elif parsed.path == "/assets/talaria-logo.png":
                logo_path = ROOT / "assets" / "talaria-logo.png"
                raw = logo_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            elif parsed.path == "/api/config":
                config = load_config()
                self.send_json(
                    {
                        "ok": True,
                        "athlete_id": config.get("athlete_id", "0"),
                        "api_key": config.get("api_key", ""),
                        "has_api_key": bool(config.get("api_key")),
                    }
                )
            elif parsed.path == "/api/workouts":
                public = [
                    {key: workout[key] for key in ("id", "date", "type", "name", "filename")}
                    for workout in workout_files()
                ]
                self.send_json({"ok": True, "workouts": public})
            elif parsed.path == "/api/progress":
                config = load_config()
                query = urllib.parse.parse_qs(parsed.query)
                today = date.today()
                oldest = query.get("oldest", [(today - timedelta(days=7)).isoformat()])[0]
                newest = query.get("newest", [today.isoformat()])[0]
                athlete_id = config.get("athlete_id", "0") or "0"
                api_key = config.get("api_key", "")
                params = {"oldest": oldest, "newest": newest}
                activities = intervals_request("GET", f"/athlete/{athlete_id}/activities", api_key, query=params) or []
                events = []
                try:
                    wellness = intervals_request("GET", f"/athlete/{athlete_id}/wellness", api_key, query=params) or []
                except Exception:
                    wellness = []
                activity_enrichment = fetch_activity_enrichment(activities, api_key)
                fitness_events = fetch_fitness_model_events(athlete_id, api_key)
                curve_context = fetch_athlete_curve_context(athlete_id, api_key, oldest, newest)
                summary = build_progress_summary(
                    activities,
                    events,
                    wellness,
                    oldest,
                    newest,
                    activity_enrichment=activity_enrichment,
                    fitness_events=fitness_events,
                    curve_context=curve_context,
                )
                message = (
                    f"Fetched {len(activities)} activities, "
                    f"{len(wellness)} wellness records, {len(fitness_events)} fitness/load events."
                )
                self.send_json(
                    {
                        "ok": True,
                        "message": message,
                        "summary": summary,
                        "activity_count": len(activities),
                        "needs_markdown_choice": len(activities) > 25,
                    }
                )
            else:
                self.send_json({"ok": False, "error": "Not found"}, 404)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 500)

    def do_POST(self) -> None:
        try:
            if self.path == "/api/config":
                body = self.read_json()
                update: dict[str, Any] = {"athlete_id": str(body.get("athlete_id") or "0")}
                if body.get("api_key"):
                    update["api_key"] = str(body["api_key"]).strip()
                save_config(update)
                self.send_json({"ok": True})
            elif self.path == "/api/test":
                config = load_config()
                athlete_id = config.get("athlete_id", "0") or "0"
                intervals_request("GET", f"/athlete/{athlete_id}/activities", config.get("api_key", ""), query={"oldest": date.today().isoformat(), "newest": date.today().isoformat()})
                self.send_json({"ok": True, "message": "API key works. Activity read succeeded."})
            elif self.path == "/api/upload":
                config = load_config()
                body = self.read_json()
                ids = body.get("ids") or []
                if not isinstance(ids, list):
                    raise ValueError("Expected ids to be a list.")
                events = selected_events([str(item) for item in ids])
                if not events:
                    raise ValueError("No matching workouts selected.")
                athlete_id = config.get("athlete_id", "0") or "0"
                response = intervals_request(
                    "POST",
                    f"/athlete/{athlete_id}/events/bulk",
                    config.get("api_key", ""),
                    body=events,
                    query={"upsert": "true"},
                )
                count = len(response) if isinstance(response, list) else len(events)
                self.send_json({"ok": True, "message": f"Uploaded or updated {count} planned workouts."})
            elif self.path == "/api/save-report":
                body = self.read_json()
                summary = str(body.get("summary") or "")
                oldest = str(body.get("oldest") or date.today().isoformat())
                newest = str(body.get("newest") or date.today().isoformat())
                if not summary.strip():
                    raise ValueError("No summary text supplied.")
                path = save_markdown_report(summary, oldest, newest)
                self.send_json({"ok": True, "message": f"Markdown report saved to {path}."})
            elif self.path == "/api/open-reports":
                path = open_reports_folder()
                self.send_json({"ok": True, "message": f"Opened reports folder: {path}."})
            elif self.path == "/api/open-workout-folder":
                path = open_workout_folder()
                self.send_json({"ok": True, "message": f"Opened workout folder: {path}."})
            else:
                self.send_json({"ok": False, "error": "Not found"}, 404)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 500)


def main() -> None:
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    else:
        port = 8765
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Talaria is running at {url}")
    print("Press Ctrl+C to stop.")
    if os.environ.get("TALARIA_OPEN_BROWSER") == "1":
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
