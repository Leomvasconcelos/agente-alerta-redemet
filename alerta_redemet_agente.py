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

# Aeródromo de interesse (conforme solicitado, apenas SBTA)
AERODROMOS_INTERESSE = ["SBTA"]

# Intervalo de verificação em segundos (5 minutos) - Usado apenas para execução local
# No GitHub Actions, o agendamento é feito pelo cron no .yml
INTERVALO_VERIFICACAO = 300

CODIGOS_METAR_TAF_MAP = {
    "TS": "Trovoada", "RA": "Chuva", "+RA": "Chuva Forte", "-RA": "Chuva Fraca",
    "GR": "Granizo", "GS": "Granizo Pequeno/Grãos de Neve", "FZRA": "Chuva Congelante",
    "SN": "Neve", "SG": "Nevoeiro Congelante", "IC": "Cristais de Gelo",
    "PL": "Pellets de Gelo", "UP": "Precipitação Desconhecida", "FG": "Nevoeiro",
    "BR": "Névoa", "FU": "Fumaça", "DU": "Poeira Generalizada", "SA": "Areia",
    "BLDU": "Poeira Levantada", "BLSA": "Areia Levantada", "BLSN": "Neve Levantada",
    "DRDU": "Poeira Arrastada", "DRSA": "Areia Arrastada", "DRSN": "Neve Arrastada",
    "PO": "Redemoinhos de Poeira/Areia", "SQ": "Rajada (Squall)",
    "FC": "Funil de Vento (Tornado/Waterspout)", "SS": "Tempestade de Areia",
    "DS": "Tempestade de Poeira", "VCTS": "Trovoada nas Proximidades",
    "SH": "Pancada (Shower)", "OVC": "Nublado (Overcast)",
    "BKN": "Parcialmente Nublado (Broken)", "CB": "Cumulunimbus",
    "TCU": "Cumulus Castellanus", "WS": "Tesoura de Vento (Wind Shear)",
}

alertas_enviados_cache = {}  # {hash_da_mensagem: timestamp_envio}

# --- Funções Auxiliares ---

def calcular_hash_mensagem(mensagem):
    """Calcula um hash simples da mensagem para evitar duplicatas."""
    return hash(mensagem)

