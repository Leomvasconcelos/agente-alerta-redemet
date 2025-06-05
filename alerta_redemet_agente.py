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
REDEMET_API_KEY = os.getenv('REDEMET_API_KEY')

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
    "SCT": "Nuvens Esparsas (Scattered)", # Adicionado para detecção, mas não para alerta por si só
    "FEW": "Poucas Nuvens (Few)",         # Adicionado para detecção, mas não para alerta por si só
    "CB": "Cumulunimbus",
    "TCU": "Cumulus Castellanus",
    "WS": "Tesoura de Vento (Wind Shear)",
}

# Armazenamento em memória para evitar alertas duplicados
alertas_enviados_cache = {}

# --- Funções Auxiliares ---

def calcular_hash_mensagem(mensagem):
    """Calcula um hash simples da mensagem para evitar duplicatas."""
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
        # print(f"Mensagem enviada com sucesso para o Telegram.") # Removido para evitar poluição de log, mas pode ser reativado
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar mensagem para o Telegram: {e}")

def obter_mensagens_redemet_real(endpoint_tipo, aerodromo):
    """
    Função para buscar dados reais da API da REDEMET.
    endpoint_tipo: 'metar', 'taf' ou 'aviso'
    """
    url = f"{REDEMET_API_BASE_URL}{endpoint_tipo}/{aerodromo}"
    headers = {
        "API-Key": REDEMET_API_KEY # Esta linha é crucial e DEVE ESTAR AQUI!
    }

    print(f"Buscando dados da REDEMET: {url}")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        mensagens_filtradas = []
        if data and 'data' in data and data['data']:
            if endpoint_tipo == "metar":
                # Pega a última mensagem de METAR/SPECI
                if isinstance(data['data'], list) and data['data'] and 'mens' in data['data'][-1]:
                    mensagens_filtradas.append({"mensagem": data['data'][-1]['mens']})
            elif endpoint_tipo == "taf":
                # Pega o último TAF não cancelado
                if isinstance(data['data'], list) and data['data']:
                    for msg_data in reversed(data['data']):
                        if 'mens' in msg_data and "CNL" not in msg_data['mens'].upper():
                            mensagens_filtradas.append({"mensagem": msg_data['mens']})
                            break
            elif endpoint_tipo == "aviso":
                # Pega todos os avisos ativos
                if isinstance(data['data'], list) and data['data']:
                    for msg_data in data['data']:
                        if 'mens' in msg_data:
                            mensagens_filtradas.append({"mensagem": msg_data['mens']})

        return {"data": mensagens_filtradas}

    except requests.exceptions.HTTPError as http_err:
        print(f"Erro HTTP ao buscar {endpoint_tipo} para {aerodromo}: {http_err} - Resposta: {response.text if 'response' in locals() else 'N/A'}")
    except requests.exceptions.ConnectionError as conn_err:
        print(f"Erro de Conexão ao buscar {endpoint_tipo} para {aerodromo}: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        print(f"Tempo esgotado ao buscar {endpoint_tipo} para {aerodromo}: {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        print(f"Erro ao buscar {endpoint_tipo} para {aerodromo}: {req_err}")
    except json.JSONDecodeError:
        print(f"Erro ao decodificar JSON para {endpoint_tipo} de {aerodromo}. Resposta: {response.text if 'response' in locals() else 'N/A'}")

    return {"data": []}

def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """
    Função para o robô 'ler' a mensagem e procurar por códigos severos e contexto.
    Retorna uma lista dos alertas de texto encontrados, com base nos seus critérios.
    """
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    # --- Análise de Fenômenos Específicos (METAR/TAF/Aviso) ---

    for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
        # Lógica para códigos que podem vir com prefixos como +/-
        if (codigo_icao == "+RA" and "+RA" in mensagem_upper) or \
           (codigo_icao == "-RA" and "-RA" in mensagem_upper) or \
           (codigo_icao == "FZRA" and "FZRA" in mensagem_upper):
            if descricao not in alertas_encontrados:
                alertas_encontrados.append(descricao)
        # Para outros códigos, usamos bordas de palavra para evitar falsos positivos
        # Utiliza raw string (r'') para regex
        elif re.search(r'\b' + re.escape(codigo_icao) + r'\b', mensagem_upper):
            if codigo_icao in ["OVC", "BKN", "SCT", "FEW"]:
                # Captura a camada de nuvem e a altura logo após o código
                cloud_match = re.search(re.escape(codigo_icao) + r'(\d{3})', mensagem_upper)
                if cloud_match:
                    cloud_height = int(cloud_match.group(1)) * 100
                    if (codigo_icao == "OVC" or codigo_icao == "BKN") and cloud_height < 600:
                        if f"{descricao} (TETO BAIXO < 600FT)" not in alertas_encontrados:
                            alertas_encontrados.append(f"{descricao} (TETO BAIXO < 600FT)")
                    elif codigo_icao == "CB":
                        if f"{descricao} a {cloud_height}FT" not in alertas_encontrados:
                            alertas_encontrados.append(f"{descricao} a {cloud_height}FT")
                    # Para outros tipos de nuvem (SCT, FEW) ou OVC/BKN com teto alto, apenas adiciona a descrição básica
                    elif descricao not in alertas_encontrados:
                        alertas_encontrados.append(descricao)
                else: # Se o código da nuvem está lá, mas a altura não foi capturada
                    if descricao not in alertas_encontrados:
                        alertas_encontrados.append(descricao)
            elif codigo_icao == "FG": # Nevoeiro
                vis_match = re.search(r'(?<!\d)\s(\d{4})\s', mensagem_upper) # Busca visibilidade como 4 dígitos isolados
                if vis_match:
                    visibility_meters = int(vis_match.group(1))
                    if visibility_meters < 1000:
                        if f"{descricao} (VISIBILIDADE < 1000M)" not in alertas_encontrados:
                            alertas_encontrados.append(f"{descricao} (VISIBILIDADE < 1000M)")
                    elif descricao not in alertas_encontrados: # FG presente mas vis >= 1000m
                         alertas_encontrados.append(descricao)
                elif "FG" in mensagem_upper and descricao not in alertas_encontrados: # FG presente sem visibilidade explícita
                     alertas_encontrados.append(descricao)
            elif codigo_icao == "BR": # Névoa
                # BR por si só não gera alerta, mas se a visibilidade for baixa (ex: 3000 BR)
                br_vis_match = re.search(r'(?<!\d)\s(\d{4})\sBR', mensagem_upper)
                if br_vis_match:
                    visibility_meters_br = int(br_vis_match.group(1))
                    if visibility_meters_br < 5000: # Névoa com visibilidade reduzida
                        if f"{descricao} (VISIBILIDADE < 5000M)" not in alertas_encontrados:
                            alertas_encontrados.append(f"{descricao} (VISIBILIDADE < 5000M)")
                    elif descricao not in alertas_encontrados:
                        alertas_encontrados.append(descricao)
                elif "BR" in mensagem_upper and descricao not in alertas_encontrados: # BR presente sem visibilidade explícita
                    alertas_encontrados.append(descricao)
            # Para outros fenômenos, basta adicionar a descrição
            elif descricao not in alertas_encontrados:
                alertas_encontrados.append(descricao)

    # DETECÇÃO ESPECÍFICA PARA CINZAS VULCÂNICAS (VA)
    # Garante que 'VA' está como um código isolado e NÃO é parte da palavra "VALID".
    if re.search(r'\bVA\b', mensagem_upper) and "VALID" not in mensagem_upper:
        if "Cinzas Vulcânicas (VA)" not in alertas_encontrados:
            alertas_encontrados.append("Cinzas Vulcânicas (VA)")

    # --- Lógica para ventos (METAR/SPECI/TAF) ---
    wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
    if wind_match:
        sustained_wind = int(wind_match.group(2))
        gust_wind_str = wind_match.group(4)

        wind_desc = []
        if sustained_wind >= 20:
            wind_desc.append(f"Vento Médio de {sustained_wind}KT")

        if gust_wind_str:
            gust_wind = int(gust_wind_str)
            if gust_wind >= 20 and gust_wind > sustained_wind + 5: # Rajadas significativas (maior que o médio + 5KT)
                wind_desc.append(f"Rajadas de {gust_wind}KT")

        if wind_desc:
            wind_alert_text = " e ".join(wind_desc)
            if wind_alert_text not in alertas_encontrados:
                alertas_encontrados.append(wind_alert_text)


    # Lógica para TAF (previsão) - procurar por fenômenos e condições em TEMPO/BECMG/PROB30/40
    if "TAF" in tipo_mensagem.upper():
        for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
            # A regex agora captura o prefixo (PROBxx, TEMPO, BECMG) e o fenômeno.
            # CORREÇÃO: Utiliza raw string (r'') para evitar SyntaxWarning.
            match_taf_phenom = re.search(r'(PROB\d{2}|TEMPO|BECMG)\s+(?:.*?)(?<!\d)(\d{4}\s)?' + re.escape(codigo_icao) + r'\b', mensagem_upper)
            if match_taf_phenom:
                prefix = match_taf_phenom.group(1)
                vis_pre_phenom_str = match_taf_phenom.group(2) # Visibilidade que pode vir antes do fenômeno

                if codigo_icao in ["OVC", "BKN"]:
                    cloud_match_taf = re.search(re.escape(codigo_icao) + r'(\d{3})', mensagem_upper)
                    if cloud_match_taf:
                        cloud_height_taf = int(cloud_match_taf.group(1)) * 100
                        if (codigo_icao == "OVC" or codigo_icao == "BKN") and cloud_height_taf < 600:
                            if f"PREVISÃO {prefix}: {descricao} (TETO BAIXO < 600FT)" not in alertas_encontrados:
                                alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao} (TETO BAIXO < 600FT)")
                        else: # OVC/BKN com teto alto, ou SCT/FEW
                            if f"PREVISÃO {prefix}: {descricao}" not in alertas_encontrados:
                                alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao}")
                    else: # Se a nuvem está lá mas não a altura (ex: TEMPO OVC)
                        if f"PREVISÃO {prefix}: {descricao}" not in alertas_encontrados:
                                alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao}")
                elif codigo_icao == "FG":
                    # Tenta capturar visibilidade antes de FG dentro do grupo de mudança
                    vis_match_taf_fg = re.search(r'(PROB\d{2}|TEMPO|BECMG)(?:.*?)(?<!\d)(\d{4})\s+FG', mensagem_upper)
                    if vis_match_taf_fg:
                        visibility_meters_taf_fg = int(vis_match_taf_fg.group(2))
                        if visibility_meters_taf_fg < 1000:
                            if f"PREVISÃO {prefix}: {descricao} (VISIBILIDADE < 1000M)" not in alertas_encontrados:
                                alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao} (VISIBILIDADE < 1000M)")
                        elif f"PREVISÃO {prefix}: {descricao}" not in alertas_encontrados: # FG mas vis >= 1000m
                            alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao}")
                    elif re.search(r'(PROB\d{2}|TEMPO|BECMG)\s+FG', mensagem_upper) and f"PREVISÃO {prefix}: {descricao}" not in alertas_encontrados:
                        alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao}")
                elif codigo_icao == "BR":
                    br_vis_match_taf = re.search(r'(PROB\d{2}|TEMPO|BECMG)(?:.*?)(?<!\d)(\d{4})\s+BR', mensagem_upper)
                    if br_vis_match_taf:
                        visibility_meters_taf_br = int(br_vis_match_taf.group(2))
                        if visibility_meters_taf_br < 5000:
                            if f"PREVISÃO {prefix}: {descricao} (VISIBILIDADE < 5000M)" not in alertas_encontrados:
                                alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao} (VISIBILIDADE < 5000M)")
                        elif f"PREVISÃO {prefix}: {descricao}" not in alertas_encontrados:
                            alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao}")
                    elif re.search(r'(PROB\d{2}|TEMPO|BECMG)\s+BR', mensagem_upper) and f"PREVISÃO {prefix}: {descricao}" not in alertas_encontrados:
                        alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao}")
                else: # Para outros fenômenos como TS, RA, etc.
                    if f"PREVISÃO {prefix}: {descricao}" not in alertas_encontrados:
                        alertas_encontrados.append(f"PREVISÃO {prefix}: {descricao}")


        # DETECÇÃO ESPECÍFICA PARA CINZAS VULCÂNICAS (VA) EM TAF
        if re.search(r'(?:PROB\d{2}|TEMPO|BECMG)\s+VA\b', mensagem_upper) and "VALID" not in mensagem_upper:
            if "PREVISÃO: Cinzas Vulcânicas (VA)" not in alertas_encontrados:
                alertas_encontrados.append("PREVISÃO: Cinzas Vulcânicas (VA)")

        # Lógica de vento em TAF para TEMPO/BECMG/PROB
        # A regex foi ajustada para ser mais robusta e usa raw string (r'')
        wind_groups_in_taf = re.findall(r'(PROB\d{2}|TEMPO|BECMG)?(?:.*?)(VRB|\d{3})(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
        for group in wind_groups_in_taf:
            prefix = group[0] if group[0] else "Previsão" # Se não houver prefixo (e.g., vento principal do TAF)
            sustained_wind_str = group[2]
            gust_wind_str = group[4]

            sustained_wind = int(sustained_wind_str)

            wind_desc_taf = []
            if sustained_wind >= 20:
                wind_desc_taf.append(f"Vento Médio de {sustained_wind}KT")

            if gust_wind_str:
                gust_wind = int(gust_wind_str)
                if gust_wind >= 20 and gust_wind > sustained_wind + 5:
                    wind_desc_taf.append(f"Rajadas de {gust_wind}KT")

            if wind_desc_taf:
                wind_alert_text_taf = f"PREVISÃO {prefix}: {' e '.join(wind_desc_taf)}"
                if wind_alert_text_taf not in alertas_encontrados:
                    alertas_encontrados.append(wind_alert_text_taf)


    # --- Lógica para Avisos de Aeródromo (Refinada) ---
    if "AD WRNG" in tipo_mensagem.upper() or "AVISO DE AERÓDROMO" in tipo_mensagem.upper():
        # Avisos de Aeródromo podem ter múltiplos fenômenos.
        # Vamos re-analisar o texto do aviso de forma mais geral para pegar tudo.

        # Detectar Trovoada
        if "TS" in mensagem_upper and "Trovoada" not in alertas_encontrados:
            alertas_encontrados.append("Trovoada")

        # Detectar Granizo
        if "GRANIZO" in mensagem_upper and "Granizo" not in alertas_encontrados:
            alertas_encontrados.append("Granizo")

        # Detectar Nevoeiro/Visibilidade Reduzida no aviso
        if "FG" in mensagem_upper or "NEVOEIRO" in mensagem_upper:
            # CORREÇÃO: Utiliza raw string (r'') para evitar SyntaxWarning.
            vis_match_aviso = re.search(r'VIS < (\d+)([MK])', mensagem_upper)
            if vis_match_aviso:
                vis_value = int(vis_match_aviso.group(1))
                vis_unit = vis_match_aviso.group(2)
                if (vis_unit == 'M' and vis_value < 1000) or (vis_unit == 'K' and vis_value < 1):
                    if "Nevoeiro (VISIBILIDADE < 1000M)" not in alertas_encontrados:
                        alertas_encontrados.append("Nevoeiro (VISIBILIDADE < 1000M)")
            elif "Nevoeiro" not in alertas_encontrados:
                alertas_encontrados.append("Nevoeiro")
        if "VISIBILIDADE REDUZIDA" in mensagem_upper and "Visibilidade Reduzida" not in alertas_encontrados:
            alertas_encontrados.append("Visibilidade Reduzida")

        # Detectar Chuva Forte
        if "CHUVA FORTE" in mensagem_upper or "+RA" in mensagem_upper:
            if "Chuva Forte" not in alertas_encontrados:
                alertas_encontrados.append("Chuva Forte")

        # Detectar Wind Shear
        if "WIND SHEAR" in mensagem_upper or "WS" in mensagem_upper:
            if "Tesoura de Vento (Wind Shear)" not in alertas_encontrados:
                alertas_encontrados.append("Tesoura de Vento (Wind Shear)")

        # Detectar Cinzas Vulcânicas
        if re.search(r'\bVA\b', mensagem_upper) and "VALID" not in mensagem_upper:
            if "Cinzas Vulcânicas (VA)" not in alertas_encontrados:
                alertas_encontrados.append("Cinzas Vulcânicas (VA)")

        # Detectar Fumaça
        if "FUMAÇA" in mensagem_upper or "FU" in mensagem_upper:
            if "Fumaça" not in alertas_encontrados:
                alertas_encontrados.append("Fumaça")

        # Vento de Superfície e Rajadas no Aviso (Ajuste crítico aqui!)
        # Ex: "SFC WSPD 15KT MAX 25 FCST"
        # CORREÇÃO: Utiliza raw string (r'') para evitar SyntaxWarning.
        wind_warning_match = re.search(r'SFC WSPD (\d+)(?:KT)?(?: MAX (\d+))?', mensagem_upper)
        if wind_warning_match:
            min_wind = int(wind_warning_match.group(1))
            max_wind_str = wind_warning_match.group(2) # Pode ser None se não houver MAX

            wind_parts = []
            if min_wind >= 15: # Vento médio a partir de 15KT no aviso
                wind_parts.append(f"Vento de Superfície de {min_wind}KT")

            if max_wind_str:
                max_wind_val = int(max_wind_str)
                if max_wind_val >= 25: # Rajadas a partir de 25KT no aviso
                    wind_parts.append(f"Rajadas de {max_wind_val}KT")

            if wind_parts:
                wind_alert_text_aviso = " e ".join(wind_parts)
                if wind_alert_text_aviso not in alertas_encontrados:
                    alertas_encontrados.append(wind_alert_text_aviso)


    # Garante que "Conteúdo não mapeado" só é adicionado se NENHUMA condição for encontrada
    # no final da análise.
    if not alertas_encontrados:
        alertas_encontrados.append("Conteúdo não mapeado")

    return list(set(alertas_encontrados)) # Usar set para remover duplicatas internas

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
