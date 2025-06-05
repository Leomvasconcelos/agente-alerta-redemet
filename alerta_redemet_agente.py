import os
import requests
import json
import time
from datetime import datetime, timedelta
import pytz
import re

# --- Configurações ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
REDEMET_API_KEY = os.getenv('REDEMET_API_KEY') # Variável de ambiente para a chave API

# Aeródromos de interesse (SBTA para testes iniciais)
AERODROMOS_INTERESSE = ["SBTA"] # Você pode adicionar mais aeródromos aqui, ex: ["SBTA", "SBBR", "SBGR"]

# Base URL da API da REDEMET
REDEMET_API_BASE_URL = "https://api-redemet.decea.mil.br/mensagens/"

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
    "BR": "Névoa", # Névoa é menos severa que Nevoeiro (FG), mas pode reduzir visibilidade
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
alertas_enviados_cache = {}

# --- Funções Auxiliares ---

def calcular_hash_mensagem(mensagem):
    """Calcula um hash simples da mensagem para evitar duplicatas."""
    # Remover espaços em branco no início/fim e normalizar múltiplos espaços
    # para garantir que pequenas variações de formatação não gerem novos hashes.
    normalized_message = re.sub(r'\s+', ' ', mensagem).strip()
    return hash(normalized_message)

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
        response.raise_for_status()
        # print(f"Mensagem enviada com sucesso para o Telegram.") # Removido o texto para não logar chaves/dados sensíveis
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar mensagem para o Telegram: {e}")

