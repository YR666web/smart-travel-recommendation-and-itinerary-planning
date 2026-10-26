"""地图核验的匹配、安全降级与路段检查。"""
from types import SimpleNamespace

from app.services import map_service


def _day(*names):
    return SimpleNamespace(day=1, places=[SimpleNamespace(name=name, period="morning",
                                                         visit_minutes=90) for name in names])


def test_without_key_is_explicitly_unverified(monkeypatch):
    monkeypatch.setattr(map_service.settings, "amap_web_key", "")
    result = map_service.check_itinerary("杭州", [_day("西湖")])
    assert result["status"] == "unavailable"
    assert result["days"] == []


def test_poi_rejects_wrong_city_and_loose_name(monkeypatch):
    monkeypatch.setattr(map_service, "_api_get", lambda path, params: {"pois": [
        {"name": "西湖", "cityname": "福州市", "location": "119.30,26.08"},
        {"name": "西湖酒店", "cityname": "杭州市", "location": "120.15,30.25"}]})
    assert map_service._poi("西湖", "杭州") is None


def test_province_destination_accepts_poi_in_its_city(monkeypatch):
    def fake_api(path, params):
        assert params["city_limit"] == "false"
        return {"pois": [{"name": "洱海", "pname": "云南省", "cityname": "大理白族自治州",
                          "location": "100.220000,25.780000", "citycode": "0872"}]}
    monkeypatch.setattr(map_service, "_api_get", fake_api)
    assert map_service._poi("洱海", "云南")["name"] == "洱海"


def test_village_can_use_named_entrance_but_not_bus_stop(monkeypatch):
    monkeypatch.setattr(map_service, "_api_get", lambda path, params: {"pois": [
        {"name": "龙井村(公交站)", "cityname": "杭州市", "location": "120.100000,30.200000"},
        {"name": "龙井村牌坊", "cityname": "杭州市", "location": "120.100001,30.200001"}]})
    assert map_service._poi("龙井村", "杭州")["name"] == "龙井村牌坊"


def test_poi_does_not_match_hotel_with_attraction_in_its_name(monkeypatch):
    monkeypatch.setattr(map_service, "_api_get", lambda path, params: {"pois": [
        {"name": "杭州印·西湖公寓(西湖音乐喷泉店)(暂停营业)", "cityname": "杭州市",
         "location": "120.100000,30.200000", "typecode": "100000"}]})
    assert map_service._poi("西湖音乐喷泉", "杭州") is None


def test_checks_transit_leg_and_warns_when_too_long(monkeypatch):
    monkeypatch.setattr(map_service.settings, "amap_web_key", "test-key")

    def fake_api(path, params):
        if path == "/place/text":
            name = params["keywords"]
            return {"pois": [{"name": name, "id": name, "cityname": "杭州市",
                              "citycode": "0571", "location": "120.150000,30.250000" if name == "西湖" else "120.250000,30.350000",
                              "address": "测试地址"}]}
        assert path == "/direction/transit/integrated"
        assert params["city1"] == "0571"
        return {"route": {"transits": [{"distance": "16000", "cost": {"duration": "6000"}}]}}

    monkeypatch.setattr(map_service, "_api_get", fake_api)
    result = map_service.check_itinerary("杭州", [_day("西湖", "灵隐寺")])
    assert result["status"] == "warning"
    assert result["days"][0]["legs"][0]["route"]["minutes"] == 100
    assert any("建议调整顺序" in issue for issue in result["issues"])


def test_route_failure_cannot_be_counted_as_zero_minutes(monkeypatch):
    monkeypatch.setattr(map_service.settings, "amap_web_key", "test-key")
    monkeypatch.setattr(map_service, "_poi", lambda name, city: {
        "name": name, "location": "120.150000,30.250000", "citycode": "0571"})
    monkeypatch.setattr(map_service, "_route", lambda origin, destination: None)
    result = map_service.check_itinerary("杭州", [_day("西湖", "灵隐寺")])
    assert result["status"] == "partial"
    assert result["days"][0]["all_routes_checked"] is False
    assert any("交通耗时未核验" in issue for issue in result["issues"])
