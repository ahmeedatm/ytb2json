from pydantic import BaseModel, HttpUrl, Field
from typing import List

class ExtractRequest(BaseModel):
    url: str = Field(..., description="L'URL de la vidéo YouTube à traiter. Peut être au format https://www.youtube.com/watch?v=... ou https://youtu.be/...")

class Chapter(BaseModel):
    timestamp: str = Field(..., description="Le timestamp du chapitre, ex: '00:00'.")
    topic: str = Field(..., description="Le sujet abordé dans ce chapitre.")

class ExtractResponse(BaseModel):
    title: str = Field(..., description="Le titre de la vidéo ou un titre généré.")
    summary: str = Field(..., description="Un résumé concis du contenu de la vidéo.")
    chapters: List[Chapter] = Field(..., description="La liste des chapitres de la vidéo.")
    keywords: List[str] = Field(..., description="Une liste de mots-clés pertinents.")
