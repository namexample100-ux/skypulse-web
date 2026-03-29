import logging
from cerebras.cloud.sdk import Cerebras
from config import CEREBRAS_API_KEY, CEREBRAS_MODEL

log = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        if not CEREBRAS_API_KEY:
            log.warning("CEREBRAS_API_KEY not found in environment variables.")
            self.client = None
        else:
            self.client = Cerebras(api_key=CEREBRAS_API_KEY)

    async def get_ai_response(self, prompt: str, system_prompt: str = "You are a helpful assistant.") -> str:
        """Получает ответ от Cerebras AI."""
        if not self.client:
            return "❌ Ошибка: API ключ Cerebras не настроен."

        try:
            # SDK Cerebras поддерживает синхронные вызовы, но мы можем обернуть их 
            # или использовать асинхронный клиент если он есть. 
            # Для простоты используем текущий клиент (он достаточно быстрый).
            response = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                model=CEREBRAS_MODEL,
            )
            return response.choices[0].message.content
        except Exception as e:
            log.error(f"Ошибка при запросе к Cerebras AI: {e}")
            return f"❌ Произошла ошибка при обращении к ИИ: {e}"

    async def summarize_news(self, news_text: str) -> str:
        """Создает краткую сводку новостей."""
        system_prompt = (
            "Ты — профессиональный редактор новостей. "
            "Твоя задача — прочитать список новостей и составить краткую, "
            "но информативную сводку в виде маркированного списка (bullet points) на русском языке. "
            "Выделяй самое важное. Пиши кратко и по существу."
        )
        return await self.get_ai_response(news_text, system_prompt)

    async def get_weather_advice(self, weather_desc: str, temp: float) -> str:
        """Дает совет по погоде."""
        prompt = f"Погода: {weather_desc}, Температура: {temp}°C. Что надеть и на что обратить внимание?"
        system_prompt = "Ты — заботливый помощник. Дай краткий совет по одежде и планам на день на основе погоды. Максимум 2-3 предложения."
        return await self.get_ai_response(prompt, system_prompt)
