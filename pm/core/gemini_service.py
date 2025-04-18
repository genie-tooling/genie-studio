import google.generativeai as genai
from loguru import logger

class GeminiService:
    def __init__(self, model: str, api_key: str, temp: float = 0.3, top_k: int = 40):
        logger.debug("Initialising GeminiService model=%s", model)
        genai.configure(api_key=api_key)
        self.chat = genai.GenerativeModel(
            model,
            generation_config=genai.GenerationConfig(temperature=temp, top_k=top_k)
        ).start_chat(history=[])

    def stream(self, prompt: str):
        logger.debug("Gemini stream start")
        for chunk in self.chat.send_message(prompt, stream=True):
            yield chunk.text

    def send(self, prompt: str) -> str:
        logger.debug("Gemini send")
        return self.chat.send_message(prompt).text
