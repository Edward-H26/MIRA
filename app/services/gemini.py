from google import genai
from django.conf import settings

client = genai.Client(api_key=settings.GEMINI_API_KEY)
MODEL_ID = "gemini-2.5-flash"


def generate_reply(user_text: str) -> str:
    response = client.models.generate_content(model=MODEL_ID, contents=user_text)
    return response.text