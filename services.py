import asyncio
import re
import json
from concurrent.futures import ThreadPoolExecutor
from youtube_transcript_api import YouTubeTranscriptApi
import httpx
from openai import AsyncOpenAI

from config import settings
from schemas import ExtractResponse

# Initialise le client OpenAI asynchrone pour OpenRouter
openai_client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    base_url="https://openrouter.ai/api/v1"
)

def extract_video_id(url: str) -> str:
    """Extraire l'ID de la vidéo depuis l'URL YouTube."""
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
    if not match:
        raise ValueError("URL YouTube invalide ou ID de vidéo introuvable.")
    return match.group(1)

def extract_transcript_sync(video_id: str) -> str:
    """
    Exécute youtube-transcript-api de manière synchrone pour extraire les sous-titres,
    avec prise en charge optionnelle d'un proxy pour éviter les bans IP des Datacenters (Google Cloud, AWS).
    """
    try:
        # Initialiser l'API avec un proxy si configuré
        if settings.proxy_url:
            from youtube_transcript_api.proxies import GenericProxyConfig
            # On formate l'URL "http://" si l'utilisateur n'a passé que ses identifiants bruts (ex: IPRoyal)
            formatted_proxy = settings.proxy_url if settings.proxy_url.startswith("http") else f"http://{settings.proxy_url}"
            # IPRoyal exige de se connecter à son proxy via HTTP même pour HTTPS (cf. requetes requests)
            proxy = GenericProxyConfig(http_url=formatted_proxy, https_url=formatted_proxy)
            ytt_api = YouTubeTranscriptApi(proxy_config=proxy)
        else:
            ytt_api = YouTubeTranscriptApi()
        
        # Récupérer la liste des transcripts
        transcript_list = ytt_api.list(video_id)
        
        try:
            # Essayer d'abord de récupérer le transcript (en français ou anglais)
            transcript = transcript_list.find_transcript(['fr', 'en'])
        except Exception:
            # Si ni fr ni en n'est dispo, prendre le premier transcript généré ou manuel en fallback
            transcript = transcript_list.find_generated_transcript(['fr', 'en']) if transcript_list._generated_transcripts else transcript_list.find_manually_created_transcript(['fr', 'en'])

        # Fetch les données
        res = transcript.fetch()
        
        # Combiner le texte de tous les segments (res est une liste de dicts ou d'objets avec attribut 'text')
        if res and hasattr(res[0], 'text'):
            text = " ".join([item.text for item in res])
        else:
            text = " ".join([item['text'] for item in res])
        return text
    except Exception as e:
        raise ValueError(f"Impossible d'extraire les sous-titres : \n{str(e)}")


async def process_youtube_url(url: str) -> ExtractResponse:
    """
    Orchestre l'extraction des sous-titres et l'appel au LLM pour obtenir le résumé structuré.
    """
    loop = asyncio.get_event_loop()
    
    video_id = extract_video_id(url)
    
    # 1. Extraire les sous-titres via youtube-transcript-api dans un ThreadPoolExecutor pour ne pas bloquer l'Event Loop
    # Timeout configurable via EXTRACT_TIMEOUT dans .env (défaut 12s en local, réduire en prod avec proxy)
    try:
        with ThreadPoolExecutor() as pool:
            transcript_text = await asyncio.wait_for(
                loop.run_in_executor(pool, extract_transcript_sync, video_id),
                timeout=settings.extract_timeout
            )
    except asyncio.TimeoutError:
        raise ValueError(f"L'extraction des sous-titres a dépassé le délai imparti ({settings.extract_timeout}s). Réessayez.")
    except Exception as e:
        raise ValueError(f"Erreur lors de l'extraction des sous-titres: {str(e)}")
        
    if not transcript_text.strip():
        raise ValueError("Les sous-titres extraits sont vides.")
        
    # Limiter le transcript à ~12 000 caractères pour laisser suffisamment de temps au LLM
    # et rester sous le timeout de 15s de RapidAPI (~3-4k tokens, amplement suffisant pour un résumé).
    transcript_text = transcript_text[:12000]

    video_title = f"Vidéo ID: {video_id}"  # youtube-transcript-api ne renvoie pas le titre, on le simplifie ou on pourrait fetch la page html.
    
    SYSTEM_PROMPT = """You are a backend data extraction API. Your sole and unique role is to analyze a raw video transcript and return a strictly formatted JSON object.
    
CRITICAL RULES:
1. THE ENTIRE JSON OUTPUT (title, summary, topics, keywords) MUST BE WRITTEN IN ENGLISH, REGARDLESS OF THE VIDEO'S ORIGINAL LANGUAGE.
2. You must NOT generate any conversational text before or after the JSON.
3. You must NOT use markdown tags like ```json or ```. Start directly with { and end with }.
4. The response MUST EXACTLY match the following structure:

{
  "title": "A catchy title deduced from the video (IN ENGLISH)",
  "summary": "A clear and concise summary (maximum 3 sentences) (IN ENGLISH)",
  "chapters": [
    {
      "timestamp": "MM:SS",
      "topic": "The topic covered in this part (IN ENGLISH)"
    }
  ],
  "keywords": ["keyword 1", "keyword 2", "keyword 3", "keyword 4", "keyword 5"]
}

PROCESSING INSTRUCTIONS:
- If the transcript lacks explicit timestamps, deduce logical chapters and put "00:00" for the first one, then estimate or leave empty for subsequent ones if impossible to determine.
- Return ONLY the valid JSON object."""

    # 5. Appel LLM avec Pydantic Structuring via JSON object mode
    # Timeout configurable via LLM_TIMEOUT dans .env (défaut 10s)
    try:
        completion = await asyncio.wait_for(
            openai_client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[
                    {
                        "role": "system", 
                        "content": SYSTEM_PROMPT
                    },
                    {"role": "user", "content": f"Titre de la vidéo : {video_title}\n\nSous-titres bruts:\n{transcript_text}"}
                ],
                response_format={"type": "json_object"},
            ),
            timeout=settings.llm_timeout
        )
        
        result_json = completion.choices[0].message.content
        return ExtractResponse.model_validate_json(result_json)
    except Exception as e:
        raise ValueError(f"Erreur lors de l'appel LLM ou de la validation JSON: {str(e)}")
