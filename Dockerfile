# Utiliser une image Python officielle allégée
FROM python:3.9-slim

# Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Empêcher Python d'écrire des fichiers .pyc et forcer l'affichage des logs (unbuffered)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Installer les dépendances système nécessaires 
# (youtube-transcript-api ne dépend de rien de spécial, mais au cas où)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copier le fichier des dépendances
COPY requirements.txt .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Copier tout le code source dans le conteneur
COPY . .

# Cloud Run s'attend à écouter sur le port stocké dans $PORT (par défaut 8000 ici pour le local)
ENV PORT=8000
EXPOSE $PORT

# Commande pour démarrer l'application avec Uvicorn sur le port fourni par Google Cloud Run
# On utilise la forme "shell" (sans les crochets []) pour que $PORT soit correctement évalué au démarrage par Bash/sh
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
