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
    try:
        with ThreadPoolExecutor() as pool:
            transcript_text = await loop.run_in_executor(pool, extract_transcript_sync, video_id)
    except Exception as e:
        raise ValueError(f"Erreur lors de l'extraction des sous-titres: {str(e)}")
        
    if not transcript_text.strip():
        raise ValueError("Les sous-titres extraits sont vides.")
        
    # Limiter grossièrement la taille du texte pour ne pas exploser le contexte (gpt-4o-mini a 128k context max, très large)
    # Mais par prudence on peut clipper à ~80000 caractères.
    transcript_text = transcript_text[:80000]

    video_title = f"Vidéo ID: {video_id}"  # youtube-transcript-api ne renvoie pas le titre, on le simplifie ou on pourrait fetch la page html.
    
    SYSTEM_PROMPT = """Tu es une API d'extraction de données backend. Ton seul et unique rôle est d'analyser une transcription brute de vidéo et de retourner un objet JSON strictement formaté.

RÈGLES ABSOLUES :
1. Tu ne dois générer AUCUN texte conversationnel avant ou après le JSON.
2. Tu ne dois PAS utiliser de balises markdown comme ```json ou ```. Commence directement par { et termine par }.
3. La réponse DOIT respecter EXACTEMENT la structure suivante :

{
  "title": "Un titre accrocheur déduit de la vidéo",
  "summary": "Un résumé clair et concis (maximum 3 phrases)",
  "chapters": [
    {
      "timestamp": "MM:SS",
      "topic": "Le sujet abordé dans cette partie"
    }
  ],
  "keywords": ["mot-clé 1", "mot-clé 2", "mot-clé 3", "mot-clé 4", "mot-clé 5"]
}

INSTRUCTIONS DE TRAITEMENT :
- Si la transcription ne contient pas de marqueurs de temps explicites, déduis des chapitres logiques et mets "00:00" pour le premier, puis estime ou laisse vide pour les suivants si impossible à déterminer.
- Ne retourne QUE l'objet JSON valide."""

    # 5. Appel LLM avec Pydantic Structuring via JSON object mode
    try:
        completion = await openai_client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": SYSTEM_PROMPT
                },
                {"role": "user", "content": f"Titre de la vidéo : {video_title}\n\nSous-titres bruts:\n{transcript_text}"}
            ],
            response_format={"type": "json_object"},
        )
        
        result_json = completion.choices[0].message.content
        return ExtractResponse.model_validate_json(result_json)
    except Exception as e:
        raise ValueError(f"Erreur lors de l'appel LLM ou de la validation JSON: {str(e)}")
