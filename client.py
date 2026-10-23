"""高德与 OpenWeather 天气接口。不依赖主仓库。"""
import logging
import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

from .errors import report_error

logger = logging.getLogger(__name__)
load_dotenv()

WEATHER_API_PROVIDER = os.getenv("WEATHER_API_PROVIDER", "amap")


def is_coordinates(location: dict) -> Tuple[bool, Optional[float], Optional[float]]:
    """判断 location 是否包含合法经纬度。"""
    try:
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if type(latitude) == str:
            latitude = float(latitude)
        if type(longitude) == str:
            longitude = float(longitude)
        if latitude and longitude:
            if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                return True, latitude, longitude
            else:
                return False, None, None
        else:
            return False, None, None
    except (ValueError, AttributeError):
        return False, None, None


def get_amap_adcode_by_coordinates(latitude: float, longitude: float) -> Optional[str]:
    """通过经纬度获取高德地图的 adcode（逆地理编码）。"""
    try:
        api_key = os.getenv("AMAP_API_KEY")
        if not api_key:
            logger.error("未配置高德API密钥")
            return None

        url = "https://restapi.amap.com/v3/geocode/regeo"
        params = {
            "key": api_key,
            "location": f"{longitude},{latitude}",
            "extensions": "base",
        }

        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "1" and data.get("regeocode"):
            adcode = data["regeocode"].get("addressComponent", {}).get("adcode")
            city = data["regeocode"].get("addressComponent", {}).get("city")
            if not city:
                city = data["regeocode"].get("addressComponent", {}).get("province")
            logger.info(f"坐标 ({latitude},{longitude}) 对应城市: {city}, adcode: {adcode}")
            if len(adcode) > 0:
                return adcode
            else:
                baseurl = "https://restapi.amap.com/v3/assistant/coordinate/convert?parameters"
                params = {
                    "key": api_key,
                    "locations": f"{longitude},{latitude}",
                }
                response = requests.get(baseurl, params=params, timeout=5)
                response.raise_for_status()
                data = response.json()
                locations = data.get("locations")
                if locations:
                    params = {
                        "key": api_key,
                        "location": locations,
                        "extensions": "base",
                    }
                    response = requests.get(url, params=params, timeout=5)
                    response.raise_for_status()
                    data = response.json()
                    print("坐标转换再次查询：", data)
                    if data.get("status") == "1" and data.get("regeocode"):
                        adcode = data["regeocode"].get("addressComponent", {}).get("adcode")
                        city = data["regeocode"].get("addressComponent", {}).get("city")
                        if not city:
                            city = data["regeocode"].get("addressComponent", {}).get("province")
                            print("城市：", city)
                        logger.info(f"坐标 ({latitude},{longitude}) 对应城市: {city}, adcode: {adcode}")
                        if len(adcode) > 0:
                            return adcode
                else:
                    return None
        else:
            logger.warning(f"未找到坐标 ({latitude},{longitude}) 的adcode")
            return None

    except Exception as e:
        report_error(29001, "get adcode by coordinates failed", e)
        return None


def get_amap_adcode(city_name: str) -> Optional[str]:
    """通过城市名称获取高德地图的 adcode。"""
    try:
        api_key = os.getenv("AMAP_API_KEY")
        if not api_key:
            logger.error("未配置高德API密钥")
            return None

        url = "https://restapi.amap.com/v3/geocode/geo"
        params = {
            "key": api_key,
            "address": city_name,
            "city": city_name,
        }

        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "1" and data.get("geocodes"):
            adcode = data["geocodes"][0].get("adcode")
            logger.info(f"城市 '{city_name}' 的adcode: {adcode}")
            return adcode
        else:
            logger.warning(f"未找到城市 '{city_name}' 的adcode")
            return None

    except Exception as e:
        report_error(29002, "get adcode by city name failed", e)
        return None


def get_amap_weather_forecast(location: dict) -> str:
    """获取天气预报（高德，未来几天）。"""
    try:
        api_key = os.getenv("AMAP_API_KEY")
        if not api_key:
            return "错误：未配置高德API密钥，请在.env文件中设置 AMAP_API_KEY"

        is_coords, lat, lon = is_coordinates(location)

        if is_coords:
            logger.info(f"使用经纬度查询天气: {lat}, {lon}")
            adcode = get_amap_adcode_by_coordinates(lat, lon)
        else:
            logger.info(f"使用城市名查询天气: {location}")
            adcode = get_amap_adcode(location.get("city"))

        if not adcode:
            return f"错误：无法找到位置 '{location}'，请确认城市名称或坐标是否正确"

        url = "https://restapi.amap.com/v3/weather/weatherInfo"
        params = {
            "key": api_key,
            "city": adcode,
            "extensions": "all",
        }

        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "1":
            return f"错误：获取天气信息失败 - {data.get('info', '未知错误')}"

        forecasts = data.get("forecasts", [])
        if not forecasts:
            return f"{location} 暂无天气预报数据"

        forecast_data = forecasts[0]
        city_name = forecast_data.get("city", location)
        casts = forecast_data.get("casts", [])

        if not casts:
            return f"{city_name} 暂无详细预报数据"

        result = f"📍 {city_name} 天气预报\n"
        result += f"🕐 更新时间：{forecast_data.get('reporttime', '未知')}\n\n"
        print(f"casts\n:{casts}", flush=True)
        for cast in casts[:7]:
            result += f"📅 日期：{cast.get('date', '未知')} ({cast.get('week', '未知')})\n"
            result += f"🌅 白天：{cast.get('dayweather', '未知')} | 温度：{cast.get('daytemp', '未知')}°C | 风向：{cast.get('daywind', '未知')} {cast.get('daypower', '未知')}级\n"
            result += f"🌙 夜间：{cast.get('nightweather', '未知')} | 温度：{cast.get('nighttemp', '未知')}°C | 风向：{cast.get('nightwind', '未知')} {cast.get('nightpower', '未知')}级\n\n"

        return result

    except requests.exceptions.RequestException as e:
        report_error(29003, "amap weather forecast network request failed", e)
        return "错误：网络请求失败"
    except Exception as e:
        report_error(29004, "error processing amap weather forecast data", e)
        return "错误：处理天气数据时出错"