def obter_mensagens_redemet_real(endpoint_tipo, aerodromo):
    """
    Função para buscar dados reais da API da REDEMET.
    endpoint_tipo: 'metar', 'taf' ou 'aviso'
    """
    url = f"{REDEMET_API_BASE_URL}{endpoint_tipo}/{aerodromo}"
    headers = {
        "API-Key": REDEMET_API_KEY
    }

    print(f"Buscando dados da REDEMET: {url}")
    try:
        response = requests.get(url, headers=headers, timeout=10) # Adicionado timeout
        response.raise_for_status() # Lança exceção para erros HTTP
        data = response.json()

        mensagens_filtradas = []
        if data and 'data' in data and data['data']:
            # A documentação mostra que as mensagens estão dentro de um dicionário com a chave 'mens'
            # Exemplo: {'data': [{'mens': 'METAR SBGL...'}, {'mens': 'METAR SBGL...'}]}

            if endpoint_tipo == "metar":
                # Para METAR/SPECI, pegamos apenas a mais recente (última da lista 'data')
                if isinstance(data['data'], list) and data['data'] and 'mens' in data['data'][-1]:
                    mensagens_filtradas.append({"mensagem": data['data'][-1]['mens']})
            elif endpoint_tipo == "taf":
                # Para TAF, pegamos a última mensagem completa que não seja um TAF de cancelamento (CNL)
                if isinstance(data['data'], list) and data['data']:
                    for msg_data in reversed(data['data']): # Começa do mais recente
                        if 'mens' in msg_data and "CNL" not in msg_data['mens'].upper():
                            mensagens_filtradas.append({"mensagem": msg_data['mens']})
                            break # Pega apenas o TAF mais recente válido
            elif endpoint_tipo == "aviso":
                # Para Aviso, a API pode retornar vários avisos válidos simultaneamente.
                # Pegamos todos os avisos presentes no retorno mais recente.
                if isinstance(data['data'], list) and data['data']:
                    for msg_data in data['data']:
                        if 'mens' in msg_data:
                            mensagens_filtradas.append({"mensagem": msg_data['mens']})

        return {"data": mensagens_filtradas}

    except requests.exceptions.HTTPError as http_err:
        print(f"Erro HTTP ao buscar {endpoint_tipo} para {aerodromo}: {http_err} - Resposta: {response.text}")
    except requests.exceptions.ConnectionError as conn_err:
        print(f"Erro de Conexão ao buscar {endpoint_tipo} para {aerodromo}: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        print(f"Tempo esgotado ao buscar {endpoint_tipo} para {aerodromo}: {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        print(f"Erro ao buscar {endpoint_tipo} para {aerodromo}: {req_err}")
    except json.JSONDecodeError:
        print(f"Erro ao decodificar JSON para {endpoint_tipo} de {aerodromo}. Resposta: {response.text if 'response' in locals() else 'N/A'}")

    return {"data": []} # Retorna lista vazia em caso de erro ou sem dados

def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """
    Função para o robô 'ler' a mensagem e procurar por códigos severos e contexto.
    Retorna uma lista dos alertas de texto encontrados, com base nos seus critérios.
    """
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    # --- Análise de Fenômenos Específicos (METAR/TAF/Aviso) ---

    for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
        # Lógica para códigos como "+RA", "-RA", "FZRA", que não são palavras completas sozinhas mas são parte de outros códigos
        if (codigo_icao == "+RA" and "+RA" in mensagem_upper) or \
           (codigo_icao == "-RA" and "-RA" in mensagem_upper) or \
           (codigo_icao == "FZRA" and "FZRA" in mensagem_upper):
            if descricao not in alertas_encontrados:
                alertas_encontrados.append(descricao)
        # Para outros códigos, usamos bordas de palavra para evitar falsos positivos (ex: "VALID" detectando "VA")
        elif re.search(r'\b' + re.escape(codigo_icao) + r'\b', mensagem_upper):
            if codigo_icao in ["OVC", "BKN", "SCT", "FEW"]: # Incluir SCT/FEW se quiser alertar sobre formações específicas de nuvens
                cloud_match = re.search(r'' + re.escape(codigo_icao) + r'(\d{3})', mensagem_upper)
                if cloud_match:
                    cloud_height = int(cloud_match.group(1)) * 100
                    if (codigo_icao == "OVC" or codigo_icao == "BKN") and cloud_height < 600:
                        if f"{descricao} (TETO BAIXO < 600FT)" not in alertas_encontrados:
                            alertas_encontrados.append(f"{descricao} (TETO BAIXO < 600FT)")
                    elif codigo_icao == "CB": # Apenas para CBs, reporta a altura se encontrada
                        if f"{descricao} a {cloud_height}FT" not in alertas_encontrados:
                            alertas_encontrados.append(f"{descricao} a {cloud_height}FT")
                    # Adiciona a descrição básica se não atende a condição de teto baixo ou CB
                    elif descricao not in alertas_encontrados:
                        alertas_encontrados.append(descricao)
                else: # Se o código da nuvem está lá mas não a altura (raro em METAR/TAF, mas para segurança)
                    if descricao not in alertas_encontrados:
                        alertas_encontrados.append(descricao)
            elif codigo_icao == "FG":
                vis_match = re.search(r'(?<!\d)\s(\d{4})\s', mensagem_upper) # Regex mais precisa para visibilidade
                if vis_match:
                    visibility_meters = int(vis_match.group(1))
                    if visibility_meters < 1000:
                        if f"{descricao} (VISIBILIDADE < 1000M)" not in alertas_encontrados:
                            alertas_encontrados.append(f"{descricao} (VISIBILIDADE < 1000M)")
                    elif descricao not in alertas_encontrados: # FG mas vis >= 1000m
                         alertas_encontrados.append(descricao)
                elif "FG" in mensagem_upper and descricao not in alertas_encontrados: # FG presente sem visibilidade explícita
                     alertas_encontrados.append(descricao)
            # Para outros fenômenos, basta adicionar a descrição
            elif descricao not in alertas_encontrados:
                alertas_encontrados.append(descricao)

    # DETECÇÃO ESPECÍFICA PARA CINZAS VULCÂNICAS (VA)
    # Garante que 'VA' está como um código isolado ou em um contexto meteorológico
    # e que NÃO seja parte da palavra "VALID".
    if re.search(r'\bVA\b', mensagem_upper) and "VALID" not in mensagem_upper:
        if "Cinzas Vulcânicas (VA)" not in alertas_encontrados:
            alertas_encontrados.append("Cinzas Vulcânicas (VA)")

    # --- Lógica para ventos (METAR/SPECI/TAF) ---
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
            if gust_wind >= 20: # Rajadas de 20KT ou mais
                wind_desc.append(f"Rajadas de {gust_wind}KT")

        if wind_desc:
            wind_alert_text = " e ".join(wind_desc)
            if wind_alert_text not in alertas_encontrados:
                alertas_encontrados.append(wind_alert_text)


    # Lógica para TAF (previsão) - procurar por fenômenos e condições em TEMPO/BECMG/PROB30/40
    if "TAF" in tipo_mensagem.upper():
        # Reforçar a detecção de fenômenos com prefixos de TAF
        for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
            # A regex agora captura o prefixo (PROBxx, TEMPO, BECMG)
            match_taf_phenom = re.search(r'(PROB\d{2}|TEMPO|BECMG)\s+' + re.escape(codigo_icao) + r'\b', mensagem_upper)
            if match_taf_phenom:
                prefix = match_taf_phenom.group(1)
                if codigo_icao in ["OVC", "BKN", "SCT", "FEW"]:
                    cloud_match_taf = re.search(r'' + re.escape(codigo_icao) + r'(\d{3})', mensagem_upper)
                    if cloud_match_taf:
                        cloud_height_taf = int(cloud_match_taf.group(1)) * 100
                        if (codigo_icao == "OVC" or codigo_icao == "BKN") and cloud_height_taf < 600:
                            if f"PREVISÃO {prefix}: {descricao} (TETO BAIXO < 600FT)" not in alertas_encontrados:
                                alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao} (TETO BAIXO < 600FT)")
                        elif codigo_icao == "CB":
                            if f"PREVISÃO {prefix}: {descricao} a {cloud_height_taf}FT" not in alertas_encontrados:
                                alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao} a {cloud_height_taf}FT")
                        else:
                            if f"PREVISÃO {prefix}: {descricao}" not in alertas_encontrados:
                                alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao}")
                    else: # Se o código está lá, mas a altura não foi capturada
                        if f"PREVISÃO {prefix}: {descricao}" not in alertas_encontrados:
                                alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao}")
                elif codigo_icao == "FG":
                    vis_match_taf = re.search(r'(PROB\d{2}|TEMPO|BECMG)\s+FG\s+(?<!\d)(\d{4})', mensagem_upper)
                    if vis_match_taf:
                        visibility_meters_taf = int(vis_match_taf.group(2))
                        if visibility_meters_taf < 1000:
                            if f"PREVISÃO {prefix}: {descricao} (VISIBILIDADE < 1000M)" not in alertas_encontrados:
                                alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao} (VISIBILIDADE < 1000M)")
                        elif f"PREVISÃO {prefix}: {descricao}" not in alertas_encontrados: # FG mas vis >= 1000m
                            alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao}")
                    elif re.search(r'(PROB\d{2}|TEMPO|BECMG)\s+FG', mensagem_upper) and f"PREVISÃO {prefix}: {descricao}" not in alertas_encontrados:
                        alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao}")
                else:
                    if f"PREVISÃO {prefix}: {descricao}" not in alertas_encontrados:
                        alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao}")

        # DETECÇÃO ESPECÍFICA PARA CINZAS VULCÂNICAS (VA) EM TAF
        if re.search(r'(?:PROB\d{2}|TEMPO|BECMG)\s+VA\b', mensagem_upper) and "VALID" not in mensagem_upper:
            if "PREVISÃO: Cinzas Vulcânicas (VA)" not in alertas_encontrados:
                alertas_encontrados.append("PREVISÃO: Cinzas Vulcânicas (VA)")

        # Lógica de vento em TAF para TEMPO/BECMG/PROB
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
                wind_alert_text_taf = f"PREVISÃO {prefix}: {' e '.join(wind_desc_taf)}"
                if wind_alert_text_taf not in alertas_encontrados:
                    alertas_encontrados.append(wind_alert_text_taf)


    # --- Lógica para Avisos de Aeródromo (Refinada) ---
    if "AD WRNG" in tipo_mensagem.upper() or "AVISO DE AERÓDROMO" in tipo_mensagem.upper():
        aviso_fenomenos_desc = []

        if "TS" in mensagem_upper:
            if "Trovoada" not in aviso_fenomenos_desc:
                aviso_fenomenos_desc.append("Trovoada")

        # Regex para capturar SFC WSPD XXKT MAX YY (ex: SFC WSPD 15KT MAX 25)
        wind_warning_match = re.search(r'SFC WSPD (\d+KT)(?: MAX (\d+))?', mensagem_upper)
        if wind_warning_match:
            min_wind_str = re.search(r'(\d+)KT', wind_warning_match.group(1)).group(1)
            min_wind = int(min_wind_str)
            max_wind = wind_warning_match.group(2)

            wind_parts = []
            if min_wind >= 15: # Se o vento médio é 15KT ou mais
                wind_parts.append(f"Vento de Superfície de {min_wind}KT")

            if max_wind:
                max_wind_val = int(max_wind)
                if max_wind_val >= 25: # Se a rajada máxima é 25KT ou mais
                    wind_parts.append(f"Rajadas de {max_wind_val}KT")

            if wind_parts:
                wind_alert_text_aviso = " e ".join(wind_parts)
                if wind_alert_text_aviso not in aviso_fenomenos_desc:
                    aviso_fenomenos_desc.append(wind_alert_text_aviso)


        if "GRANIZO" in mensagem_upper:
            if "Granizo" not in aviso_fenomenos_desc:
                aviso_fenomenos_desc.append("Granizo")
        if "FG" in mensagem_upper or "NEVOEIRO" in mensagem_upper:
            vis_match_aviso = re.search(r'VIS < (\d+)([MK])', mensagem_upper)
            if vis_match_aviso:
                vis_value = int(vis_match_aviso.group(1))
                vis_unit = vis_match_aviso.group(2)
                if (vis_unit == 'M' and vis_value < 1000) or (vis_unit == 'K' and vis_value < 1): # Convert K to meters
                    if "Nevoeiro (VISIBILIDADE < 1000M)" not in aviso_fenomenos_desc: # Padroniza a descrição
                        aviso_fenomenos_desc.append("Nevoeiro (VISIBILIDADE < 1000M)")
            elif "Nevoeiro" not in aviso_fenomenos_desc:
                aviso_fenomenos_desc.append("Nevoeiro")

        if "CHUVA FORTE" in mensagem_upper or "+RA" in mensagem_upper:
            if "Chuva Forte" not in aviso_fenomenos_desc:
                aviso_fenomenos_desc.append("Chuva Forte")
        if "VISIBILIDADE REDUZIDA" in mensagem_upper:
            if "Visibilidade Reduzida" not in aviso_fenomenos_desc:
                aviso_fenomenos_desc.append("Visibilidade Reduzida")
        if "WIND SHEAR" in mensagem_upper or "WS" in mensagem_upper:
            if "Tesoura de Vento (Wind Shear)" not in aviso_fenomenos_desc:
                aviso_fenomenos_desc.append("Tesoura de Vento (Wind Shear)")

        # CORREÇÃO PARA CINZAS VULCÂNICAS (VA) EM AVISOS: verifica se VA é uma palavra separada
        # e não é parte da palavra "VALID"
        if re.search(r'\bVA\b', mensagem_upper) and "VALID" not in mensagem_upper:
            if "Cinzas Vulcânicas (VA)" not in aviso_fenomenos_desc:
                aviso_fenomenos_desc.append("Cinzas Vulcânicas (VA)")

        if "FUMAÇA" in mensagem_upper or "FU" in mensagem_upper:
            if "Fumaça" not in aviso_fenomenos_desc:
                aviso_fenomenos_desc.append("Fumaça")

        if aviso_fenomenos_desc:
            # Adiciona os fenômenos detectados na parte do aviso à lista principal de alertas
            alertas_encontrados.extend(list(set(aviso_fenomenos_desc)))


    # Garante que "Conteúdo não mapeado" só é adicionado se NENHUMA condição for encontrada
    # no final da análise.
    if not alertas_encontrados:
        alertas_encontrados.append("Conteúdo não mapeado")

    return list(set(alertas_encontrados)) # Usa set para remover duplicatas e converte de volta para lista

