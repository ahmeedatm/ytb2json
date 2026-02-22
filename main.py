import re
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import ValidationError

from schemas import ExtractRequest, ExtractResponse
from services import process_youtube_url
from config import settings

app = FastAPI(
    title="YouTube to JSON API",
    description="API permettant d'extraire les sous-titres d'une URL YouTube et de générer un résumé JSON structuré.",
    version="1.0.0"
)

def is_valid_youtube_url(url: str) -> bool:
    """
    Valide l'expression régulière basique d'une URL YouTube
    """
    youtube_regex = (
        r'(https?://)?(www\.)?'
        r'(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    return re.match(youtube_regex, url) is not None

def verify_api_key(x_rapidapi_proxy_secret: str = Header(None, alias="X-RapidAPI-Proxy-Secret")):
    """
    Vérifie que la requête provient bien de RapidAPI en comparant le Header secret avec celui défini dans la configuration.
    Si vous testez en local, assurez-vous de passer ce Header dans votre requête.
    """
    if not x_rapidapi_proxy_secret or x_rapidapi_proxy_secret != settings.api_secret_key:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid or missing X-RapidAPI-Proxy-Secret header"
        )

@app.post("/api/v1/extract", response_model=ExtractResponse, dependencies=[Depends(verify_api_key)])
async def extract_endpoint(request: ExtractRequest):
    """
    Endpoint principal pour traiter la vidéo YouTube fournie.
    Protégé par le Header X-RapidAPI-Proxy-Secret.
    """
    if not is_valid_youtube_url(request.url):
        raise HTTPException(status_code=400, detail="L'URL fournie ne semble pas être une URL YouTube valide.")
        
    try:
        response = await process_youtube_url(request.url)
        return response
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        # Erreurs génériques
        raise HTTPException(status_code=500, detail=f"Une erreur interne est survenue: {str(e)}")

# Point d'entrée pour le démarrage via uvicorn (utilisé principalement en dev, en prod on lance directement uvicorn main:app)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