def get_amap_current_weather(location: dict) -> str:
    """获取当前实时天气（高德）。"""
    try:
        api_key = os.getenv("AMAP_API_KEY")
        if not api_key:
            return "错误：未配置高德API密钥，请在.env文件中设置 AMAP_API_KEY"

        is_coords, lat, lon = is_coordinates(location)

        if is_coords:
            logger.info(f"使用经纬度查询实时天气: {lat}, {lon}")
            adcode = get_amap_adcode_by_coordinates(lat, lon)
        else:
            logger.info(f"使用城市名查询实时天气: {location}")
            adcode = get_amap_adcode(location.get("city"))

        if not adcode:
            return f"错误：无法找到位置 '{location}'，请确认城市名称或坐标是否正确"

        url = "https://restapi.amap.com/v3/weather/weatherInfo"
        params = {
            "key": api_key,
            "city": adcode,
            "extensions": "base",
        }

        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "1":
            return f"错误：获取天气信息失败 - {data.get('info', '未知错误')}"

        lives = data.get("lives", [])
        if not lives:
            return f"{location} 暂无实时天气数据"

        live = lives[0]
        city_name = live.get("city", location)

        result = f"📍 {city_name} 实时天气\n\n"
        result += f"🕐 更新时间：{live.get('reporttime', '未知')}\n"
        result += f"☁️  天气：{live.get('weather', '未知')}\n"
        result += f"🌡️  温度：{live.get('temperature', '未知')}°C\n"
        result += f"💨 风向：{live.get('winddirection', '未知')}风\n"
        result += f"💨 风力：{live.get('windpower', '未知')}级\n"
        result += f"💧 湿度：{live.get('humidity', '未知')}%\n"

        return result

    except requests.exceptions.RequestException as e:
        report_error(29005, "amap realtime weather network request failed", e)
        return "错误：网络请求失败"
    except Exception as e:
        report_error(29006, "error processing amap realtime weather data", e)
        return "错误：处理天气数据时出错"


def get_weather_forecast(location: dict) -> str:
    """获取天气预报（OpenWeather）。"""
    try:
        api_key = os.getenv("OPENWEATHER_API_KEY")
        if not api_key:
            return "错误：未配置天气API密钥，请在.env文件中设置 OPENWEATHER_API_KEY"

        base_url = "https://api.openweathermap.org/data/2.5"
        city_name = location.get("city")
        if location.get("latitude") and location.get("longitude"):
            params = {
                "lat": location.get("latitude"),
                "lon": location.get("longitude"),
                "appid": api_key,
                "units": "metric",
                "lang": "zh_cn",
            }
        else:
            city_url = "https://api.openweathermap.org/geo/1.0/direct"
            city_query = location.get("city")
            if location.get("country") == "中国":
                city_query = city_query + ",CN"
            city_param = {
                "q": city_query,
                "appid": api_key,
            }
            city_response = requests.get(city_url, params=city_param)
            city_response.raise_for_status()
            city_data = city_response.json()

            if not city_data:
                return f"错误：无法找到城市 '{location}'，请确认城市名称是否正确"

            city_name = city_data[0]["name"].split(" ")[0]
            logger.info(f"city_name:{city_name}")
            params = {
                "q": city_name,
                "appid": api_key,
                "units": "metric",
                "lang": "zh_cn",
            }

        response = requests.get(f"{base_url}/forecast", params=params)
        response.raise_for_status()
        data = response.json()

        forecast_list = data.get("list", [])
        if not forecast_list:
            return f"{city_name} 暂无天气预报数据"

        daily_forecast = process_weather_forecast(forecast_list)

        if not daily_forecast:
            return f"{city_name} 处理天气预报数据失败"

        result = f"{city_name} 天气预报：\n\n"
        for day_weather in daily_forecast[:7]:
            result += f"📅 日期：{day_weather['date']}\n"
            result += f"🌡️  温度：{day_weather['temp_min']}°C ~ {day_weather['temp_max']}°C\n"
            result += f"☁️  天气：{day_weather['condition']}\n"
            result += f"💧 湿度：{day_weather['humidity']}%\n"
            result += f"💨 风速：{day_weather['wind_speed']} m/s\n"
            result += f"👁️  能见度：{day_weather['visibility']} m\n\n"

        return result

    except requests.exceptions.RequestException as e:
        report_error(29007, "OpenWeather forecast request failed", e)
        return "错误：获取天气信息失败"
    except Exception as e:
        report_error(29008, "error processing OpenWeather forecast data", e)
        return "错误：处理天气数据时出错"


