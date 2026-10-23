"""
WeatherAgent - 天气查询 Agent。

这个文件属于 weather 模块，交给负责天气的同事修改。
模型、配置和国际化仍使用主仓库提供的接口。
"""
import os
import re
import sys
import time
import logging
from typing import Dict, List, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
from agno.agent import Agent
from agno.models.openai import OpenAILike
from agno.tools import tool

from llm.llm_service import LLMService
from config.config import Config
from util.error_emitter import emit_error, get_current_language
from util.i18n import t as i18n_t, normalize_language
from .client import (
    WEATHER_API_PROVIDER,
    get_unified_current_weather,
    get_unified_weather_forecast,
)
from .errors import set_error_reporter
from .prompts import WEATHER_AGENT, WEATHER_ANSWER

logger = logging.getLogger(__name__)
load_dotenv()
AGENT_NAME = "weatherAgent"


def _report_weather_error(code: int, message: str, detail=None) -> None:
    kwargs = {"code": code, "message": message, "agent": AGENT_NAME}
    if detail is not None:
        kwargs["detail"] = detail
    emit_error(**kwargs)


set_error_reporter(_report_weather_error)


@tool
def _get_weather_forecast_impl(location: str) -> str:
    """获取天气预报（工具函数）"""
    return get_unified_weather_forecast(location)


@tool
def _get_current_weather_impl(location: str) -> str:
    """获取实时天气（工具函数）"""
    return get_unified_current_weather(location)


class WeatherAgent:
    """基于天气接口的智能天气服务 Agent。"""

    def __init__(
        self,
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        db=None,
        enable_memory: bool = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_agent: bool = True,
    ):
        config = Config(type="inference")
        model_config = config.getModelConfig()
        self.model_id = model_id or model_config.get("modelname", "qwen-plus-2025-07-14")
        self.api_key = api_key or model_config.get("apikey")
        self.base_url = base_url or model_config.get("base_url")
        self.db = db
        self.user_id = user_id
        self.session_id = session_id
        self.use_agent = use_agent

        if not self.api_key:
            emit_error(
                code=29011,
                message="weather Agent missing API Key config",
                agent=AGENT_NAME,
            )

        if use_agent:
            self.model = OpenAILike(
                id=self.model_id,
                api_key=self.api_key,
                base_url=self.base_url,
            )
            self.agent = Agent(
                name="天气助手",
                role="天气信息查询专家",
                model=self.model,
                tools=[_get_weather_forecast_impl, _get_current_weather_impl],
                instructions=WEATHER_AGENT,
                markdown=True,
                add_datetime_to_context=True,
                db=self.db,
                enable_user_memories=enable_memory,
                user_id=self.user_id,
                session_id=self.session_id,
            )

        logger.info(f"WeatherAgent 初始化完成 (use_agent={use_agent}, provider={WEATHER_API_PROVIDER})")

    def query(self, question: str, stream: bool = False) -> str:
        try:
            if self.use_agent:
                response = self.agent.run(
                    message=question,
                    stream=stream,
                )
                if hasattr(response, "content"):
                    answer = response.content
                elif isinstance(response, str):
                    answer = response
                else:
                    answer = str(response)
            else:
                answer = self.query_without_agent(question)

            return answer

        except Exception as e:
            emit_error(
                code=29012,
                message="weather Agent query failed",
                agent=AGENT_NAME,
                detail=e,
            )
            return i18n_t("weather_query_error", get_current_language())

    def query_without_agent(
        self,
        question: str,
        context_messages: List[Dict[str, str]] = None,
        stream: bool = False,
        user_info: str = None,
        location: dict = None,
        language: str = "中文",
        intent_total_tokens: int = 0,
    ):
        _lang = normalize_language(language)
        try:
            current_time = time.strftime("%Y-%m-%d %H:%M:%S")
            loc_city = location.get("city")
            latitude = location.get("latitude")
            longitude = location.get("longitude")
            original_country = location.get("country")
            country = original_country
            region = location.get("region")
            if loc_city and not latitude and not longitude and not country and not region:
                region = loc_city
            if not country:
                country = "中国"
            routing_country = original_country
            if not loc_city and (not latitude or not longitude):
                yield i18n_t("weather_no_location", _lang)
                return

            time_start = time.time()

            if re.search(r"当前|目前|现在|此刻|实时", question):
                weather_data = get_unified_current_weather(location, routing_country, region)
            else:
                weather_data = get_unified_weather_forecast(location, routing_country, region)

            time_duration = time.time() - time_start
            logger.info(f"天气API用时：{time_duration:.2f}秒")

            final_prompt = WEATHER_ANSWER.format(
                question=question,
                weather_data=weather_data,
                user_info=user_info or "",
                current_time=current_time,
                language=language,
                country=country,
                region=region,
                city=loc_city,
            )

            messages = [{"role": "system", "content": final_prompt}]

            if context_messages and len(context_messages) > 0:
                for message in context_messages:
                    if message["role"] in ["user", "assistant"]:
                        messages.append({
                            "role": message["role"],
                            "content": message["content"],
                        })

            messages.append({"role": "user", "content": question})

            logger.info(f"天气messages: {messages}")

            llm_service = LLMService(
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model_id,
            )

            time_start = time.time()
            result = llm_service.query_common_response(messages, stream=stream)
            if stream:
                time_duration = time.time() - time_start
                logger.info(f"天气模型推理用时：{time_duration:.2f}秒")
                for chunk in result:
                    yield chunk
            else:
                if isinstance(result, dict):
                    content = result.get("content", "")
                    yield content
                else:
                    yield result
        except Exception as e:
            emit_error(
                code=29013,
                message="weather Agent streaming query failed",
                agent=AGENT_NAME,
                detail=e,
            )
            yield i18n_t("weather_query_error", _lang)

    def get_agent(self):
        return self.agent


def main():
    weather_agent = WeatherAgent(use_agent=False)
    location = {
        "country": "中国",
        "province": "香港",
        "region": "香港",
        "city": "香港元朗区友善街3号元朗区",
        "latitude": "22.4425253",
        "longitude": "114.044859",
        "address": "香港元朗区友善街3号",
    }
    result = weather_agent.query_without_agent(
        question="明天天气如何",
        stream=True,
        location=location,
    )
    for chunk in result:
        print(chunk, end="", flush=True)
    print("\n")


if __name__ == "__main__":
    main()
