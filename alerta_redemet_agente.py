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

# Intervalo de verificação em segundos (por exemplo, 5 minutos)
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
    
    # EXEMPLOS DE MENSAGENS PARA TESTE SBTA:
    # AVISOS DE AERÓDROMO
    avisos_simulados = [
        "SBRF SBLE/SBTA/SBJE/SNBR/SWKQ AD WRNG 4 VALID 281210/281310 SFC WSPD 15KT MAX 25 FCST NC=", # Vento de Superfície [cite: 1]
        "SBRF SBLE/SBTA/SBJE/SNBR/SWKQ AD WRNG 9 VALID 281310/281710 SFC WSPD 15KT MAX 25 FCST NC=", # Vento de Superfície [cite: 1]
        "SBPA SBML/SBTA/SBAE AD WRNG 35 VALID 281310/281710 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 1]
        "SBPA SBML/SBTA/SBAE AD WRNG 25 VALID 281152/281310 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 1]
        "SBPA SBGW/SBTA/SBAF/SDCO/SDAG AD WRNG 33 VALID 281310/281710 SFC WSPD 15KT MAX 32 FCST NC=", # Vento de Superfície e Rajada [cite: 1]
        "SBPA SBGW/SBTA/SBAF/SDCO/SDAG AD WRNG 23 VALID 281030/281310 SFC WSPD 15KT MAX 32 FCST NC=", # Vento de Superfície e Rajada [cite: 1]
        "SBPA SBUG/SBTA/SBPK/SBSM/SBNM AD WRNG 16 VALID 281030/281310 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 1]
        "SBPA SBUG/SBTA/SBPK/SBSM/SBNM AD WRNG 26 VALID 281310/281710 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 2]
        "SBPA SBJV/SBTA/SBBI/SBFI/SBPG AD WRNG 29 VALID 281310/281710 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 2]
        "SBPA SBJV/SBTA/SBBI/SBFI/SBPG AD WRNG 19 VALID 281030/281310 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 2]
        "SBGR SBBP/SBTA/SBKP/SDAM/SBSP AD WRNG 2 VALID 281040/281310 SFC WSPD 15KT MAX 32 FCST NC=", # Vento de Superfície e Rajada [cite: 2]
        "SBGR SBBP/SBTA/SBKP/SDAM/SBSP AD WRNG 4 VALID 281310/281710 SFC WSPD 15KT MAX 32 FCST NC=", # Vento de Superfície e Rajada [cite: 2]
        "SBPA SSGG/SBTA/SBCA/SBTD/SBPP AD WRNG 30 VALID 281310/281710 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 2]
        "SBPA SSGG/SBTA/SBCA/SBTD/SBPP AD WRNG 20 VALID 281030/281310 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 2]
        "SBGL SBGL/SBTA/SBCB/SBME/SBCP AD WRNG 13 VALID 281310/281710 SFC WSPD 15KT MAX 32 FCST NC=", # Vento de Superfície e Rajada [cite: 3]
        "SBGL SBGL/SBTA/SBCB/SBME/SBCP AD WRNG 8 VALID 281030/281310 SFC WSPD 15KT MAX 32 FCST NC=", # Vento de Superfície e Rajada [cite: 3]
        "SBPA SBCG/SBTA/SBDN AD WRNG 24 VALID 281042/281310 TS SFC WSPD 20KT MAX 42 FCST NC=", # Trovoada, Vento de Superfície e Rajada [cite: 3]
        "SBPA SBCG/SBTA/SBDN AD WRNG 34 VALID 281310/281710 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 3]
        "SBPA SBLJ/SBTA/SBCD/SBFL/SBNF AD WRNG 28 VALID 281310/281710 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 3]
        "SBPA SBLJ/SBTA/SBCD/SBFL/SBNF AD WRNG 18 VALID 281030/281310 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 3]
        "SBPA SBPF/SBTA/SBCO/SBCX/SBJA AD WRNG 17 VALID 281030/281310 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 3]
        "SBPA SBPF/SBTA/SBCO/SBCX/SBJA AD WRNG 27 VALID 281310/281710 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 3]
        "SBPA SBDB/SBTA/SBCR/SBMG/SBLO AD WRNG 31 VALID 281310/281710 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 4]
        "SBPA SBDB/SBTA/SBCR/SBMG/SBLO AD WRNG 21 VALID 281030/281310 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 4]
        "SBGL SBMM/SBTA/SBLB/SBEN/SBLI AD WRNG 10 VALID 281310/281710 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 4]
        "SBGL SBMM/SBTA/SBLB/SBEN/SBLI AD WRNG 5 VALID 281030/281310 SFC WSPD 20KT MAX 42 FCST NC=", # Vento de Superfície e Rajada [cite: 4]
        "SBRF SBLP/SBTA/SBFN/SBPB/SBMS AD WRNG 3 VALID 281210/281310 SFC WSPD 15KT MAX 25 FCST NC=", # Vento de Superfície [cite: 4]
        "SBRF SBLP/SBTA/SBFN/SBPB/SBMS AD WRNG 8 VALID 281310/281710 SFC WSPD 15KT MAX 25 FCST NC=", # Vento de Superfície [cite: 4]
        "SBGL SBFS/SBTA/SBPW AD WRNG 14 VALID 281310/281710 SFC WSPD 15KT MAX 32 FCST NC=", # Vento de Superfície e Rajada [cite: 4]
        "SBGL SBFS/SBTA/SBPW AD WRNG 9 VALID 281030/281310 SFC WSPD 15KT MAX 32 FCST NC=", # Vento de Superfície e Rajada [cite: 4]
        "SBRF SBFZ/SBTA/SBNT/SBJP/SBKG AD WRNG 1 VALID 281210/281310 SFC WSPD 15KT MAX 25 FCST NC=", # Vento de Superfície [cite: 5]
        "SBRF SBFZ/SBTA/SBNT/SBJP/SBKG AD WRNG 6 VALID 281310/281710 SFC WSPD 15KT MAX 25 FCST NC=", # Vento de Superfície [cite: 5]
        "SBGR SBTA WS WRNG 2 VALID 281134/281340 MOD WS IN APCH RWY10R REP AT 1118Z B738=", # Wind Shear (Tesoura de Vento) [cite: 5]
        "SBGR SBTA/SBGR/SBJH AD WRNG 3 VALID 281040/281310 SFC WSPD 15KT MAX 32 FCST NC=", # Vento de Superfície e Rajada [cite: 5]
        "SBGR SBTA/SBGR/SBJH AD WRNG 5 VALID 281310/281710 SFC WSPD 15KT MAX 32 FCST NC=", # Vento de Superfície e Rajada [cite: 5]
        "SBGL SBSJ/SBST/SBTA/SBJR/SBRJ AD WRNG 12 VALID 281310/281710 SFC WSPD 15KT MAX 32 FCST NC=", # Vento de Superfície e Rajada [cite: 5]
        "SBGL SBSJ/SBST/SBTA/SBJR/SBRJ AD WRNG 7 VALID 281030/281310 SFC WSPD 15KT MAX 32 FCST NC=", # Vento de Superfície e Rajada [cite: 5]
        "SBRF SBTA/SBMO/SBPL/SBJU/SBVC AD WRNG 2 VALID 281210/281310 SFC WSPD 15KT MAX 25 FCST NC=", # Vento de Superfície [cite: 6]
        "SBRF SBTA/SBMO/SBPL/SBJU/SBVC AD WRNG 7 VALID 281310/281710 SFC WSPD 15KT MAX 25 FCST NC=", # Vento de Superfície [cite: 6]
        "SBGR SBTA WS WRNG 3 VALID 281212/281340 MOD WS IN APCH RWY30 REP AT 1150Z E1000=", # Wind Shear (Tesoura de Vento) [cite: 6]
        "SBRF SBTA/SNHS/SNRU/SNGI/SJDS AD WRNG 5 VALID 281210/281310 SFC WSPD 15KT MAX 25 FCST NC=", # Vento de Superfície [cite: 6]
        "SBRF SBTA/SNHS/SNRU/SNGI/SJDS AD WRNG 10 VALID 281310/281710 SFC WSPD 15KT MAX 25 FCST NC=", # Vento de Superfície [cite: 6]
    ]

    # TAFs
    tafs_simulados = [
        "TAF SBTA 281500Z 2812/2912 33010KT 9999 SCT013 BKN025 FEW035TCU TX19/2812Z TN08/2903Z TEMPO 2812/2821 30015G25KT 3000 RA BKN008 BECMG 2821/2823 27013KT BKN015 OVC025 TEMPO 2823/2906 27018G30KT 2000 +RA BKN005 TEMPO 2906/2912 27015G25KT 2000 +RA BKN010 RMK PES=", # [cite: 6]
        "TAF SBTA 281600Z 2812/2912 36008KT 9999 SCT020 TX20/2814Z TN05/2908Z TEMPO 2812/2818 32015G25KT 7000 RA SCT012 BKN020 BECMG 2818/2820 27010KT 9999 NSW SCT015 RMK PEL=", # [cite: 7]
        "TAF AMD SBTA 281830Z 2813/2912 28005KT 2000 BR BKN001 BKN015 FEW030TCU TX18/2813Z TN07/2909Z TEMPO 2813/2815 2000 TSRA BKN012 FEW045CB BECMG 2815/2817 22011KT 9999 NSW SCT030 BECMG 2821/2823 CAVOK BECMG 2904/2906 17013KT RMK PGL=", # [cite: 7]
        "TAF SBTA 282000Z 2812/2824 34005KT 7000 BKN008 TN26/2812Z TX32/2816Z BECMG 2812/2814 07007KT 9999 SCT023 BECMG 2816/2818 12005KT 8000 SHRA SCT023 FEW033TCU BECMG 2819/2821 07005KT 9999 NSW RMK PEJ=", # [cite: 7]
        "TAF SBTA 282100Z 2812/2918 35008KT CAVOK TX27/2817Z TN14/2912Z BECMG 2813/2815 33015G25KT SCT040 BECMG 2818/2820 29010KT BKN035 FEW045TCU PROB30 2822/2901 8000 TS BKN035 FEW040CB BECMG 2902/2904 8000 RA SCT015 BKN025 BECMG 2906/2908 32010KT NSW BECMG 2909/2911 31006KT BECMG 2912/2914 RA SCT020 BECMG 2915/2917 31010KT NSW RMK PHG=", # [cite: 7, 8]
    ]

    # SPECIs
    specis_simulados = [
        "SPECI SBTA 022220Z 25008KT 210V290 6000 RA BKN035 FEW040TCU OVC090 21/20 Q1013=", # [cite: 8]
        "SPECI SBTA 022340Z 20007KT 5000 RA BR BKN035 FEW040TCU OVC050 21/20 Q1014=", # [cite: 8]
        "SPECI SBTA 030035Z 12004KT 070V170 7000 BKN025 FEW030TCU OVC045 21/21 Q1014 RERA=", # [cite: 8]
        "SPECI SBTA 031812Z VRB02KT 9999 4000N TS VCSH SCT035 FEW045CB BKN100 29/20 Q1009=", # [cite: 8]
        "SPECI SBTA 032219Z 02005KT 350V100 2000 TSRA FEW010 BKN030 FEW035CB OVC040 21/21 Q1012=", # [cite: 8]
        "SPECI SBTA 081638Z VRB01KT 9999 TS VCSH SCT035 FEW040CB 32/21 Q1012=", # [cite: 8]
        "SPECI SBTA 081920Z VRB02KT 9999 TS SCT040 FEW045CB BKN100 28/18 Q1012=", # [cite: 8, 9]
        "SPECI SBTA 102018Z 15008G23KT 080V220 9000 TS VCSH BKN045 FEW050CB BKN070 29/20 Q1011=", # [cite: 9]
        "SPECI SBTA 102034Z 17010G26KT 4000 -TSRA HZ BKN045 FEW050CB BKN070 27/19 Q1012=", # [cite: 9]
        "SPECI SBTA 102040Z 20017G27KT 2000 TSRA HZ BKN045 FEW050CB BKN070 26/21 Q1013=", # [cite: 9]
        "SPECI SBTA 111739Z 30007KT 250V340 9999 TS VCSH BKN035 FEW040CB 33/19 Q1010=", # [cite: 9]
        "SPECI SBTA 112345Z 21010KT 9999 -TSRA SCT035 FEW040CB OVC100 23/22 Q1013=", # [cite: 9]
        "SPECI SBTA 121509Z 23016KT 6000 -RA SCT035 FEW040TCU BKN100 24/22 Q1012=", # [cite: 9]
        "SPECI SBTA 121521Z 22012KT 190V260 6000 -TSRA BKN035 FEW040CB BKN100 23/22 Q1012=", # [cite: 9]
        "SPECI SBTA 121538Z VRB02KT 5000 TSRA BR BKN035 FEW040CB OVC100 23/23 Q1012=", # [cite: 9]
        "SPECI SBTA 122027Z 18009KT 9999 2000E TS VCSH BKN015 SCT030 FEW035CB OVC100 25/22 Q1012=", # [cite: 9, 10]
        "SPECI SBTA 122220Z VRB01KT 9999 VCTS FEW015 BKN020 FEW040CB OVC100 23/23 Q1014 RETS=", # [cite: 10]
        "SPECI SBTA 131307Z 22009KT 200V260 3000 RA BR BKN017 BKN025 FEW030TCU OVC049 23/23 Q1017=", # [cite: 10]
        "SPECI SBTA 131317Z 22008KT 5000 RA BR BKN014 BKN025 FEW030TCU OVC049 23/22 Q1017=", # [cite: 10]
        "SPECI SBTA 131715Z 21008KT 2000 -RA BKN015 BKN030 23/23 Q1015=", # [cite: 10]
        "SPECI SBTA 132153Z 23007KT 9999 FEW018 BKN025 BKN100 23/21 Q1016=", # [cite: 10]
        "SPECI SBTA 142035Z 05003KT 020V100 9999 TS VCSH SCT040 FEW045CB SCT100 29/21 Q1013=", # [cite: 10]
        "SPECI SBTA 151808Z 02021G41KT 1200 TSRA BR BKN030 FEW035CB BKN100 22/22 Q1015=", # [cite: 10]
        "SPECI SBTA 171537Z 16003KT 080V240 9999 TS VCSH BKN045 FEW050CB BKN070 32/21 Q1015=", # [cite: 10]
        "SPECI SBTA 172219Z 19003KT 160V230 9999 TS VCSH BKN040 FEW045CB BKN060 BKN090 25/19 Q1016=", # [cite: 10, 11]
        "SPECI SBTA 182145Z 01004KT 9999 TS VCSH FEW040 FEW045CB BKN100 26/21 Q1014=", # [cite: 11]
        "SPECI SBTA 182206Z VRB05KT 5000 TSRA BR BKN035 FEW040CB OVC100 24/23 Q1014=", # [cite: 11]
        "SPECI SBTA 182230Z 20005KT 9000 TS SCT035 FEW040CB BKN100 24/23 Q1016 RERA=", # [cite: 11]
        "SPECI SBTA 202152Z VRB02KT 9999 BKN040 BKN100 26/23 Q1010=", # [cite: 11]
        "SPECI SBTA 211830Z 23011KT 9999 TS VCSH SCT035 FEW040CB BKN080 29/18 Q1011=", # [cite: 11]
        "SPECI SBTA 211905Z 19015G28KT 4000 -TSRA BR BKN035 FEW040CB 23/20 Q1012=", # [cite: 11]
        "SPECI SBTA 211934Z 15007KT 9999 VCSH SCT035 FEW040TCU BKN100 22/21 Q1012 RETS=", # [cite: 11]
        "SPECI SBTA 212152Z 19004KT 9999 FEW025 BKN035 BKN100 23/21 Q1014=", # [cite: 11]
        "SPECI SBTA 231230Z 08003KT 050V130 5000 -RA BR SCT008 BKN017 OVC020 19/19 Q1016=", # [cite: 11, 12]
        "SPECI SBTA 231340Z 09005KT 060V120 5000 -RA BR BKN007 OVC020 20/19 Q1016=", # [cite: 12]
        "SPECI SBTA 231730Z 00000KT 5000 RA BR BKN008 BKN020 OVC035 20/19 Q1014=", # [cite: 12]
        "SPECI SBTA 231914Z 18005KT 130V230 4000 -RA SCT009 BKN020 OVC050 19/18 Q1014 RERA=", # [cite: 12]
        "SPECI SBTA 242112Z 16004KT 9000 -TSRA BKN035 FEW040CB 22/19 Q1010=", # [cite: 12]
        "SPECI SBTA 242142Z 17005KT 130V220 1500 TSRA BKN018 BKN035 FEW040CB 20/19 Q1011=", # [cite: 12]
        "SPECI SBTA 242210Z 14003KT 4000 -RA BR BKN016 BKN025 FEW030TCU 20/19 Q1011 RETSRA=", # [cite: 12]
        "SPECI SBTA 242240Z 11005KT 2000 RA BR BKN018 OVC025 19/19 Q1012=", # [cite: 12]
        "SPECI SBTA 250134Z 28006KT 1500 RA BR BKN006 OVC010 19/18 Q1013=", # [cite: 12]
        "SPECI SBTA 251233Z 26005KT 5000 BR SCT008 BKN015 BKN025 21/19 Q1012=", # [cite: 12]
        "SPECI SBTA 271811Z 27017G32KT 9999 VCSH SCT040 FEW045TCU SCT080 25/16 Q1012=", # [cite: 12, 13]
        "SPECI SBTA 271940Z 20005KT 150V280 9000 -TSRA BKN040 FEW045CB BKN090 23/17 Q1013=", # [cite: 13]
        "SPECI SBTA 272017Z 14006KT 100V160 7000 TS BKN035 FEW040CB BKN090 20/19 Q1012=", # [cite: 13]
        "SPECI SBTA 281231Z VRB02KT 9999 SCT014 25/20 Q1016=", # [cite: 13]
        "SPECI SBTA 281443Z 34005KT 270V030 8000 -TSRA SCT025 FEW030CB BKN100 27/21 Q1015=", # [cite: 13]
        "SPECI SBTA 281628Z 25008KT 5000 -TSRA BR SCT010 BKN020 FEW030CB BKN060 18/18 Q1018=", # [cite: 13]
        "SPECI SBTA 281835Z 12003KT 060V200 9999 FEW035 FEW045TCU SCT100 21/17 Q1015 RETS=", # [cite: 13]
        "SPECI SBTA 291118Z VRB02KT 9000 SCT008 21/18 Q1017=", # [cite: 13]
        "SPECI SBTA 291920Z 29010KT 260V330 9999 -TSRA BKN040 FEW045CB BKN070 26/19 Q1013=", # [cite: 13]
        "SPECI SBTA 292302Z 28012G25KT 3000 TSRA SCT020 BKN040 FEW045CB BKN090 20/19 Q1015=", # [cite: 13]
        "SPECI SBTA 292313Z 06011KT 9999 BKN025 BKN045 FEW050TCU BKN100 20/19 Q1014 RETSRA=", # [cite: 14]
        "SPECI SBTA 011140Z 26003KT 210V290 9999 BKN013 SCT100 21/18 Q1019=", # [cite: 14]
        "SPECI SBTA 021443Z 22011G30KT 1500 TSRA BR SCT010 BKN030 FEW040CB OVC100 22/20 Q1023=", # [cite: 14]
        "SPECI SBTA 021520Z 14003KT 120V210 5000 -RA BR SCT012 BKN030 FEW040TCU OVC100 19/19 Q1021 RETSRA=", # [cite: 14]
        "SPECI SBTA 031910Z 18003KT 9999 TS VCSH BKN035 FEW040CB 28/21 Q1017=", # [cite: 14]
        "SPECI SBTA 032016Z 08020G32KT 5000 -TSRA BR BKN025 FEW035CB OVC040 20/19 Q1019=", # [cite: 14]
        "SPECI SBTA 041615Z 36006KT 310V040 9999 TS BKN035 FEW040CB BKN090 28/22 Q1017=", # [cite: 14]
        "SPECI SBTA 041740Z 16009KT 3000 -TSRA BR BKN020 BKN035 FEW040CB BKN100 22/19 Q1019=", # [cite: 14]
        "SPECI SBTA 041820Z 16014KT 5000 -RA BR FEW007 SCT020 BKN035 FEW040TCU 19/18 Q1019 RETS=", # [cite: 14, 15]
        "SPECI SBTA 042148Z 27003KT 9999 FEW006 OVC100 20/20 Q1019=", # [cite: 15]
        "SPECI SBTA 050930Z 26003KT 220V280 1500 BR BKN003 OVC100 19/18 Q1018=", # [cite: 15]
        "SPECI SBTA 051235Z VRB02KT 9000 SCT009 23/19 Q1019=", # [cite: 15]
        "SPECI SBTA 102144Z 16005KT 120V190 9999 FEW030 27/17 Q1016=", # [cite: 15]
        "SPECI SBTA 112144Z 17004KT 9999 FEW030 29/18 Q1015=", # [cite: 15]
        "SPECI SBTA 121931Z 32006KT 9999 TS VCSH BKN040 FEW045CB BKN100 31/18 Q1016=", # [cite: 15]
        "SPECI SBTA 131710Z 28004KT 230V350 9999 TS VCSH SCT040 FEW045CB 32/20 Q1016=", # [cite: 15]
        "SPECI SBTA 150110Z 01003KT 300V050 3000 RA BR BKN020 OVC030 22/22 Q1017=", # [cite: 15]
        "SPECI SBTA 172140Z 20006KT 170V230 9999 TS SCT040 FEW045CB BKN100 23/19 Q1013=", # [cite: 15]
        "SPECI SBTA 182139Z 22011KT 9000 -RA BKN035 FEW040TCU 21/18 Q1011 RETS=", # [cite: 15]
        "SPECI SBTA 191025Z VRB02KT 9000 BKN007 BKN020 20/20 Q1011=", # [cite: 15, 16]
        "SPECI SBTA 191130Z 28003KT 240V360 9999 SCT008 SCT010 22/20 Q1011=", # [cite: 16]
        "SPECI SBTA 192135Z VRB02KT 9999 TS SCT035 FEW040CB SCT100 24/21 Q1009=", # [cite: 16]
        "SPECI SBTA 201713Z 27011G23KT 9999 -TSRA BKN022 FEW040CB BKN060 24/22 Q1007=", # [cite: 16]
        "SPECI SBTA 211914Z 17009KT 4000 -TSRA BKN025 FEW040CB BKN050 25/22 Q1007=", # [cite: 16]
        "SPECI SBTA 211943Z 12009KT 1500 TSRA BR BKN020 FEW030CB 22/22 Q1008=", # [cite: 16]
        "SPECI SBTA 212129Z 10004KT 3000 RA BR BKN015 FEW030TCU OVC035 21/21 Q1010=", # [cite: 16]
        "SPECI SBTA 221010Z 07004KT 040V110 9999 SCT006 SCT015 21/21 Q1011=", # [cite: 16]
        "SPECI SBTA 221925Z 31009KT 3000 -TSRA BR SCT025 BKN040 FEW045CB 25/24 Q1010=", # [cite: 16]
        "SPECI SBTA 241640Z 31015G25KT 2000 RA BR FEW015 BKN040 FEW045TCU 25/23 Q1018=", # [cite: 16]
        "SPECI SBTA 242134Z VRB02KT CAVOK 23/22 Q1019=", # [cite: 16, 17]
        "SPECI SBTA 251130Z VRB02KT 4000 BR BKN006 23/22 Q1022=", # [cite: 17]
        "SPECI SBTA 251240Z VRB03KT 9000 SCT010 25/22 Q1022=", # [cite: 17]
        "SPECI SBTA 251820Z 17005KT 150V210 9999 TS VCSH BKN035 FEW040CB BKN090 28/21 Q1018=", # [cite: 17]
        "SPECI SBTA 252035Z 28003KT 240V330 9999 SCT040 FEW045TCU SCT080 24/22 Q1019 RETS=", # [cite: 17]
        "SPECI SBTA 270421Z 17003KT 9999 FEW009 BKN020 BKN100 23/21 Q1016=", # [cite: 17]
        "SPECI SBTA 281610Z 24005KT 200V280 9999 TS VCSH SCT040 FEW045CB 32/22 Q1013=", # [cite: 17]
        "SPECI SBTA 281835Z 11005KT 080V150 9999 BKN040 FEW045TCU SCT080 27/21 Q1013 RETS=", # [cite: 17]
        "SPECI SBTA 290526Z 00000KT 9999 FEW007 SCT080 23/22 Q1015=", # [cite: 17]
        "SPECI SBTA 010433Z 00000KT CAVOK 22/22 Q1015=", # [cite: 17]
        "SPECI SBTA 032128Z 15005KT 9999 FEW035 SCT100 29/17 Q1012=", # [cite: 17]
        "SPECI SBTA 050444Z 28001KT CAVOK 21/21 Q1015=", # [cite: 17]
        "SPECI SBTA 051835Z 30015G25KT 9999 TS VCSH BKN045 FEW050CB BKN100 26/17 Q1013=", # [cite: 18]
        "SPECI SBTA 070335Z 16005KT 120V190 3000 -RA BR BKN015 BKN035 22/22 Q1018=", # [cite: 18]
        "SPECI SBTA 080410Z 10004KT 9999 -DZ BKN006 BKN016 BKN100 23/22 Q1019=", # [cite: 18]
        "SPECI SBTA 082202Z 10007KT 060V140 9999 TS VCSH SCT025 BKN030 FEW035CB 24/23 Q1016=", # [cite: 18]
        "SPECI SBTA 091643Z VRB02KT 9999 -TSRA SCT035 FEW040CB 30/21 Q1012=", # [cite: 18]
        "SPECI SBTA 091712Z 24010KT 8000 TSRA BKN030 FEW035CB 26/25 Q1013=", # [cite: 18]
        "SPECI SBTA 091717Z 25010KT 210V300 2000 TSRA BR SCT014 BKN030 FEW035CB 25/25 Q1013=", # [cite: 18]
        "SPECI SBTA 091737Z VRB01KT 6000 TS SCT025 FEW030CB 24/24 Q1013 RERA=", # [cite: 18]
        "SPECI SBTA 091834Z 02003KT 290V070 9999 FEW030 FEW035TCU SCT080 26/24 Q1012 RETS=", # [cite: 18]
        "SPECI SBTA 091913Z 08004KT 020V120 9999 -TSRA FEW030 FEW040CB BKN080 26/23 Q1012=", # [cite: 18, 19]
        "SPECI SBTA 091936Z VRB10KT 2000 TSRA BR BKN013 FEW030CB BKN080 24/23 Q1013=", # [cite: 19]
        "SPECI SBTA 092019Z 14003KT 100V200 9999 FEW013 FEW030TCU BKN080 24/24 Q1012 RETS=", # [cite: 19]
        "SPECI SBTA 092122Z VRB02KT 9999 FEW025 BKN100 24/24 Q1013=", # [cite: 19]
        "SPECI SBTA 102121Z 18006KT 150V230 9999 VCSH FEW030 FEW035TCU 26/20 Q1014=", # [cite: 19]
        "SPECI SBTA 120347Z 19005KT 9999 BKN024 21/17 Q1020=", # [cite: 19]
        "SPECI SBTA 141238Z 09006KT 050V120 8000 SCT013 BKN018 25/21 Q1017=", # [cite: 19]
        "SPECI SBTA 162116Z 24007KT 9999 FEW040 SCT070 28/20 Q1010=", # [cite: 19]
        "SPECI SBTA 172115Z VRB02KT 9999 SCT040 FEW045TCU SCT080 28/22 Q1012=", # [cite: 19]
        "SPECI SBTA 190930Z 16003KT 3000 BR OVC005 22/22 Q1014=", # [cite: 19]
        "SPECI SBTA 191222Z VRB02KT 5000 BR OVC008 23/22 Q1015=", # [cite: 19]
        "SPECI SBTA 200933Z 01004KT 070V130 4000 1000NE BR BKN006 22/22 Q1011=", # [cite: 19, 20]
        "SPECI SBTA 201245Z VRB03KT 9999 SCT010 26/23 Q1013=", # [cite: 20]
        "SPECI SBTA 201922Z 12004KT 9999 SCT035 FEW040TCU BKN100 26/22 Q1008 RETS=", # [cite: 20]
        "SPECI SBTA 221113Z 13006KT 090V170 2000 -RA BR BKN005 BKN015 OVC035 22/22 Q1017=", # [cite: 20]
        "SPECI SBTA 221140Z 17004KT 120V220 3000 -RA BR BKN005 BKN010 OVC020 22/22 Q1018=", # [cite: 20]
        "SPECI SBTA 221225Z 20003KT 120V260 6000 -RA SCT010 BKN020 OVC035 22/22 Q1018=", # [cite: 20]
        "SPECI SBTA 222111Z 18006KT 110V240 3000 -RA BR BKN020 OVC040 20/17 Q1020=", # [cite: 20]
        "SPECI SBTA 231912Z 35003KT 310V020 6000 -RA BKN008 OVC015 19/19 Q1020=", # [cite: 20]
        "SPECI SBTA 232011Z VRB02KT 3000 RA BR OVC015 19/19 Q1020=", # [cite: 20]
        "SPECI SBTA 232109Z VRB02KT 4000 RA BR OVC015 19/18 Q1021=", # [cite: 20]
        "SPECI SBTA 242108Z VRB02KT 8000 SCT019 BKN040 OVC047 21/20 Q1017=", # [cite: 20, 21]
        "SPECI SBTA 251135Z VRB01KT 9000 SCT007 BKN010 21/20 Q1016=", # [cite: 21]
        "SPECI SBTA 271010Z 06002KT 3000 BR BKN003 OVC010 19/19 Q1019=", # [cite: 21]
        "SPECI SBTA 271030Z 00000KT 4000 BR SCT003 OVC006 19/19 Q1019=", # [cite: 21]
        "SPECI SBTA 271920Z 02004KT 4000 -RA BR SCT010 BKN020 OVC028 21/20 Q1018=", # [cite: 21]
        "SPECI SBTA 030517Z VRB01KT CAVOK 19/19 Q1014=", # [cite: 21]
        "SPECI SBTA 090002Z 16009KT 4000 RA BR BKN030 SCT070 BKN100 22/19 Q1017=", # [cite: 21]
        "SPECI SBTA 090015Z 16009KT 120V190 5000 -RA BR FEW019 SCT025 BKN030 21/20 Q1017 RERA=", # [cite: 21]
        "SPECI SBTA 101335Z VRB02KT 7000 SCT010 24/21 Q1016=", # [cite: 21]
        "SPECI SBTA 122007Z 15006KT 120V190 4000 -RA HZ SCT035 25/20 Q1017=", # [cite: 21]
        "SPECI SBTA 171925Z 35004KT 9000 RA BKN025 FEW035TCU BKN100 26/21 Q1013=", # [cite: 21]
        "SPECI SBTA 290930Z VRB01KT 0800 FG SCT004 BKN008 19/18 Q1018=", # [cite: 22]
        "SPECI SBTA 290940Z 00000KT 1500 BR FEW001 SCT004 19/19 Q1018=", # [cite: 22]
        "SPECI SBTA 050815Z VRB01KT CAVOK 16/16 Q1019=", # [cite: 22]
        "SPECI SBTA 052105Z VRB01KT CAVOK 24/16 Q1018=", # [cite: 22]
        "SPECI SBTA 100940Z 00000KT 5000 BR BKN005 16/16 Q1019=", # [cite: 22]
        "SPECI SBTA 101227Z 02002KT 5000 BR SCT005 22/19 Q1020=", # [cite: 22]
        "SPECI SBTA 111024Z VRB01KT 0800 FG OVC002 18/17 Q1017=", # [cite: 22]
        "SPECI SBTA 111312Z 02003KT 300V090 4000 BR SCT007 22/19 Q1017=", # [cite: 22]
    ]

    # METARs
    metars_simulados = [
        "METAR SBTA 032000Z 04004KT 9999 TS VCSH BKN035 FEW040CB 22/19 Q1017=", # [cite: 22]
        "METAR SBTA 032100Z 16009KT 9999 VCSH BKN035 FEW040TCU OVC100 20/18 Q1019 RETS=", # [cite: 22]
        "METAR SBTA 032200Z 05002KT 9999 -TSRA BKN035 FEW040TCU OVC080 20/19 Q1019=", # [cite: 22]
        "METAR SBTA 040900Z 18002KT 0800 FG FEW015 19/19 Q1018=", # [cite: 22, 23]
        "METAR SBTA 041000Z 25002KT 9999 TS SCT015CB 20/19 Q1019=", # [cite: 23]
        "METAR SBTA 041100Z VRB02KT 9999 TS SCT020CB 21/19 Q1019=", # [cite: 23]
        "METAR SBTA 041200Z VRB02KT 9999 4000E BCFG SCT017 24/19 Q1019=", # [cite: 23]
        "METAR SBTA 041300Z 05007KT 9999 4000E SCT017 25/21 Q1020=", # [cite: 23]
        "METAR SBTA 041400Z 07005KT 9999 FEW025 27/21 Q1019=", # [cite: 23]
        "METAR SBTA 041500Z VRB02KT 9999 FEW030 28/20 Q1018=", # [cite: 23]
        "METAR SBTA 041600Z 27003KT 200V010 9999 SCT035 FEW040TCU BKN080 29/20 Q1017=", # [cite: 23]
        "METAR SBTA 041700Z 35009KT 9999 4000S TS VCSH BKN035 FEW040CB BKN100 26/19 Q1017=", # [cite: 23]
        "METAR SBTA 041800Z 14011KT 080V180 3000 -TSRA BR FEW006 BKN020 BKN030 FEW040CB 21/19 Q1019=", # [cite: 23, 24]
        "METAR SBTA 041900Z VRB06KT 9999 -RA FEW009 SCT025 BKN040 FEW045TCU 20/18 Q1019 RETS=", # [cite: 24]
        "METAR SBTA 042000Z VRB02KT 9999 FEW009 SCT045 OVC090 20/19 Q1019=", # [cite: 24]
        "METAR SBTA 042100Z 21050KT 9999 SCT045 OVC090 20/19 Q1019=", # [cite: 24]
        "METAR SBTA 050900Z 29030KT 260V320 6000 FEW004 BKN100 18/18 Q1018=", # [cite: 24]
        "METAR SBTA 051000Z 27003KT 240V300 3000 BR OVC003 19/18 Q1018=", # [cite: 24]
        "METAR SBTA 051100Z VRB02KT 5000 BR OVC007 20/19 Q1019=", # [cite: 24]
        "METAR SBTA 051200Z VRB02KT 6000 OVC008 21/19 Q1019=", # [cite: 24]
        "METAR SBTA 051300Z VRB02KT 9999 FEW010 23/19 Q1019=", # [cite: 24]
        "METAR SBTA 051400Z VRB02KT 9999 FEW020 25/20 Q1019=", # [cite: 24]
        "METAR SBTA 051500Z VRB03KT 9999 FEW030 FEW035TCU 28/19 Q1018=", # [cite: 24]
        "METAR SBTA 051600Z VRB03KT 9999 FEW035 FEW040TCU 29/19 Q1017=", # [cite: 24]
        "METAR SBTA 051700Z VRB03KT 9999 FEW035 FEW040TCU 30/18 Q1016=", # [cite: 24]
        "METAR SBTA 051800Z 26003KT 210V330 9999 SCT040 FEW045TCU 31/18 Q1015=", # [cite: 24, 25]
        "METAR SBTA 051900Z 27004KT 230V310 9999 SCT040 FEW045TCU 30/18 Q1014=", # [cite: 25]
        "METAR SBTA 052000Z 18005KT 140V230 9999 SCT045 FEW050TCU 30/17 Q1014=", # [cite: 25]
        "METAR SBTA 052100Z 16006KT 120V210 9999 VCSH FEW045 FEW050TCU 29/18 Q1014=", # [cite: 25]
        "METAR SBTA 052200Z 15004KT 9999 FEW045 27/19 Q1015=", # [cite: 25]
        "METAR SBTA 052300Z 15005KT 110V180 9999 FEW045 25/18 Q1016=", # [cite: 25]
        "METAR SBTA 060000Z 14005KT 080V170 9999 FEW040 24/17 Q1017=", # [cite: 25]
        "METAR SBTA 060100Z VRB01KT CAVOK 22/19 Q1018=", # [cite: 25]
        "METAR SBTA 060200Z VRB01KT CAVOK 21/19 Q1018=", # [cite: 25]
        "METAR SBTA 060300Z VRB01KT CAVOK 21/19 Q1018=", # [cite: 25]
        "METAR SBTA 060900Z VRB01KT CAVOK 18/18 Q1018=", # [cite: 25]
        "METAR SBTA 061000Z VRB02KT CAVOK 20/18 Q1018=", # [cite: 25]
        "METAR SBTA 061100Z VRB02KT CAVOK 22/19 Q1019=", # [cite: 25]
        "METAR SBTA 061200Z VRB02KT 9999 FEW020 25/19 Q1019=", # [cite: 25, 26]
        "METAR SBTA 061300Z 14002KT 9999 FEW020 26/20 Q1019=", # [cite: 26]
        "METAR SBTA 061400Z VRB03KT 9999 SCT025 28/20 Q1019=", # [cite: 26]
        "METAR SBTA 061600Z VRB03KT 9999 SCT035 FEW040TCU 31/18 Q1018=", # [cite: 26]
        "METAR SBTA 061500Z 22005KT 150V260 9999 SCT030 FEW035TCU 30/17 Q1018=", # [cite: 26]
        "METAR SBTA 061700Z 22005KT 150V260 9999 SCT040 FEW045TCU BKN070 30/19 Q1017=", # [cite: 26]
        "METAR SBTA 061800Z 29004KT 9999 SCT040 FEW045TCU SCT078 28/19 Q1016=", # [cite: 26]
        "METAR SBTA 061900Z 18005KT 120V250 9999 SCT040 FEW045TCU SCT100 31/19 Q1015=", # [cite: 26]
        "METAR SBTA 062000Z 16008KT 120V190 9999 SCT040 FEW045TCU 30/17 Q1015=", # [cite: 26]
        "METAR SBTA 062100Z 16009KT 130V190 9999 FEW040 FEW045TCU 28/18 Q1015=", # [cite: 26]
        "METAR SBTA 062200Z 15004KT 110V190 9999 FEW040 FEW045TCU 26/19 Q1016=", # [cite: 26]
    ]


    # Distribui as mensagens de acordo com o endpoint e o aeródromo
    # A lógica foi aprimorada para retornar todas as mensagens para SBTA
    mensagens_para_aerodromo = []
    
    if aerodromo and aerodromo.upper() == "SBTA":
        if "AVISO" in endpoint.upper(): # Alterado para .upper()
            for msg in avisos_simulados:
                # Filtrar apenas avisos que incluem SBTA
                if aerodromo.upper() in msg.upper().split('/'): # Verifica se SBTA está na lista de aeródromos do aviso
                    mensagens_para_aerodromo.append({"mensagem": msg})
        elif "TAF" in endpoint.upper(): # Alterado para .upper()
            for msg in tafs_simulados:
                if aerodromo.upper() in msg.upper():
                    mensagens_para_aerodromo.append({"mensagem": msg})
        elif "METAR" in endpoint.upper(): # Alterado para .upper() # Inclui SPECI
            for msg in metars_simulados + specis_simulados: # Concatena as listas de METAR e SPECI
                if aerodromo.upper() in msg.upper():
                    mensagens_para_aerodromo.append({"mensagem": msg})
        else:
            print(f"Endpoint desconhecido para simulação: {endpoint}")

    return {"data": mensagens_para_aerodromo}


