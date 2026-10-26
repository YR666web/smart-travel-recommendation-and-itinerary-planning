"""用高德 Web 服务核对结构化行程；没有 Key 时明确返回未核验。"""
from __future__ import annotations

import math
import re
from typing import Any

import requests

from app.config import settings

AMAP_BASE = "https://restapi.amap.com/v5"
MAX_STOPS = 21
PROVINCES = {"北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
             "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东",
             "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾", "内蒙古",
             "广西", "西藏", "宁夏", "新疆", "香港", "澳门"}


def _api_get(path: str, params: dict[str, str]) -> dict[str, Any] | None:
    try:
        response = requests.get(f"{AMAP_BASE}{path}",
                                params={**params, "key": settings.amap_web_key}, timeout=5)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) and payload.get("status") == "1" else None
    except (requests.RequestException, ValueError):
        return None


def _name_key(value: str) -> str:
    return re.sub(r"[\s·•（）()\-—]", "", value).lower()


def _poi(name: str, city: str) -> dict[str, Any] | None:
    region = city.removesuffix("省").removesuffix("市")
    province_level = region in PROVINCES
    payload = _api_get("/place/text", {"keywords": name[:80], "region": city,
                                       "city_limit": "false" if province_level else "true", "page_size": "5",
                                       "show_fields": "business"})
    if not payload:
        return None
    target = _name_key(name)
    for item in payload.get("pois", []):
        candidate = _name_key(str(item.get("name", ""))).removeprefix(_name_key(region))
        location = str(item.get("location", ""))
        cityname = str(item.get("cityname", ""))
        pname = str(item.get("pname", ""))
        # 村落在地图中常以牌坊/游客中心作为可导航入口；保留实际匹配名供前端辨认。
        known_suffixes = {"景区", "风景区", "风景名胜区", "公园", "博物馆", "牌坊", "游客中心"}
        scenic_prefixes = ("景区", "风景名胜区", "公园", "博物馆")
        name_matches = (candidate == target
                        or (candidate.startswith(target) and candidate[len(target):] in known_suffixes)
                        or (candidate.endswith(target) and candidate[:-len(target)].endswith(scenic_prefixes)))
        if name_matches \
                and region in (pname if province_level else cityname) \
                and re.fullmatch(r"\d{2,3}\.\d+,-?\d{1,2}\.\d+", location):
            business = item.get("business")
            return {"name": item["name"], "poi_id": item.get("id"),
                    "location": location, "address": item.get("address") or "",
                    "citycode": item.get("citycode") or "",
                    "opening_hours_today": business.get("opentime_today") if isinstance(business, dict) else None}
    return None


def _route(origin: dict, destination: dict) -> dict[str, Any] | None:
    lon1, lat1 = map(float, origin["location"].split(","))
    lon2, lat2 = map(float, destination["location"].split(","))
    # 近距离优先步行；远距离用公交/地铁耗时，避免拿驾车时间冒充公共交通。
    km = 111 * math.hypot(lat2 - lat1, (lon2 - lon1) * math.cos(math.radians(lat1)))
    mode = "walking" if km <= 1.5 else "transit"
    params = {"origin": origin["location"], "destination": destination["location"],
              "show_fields": "cost"}
    if mode == "transit":
        if not origin["citycode"] or not destination["citycode"]:
            return None
        params.update(city1=origin["citycode"], city2=destination["citycode"],
                      AlternativeRoute="1")
    else:
        if origin.get("poi_id") and destination.get("poi_id"):
            params.update(origin_id=origin["poi_id"], destination_id=destination["poi_id"])
    path = "/direction/walking" if mode == "walking" else "/direction/transit/integrated"
    payload = _api_get(path, params)
    if not payload:
        return None
    choices = payload.get("route", {}).get("paths" if mode == "walking" else "transits") or []
    if not choices:
        return None
    try:
        seconds = int(float(choices[0]["cost"]["duration"]))
        distance = int(float(choices[0]["distance"]))
    except (KeyError, TypeError, ValueError):
        return None
    return {"mode": mode, "minutes": math.ceil(seconds / 60), "distance_m": distance}


def check_itinerary(city: str, days: list[Any]) -> dict[str, Any]:
    """核验地点和相邻路段。无法核验的路段不作为零分钟计入可行结论。"""
    if not settings.amap_web_key:
        return {"status": "unavailable", "message": "未配置高德 Web 服务 Key，地点与交通耗时尚未核验。",
                "days": [], "issues": []}
    stop_count = sum(len(day.places) for day in days)
    if stop_count > MAX_STOPS:
        return {"status": "unavailable", "message": "地点数量超过地图核验上限。", "days": [], "issues": []}
    poi_cache: dict[str, dict | None] = {}
    route_cache: dict[tuple[str, str], dict | None] = {}
    checked_days = []
    issues = []
    unresolved = False
    for day in days:
        places = []
        for stop in day.places:
            if stop.name not in poi_cache:
                poi_cache[stop.name] = _poi(stop.name, city)
            poi = poi_cache[stop.name]
            places.append({"period": stop.period, "requested_name": stop.name,
                           "visit_minutes": stop.visit_minutes, "matched": bool(poi),
                           "poi": poi})
            if not poi:
                unresolved = True
                issues.append(f"第{day.day}天「{stop.name}」未匹配到{city}的可靠地点。")
        legs = []
        travel_minutes = 0
        for left, right in zip(places, places[1:]):
            route = None
            if left["poi"] and right["poi"]:
                pair = (left["poi"]["location"], right["poi"]["location"])
                if pair not in route_cache:
                    route_cache[pair] = _route(left["poi"], right["poi"])
                route = route_cache[pair]
            if route:
                travel_minutes += route["minutes"]
                if route["minutes"] > 90:
                    issues.append(f"第{day.day}天「{left['requested_name']}→{right['requested_name']}」约{route['minutes']}分钟，建议调整顺序或拆到不同天。")
            else:
                unresolved = True
                issues.append(f"第{day.day}天「{left['requested_name']}→{right['requested_name']}」交通耗时未核验。")
            legs.append({"from": left["requested_name"], "to": right["requested_name"],
                         "route": route})
        total = sum(p["visit_minutes"] for p in places) + travel_minutes
        if total > 540:
            issues.append(f"第{day.day}天游览加交通约{total}分钟，超过每日9小时建议上限。")
        checked_days.append({"day": day.day, "places": places, "legs": legs,
                             "known_minutes": total, "all_routes_checked": all(leg["route"] for leg in legs)})
    status = "partial" if unresolved else "warning" if issues else "checked"
    return {"status": status, "message": "地图核验完成" if status == "checked" else "行程存在需核实或调整的地点与路段",
            "days": checked_days, "issues": issues}
