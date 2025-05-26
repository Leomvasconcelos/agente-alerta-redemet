import os
import requests
import datetime
import json
import re
import time 

# --- Configurações Importantes ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
REDEMET_API_KEY = os.getenv("REDEMET_API_KEY")
GIST_TOKEN = os.getenv("GIST_TOKEN") 
GIST_ID = os.getenv("GIST_ID")       

# Verifica se os tokens essenciais estão configurados
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("Erro: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não encontrados nas variáveis de ambiente.")
    print("Certifique-se de configurar TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID como GitHub Secrets.")
    exit()

if not GIST_TOKEN or not GIST_ID:
    print("Erro: GIST_TOKEN ou GIST_ID não encontrados nas variáveis de ambiente.")
    print("Certifique-se de configurar GIST_TOKEN e GIST_ID como GitHub Secrets.")
    exit()

# --- Sua Lista de Códigos de Tempo Severo e Critérios ---
CODIGOS_SEVEROS = [
    "TS",     # Tempestade
    "GR",     # Granizo
    "VA",     # Cinzas Vulcânicas
    "VCTS",   # Tempestade Próxima
    "VCFG",   # Nevoeiro Próximo
    "VV",     # Visibilidade Vertical (Céu Obscurecido, Teto Ilimitado)
    "OVC",    # Coberto (com critério de teto)
    "BKN",    # Quebrado (com critério de teto)
    "FG",     # Nevoeiro (com critério de visibilidade)
    "FU",     # Fumaça
    "SHGR",   # Pancada de Granizo (GR pequeno)
    "RA",     # Chuva (com critério de +RA)
    "WS",     # Tesoura de Vento (Wind Shear)
]

# Lista de aeródromos a serem monitorados (APENAS SBTA)
AERODROMOS_INTERESSE = ["SBTA"]
