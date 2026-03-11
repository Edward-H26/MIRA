from google import genai
from django.conf import settings

client = genai.Client(api_key=settings.GEMINI_API_KEY)
MODEL_ID = "gemini-2.5-flash"


def generate_reply_stream(user_text: str):
    response = client.models.generate_content_stream(model=MODEL_ID, contents=user_text)
    for chunk in response:
        text = getattr(chunk, "text", None)
        if text:
            yield text


def generate_reply_text(user_text: str):
    chunks = []
    for chunk in generate_reply_stream(user_text):
        if chunk:
            chunks.append(chunk)
    return "".join(chunks).strip()