def enviar_mensagem_telegram(chat_id, texto):
    """Envia uma mensagem para o Telegram."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        print("Token do Telegram ou Chat ID não configurados. Não é possível enviar mensagem.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10) # Adicionado timeout
        response.raise_for_status()
        print(f"Mensagem enviada com sucesso para o Telegram: {texto[:100]}...") # Log truncado
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar mensagem para o Telegram: {e}")

def obter_mensagens_redemet(endpoint, aerodromo):
    """
    Obtém dados meteorológicos da API da REDEMET.
    Retorna um dicionário contendo a lista de mensagens sob a chave 'data'.
    Ex: {"data": [lista_de_mensagens]}
    """
    url = f"https://api-redemet.decea.mil.br/mensagens/{endpoint}/{aerodromo}"
    headers = {"x-api-key": REDEMET_API_KEY}

    print(f"Buscando dados da REDEMET para {endpoint.upper()} em {aerodromo.upper()}...")

    try:
        response = requests.get(url, headers=headers, timeout=30) # Timeout para a requisição
        response.raise_for_status() # Levanta erro para status HTTP 4xx/5xx
        data_json = response.json()

        if data_json and 'data' in data_json:
            data_principal = data_json['data']

            if isinstance(data_principal, dict):
                lista_mensagens_aninhada = data_principal.get('data')
                if isinstance(lista_mensagens_aninhada, list):
                    print(f"Dados da REDEMET (estrutura aninhada) obtidos com sucesso para {aerodromo.upper()}. {len(lista_mensagens_aninhada)} mensagens.")
                    return {"data": lista_mensagens_aninhada}
                else:
                    # Log se a 'data' aninhada não for uma lista ou não existir, mas havia algo na 'data' principal (dict)
                    conteudo_data_principal = str(data_principal)[:200] # Log truncado do dicionário 'data' principal
                    if not lista_mensagens_aninhada and 'data' in data_principal and not data_principal['data']: # Se data:[] aninhado
                         print(f"Dados da REDEMET (estrutura aninhada) obtidos para {aerodromo.upper()}, mas a lista de mensagens está vazia. Detalhes da paginação: {conteudo_data_principal}")
                         return {"data": []} # Lista de mensagens aninhada vazia
                    print(f"Chave 'data' principal é um dicionário, mas a chave 'data' aninhada não é uma lista ou não foi encontrada como esperado. "
                          f"Aeroporto: {aerodromo.upper()}. Tipo da 'data' aninhada: {type(lista_mensagens_aninhada)}. Conteúdo da 'data' principal: {conteudo_data_principal}")
                    return {"data": []}
            elif isinstance(data_principal, list):
                print(f"Dados da REDEMET (estrutura direta) obtidos com sucesso para {aerodromo.upper()}. {len(data_principal)} mensagens.")
                return {"data": data_principal}
            else:
                print(f"Chave 'data' principal encontrada para {aerodromo.upper()}, mas seu conteúdo não é um dicionário (esperado) nem uma lista. "
                      f"Tipo: {type(data_principal)}, Conteúdo: {str(data_principal)[:200]}")
                return {"data": []}
        else:
            resposta_api_str = str(data_json)[:200] if data_json else "Resposta vazia ou inválida"
            print(f"Nenhuma chave 'data' principal encontrada para {aerodromo.upper()} no endpoint {endpoint.upper()}. "
                  f"Resposta da API: {resposta_api_str}")
            return {"data": []}

    except requests.exceptions.HTTPError as http_err:
        print(f"Erro HTTP ao acessar REDEMET API para {aerodromo.upper()} ({endpoint.upper()}): {http_err}")
        if hasattr(http_err, 'response') and http_err.response is not None:
            print(f"Status Code: {http_err.response.status_code}")
            print(f"Response Body: {http_err.response.text[:200]}")
            if http_err.response.status_code == 403:
                print("Verifique se a sua REDEMET_API_KEY está correta e ativa.")
        else:
            print(f"Erro HTTP sem objeto de resposta: {http_err}")
    except requests.exceptions.ConnectionError as conn_err:
        print(f"Erro de conexão com a REDEMET API para {aerodromo.upper()} ({endpoint.upper()}): {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        print(f"Timeout ao acessar REDEMET API para {aerodromo.upper()} ({endpoint.upper()}): {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        print(f"Erro geral ao acessar REDEMET API para {aerodromo.upper()} ({endpoint.upper()}): {req_err}")
    except json.JSONDecodeError as json_err:
        print(f"Erro ao decodificar JSON da REDEMET API para {aerodromo.upper()}: {json_err}")
        # Para depurar a resposta bruta em caso de erro JSON, podemos tentar obter o response.text
        # if 'response' in locals() and hasattr(response, 'text'):
        # print(f"Response text (antes do JSONDecodeError): {response.text}")
    return {"data": []}


def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """
    Analisa a mensagem meteorológica e retorna uma lista de descrições de condições perigosas.
    """
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    if "METAR" in tipo_mensagem.upper() or "SPECI" in tipo_mensagem.upper() or "TAF" in tipo_mensagem.upper():
        for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
            if re.search(r'\b' + re.escape(codigo_icao) + r'\b', mensagem_upper):
                if codigo_icao in ["OVC", "BKN"] and re.search(f"{codigo_icao}00[1-5]", mensagem_upper):
                    alertas_encontrados.append(f"{descricao} (TETO BAIXO < 600FT)")
                elif codigo_icao == "FG":
                    vis_match = re.search(r'\s(\d{4})\s', mensagem_upper) # Visibilidade como 4 dígitos (ex: 0800)
                    # Tenta encontrar visibilidade fracionada também, comum em alguns METARs, ex: 1/4SM
                    # Esta regex é um exemplo e pode precisar de ajustes para formatos específicos de visibilidade fracionada
                    vis_frac_match = re.search(r'\s(\d/\dSM)\s', mensagem_upper)
                    if vis_match and int(vis_match.group(1)) < 1000:
                        alertas_encontrados.append(f"{descricao} (VISIBILIDADE < 1000M)")
                    elif vis_frac_match: # Se encontrar visibilidade fracionada, considerar como perigosa
                        alertas_encontrados.append(f"{descricao} (VISIBILIDADE RESTRITA: {vis_frac_match.group(1)})")
                    elif "FG" in mensagem_upper and not vis_match and not vis_frac_match:
                        alertas_encontrados.append(descricao) # FG presente, mas visibilidade não parsada/crítica
                elif codigo_icao == "CB":
                    cb_match = re.search(r'(FEW|SCT|BKN|OVC)(\d{3})CB', mensagem_upper)
                    if cb_match:
                        cloud_height = int(cb_match.group(2)) * 100
                        alertas_encontrados.append(f"{descricao} a {cloud_height}FT")
                    else:
                        alertas_encontrados.append(descricao)
                elif codigo_icao != "CAVOK": # Não alertar para CAVOK como fenômeno isolado
                    alertas_encontrados.append(descricao)

        if re.search(r'\bVA\b', mensagem_upper) and "VALID" not in mensagem_upper:
            alertas_encontrados.append("Cinzas Vulcânicas (VA)")

        wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
        if wind_match:
            sustained_wind = int(wind_match.group(2))
            gust_wind_str = wind_match.group(4)
            wind_desc = []
            if sustained_wind >= 20:
                wind_desc.append(f"Vento Médio de {sustained_wind}KT")
            if gust_wind_str and int(gust_wind_str) >= 20: # Considerar rajadas a partir de 20KT também como alerta
                wind_desc.append(f"Rajadas de {int(gust_wind_str)}KT")
            if wind_desc:
                alertas_encontrados.append(" e ".join(wind_desc))

        if "TAF" in tipo_mensagem.upper():
            # Analisa fenômenos e ventos dentro de blocos de tendência (TEMPO, BECMG, PROB)
            taf_sections = re.split(r'(PROB\d{2}\s(?:TEMPO)?|FM\d{6}|TEMPO\s(?:FM\d{6}\sTL\d{6}|FM\d{6}|TL\d{6})?|BECMG\s(?:FM\d{6}\sTL\d{6}|FM\d{6}|TL\d{6})?)', mensagem_upper)
            
            current_prefix = "PREVISÃO (Principal)"
            for i, section_content in enumerate(taf_sections):
                if i % 2 == 1: # Se for um prefixo capturado
                    current_prefix = section_content.strip() if section_content else "Bloco de Tendência"
                    continue # O conteúdo estará na próxima iteração

                # current_prefix agora é o prefixo do bloco (ou "Principal")
                # section_content é o texto desse bloco
                
                for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
                    if re.search(r'\b' + re.escape(codigo_icao) + r'\b', section_content):
                        prefix_str = f"{current_prefix}: " if current_prefix != "PREVISÃO (Principal)" else "PREVISÃO: "
                        if codigo_icao in ["OVC", "BKN"] and re.search(f"{codigo_icao}00[1-5]", section_content):
                            alertas_encontrados.append(f"{prefix_str}{descricao} (TETO BAIXO < 600FT)")
                        elif codigo_icao == "FG":
                            vis_match_taf = re.search(r'\s(\d{4})\s', section_content)
                            if vis_match_taf and int(vis_match_taf.group(1)) < 1000:
                                alertas_encontrados.append(f"{prefix_str}{descricao} (VISIBILIDADE < 1000M)")
                            elif "FG" in section_content:
                                alertas_encontrados.append(f"{prefix_str}{descricao}")
                        elif codigo_icao != "CAVOK":
                             alertas_encontrados.append(f"{prefix_str}{descricao}")
                
                if re.search(r'\bVA\b', section_content):
                    prefix_str = f"{current_prefix}: " if current_prefix != "PREVISÃO (Principal)" else "PREVISÃO: "
                    alertas_encontrados.append(f"{prefix_str}Cinzas Vulcânicas (VA)")

                wind_match_taf_section = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', section_content)
                if wind_match_taf_section:
                    sustained_wind_taf = int(wind_match_taf_section.group(2))
                    gust_wind_taf_str = wind_match_taf_section.group(4)
                    wind_desc_taf_section = []
                    if sustained_wind_taf >= 20:
                        wind_desc_taf_section.append(f"Vento Médio de {sustained_wind_taf}KT")
                    if gust_wind_taf_str and int(gust_wind_taf_str) >= 20:
                        wind_desc_taf_section.append(f"Rajadas de {int(gust_wind_taf_str)}KT")
                    if wind_desc_taf_section:
                        prefix_str = f"{current_prefix.upper()}: " if current_prefix != "PREVISÃO (Principal)" else "PREVISÃO: "
                        alertas_encontrados.append(f"{prefix_str}{' e '.join(wind_desc_taf_section)}")


    elif "AD WRNG" in tipo_mensagem.upper() or "AVISO DE AERÓDROMO" in tipo_mensagem.upper():
        aviso_fenomenos_desc = []
        if "TS" in mensagem_upper or "TROVOADA" in mensagem_upper: aviso_fenomenos_desc.append("Trovoada")
        
        wind_warning_match = re.search(r'SFC WSPD (\d+)KT(?: MAX (\d+)KT)?', mensagem_upper)
        if wind_warning_match:
            min_wind = int(wind_warning_match.group(1))
            max_wind_str = wind_warning_match.group(2)
            wind_parts = []
            if min_wind >= 15: wind_parts.append(f"Vento de Superfície de {min_wind}KT")
            if max_wind_str and int(max_wind_str) >= 25: wind_parts.append(f"Rajadas de {int(max_wind_str)}KT")
            if wind_parts: aviso_fenomenos_desc.append(" e ".join(wind_parts))

        if "GRANIZO" in mensagem_upper: aviso_fenomenos_desc.append("Granizo")
        
        if "FG" in mensagem_upper or "NEVOEIRO" in mensagem_upper:
            vis_match_aviso = re.search(r'VIS\s*<\s*(\d+)\s*([MK]M?)', mensagem_upper) # VIS < 1000M ou VIS < 1K ou VIS < 1KM
            if vis_match_aviso:
                vis_value = int(vis_match_aviso.group(1))
                vis_unit = vis_match_aviso.group(2).upper()
                vis_meters = vis_value
                if 'K' in vis_unit: # Se for KM, converte para metros
                    vis_meters = vis_value * 1000
                
                if vis_meters < 1000:
                    alertas_encontrados.append(f"Nevoeiro (VISIBILIDADE < {vis_value}{vis_unit.replace('M','') if vis_unit != 'M' else 'M'})") # Ex: < 1000M ou < 1K
            elif "FG" in mensagem_upper or "NEVOEIRO" in mensagem_upper: # Se apenas "FG" ou "NEVOEIRO"
                 aviso_fenomenos_desc.append("Nevoeiro")
        
        if "CHUVA FORTE" in mensagem_upper or re.search(r'\+RA\b', mensagem_upper): aviso_fenomenos_desc.append("Chuva Forte")
        if "VISIBILIDADE REDUZIDA" in mensagem_upper: aviso_fenomenos_desc.append("Visibilidade Reduzida") # Termo genérico
        if "WIND SHEAR" in mensagem_upper or re.search(r'\bWS\b', mensagem_upper): aviso_fenomenos_desc.append("Tesoura de Vento (Wind Shear)")
        if re.search(r'\bVA\b', mensagem_upper): aviso_fenomenos_desc.append("Cinzas Vulcânicas (VA)")
        if "FUMAÇA" in mensagem_upper or re.search(r'\bFU\b', mensagem_upper): aviso_fenomenos_desc.append("Fumaça")
        
        if aviso_fenomenos_desc:
            alertas_encontrados.extend(aviso_fenomenos_desc)
    
    return list(set(alertas_encontrados))


def verificar_e_alertar():
    """Verifica as condições meteorológicas e envia alertas."""
    timestamp_inicio = datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"[{timestamp_inicio}] Iniciando verificação de condições meteorológicas...")

    if not REDEMET_API_KEY:
        print("Erro: REDEMET_API_KEY não configurada. Defina a secret 'REDEMET_API_KEY' no GitHub.")
        return

    agora_utc = datetime.now(pytz.utc)

    for aerodromo in AERODROMOS_INTERESSE:
        endpoints_e_tipos = {
            "aviso": "AVISO DE AERÓDROMO",
            "taf": "TAF",
            "metar": "METAR/SPECI"
        }

        print(f"--- Processando Aeródromo: {aerodromo} ---")
        for endpoint, tipo_base_mensagem in endpoints_e_tipos.items():
            mensagens_api_data = obter_mensagens_redemet(endpoint, aerodromo)

            if mensagens_api_data and isinstance(mensagens_api_data.get('data'), list):
                lista_mensagens = mensagens_api_data['data']
                if not lista_mensagens:
                    print(f"Nenhuma mensagem em '{endpoint}' para {tipo_base_mensagem} de {aerodromo}.")
                    continue

                print(f"Encontradas {len(lista_mensagens)} mensagens para {tipo_base_mensagem} de {aerodromo}.")
                for item_msg in lista_mensagens:
                    mensagem_real = ""
                    # A API da REDEMET retorna as mensagens dentro de um objeto com chave "mensagem"
                    # ou, para alguns endpoints/situações, pode ser que o item_msg já seja a string.
                    # O mais comum é ser um dicionário com 'id_localidade', 'validade_inicial', 'mensagem'.
                    if isinstance(item_msg, dict) and 'mensagem' in item_msg:
                        mensagem_real = item_msg['mensagem']
                    elif isinstance(item_msg, str):
                        mensagem_real = item_msg # Fallback menos comum
                    else:
                        print(f"Item de mensagem em formato inesperado para {aerodromo} ({endpoint}): {str(item_msg)[:100]}")
                        continue
                    
                    if not mensagem_real.strip():
                        print(f"Mensagem {tipo_base_mensagem} vazia ou inválida para {aerodromo}. Item: {str(item_msg)[:100]}")
                        continue

                    tipo_atual_mensagem = tipo_base_mensagem
                    if endpoint == "metar": # Se for do endpoint metar, pode ser METAR ou SPECI
                        tipo_atual_mensagem = "SPECI" if mensagem_real.upper().startswith("SPECI") else "METAR"

                    msg_hash = calcular_hash_mensagem(mensagem_real)

                    if msg_hash not in alertas_enviados_cache:
                        condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_real, tipo_atual_mensagem)
                        if condicoes_perigosas:
                            emoji_alerta = "🚨" # Aviso
                            if tipo_atual_mensagem == "TAF": emoji_alerta = "⚠️"
                            elif tipo_atual_mensagem in ["METAR", "SPECI"]: emoji_alerta = "⚡️"
                            
                            titulo_condicao = "Condições Reportadas" if tipo_atual_mensagem in ["METAR", "SPECI"] else "Condições Previstas/Alertadas"

                            alert_text = (
                                f"{emoji_alerta} *NOVO ALERTA MET {aerodromo}!* {emoji_alerta}\n\n"
                                f"Aeródromo: *{aerodromo}* - Tipo: *{tipo_atual_mensagem}*\n"
                                f"{titulo_condicao}: *{', '.join(condicoes_perigosas)}*\n"
                                f"Mensagem Original:\n`{mensagem_real}`\n\n"
                                f"(Hora do Agente: {agora_utc.strftime('%Y-%m-%d %H:%M:%S UTC')})"
                            )
                            enviar_mensagem_telegram(TELEGRAM_CHAT_ID, alert_text)
                            alertas_enviados_cache[msg_hash] = agora_utc
                            print(f"Alerta de {tipo_atual_mensagem} enviado para {aerodromo}: {', '.join(condicoes_perigosas)}")
                        else:
                            print(f"{tipo_atual_mensagem} para {aerodromo} sem condições perigosas detectadas: {mensagem_real[:70]}...")
                    else:
                        print(f"{tipo_atual_mensagem} para {aerodromo} já alertado (cache): {mensagem_real[:70]}...")
            else:
                print(f"Falha ao obter ou processar dados para {endpoint.upper()} de {aerodromo}. Resposta da API não continha lista de dados válida.")
        print(f"--- Fim do processamento para Aeródromo: {aerodromo} ---")


    # Limpeza do cache de alertas mais antigos que 24 horas
    chaves_para_remover = [
        msg_hash for msg_hash, timestamp_envio in alertas_enviados_cache.items()
        if agora_utc - timestamp_envio > timedelta(hours=24)
    ]
    for msg_hash in chaves_para_remover:
        del alertas_enviados_cache[msg_hash]
        print(f"Hash {msg_hash} removido do cache (expirado).")
    if chaves_para_remover:
        print(f"Limpeza de cache concluída. {len(chaves_para_remover)} itens removidos.")
    else:
        print("Nenhum item expirado no cache para limpar.")

# --- Execução Principal ---
if __name__ == "__main__":
    # Verifica se as variáveis de ambiente essenciais estão configuradas
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erro Crítico: Variáveis de ambiente TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configuradas.")
        print("Por favor, defina-as como secrets no GitHub.")
    elif not REDEMET_API_KEY:
        print("Erro Crítico: REDEMET_API_KEY não configurada.")
        print("Certifique-se de que a secret 'REDEMET_API_KEY' está definida no GitHub.")
    else:
        # Execução única para GitHub Actions (ou pode ser adaptado para loop local)
        print("Executando verificação de alertas REDEMET (configurado para execução única).")
        verificar_e_alertar()
        timestamp_fim = datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"[{timestamp_fim}] Verificação concluída.")