# def obter_mensagens_redemet(endpoint, aerodromo=None):
#     """Busca dados na API da REDEMET."""
#     headers = {"X-API-KEY": REDEMET_API_KEY}
#     url = f"https://api-redemet.decea.mil.br/mensagens/{endpoint}"
#     params = {"localidade": aerodromo} if aerodromo else {}
#     try:
#         response = requests.get(url, headers=headers, params=params)
#         response.raise_for_status()
#         return response.json()
#     except requests.exceptions.RequestException as e:
#         print(f"Erro ao buscar dados da REDEMET: {e}")
#         return None

def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """
    Função para o robô 'ler' a mensagem e procurar por códigos severos e contexto.
    Retorna uma lista dos alertas de texto encontrados, com base nos seus critérios.
    """
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    # --- Análise de Fenômenos Específicos (METAR/TAF/Aviso) ---

    # Lógica principal para METAR e TAF (Mantida como estava e funciona bem)
    if "METAR" in tipo_mensagem.upper() or "SPECI" in tipo_mensagem.upper() or "TAF" in tipo_mensagem.upper():
        for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
            if codigo_icao in mensagem_upper:
                # Lógica para "OVC" e "BKN" abaixo de 600 pés (006)
                if codigo_icao in ["OVC", "BKN"]:
                    if re.search(f"{codigo_icao}00[1-5]", mensagem_upper): 
                        alertas_encontrados.append(f"{descricao} (TETO BAIXO < 600FT)")
                # Lógica para "FG" (Nevoeiro) - verificar visibilidade < 1000m
                elif codigo_icao == "FG":
                    vis_match = re.search(r'\s(\d{4})\s', mensagem_upper) 
                    if vis_match:
                        visibility_meters = int(vis_match.group(1))
                        if visibility_meters < 1000:
                            alertas_encontrados.append(f"{descricao} (VISIBILIDADE < 1000M)")
                    elif "FG" in mensagem_upper: 
                         alertas_encontrados.append(descricao) 
                # Lógica para "+RA" (Chuva Forte)
                elif codigo_icao == "RA" and "+RA" in mensagem_upper:
                    alertas_encontrados.append("Chuva Forte")
                # Lógica para CB (Cumulunimbus) com altura
                elif codigo_icao == "CB":
                    cb_match = re.search(r'(FEW|SCT|BKN|OVC)(\d{3})CB', mensagem_upper)
                    if cb_match:
                        cloud_height = int(cb_match.group(2)) * 100
                        alertas_encontrados.append(f"{descricao} a {cloud_height}FT")
                    else: # Se CB está, mas sem altura específica na formação
                        alertas_encontrados.append(descricao)
                # Outros códigos que são diretos
                else: 
                    alertas_encontrados.append(descricao)
            
        # --- Lógica para ventos acima de 20KT e rajadas acima de 20KT (para METAR/SPECI/TAF) ---
        wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
        if wind_match:
            sustained_wind_str = wind_match.group(2)
            gust_wind_str = wind_match.group(4) 

            sustained_wind = int(sustained_wind_str)
            
            wind_desc = []
            if sustained_wind > 20:
                wind_desc.append(f"Vento Médio de {sustained_wind}KT")
            
            if gust_wind_str:
                gust_wind = int(gust_wind_str)
                if gust_wind > 20:
                    wind_desc.append(f"Rajadas de {gust_wind}KT")

            if wind_desc: 
                alertas_encontrados.append(" e ".join(wind_desc))

        # Lógica para TAF (previsão) - procurar por fenômenos e condições em TEMPO/BECMG/PROB30/40
        if "TAF" in tipo_mensagem.upper(): # Verifica novamente, caso a mensagem seja TAF
            for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
                # Fenômenos em PROB, TEMPO, BECMG
                if f"PROB30 {codigo_icao}" in mensagem_upper or f"PROB40 {codigo_icao}" in mensagem_upper:
                    alertas_encontrados.append(f"PREVISÃO PROB: {descricao}")
                if f"TEMPO {codigo_icao}" in mensagem_upper:
                    alertas_encontrados.append(f"PREVISÃO TEMPO: {descricao}")
                if f"BECMG {codigo_icao}" in mensagem_upper:
                    alertas_encontrados.append(f"PREVISÃO BECMG: {descricao}")
                
                # Teto baixo em TAF
                if codigo_icao in ["OVC", "BKN"]:
                    if re.search(f"{codigo_icao}00[1-5]", mensagem_upper): 
                        alertas_encontrados.append(f"PREVISÃO: {descricao} (TETO BAIXO < 600FT)")
                # Nevoeiro em TAF
                if codigo_icao == "FG":
                    if re.search(r'\s(\d{4})\s', mensagem_upper) and int(re.search(r'\s(\d{4})\s', mensagem_upper).group(1)) < 1000:
                        alertas_encontrados.append(f"PREVISÃO: {descricao} (VISIBILIDADE < 1000M)")
                    elif "FG" in mensagem_upper:
                        alertas_encontrados.append(f"PREVISÃO: {descricao}")

            # Ventos e rajadas em TAF (revisado para usar a lógica comum)
            wind_groups_in_taf = re.findall(r'(TEMPO|BECMG|PROB\d{2})\s.*?(VRB|\d{3})(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
            for group in wind_groups_in_taf:
                prefix = group[0]
                sustained_wind_str = group[2]
                gust_wind_str = group[4] 
                
                sustained_wind = int(sustained_wind_str)
                
                wind_desc_taf = []
                if sustained_wind > 20:
                    wind_desc_taf.append(f"Vento Médio de {sustained_wind}KT")
                
                if gust_wind_str:
                    gust_wind = int(gust_wind_str)
                    if gust_wind > 20:
                        wind_desc_taf.append(f"Rajadas de {gust_wind}KT")

                if wind_desc_taf:
                    alertas_encontrados.append(f"PREVISÃO {prefix}: {' e '.join(wind_desc_taf)}")


    # --- Lógica para Avisos de Aeródromo (Refinada) ---
    if "AVISO" in tipo_mensagem.upper():
        aviso_fenomenos_desc = []
        
        # 1. Detectar TS (Trovoada) explicitamente
        if "TS" in mensagem_upper:
            aviso_fenomenos_desc.append("Trovoada")

        # 2. Detectar Vento de Superfície e Rajada (SFC WSPD 15KT MAX 25)
        wind_warning_match = re.search(r'SFC WSPD (\d+KT)(?: MAX (\d+))?', mensagem_upper)
        if wind_warning_match:
            min_wind = wind_warning_match.group(1)
            max_wind = wind_warning_match.group(2)
            if max_wind:
                aviso_fenomenos_desc.append(f"Vento de Superfície entre {min_wind} e {max_wind}KT")
            else:
                aviso_fenomenos_desc.append(f"Vento de Superfície de {min_wind}")

        # 3. Detectar outros termos relevantes de Avisos (se necessário, adicione aqui de forma explícita)
        # Ex: Se aparecer "GRANIZO" em texto, adicione. Evite apenas "GR" para não pegar falsos positivos.
        if "GRANIZO" in mensagem_upper:
            aviso_fenomenos_desc.append("Granizo")
        if "NEVOEIRO" in mensagem_upper or "FG" in mensagem_upper: # Adicionado FG para o aviso
             aviso_fenomenos_desc.append("Nevoeiro")
        if "CHUVA FORTE" in mensagem_upper or "+RA" in mensagem_upper:
            aviso_fenomenos_desc.append("Chuva Forte")
        if "VISIBILIDADE REDUZIDA" in mensagem_upper:
            aviso_fenomenos_desc.append("Visibilidade Reduzida")
        if "WIND SHEAR" in mensagem_upper or "WS" in mensagem_upper:
            aviso_fenomenos_desc.append("Tesoura de Vento (Wind Shear)")
        if "CINZAS VULCÂNICAS" in mensagem_upper or "VA" in mensagem_upper:
            aviso_fenomenos_desc.append("Cinzas Vulcânicas")
        if "FUMAÇA" in mensagem_upper or "FU" in mensagem_upper:
            aviso_fenomenos_desc.append("Fumaça")
            
        # Adiciona os fenômenos detectados à lista final, garantindo que não há duplicatas
        if aviso_fenomenos_desc:
            alertas_encontrados.extend(list(set(aviso_fenomenos_desc)))
        else: 
            alertas_encontrados.append("Conteúdo não mapeado")


    return list(set(alertas_encontrados)) # Retorna a lista de alertas únicos no final


def verificar_e_alertar():
    """Verifica as condições meteorológicas e envia alertas."""
    print("Verificando condições meteorológicas...")
    
    agora_utc = datetime.now(pytz.utc)

    for aerodromo in AERODROMOS_INTERESSE:
        # --- Avisos de Aeródromo ---
        avisos_data = obter_mensagens_redemet_simulada("avisos", aerodromo) # Usando a função simulada
        if avisos_data and avisos_data['data']:
            for aviso in avisos_data['data']:
                mensagem_aviso = aviso['mensagem']
                aviso_hash = calcular_hash_mensagem(mensagem_aviso)

                if aviso_hash not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_aviso, "AVISO")
                    if condicoes_perigosas and "Conteúdo não mapeado" not in condicoes_perigosas: # Evita alertar se não mapeou nada
                        alert_message = (
                            f"🚨 *NOVO ALERTA DE AERÓDROMO PARA {aerodromo}!* 🚨\n\n"
                            f"Condições Previstas: {', '.join(condicoes_perigosas)}\n\n"
                            f"Mensagem Original:\n`{mensagem_aviso}`\n\n"
                            f"(Hora do Agente: {agora_utc.strftime('%Y-%m-%d %H:%M:%S UTC')})"
                        )
                        enviar_mensagem_telegram(TELEGRAM_CHAT_ID, alert_message)
                        alertas_enviados_cache[aviso_hash] = agora_utc
                        print(f"Alerta de AVISO enviado para {aerodromo}.")
                    else:
                        print(f"Aviso de Aeródromo para {aerodromo} sem condições perigosas detectadas ou não mapeadas: {mensagem_aviso}")
                else:
                    print(f"Aviso de Aeródromo para {aerodromo} já alertado: {mensagem_aviso}")

        # --- TAFs ---
        tafs_data = obter_mensagens_redemet_simulada("taf", aerodromo) # Usando a função simulada
        if tafs_data and tafs_data['data']:
            for taf in tafs_data['data']:
                mensagem_taf = taf['mensagem']
                taf_hash = calcular_hash_mensagem(mensagem_taf)

                if taf_hash not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_taf, "TAF")
                    if condicoes_perigosas and "Conteúdo não mapeado" not in condicoes_perigosas:
                        alert_message = (
                            f"⚠️ *NOVO ALERTA TAF PARA {aerodromo}!* ⚠️\n\n"
                            f"Previsão de Fenômenos: {', '.join(condicoes_perigosas)}\n\n"
                            f"Mensagem Original:\n`{mensagem_taf}`\n\n"
                            f"(Hora do Agente: {agora_utc.strftime('%Y-%m-%d %H:%M:%S UTC')})"
                        )
                        enviar_mensagem_telegram(TELEGRAM_CHAT_ID, alert_message)
                        alertas_enviados_cache[taf_hash] = agora_utc
                        print(f"Alerta de TAF enviado para {aerodromo}.")
                    else:
                        print(f"TAF para {aerodromo} sem condições perigosas detectadas ou não mapeadas: {mensagem_taf}")
                else:
                    print(f"TAF para {aerodromo} já alertado: {mensagem_taf}")

        # --- METARs e SPECI ---
        # A API da REDEMET tem um endpoint para "metar" que geralmente inclui SPECI.
        # Estamos concatenando as listas simuladas de METAR e SPECI na função `obter_mensagens_redemet_simulada`.
        metars_data = obter_mensagens_redemet_simulada("metar", aerodromo) # Usando a função simulada
        if metars_data and metars_data['data']:
            for metar_speci in metars_data['data']:
                mensagem_metar_speci = metar_speci['mensagem']
                metar_speci_hash = calcular_hash_mensagem(mensagem_metar_speci)

                # Determinar se é METAR ou SPECI
                tipo = "SPECI" if mensagem_metar_speci.startswith("SPECI") else "METAR"

                if metar_speci_hash not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_metar_speci, tipo)
                    if condicoes_perigosas and "Conteúdo não mapeado" not in condicoes_perigosas:
                        alert_message = (
                            f"⚡️ *NOVO ALERTA {tipo} PARA {aerodromo}!* ⚡️\n\n"
                            f"Condições Atuais: {', '.join(condicoes_perigosas)}\n\n"
                            f"Mensagem Original:\n`{mensagem_metar_speci}`\n\n"
                            f"(Hora do Agente: {agora_utc.strftime('%Y-%m-%d %H:%M:%S UTC')})"
                        )
                        enviar_mensagem_telegram(TELEGRAM_CHAT_ID, alert_message)
                        alertas_enviados_cache[metar_speci_hash] = agora_utc
                        print(f"Alerta de {tipo} enviado para {aerodromo}.")
                    else:
                        print(f"{tipo} para {aerodromo} sem condições perigosas detectadas ou não mapeadas: {mensagem_metar_speci}")
                else:
                    print(f"{tipo} para {aerodromo} já alertado: {mensagem_metar_speci}")

    # Limpar cache de alertas antigos (opcional, para evitar que o cache cresça indefinidamente)
    # Por exemplo, remover alertas com mais de 24 horas
    for msg_hash in list(alertas_enviados_cache.keys()):
        if agora_utc - alertas_enviados_cache[msg_hash] > timedelta(hours=24):
            del alertas_enviados_cache[msg_hash]

# --- Loop Principal ---
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erro: Variáveis de ambiente TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configuradas.")
        print("Por favor, defina-as antes de executar o script.")
    else:
        print(f"Iniciando monitoramento. Verificando a cada {INTERVALO_VERIFICACAO} segundos.")
        while True:
            verificar_e_alertar()
            time.sleep(INTERVALO_VERIFICACAO)
