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
# ATENÇÃO: HZ (Névoa Seca) foi removido, e a detecção de VA (Cinzas Vulcânicas) será mais específica.
CODIGOS_METAR_TAF_MAP = {
    "TS": "Trovoada",
    "RA": "Chuva",
    "+RA": "Chuva Forte", 
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
    # "HZ": "Névoa Seca (Haze)", # REMOVIDO: Não necessário para alertas críticos
    "FU": "Fumaça",
    # "VA": "Cinzas Vulcânicas", # REMOVIDO DAQUI para detecção mais específica
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
    "SH": "Pancada (Shower)", 
    "OVC": "Nublado (Overcast)", 
    "BKN": "Parcialmente Nublado (Broken)", 
    "CB": "Cumulunimbus", 
    "TCU": "Cumulus Castellanus", 
    "WS": "Tesoura de Vento (Wind Shear)", 
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
    
    # Exemplo de data dinâmica para as mensagens simuladas
    hoje_utc = datetime.now(pytz.utc)
    dia_str = hoje_utc.strftime('%d') # Dia atual
    hora_str = hoje_utc.strftime('%H') # Hora atual
    minuto_str = hoje_utc.strftime('%M') # Minuto atual
    proxima_hora_str = (hoje_utc + timedelta(hours=1)).strftime('%H') # Próxima hora
    proxima_hora_min_str = (hoje_utc + timedelta(minutes=5)).strftime('%H%M') # Próxima hora e 5 minutos


    # AVISOS DE AERÓDROMO (usando data dinâmica para parecerem "frescos")
    avisos_simulados = [
        f"SBGL SBSJ/SBTA AD WRNG 1 VALID {dia_str}{hora_str}00/{dia_str}{proxima_hora_str}00 TS SFC WSPD 15KT MAX 30 FCST NC=", 
        f"SBGR SBBP/SBTA AD WRNG 2 VALID {dia_str}{hoje_utc.strftime('%H%M')}/{dia_str}{(hoje_utc + timedelta(hours=2)).strftime('%H%M')} SFC WSPD 20KT MAX 35 FCST NC=",
        f"SBSP SBTA AD WRNG 3 VALID {dia_str}{hoje_utc.replace(hour=2, minute=0, second=0, microsecond=0).strftime('%H%M')}/{dia_str}{hoje_utc.replace(hour=6, minute=0, second=0, microsecond=0).strftime('%H%M')} FG VIS < 500M FCST NC=",
        f"SBTA WS WRNG 4 VALID {dia_str}{hoje_utc.strftime('%H%M')}/{dia_str}{(hoje_utc + timedelta(minutes=90)).strftime('%H%M')} MOD WS IN APCH RWY28 REP AT {hoje_utc.strftime('%H%M')}Z A320=",
        f"SBRJ SBTA AD WRNG 5 VALID {dia_str}{hoje_utc.strftime('%H%M')}/{dia_str}{(hoje_utc + timedelta(hours=4)).strftime('%H%M')} TS SFC WSPD 25KT MAX 45 FCST NC=",
        f"SBGO SBTA AD WRNG 6 VALID {dia_str}{hoje_utc.replace(hour=11, minute=0, second=0, microsecond=0).strftime('%H%M')}/{dia_str}{hoje_utc.replace(hour=14, minute=0, second=0, microsecond=0).strftime('%H%M')} +RA FCST NC=",
        f"SBTA AD WRNG 7 VALID {dia_str}{hora_str}{minuto_str}/{dia_str}{(hoje_utc + timedelta(hours=3)).strftime('%H%M')} VA FCST NC=", # Exemplo com VA real
    ]

    # TAFs (usando data dinâmica)
    tafs_simulados = [
        f"TAF SBTA {dia_str}{hora_str}00Z {dia_str}{hora_str}/{(int(dia_str)+1):02d}{hora_str} 33010KT 9999 SCT015 BKN030 TX25/{dia_str}{(hoje_utc + timedelta(hours=3)).strftime('%H')}Z TN18/{ (int(dia_str)+1):02d}{(hoje_utc + timedelta(hours=15)).strftime('%H')}Z TEMPO {dia_str}{(hoje_utc + timedelta(hours=2)).strftime('%H')}/{dia_str}{(hoje_utc + timedelta(hours=6)).strftime('%H')} 30020G35KT 4000 TSRA BKN008 FEW030CB BECMG {dia_str}{(hoje_utc + timedelta(hours=6)).strftime('%H')}/{dia_str}{(hoje_utc + timedelta(hours=8)).strftime('%H')} 27010KT 9999 NSW SCT020 RMK PBZ=",
        f"TAF SBTA {dia_str}0000Z {dia_str}00/{dia_str}24 00000KT 9999 SKC TX28/{dia_str}17Z TN15/{dia_str}06Z PROB40 {dia_str}03/{dia_str}08 0800 FG OVC002 BECMG {dia_str}10/{dia_str}12 9999 NSW RMK PST=",
        f"TAF SBTA {dia_str}0600Z {dia_str}06/{(int(dia_str)+1):02d}06 18008KT 9999 FEW025 SCT040 TEMPO {dia_str}08/{dia_str}12 20015KT 3000 +RA BKN010 RMK PQL=",
        f"TAF SBTA {dia_str}1800Z {dia_str}18/{(int(dia_str)+1):02d}18 27005KT CAVOK TX26/{dia_str}19Z TN16/{(int(dia_str)+1):02d}07Z RMK PRS=",
    ]

    # SPECIs (usando data dinâmica)
    specis_simulados = [
        f"SPECI SBTA {dia_str}{proxima_hora_min_str}Z 25022KT 9000 TS SCT030 FEW040CB BKN100 22/18 Q1015=",
        f"SPECI SBTA {dia_str}{(hoje_utc + timedelta(minutes=10)).strftime('%H%M')}Z 18015G30KT 3000 +RA BR BKN010 OVC020 20/19 Q1016=",
        f"SPECI SBTA {dia_str}{hoje_utc.replace(hour=3, minute=30, second=0, microsecond=0).strftime('%H%M')}Z 00000KT 0500 FG OVC001 15/15 Q1020=",
        # Exemplo de SPECI com VA para testar a detecção precisa
        f"SPECI SBTA {dia_str}{(hoje_utc + timedelta(minutes=30)).strftime('%H%M')}Z VRB03KT 9999 VA BKN008 20/19 Q1018=",
        f"SPECI SBTA {dia_str}{(hoje_utc + timedelta(minutes=5)).strftime('%H%M')}Z VRB02KT 9999 WS RWY28 25/20 Q1015=",
    ]

    # METARs (usando data dinâmica)
    metars_simulados = [
        f"METAR SBTA {dia_str}{proxima_hora_min_str}Z 18005KT 9999 SCT025 24/18 Q1017=",
        f"METAR SBTA {dia_str}{(hoje_utc + timedelta(minutes=10)).strftime('%H%M')}Z 15012KT 9999 -RA BKN030 23/19 Q1016=",
        f"METAR SBTA {dia_str}{(hoje_utc + timedelta(minutes=15)).strftime('%H%M')}Z 29025G38KT 9999 FEW040 25/17 Q1014=",
        f"METAR SBTA {dia_str}{(hoje_utc + timedelta(minutes=20)).strftime('%H%M')}Z VRB03KT 9999 BKN005 20/19 Q1018=",
        f"METAR SBTA {dia_str}{(hoje_utc + timedelta(minutes=25)).strftime('%H%M')}Z 12007KT 9999 TS SCT030 FEW040CB 26/20 Q1015=",
    ]


    # Distribui as mensagens de acordo com o endpoint e o aeródromo
    mensagens_para_aerodromo = []
    
    if aerodromo and aerodromo.upper() == "SBTA":
        if "AVISO" in endpoint.upper():
            for msg in avisos_simulados:
                if aerodromo.upper() in msg.upper():
                    mensagens_para_aerodromo.append({"mensagem": msg})
        elif "TAF" in endpoint.upper():
            for msg in tafs_simulados: 
                if aerodromo.upper() in msg.upper():
                    mensagens_para_aerodromo.append({"mensagem": msg})
        elif "METAR" in endpoint.upper():
            for msg in metars_simulados + specis_simulados: 
                if aerodromo.upper() in msg.upper():
                    mensagens_para_aerodromo.append({"mensagem": msg})
        else:
            print(f"Endpoint desconhecido para simulação: {endpoint}")

    return {"data": mensagens_para_aerodromo}

def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """
    Função para o robô 'ler' a mensagem e procurar por códigos severos e contexto.
    Retorna uma lista dos alertas de texto encontrados, com base nos seus critérios.
    """
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    # --- Análise de Fenômenos Específicos (METAR/TAF/Aviso) ---

    if "METAR" in tipo_mensagem.upper() or "SPECI" in tipo_mensagem.upper() or "TAF" in tipo_mensagem.upper():
        for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
            # Usar regex para garantir que o código é uma palavra inteira (delimitações)
            # ou parte de um código composto relevante (ex: +RA, FZRA)
            if re.search(r'\b' + re.escape(codigo_icao) + r'\b', mensagem_upper) or \
               (codigo_icao == "+RA" and "+RA" in mensagem_upper) or \
               (codigo_icao == "-RA" and "-RA" in mensagem_upper) or \
               (codigo_icao == "FZRA" and "FZRA" in mensagem_upper):

                if codigo_icao in ["OVC", "BKN"]:
                    if re.search(f"{codigo_icao}00[1-5]", mensagem_upper): 
                        alertas_encontrados.append(f"{descricao} (TETO BAIXO < 600FT)")
                elif codigo_icao == "FG":
                    vis_match = re.search(r'\s(\d{4})\s', mensagem_upper) 
                    if vis_match:
                        visibility_meters = int(vis_match.group(1))
                        if visibility_meters < 1000:
                            alertas_encontrados.append(f"{descricao} (VISIBILIDADE < 1000M)")
                    elif "FG" in mensagem_upper: 
                         alertas_encontrados.append(descricao) 
                elif codigo_icao == "+RA": # +RA já é um código específico agora
                    alertas_encontrados.append("Chuva Forte")
                elif codigo_icao == "CB":
                    cb_match = re.search(r'(FEW|SCT|BKN|OVC)(\d{3})CB', mensagem_upper)
                    if cb_match:
                        cloud_height = int(cb_match.group(2)) * 100
                        alertas_encontrados.append(f"{descricao} a {cloud_height}FT")
                    else: 
                        alertas_encontrados.append(descricao)
                else: 
                    alertas_encontrados.append(descricao)
        
        # DETECÇÃO ESPECÍFICA PARA CINZAS VULCÂNICAS (VA)
        # Verifica se VA está como um fenômeno (ex: em uma sequência de tempo, após vento/visibilidade)
        if re.search(r'(?:[A-Z]{2}\s)?VA\b', mensagem_upper) and "VALID" not in mensagem_upper: # Ignora se "VALID" estiver na mesma linha
            alertas_encontrados.append("Cinzas Vulcânicas (VA)")

        # --- Lógica para ventos acima de 20KT e rajadas acima de 20KT (para METAR/SPECI/TAF) ---
        wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
        if wind_match:
            sustained_wind_str = wind_match.group(2)
            gust_wind_str = wind_match.group(4) 

            sustained_wind = int(sustained_wind_str)
            
            wind_desc = []
            if sustained_wind >= 20: 
                wind_desc.append(f"Vento Médio de {sustained_wind}KT")
            
            if gust_wind_str:
                gust_wind = int(gust_wind_str)
                if gust_wind >= 20: 
                    wind_desc.append(f"Rajadas de {gust_wind}KT")

            if wind_desc: 
                alertas_encontrados.append(" e ".join(wind_desc))

        # Lógica para TAF (previsão) - procurar por fenômenos e condições em TEMPO/BECMG/PROB30/40
        if "TAF" in tipo_mensagem.upper(): 
            for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
                if f"PROB30 {codigo_icao}" in mensagem_upper or f"PROB40 {codigo_icao}" in mensagem_upper:
                    alertas_encontrados.append(f"PREVISÃO PROB: {descricao}")
                if f"TEMPO {codigo_icao}" in mensagem_upper:
                    alertas_encontrados.append(f"PREVISÃO TEMPO: {descricao}")
                if f"BECMG {codigo_icao}" in mensagem_upper:
                    alertas_encontrados.append(f"PREVISÃO BECMG: {descricao}")
                
                if codigo_icao in ["OVC", "BKN"]:
                    if re.search(f"{codigo_icao}00[1-5]", mensagem_upper): 
                        alertas_encontrados.append(f"PREVISÃO: {descricao} (TETO BAIXO < 600FT)")
                if codigo_icao == "FG":
                    if re.search(r'\s(\d{4})\s', mensagem_upper) and int(re.search(r'\s(\d{4})\s', mensagem_upper).group(1)) < 1000:
                        alertas_encontrados.append(f"PREVISÃO: {descricao} (VISIBILIDADE < 1000M)")
                    elif "FG" in mensagem_upper:
                        alertas_encontrados.append(f"PREVISÃO: {descricao}")
            
            # DETECÇÃO ESPECÍFICA PARA CINZAS VULCÂNICAS (VA) EM TAF
            if re.search(r'(?:PROB\d{2}|TEMPO|BECMG)\s+VA\b', mensagem_upper): # Verifica VA com prefixo de tendência/probabilidade
                alertas_encontrados.append("PREVISÃO: Cinzas Vulcânicas (VA)")

            wind_groups_in_taf = re.findall(r'(?:(TEMPO|BECMG|PROB\d{2})\s)?(?:.*?)(VRB|\d{3})(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
            for group in wind_groups_in_taf:
                prefix = group[0] if group[0] else "Previsão" 
                sustained_wind_str = group[2]
                gust_wind_str = group[4] 
                
                sustained_wind = int(sustained_wind_str)
                
                wind_desc_taf = []
                if sustained_wind >= 20:
                    wind_desc_taf.append(f"Vento Médio de {sustained_wind}KT")
                
                if gust_wind_str:
                    gust_wind = int(gust_wind_str)
                    if gust_wind >= 20:
                        wind_desc_taf.append(f"Rajadas de {gust_wind}KT")

                if wind_desc_taf:
                    alertas_encontrados.append(f"PREVISÃO {prefix}: {' e '.join(wind_desc_taf)}")


    # --- Lógica para Avisos de Aeródromo (Refinada) ---
    if "AD WRNG" in tipo_mensagem.upper() or "AVISO DE AERÓDROMO" in tipo_mensagem.upper(): 
        aviso_fenomenos_desc = []
        
        if "TS" in mensagem_upper:
            aviso_fenomenos_desc.append("Trovoada")

        wind_warning_match = re.search(r'SFC WSPD (\d+KT)(?: MAX (\d+))?', mensagem_upper)
        if wind_warning_match:
            min_wind_str = re.search(r'(\d+)KT', wind_warning_match.group(1)).group(1) 
            min_wind = int(min_wind_str)
            max_wind = wind_warning_match.group(2)
            
            wind_parts = []
            if min_wind >= 15: 
                wind_parts.append(f"Vento de Superfície de {min_wind}KT")

            if max_wind:
                max_wind_val = int(max_wind)
                if max_wind_val >= 25: 
                    wind_parts.append(f"Rajadas de {max_wind_val}KT")
            
            if wind_parts:
                aviso_fenomenos_desc.append(" e ".join(wind_parts))


        if "GRANIZO" in mensagem_upper:
            aviso_fenomenos_desc.append("Granizo")
        if "FG" in mensagem_upper or "NEVOEIRO" in mensagem_upper: 
            vis_match_aviso = re.search(r'VIS < (\d+)([MK])', mensagem_upper)
            if vis_match_aviso:
                vis_value = int(vis_match_aviso.group(1))
                vis_unit = vis_match_aviso.group(2)
                if (vis_unit == 'M' and vis_value < 1000) or (vis_unit == 'K' and vis_value < 1): 
                    alertas_encontrados.append(f"Nevoeiro (VISIBILIDADE < {vis_value}{vis_unit})")
            else:
                alertas_encontrados.append("Nevoeiro")
        
        if "CHUVA FORTE" in mensagem_upper or "+RA" in mensagem_upper:
            aviso_fenomenos_desc.append("Chuva Forte")
        if "VISIBILIDADE REDUZIDA" in mensagem_upper:
            aviso_fenomenos_desc.append("Visibilidade Reduzida")
        if "WIND SHEAR" in mensagem_upper or "WS" in mensagem_upper:
            aviso_fenomenos_desc.append("Tesoura de Vento (Wind Shear)")
            
        # CORREÇÃO PARA CINZAS VULCÂNICAS (VA) EM AVISOS: verifica se VA é uma palavra separada
        if re.search(r'\bVA\b', mensagem_upper) and "VALID" not in mensagem_upper: 
            aviso_fenomenos_desc.append("Cinzas Vulcânicas (VA)")
            
        if "FUMAÇA" in mensagem_upper or "FU" in mensagem_upper:
            aviso_fenomenos_desc.append("Fumaça")
            
        if aviso_fenomenos_desc:
            alertas_encontrados.extend(list(set(aviso_fenomenos_desc)))
        else: 
            # Manter esta parte para debug se um aviso não mapeado passar
            alertas_encontrados.append("Conteúdo não mapeado")


    return list(set(alertas_encontrados)) 


def verificar_e_alertar():
    """Verifica as condições meteorológicas e envia alertas."""
    print("Verificando condições meteorológicas...")
    
    agora_utc = datetime.now(pytz.utc)

    for aerodromo in AERODROMOS_INTERESSE:
        # --- Avisos de Aeródromo ---
        avisos_data = obter_mensagens_redemet_simulada("avisos", aerodromo) 
        if avisos_data and avisos_data['data']:
            for aviso in avisos_data['data']:
                mensagem_aviso = aviso['mensagem']
                aviso_hash = calcular_hash_mensagem(mensagem_aviso)

                if aviso_hash not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_aviso, "AVISO DE AERÓDROMO") 
                    if condicoes_perigosas and "Conteúdo não mapeado" not in condicoes_perigosas:
                        alert_message = (
                            f"🚨 *NOVO ALERTA MET {aerodromo}!* 🚨\n\n"
                            f"Aeródromo: {aerodromo} - Tipo: AVISO DE AERÓDROMO\n"
                            f"Condições Previstas: {', '.join(condicoes_perigosas)}\n"
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
        tafs_data = obter_mensagens_redemet_simulada("taf", aerodromo) 
        if tafs_data and tafs_data['data']:
            for taf in tafs_data['data']:
                mensagem_taf = taf['mensagem']
                taf_hash = calcular_hash_mensagem(mensagem_taf)

                if taf_hash not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_taf, "TAF")
                    if condicoes_perigosas and "Conteúdo não mapeado" not in condicoes_perigosas:
                        alert_message = (
                            f"⚠️ *NOVO ALERTA MET {aerodromo}!* ⚠️\n\n"
                            f"Aeródromo: {aerodromo} - Tipo: TAF\n"
                            f"Condições Previstas: {', '.join(condicoes_perigosas)}\n"
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
        metars_data = obter_mensagens_redemet_simulada("metar", aerodromo) 
        if metars_data and metars_data['data']:
            for metar_speci in metars_data['data']:
                mensagem_metar_speci = metar_speci['mensagem']
                metar_speci_hash = calcular_hash_mensagem(mensagem_metar_speci)

                tipo = "SPECI" if mensagem_metar_speci.startswith("SPECI") else "METAR"

                if metar_speci_hash not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_metar_speci, tipo)
                    if condicoes_perigosas and "Conteúdo não mapeado" not in condicoes_perigosas:
                        alert_message = (
                            f"⚡️ *NOVO ALERTA MET {aerodromo}!* ⚡️\n\n"
                            f"Aeródromo: {aerodromo} - Tipo: {tipo}\n"
                            f"Condições Reportadas: {', '.join(condicoes_perigosas)}\n" 
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

    for msg_hash in list(alertas_enviados_cache.keys()):
        if agora_utc - alertas_enviados_cache[msg_hash] > timedelta(hours=24):
            del alertas_enviados_cache[msg_hash]

# --- Execução Principal (para GitHub Actions) ---
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erro: Variáveis de ambiente TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configuradas.")
        print("Por favor, defina-as antes de executar o script.")
    else:
        print("Executando verificação de alertas REDEMET (execução única para GitHub Actions).")
        verificar_e_alertar() 
        print("Verificação concluída.")
