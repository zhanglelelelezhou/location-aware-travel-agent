from __future__ import annotations

import math
from typing import Any

import httpx

from travel_agent.tools.poi import PoiItem, PoiSearchResult

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"

CATEGORY_FILTERS = {
    "restaurant": ("amenity", "restaurant"),
    "cafe": ("amenity", "cafe"),
    "museum": ("tourism", "museum"),
    "attraction": ("tourism", "attraction"),
    "park": ("leisure", "park"),
    "place_of_worship": ("amenity", "place_of_worship"),
}
DEFAULT_CATEGORIES = ["restaurant", "cafe", "museum", "attraction", "park"]


class PoiToolError(RuntimeError):
    """Normalized boundary error for the POI provider."""


class OverpassPoiSearchTool:
    name = "search_poi"
    description = "Search nearby named places using OpenStreetMap Overpass."

    def __init__(
        self,
        *,
        timeout_seconds: float = 12.0,
        client: httpx.Client | None = None,
        endpoint: str = OVERPASS_URL,
    ) -> None:
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.endpoint = endpoint

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        location = arguments.get("location")
        if not isinstance(location, str) or not location.strip():
            raise ValueError("search_poi requires a non-empty location")
        latitude = _coordinate(arguments.get("latitude"), "latitude", -90, 90)
        longitude = _coordinate(arguments.get("longitude"), "longitude", -180, 180)
        radius_m = _bounded_int(arguments.get("radius_m", 1500), "radius_m", 100, 5000)
        limit = _bounded_int(arguments.get("limit", 5), "limit", 1, 10)
        categories = _categories(arguments.get("categories"))
        preferences = _strings(arguments.get("preferences"))
        required_diets, unverified_preferences = _preference_constraints(preferences)

        query = build_overpass_query(
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            categories=categories,
        )
        payload = self._post_query(query)
        elements = payload.get("elements")
        if not isinstance(elements, list):
            raise PoiToolError("POI provider returned no elements array")

        results: list[PoiItem] = []
        for element in elements:
            item = _parse_element(
                element,
                origin_latitude=latitude,
                origin_longitude=longitude,
                required_diets=required_diets,
            )
            if item is not None:
                results.append(item)
        results.sort(key=lambda item: item.distance_m)

        output = PoiSearchResult(
            location=location.strip(),
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            provider="openstreetmap-overpass",
            attribution=OSM_ATTRIBUTION,
            verified_preferences=[label for _, label in required_diets],
            unverified_preferences=unverified_preferences,
            results=results[:limit],
        )
        return output.model_dump()

    def _post_query(self, query: str) -> dict[str, Any]:
        try:
            response = self.client.post(
                self.endpoint,
                data={"data": query},
                headers={"User-Agent": "location-aware-travel-agent/0.1"},
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PoiToolError("POI provider timed out") from exc
        except httpx.HTTPError as exc:
            raise PoiToolError("POI provider request failed") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise PoiToolError("POI provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise PoiToolError("POI provider returned an invalid payload")
        return payload


def build_overpass_query(
    *, latitude: float, longitude: float, radius_m: int, categories: list[str]
) -> str:
    selectors = []
    for category in categories:
        key, value = CATEGORY_FILTERS[category]
        selectors.append(
            f'nwr(around:{radius_m},{latitude:.6f},{longitude:.6f})'
            f'["{key}"="{value}"]["name"];'
        )
    return "[out:json][timeout:10];(" + "".join(selectors) + ");out center tags 60;"


def _categories(value: object) -> list[str]:
    if value is None:
        return list(DEFAULT_CATEGORIES)
    if not isinstance(value, list) or not value:
        raise ValueError("categories must be a non-empty list")
    categories = []
    for item in value:
        if not isinstance(item, str) or item not in CATEGORY_FILTERS:
            raise ValueError(f"unsupported POI category: {item}")
        if item not in categories:
            categories.append(item)
    return categories


def _strings(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("preferences must be a list of strings")
    return value


def _coordinate(value: object, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"search_poi requires numeric {field}")
    coordinate = float(value)
    if not minimum <= coordinate <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return coordinate


def _bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")
    return value


def _preference_constraints(
    preferences: list[str],
) -> tuple[list[tuple[str, str]], list[str]]:
    mappings = [
        (("纯素", "vegan"), "diet:vegan", "vegan"),
        (
            ("素食", "不含肉", "无肉", "vegetarian", "meat-free", "no meat"),
            "diet:vegetarian",
            "vegetarian",
        ),
        (("清真", "halal"), "diet:halal", "halal"),
        (("无麸质", "gluten-free", "gluten free"), "diet:gluten_free", "gluten-free"),
    ]
    required: list[tuple[str, str]] = []
    unverified: list[str] = []
    for preference in preferences:
        normalized = preference.casefold()
        matched = next(
            (
                (tag, label)
                for keywords, tag, label in mappings
                if any(keyword in normalized for keyword in keywords)
            ),
            None,
        )
        if matched is None:
            unverified.append(preference)
        elif matched not in required:
            required.append(matched)
    return required, unverified


def _parse_element(
    element: object,
    *,
    origin_latitude: float,
    origin_longitude: float,
    required_diets: list[tuple[str, str]],
) -> PoiItem | None:
    if not isinstance(element, dict):
        return None
    tags = element.get("tags")
    if not isinstance(tags, dict):
        return None
    name = tags.get("name:zh") or tags.get("name:en") or tags.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    coordinates = _element_coordinates(element)
    if coordinates is None:
        return None
    latitude, longitude = coordinates

    supports = [
        label
        for tag, label in _all_diet_tags()
        if str(tags.get(tag, "")).casefold() in {"yes", "only"}
    ]
    if required_diets and not all(
        str(tags.get(tag, "")).casefold() in {"yes", "only"}
        for tag, _ in required_diets
    ):
        return None

    distance_m = round(
        _haversine_m(origin_latitude, origin_longitude, latitude, longitude)
    )
    element_type = str(element.get("type") or "node")
    element_id = str(element.get("id") or "unknown")
    return PoiItem(
        id=f"{element_type}/{element_id}",
        name=name.strip(),
        category=_element_category(tags),
        distance_m=distance_m,
        walking_minutes=max(1, round(distance_m / 80)),
        supports=supports,
        source=f"https://www.openstreetmap.org/{element_type}/{element_id}",
    )


def _all_diet_tags() -> list[tuple[str, str]]:
    return [
        ("diet:vegan", "vegan"),
        ("diet:vegetarian", "vegetarian"),
        ("diet:halal", "halal"),
        ("diet:gluten_free", "gluten-free"),
    ]


def _element_coordinates(element: dict[str, Any]) -> tuple[float, float] | None:
    latitude = element.get("lat")
    longitude = element.get("lon")
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        center = element.get("center")
        if not isinstance(center, dict):
            return None
        latitude = center.get("lat")
        longitude = center.get("lon")
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return None
    return float(latitude), float(longitude)


def _element_category(tags: dict[str, Any]) -> str:
    for key in ("amenity", "tourism", "leisure"):
        value = tags.get(key)
        if isinstance(value, str) and value:
            return value
    return "place"


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return earth_radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
