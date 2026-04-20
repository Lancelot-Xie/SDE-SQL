import os
import time

import openai
from openai import OpenAI


def create_client(engine: str) -> OpenAI:
    if "vllm" in engine:
        time.sleep(1)
        return OpenAI(
            api_key=os.environ.get("VLLM_API_KEY", "EMPTY"),
            base_url=os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1"),
        )
    if "/" in engine:
        time.sleep(1)
        return OpenAI(
            api_key=os.environ.get("SILICONFLOW_API_KEY"),
            base_url=os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
        )
    if "deepseek" in engine:
        time.sleep(1)
        return OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        )
    if "qwen" in engine:
        time.sleep(1)
        return OpenAI(
            api_key=os.environ.get("DASHSCOPE_API_KEY"),
            base_url=os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )

    openai.debug = True
    return OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("OPENAI_BASE_URL"),
    )
