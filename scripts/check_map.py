"""验证高德 Web Key 和基础地点/路线服务，不打印密钥。"""
from app.services.map_service import _poi, _route
from app.config import settings


def main() -> None:
    if not settings.amap_web_key:
        print("未配置 AMAP_WEB_KEY")
        return
    first = _poi("西湖风景名胜区", "杭州")
    second = _poi("灵隐寺", "杭州")
    print(f"地点匹配：{bool(first)}/{bool(second)}")
    if first and second:
        route = _route(first, second)
        print(f"交通路线：{route or '未核验'}")


if __name__ == "__main__":
    main()
