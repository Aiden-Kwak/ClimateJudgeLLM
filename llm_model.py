import requests
import json
from openai import OpenAI

class LLMModel:
    def __init__(self, deepseek_api_key=None, openai_api_key=None, deepseek_base_url=None):
        self.deepseek_api_key = deepseek_api_key
        self.openai_api_key = openai_api_key
        self.deepseek_base_url = deepseek_base_url

    def call_deepseek(self, prompt: str, model: str = "deepseek-chat"):
        headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json"
        }
        try:
            response = requests.post(
                url=f"{self.deepseek_base_url}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": prompt}],
                    "max_tokens": 1500,
                    "temperature": 0.9
                }
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"DeepSeek API 호출 실패: {e}")

    def call_openai(self, prompt: str, model: str = "gpt-3.5-turbo"):
        client = OpenAI(api_key=self.openai_api_key)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt}
                ],
                max_tokens=1500,
                temperature=0.9
            )
            return response
        except Exception as e:
            raise RuntimeError(f"OpenAI 호출 실패: {e}")

    @staticmethod
    def parse_response(response: dict):
        if "choices" not in response or not response["choices"]:
            raise ValueError("API에서 올바르지 않은 응답 형식이 반환되었습니다.")
        
        content = response["choices"][0]["message"]["content"].strip()

        # 코드 블록 제거
        if content.startswith("```") and content.endswith("```"):
            content = content[content.find("\n") + 1:content.rfind("\n")].strip()

        try:
            # JSON 형식으로 파싱 시도
            return json.loads(content)
        except json.JSONDecodeError:
            # JSON 파싱 실패 시 개행으로 분리
            return [q.strip() for q in content.split("\n") if q.strip()]
