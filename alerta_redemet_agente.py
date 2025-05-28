import os
import requests
import json
import time
from datetime import datetime, timedelta
import pytz
import re

# --- Configurações ---
# Use o token do seu bot no Telegram
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
# ID do chat para onde as mensagens serão enviadas (pode ser um grupo ou um usuário)
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Substitua pela sua chave da API da REDEMET (quando disponível)
# REDEMET_API_KEY = os.getenv('REDEMET_API_KEY') 

# Aeródromos de interesse (SBTA para testes iniciais)
AERODROMOS_INTERESSE = ["SBTA"]

# Intervalo de verificação em segundos (5 minutos) - Este será o intervalo de sleep SE rodar localmente
# No GitHub Actions, o agendamento é feito pelo cron no .yml
INTERVALO_VERIFICACAO = 300 

# Dicionário de códigos METAR/TAF e suas descrições
CODIGOS_METAR_TAF_MAP = {
    "TS": "Trovoada",
    "RA": "Chuva",
    "+RA": "Chuva Forte", # Adicionado para detecção específica
    "-RA": "Chuva Fraca",
    "GR": "Granizo",
    "GS": "Granizo Pequeno/Grãos de Neve",
    "FZRA": "Chuva Congelante",
    "SN": "Neve",
    "SG": "Nevoeiro Congelante",
    "IC": "Cristais de Gelo",
    "PL": "Pellets de Gelo",
    "UP": "Precipitação Desconhecida",
    "FG": "Nevoeiro",
    "BR": "Névoa",
    "HZ": "Névoa Seca (Haze)",
    "FU": "Fumaça",
    "VA": "Cinzas Vulcânicas",
    "DU": "Poeira Generalizada",
    "SA": "Areia",
    "BLDU": "Poeira Levantada",
    "BLSA": "Areia Levantada",
    "BLSN": "Neve Levantada",
    "DRDU": "Poeira Arrastada",
    "DRSA": "Areia Arrastada",
    "DRSN": "Neve Arrastada",
    "PO": "Redemoinhos de Poeira/Areia",
    "SQ": "Rajada (Squall)",
    "FC": "Funil de Vento (Tornado/Waterspout)",
    "SS": "Tempestade de Areia",
    "DS": "Tempestade de Poeira",
    "VCTS": "Trovoada nas Proximidades",
    "SH": "Pancada (Shower)", # Para SHRA, SHSN, etc.
    "OVC": "Nublado (Overcast)", # Teto Baixo
    "BKN": "Parcialmente Nublado (Broken)", # Teto Baixo
    "CB": "Cumulunimbus", # Nuvem de Trovoada
    "TCU": "Cumulus Castellanus", # Nuvem convectiva significante
    "WS": "Tesoura de Vento (Wind Shear)", # Adicionado para Avisos de Aeródromo
}

# Armazenamento em memória para evitar alertas duplicados
# Em um ambiente de produção, isso seria um banco de dados ou cache persistente
alertas_enviados_cache = {} # {hash_da_mensagem: timestamp_envio}

# --- Funções Auxiliares ---

def calcular_hash_mensagem(mensagem):
    """Calcula um hash simples da mensagem para evitar duplicatas."""
    return hash(mensagem)

def enviar_mensagem_telegram(chat_id, texto):
    """Envia uma mensagem para o Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status() # Lança exceção para erros HTTP
        print(f"Mensagem enviada com sucesso para o Telegram: {texto}")
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar mensagem para o Telegram: {e}")

def obter_mensagens_redemet_simulada(endpoint, aerodromo=None):
    """
    Função de simulação para testar a lógica SEM a API real.
    Retorna dados de exemplo como se viessem da API da REDEMET.
    """
    print(f"Simulando busca de dados da REDEMET para {endpoint} em {aerodromo}...")
    
    # NOVOS EXEMPLOS DE MENSAGENS PARA TESTE SBTA (28 de maio de 2025):
    # As horas foram ajustadas para o dia atual para parecerem "frescas"
    
    # AVISOS DE AERÓDROMO
    avisos_simulados = [
        # Aviso de Trovoada e Vento Forte
        "SBGL SBSJ/SBTA AD WRNG 1 VALID 281400/281800 TS SFC WSPD 15KT MAX 30 FCST NC=", 
        # Aviso de Vento de Superfície e Rajada
        "SBGR SBBP/SBTA AD WRNG 2 VALID 281530/281930 SFC WSPD 20KT MAX 35 FCST NC=",
        # Aviso de Visibilidade Reduzida por Nevoeiro
        "SBSP SBTA AD WRNG 3 VALID 280200/280600 FG VIS < 500M FCST NC=",
        # Aviso de Wind Shear
        "SBTA WS WRNG 4 VALID 281600/281730 MOD WS IN APCH RWY28 REP AT 1545Z A320=",
        # Outro Aviso de Trovoada, com vento mais forte
        "SBRJ SBTA AD WRNG 5 VALID 281700/282100 TS SFC WSPD 25KT MAX 45 FCST NC=",
        # Aviso de Chuva Forte
        "SBGO SBTA AD WRNG 6 VALID 281100/281400 +RA FCST NC=",
    ]

    # TAFs
    tafs_simulados = [
        # TAF com previsão de TS e rajadas, teto baixo
        "TAF SBTA 281200Z 2812/2912 33010KT 9999 SCT015 BKN030 TX25/2815Z TN18/2903Z TEMPO 2814/2818 30020G35KT 4000 TSRA BKN008 FEW030CB BECMG 2818/2820 27010KT 9999 NSW SCT020 RMK PBZ=",
        # TAF com previsão de nevoeiro e visibilidade reduzida
        "TAF SBTA 280000Z 2800/2824 00000KT 9999 SKC TX28/2817Z TN15/2806Z PROB40 2803/28
