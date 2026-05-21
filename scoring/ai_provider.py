import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = Path(__file__).parent.parent / "config" / "system_config.json"


class AIProvider:
    def __init__(self, config_path: str = None):
        path = Path(config_path) if config_path else CONFIG_PATH
        with open(path) as f:
            self.config = json.load(f)

        # Environment variable overrides take precedence over config file
        self.provider = os.getenv("AI_PROVIDER", self.config["ai_provider"])
        self.provider_config = dict(self.config["ai_providers"][self.provider])

        if os.getenv("AI_MODEL"):
            self.provider_config["model"] = os.getenv("AI_MODEL")

        self._client = None
        self._initialize_client()

    def _initialize_client(self):
        api_key_env = self.provider_config["api_key_env"]
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise EnvironmentError(
                f"Missing API key: set {api_key_env} in your .env file or environment"
            )

        if self.provider == "anthropic":
            from anthropic import Anthropic
            self._client = Anthropic(api_key=api_key)

        elif self.provider == "openai":
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key)

        elif self.provider == "google":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self._client = genai.GenerativeModel(self.provider_config["model"])

        else:
            raise ValueError(f"Unknown AI provider: {self.provider}")

    def score_job(self, prompt: str) -> str:
        model = self.provider_config["model"]
        max_tokens = self.provider_config["max_tokens"]
        temperature = self.provider_config["temperature"]

        if self.provider == "anthropic":
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

        elif self.provider == "openai":
            response = self._client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content

        elif self.provider == "google":
            response = self._client.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            return response.text

        raise ValueError(f"Unknown provider: {self.provider}")

    def get_provider_info(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.provider_config["model"],
            "temperature": self.provider_config["temperature"],
        }
