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

# Chave da API da REDEMET (OBRIGATÓRIO AGORA!)
REDEMET_API_KEY = os.getenv('REDEMET_API_KEY') 

# Aeródromos de interesse (SBTA para testes iniciais)
AERODROMOS_INTERESSE = ["SBTA"]

# Intervalo de verificação em segundos (5 minutos) - Este será o intervalo de sleep SE rodar localmente
# No GitHub Actions, o agendamento é feito pelo cron no .yml
INTERVALO_VERIFICACAO = 300 

# URLs da API REDEMET
BASE_REDEMET_API_URL = "https://api-redemet.decea.mil.br/mensagens"
REDEMET_ENDPOINTS = {
    "METAR": f"{BASE_REDEMET_API_URL}/metar",
    "TAF": f"{BASE_REDEMET_API_URL}/taf",
    "AVISO": f"{BASE_REDEMET_API_URL}/aviso",
}

# Dicionário de códigos METAR/TAF e suas descrições
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
    "FU": "Fumaça",
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
alertas_enviados_cache = {} # {hash_da_mensagem: timestamp_envio}

# --- Funções Auxiliares ---

def calcular_hash_mensagem(mensagem):
    """Calcula um hash simples da mensagem para evitar duplicatas."""
    # Para Avisos, o número do aviso e o ICAO de origem são importantes
    # Ex: SBRF SBLE/SBTA/SBJE/SNBR/SWKQ AD WRNG 4 VALID...
    # Extrair "AD WRNG X" e o aeródromo de interesse
    if "AD WRNG" in mensagem:
        match = re.search(r'AD WRNG (\d+)\s+VALID', mensagem)
        if match:
            # Hash baseado no aeródromo de interesse e no número do aviso
            return hash(f"AVISO_WRNG_{match.group(1)}_{AERODROMOS_INTERESSE[0]}")
    # Para METAR/SPECI/TAF, o corpo da mensagem é suficiente, mas podemos incluir o ICAO e o tipo
    # para garantir unicidade mesmo se mensagens idênticas aparecerem em outros aeródromos (improvável)
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

def obter_mensagens_redemet_real(endpoint_type, aerodromo):
    """
    Função para buscar dados reais da API da REDEMET.
    endpoint_type pode ser "METAR", "TAF" ou "AVISO".
    """
    print(f"Buscando dados da REDEMET para {endpoint_type} em {aerodromo}...")
    
    url = f"{REDEMET_ENDPOINTS[endpoint_type]}/{aerodromo}"
    headers = {
        "x-api-key": REDEMET_API_KEY
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status() # Lança exceção para erros HTTP 4xx/5xx
        data = response.json()
        
        # A API retorna um dicionário com uma chave 'data' que contém a lista de mensagens
        if data and 'data' in data and isinstance(data['data'], list):
            # As mensagens vêm como objetos {'id': ..., 'mens': 'TEXTO_DA_MENSAGEM'}
            # Queremos apenas o texto da mensagem.
            # Também filtra mensagens vazias ou inválidas.
            valid_messages = []
            for item in data['data']:
                if isinstance(item, dict) and 'mens' in item and item['mens']:
                    valid_messages.append({"mensagem": item['mens']})
                elif isinstance(item, dict) and 'mensagem' in item and item['mensagem']: # Para caso a chave seja 'mensagem' em vez de 'mens'
                     valid_messages.append({"mensagem": item['mensagem']})
            return {"data": valid_messages}
        else:
            print(f"Resposta da API REDEMET para {endpoint_type} em {aerodromo} não contém 'data' ou não é uma lista: {data}")
            return {"data": []}

    except requests.exceptions.Timeout:
        print(f"Erro de Timeout ao buscar {endpoint_type} para {aerodromo} na REDEMET.")
        return {"data": []}
    except requests.exceptions.RequestException as e:
        print(f"Erro ao buscar {endpoint_type} para {aerodromo} na REDEMET: {e}")
        # Se a chave API estiver inválida, isso pode aparecer aqui
        if response.status_code == 401 or response.status_code == 403:
            print("Verifique se a sua REDEMET_API_KEY está correta e ativa.")
        return {"data": []}
    except json.JSONDecodeError:
        print(f"Erro ao decodificar JSON para {endpoint_type} em {aerodromo}: {response.text}")
        return {"data": []}

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
                elif codigo_icao == "+RA": 
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
        
        # DETECÇÃO ESPECÍFICA PARA CINZAS VULCÂNICAS (VA) em METAR/SPECI
        # Procura por 'VA' como um código de fenômeno e não na palavra 'VALID'
        # Verifica se 'VA' não é precedido ou seguido por caracteres que o tornem parte de outra palavra
        if re.search(r'(?<![A-Z])VA(?![A-Z])', mensagem_upper) and "VALID" not in mensagem_upper:
             # Adiciona uma verificação extra para garantir que não é parte de uma data ou hora (ex: 2817VA)
             if not re.search(r'\d{4}VA|\d{2}VA\d{2}', mensagem_upper):
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
            # Procura por 'VA' como um código de fenômeno dentro de TEMPO, BECMG, PROB
            if re.search(r'(?:PROB\d{2}|TEMPO|BECMG)\s+VA\b', mensagem_upper):
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
        # e explicitamente NÃO está contido na palavra "VALID"
        if re.search(r'\bVA\b', mensagem_upper) and "VALID" not in mensagem_upper: 
            aviso_fenomenos_desc.append("Cinzas Vulcânicas (VA)")
            
        if "FUMAÇA" in mensagem_upper or "FU" in mensagem_upper:
            aviso_fenomenos_desc.append("Fumaça")
            
        if aviso_fenomenos_desc:
            alertas_encontrados.extend(list(set(aviso_fenomenos_desc)))
        else: 
            alertas_encontrados.append("Conteúdo não mapeado")


    return list(set(alertas_encontrados)) 


def verificar_e_alertar():
    """Verifica as condições meteorológicas e envia alertas."""
    print("Verificando condições meteorológicas...")
    
    agora_utc = datetime.now(pytz.utc)

    for aerodromo in AERODROMOS_INTERESSE:
        # --- Avisos de Aeródromo ---
        # ATENÇÃO: Mudando de obter_mensagens_redemet_simulada para obter_mensagens_redemet_real
        avisos_data = obter_mensagens_redemet_real("AVISO", aerodromo) 
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
        # ATENÇÃO: Mudando de obter_mensagens_redemet_simulada para obter_mensagens_redemet_real
        tafs_data = obter_mensagens_redemet_real("TAF", aerodromo) 
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
        # ATENÇÃO: Mudando de obter_mensagens_redemet_simulada para obter_mensagens_redemet_real
        metars_data = obter_mensagens_redemet_real("METAR", aerodromo) 
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

    # Limpar cache de alertas antigos (opcional, para evitar que o cache cresça indefinidamente)
    for msg_hash in list(alertas_enviados_cache.keys()):
        if agora_utc - alertas_enviados_cache[msg_hash] > timedelta(hours=24):
            del alertas_enviados_cache[msg_hash]

# --- Execução Principal (para GitHub Actions) ---
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erro: Variáveis de ambiente TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configuradas.")
        print("Por favor, defina-as antes de executar o script.")
    elif not REDEMET_API_KEY:
        print("Erro: Variável de ambiente REDEMET_API_KEY não configurada.")
        print("Por favor, defina-a antes de executar o script.")
    else:
        print("Executando verificação de alertas REDEMET (execução única para GitHub Actions).")
        verificar_e_alertar() 
        print("Verificação concluída.")