def verificar_e_alertar():
    """Verifica as condições meteorológicas e envia alertas."""
    print("Verificando condições meteorológicas...")

    agora_utc = datetime.now(pytz.utc)

    for aerodromo in AERODROMOS_INTERESSE:
        # --- Avisos de Aeródromo ---
        avisos_data = obter_mensagens_redemet_real("aviso", aerodromo)
        if avisos_data and avisos_data['data']:
            for aviso in avisos_data['data']:
                mensagem_aviso = aviso.get('mensagem', '')
                if not mensagem_aviso: continue

                aviso_hash = calcular_hash_mensagem(mensagem_aviso)

                if aviso_hash not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_aviso, "AVISO DE AERÓDROMO")
                    # Só alerta se houver condições perigosas e não for "Conteúdo não mapeado"
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
        tafs_data = obter_mensagens_redemet_real("taf", aerodromo)
        if tafs_data and tafs_data['data']:
            for taf in tafs_data['data']:
                mensagem_taf = taf.get('mensagem', '')
                if not mensagem_taf: continue

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
        metars_data = obter_mensagens_redemet_real("metar", aerodromo)
        if metars_data and metars_data['data']:
            for metar_speci in metars_data['data']:
                mensagem_metar_speci = metar_speci.get('mensagem', '')
                if not mensagem_metar_speci: continue

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

    # Limpar cache de alertas mais antigos que 24 horas
    # Isso garante que se um METAR mudar (um novo for emitido), ele poderá ser alertado novamente.
    # Avisos e TAFs geralmente têm validade, e novos avisos/TAFs com mesmo conteúdo mas nova validade
    # terão um hash diferente, então não devem ser problema.
    for msg_hash in list(alertas_enviados_cache.keys()):
        if agora_utc - alertas_enviados_cache[msg_hash] > timedelta(hours=24):
            del alertas_enviados_cache[msg_hash]

# --- Execução Principal (para GitHub Actions) ---
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not REDEMET_API_KEY:
        print("Erro: Variáveis de ambiente TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID ou REDEMET_API_KEY não configuradas.")
        print("Por favor, defina-as como Secrets no seu repositório GitHub.")
    else:
        print("Executando verificação de alertas REDEMET (execução única para GitHub Actions).")
        verificar_e_alertar()
        print("Verificação concluída.")