def get_current_weather(location: dict) -> str:
    """获取当前实时天气（OpenWeather）。"""
    try:
        api_key = os.getenv("OPENWEATHER_API_KEY")
        if not api_key:
            return "错误：未配置天气API密钥，请在.env文件中设置 OPENWEATHER_API_KEY"

        city_url = "https://api.openweathermap.org/geo/1.0/direct"
        city_query = location.get("city")
        if location.get("country") == "中国":
            city_query = city_query + ",CN"
        city_param = {
            "q": city_query,
            "appid": api_key,
        }
        city_response = requests.get(city_url, params=city_param)
        city_response.raise_for_status()
        city_data = city_response.json()

        if not city_data:
            return f"错误：无法找到城市 '{location}'，请确认城市名称是否正确"

        city_name = city_data[0]["name"].split(" ")[0]
        logger.info(f"city_name:{city_name}")

        base_url = "https://api.openweathermap.org/data/2.5"
        params = {
            "q": city_name,
            "appid": api_key,
            "units": "metric",
            "lang": "zh_cn",
        }

        response = requests.get(f"{base_url}/weather", params=params)
        response.raise_for_status()
        data = response.json()

        result = f"{data['name']} 当前天气：\n\n"
        result += f"时间：{datetime.fromtimestamp(data['dt']).strftime('%Y-%m-%d %H:%M:%S')}\n"
        result += f"温度：{data['main']['temp']}°C\n"
        result += f"体感温度：{data['main']['feels_like']}°C\n"
        result += f"天气：{data['weather'][0]['description']}\n"
        result += f"湿度：{data['main']['humidity']}%\n"
        result += f"风速：{data['wind']['speed']} m/s\n"
        result += f"气压：{data['main']['pressure']} hPa\n"
        result += f"云量：{data['clouds']['all']}%\n"
        result += f"能见度：{data.get('visibility', '未知')} m\n"

        return result

    except requests.exceptions.RequestException as e:
        report_error(29009, "OpenWeather realtime weather request failed", e)
        return "错误：获取天气信息失败"
    except Exception as e:
        report_error(29010, "error processing OpenWeather realtime weather data", e)
        return "错误：处理天气数据时出错"


def process_weather_forecast(weather_list: List[Dict]) -> List[Dict]:
    """按天汇总 OpenWeather 预报。"""
    if not weather_list:
        return []

    grouped = defaultdict(list)

    for item in weather_list:
        dt = item.get("dt")
        if not dt:
            continue
        date_str = datetime.fromtimestamp(dt).strftime("%Y-%m-%d")
        grouped[date_str].append(item)

    result = []
    for date, items in sorted(grouped.items()):
        try:
            temp_max = max(i["main"]["temp_max"] for i in items)
            temp_min = min(i["main"]["temp_min"] for i in items)

            avg_feels_like = int(sum(i["main"]["feels_like"] for i in items) / len(items))
            avg_humidity = int(sum(i["main"]["humidity"] for i in items) / len(items))
            wind_speed = round(sum(i["wind"]["speed"] for i in items) / len(items), 1)
            visibility = int(sum(i.get("visibility", 10000) for i in items) / len(items))

            descriptions = set()
            for i in items:
                for w in i.get("weather", []):
                    s = w.get("description", "")
                    if s:
                        ds = s.split("，")
                        for desc in ds:
                            descriptions.add(desc)
            weather = "，".join(descriptions) if descriptions else "未知"

            result.append({
                "date": date,
                "temp_max": int(temp_max),
                "temp_min": int(temp_min),
                "feels_like": avg_feels_like,
                "humidity": avg_humidity,
                "wind_speed": wind_speed,
                "visibility": visibility,
                "condition": weather,
            })
        except (KeyError, ValueError, ZeroDivisionError) as e:
            logger.warning(f"处理日期 {date} 的天气数据时出错: {e}")
            continue

    return result


def get_unified_weather_forecast(location: dict, country: str = None, region: str = None) -> str:
    """按国家/地区选择天气预报接口。"""
    if country == "中国" and region not in ["香港", "台湾"]:
        if WEATHER_API_PROVIDER == "amap":
            return get_amap_weather_forecast(location)
        else:
            return get_weather_forecast(location)
    else:
        return get_weather_forecast(location)


def get_unified_current_weather(location: dict, country: str = None, region: str = None) -> str:
    """按国家/地区选择实时天气接口。"""
    if country == "中国" and region not in ["香港", "台湾"]:
        if WEATHER_API_PROVIDER == "amap":
            return get_amap_current_weather(location)
        else:
            return get_current_weather(location)
    else:
        return get_current_weather(location)
