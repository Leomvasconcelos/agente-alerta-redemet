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

AERODROMOS_INTERESSE = ["SBTA"]
INTERVALO_VERIFICACAO = 300  # Usado apenas para execução local

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
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
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
    # A documentação sugere que a chave pode ir como parâmetro também, mas o header é mais comum.
    # params = {"api_key": REDEMET_API_KEY} 

    print(f"Buscando dados da REDEMET para {endpoint.upper()} em {aerodromo.upper()}...")

    try:
        response = requests.get(url, headers=headers, timeout=30) # Adicionado timeout
        response.raise_for_status()
        data_json = response.json()

        # *** CORREÇÃO PRINCIPAL: Assegurar que estamos pegando a lista de mensagens ***
        if data_json and 'data' in data_json:
            if isinstance(data_json['data'], list):
                print(f"Dados da REDEMET obtidos com sucesso para {aerodromo.upper()}. {len(data_json['data'])} mensagens em 'data'.")
                return {"data": data_json['data']}
            else:
                # Log para ajudar a diagnosticar se 'data' não é uma lista como esperado
                print(f"Chave 'data' encontrada para {aerodromo.upper()}, mas seu conteúdo não é uma lista. "
                      f"Tipo: {type(data_json['data'])}, Conteúdo: {str(data_json['data'])[:200]}")
                return {"data": []}
        else:
            print(f"Nenhuma chave 'data' válida (ou lista de dados) encontrada para {aerodromo.upper()} no endpoint {endpoint.upper()}. "
                  f"Resposta da API: {str(data_json)[:200]}")
            return {"data": []}

    except requests.exceptions.HTTPError as http_err:
        print(f"Erro HTTP ao acessar REDEMET API para {aerodromo.upper()} ({endpoint.upper()}): {http_err}")
        print(f"Status Code: {http_err.response.status_code}")
        print(f"Response Body: {http_err.response.text[:200]}")
        if http_err.response.status_code == 403:
            print("Verifique se a sua REDEMET_API_KEY está correta e ativa.")
    except requests.exceptions.ConnectionError as conn_err:
        print(f"Erro de conexão com a REDEMET API para {aerodromo.upper()}: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        print(f"Timeout ao acessar REDEMET API para {aerodromo.upper()}: {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        print(f"Erro geral ao acessar REDEMET API para {aerodromo.upper()}: {req_err}")
    except json.JSONDecodeError as json_err:
        print(f"Erro ao decodificar JSON da REDEMET API para {aerodromo.upper()}: {json_err}")
        # A resposta pode não estar disponível aqui se o erro for no response.json()
        # Se precisar depurar a resposta bruta em caso de erro JSON, adicione o print antes do response.json()
        # print(f"Response text (antes do JSONDecodeError): {response.text}")
    return {"data": []} # Retorna estrutura vazia consistente em caso de erro


def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """
    Analisa a mensagem meteorológica e retorna uma lista de descrições de condições perigosas.
    """
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    # --- Análise de Fenômenos Específicos (METAR/TAF/Aviso) ---
    if "METAR" in tipo_mensagem.upper() or "SPECI" in tipo_mensagem.upper() or "TAF" in tipo_mensagem.upper():
        for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
            if re.search(r'\b' + re.escape(codigo_icao) + r'\b', mensagem_upper):
                if codigo_icao in ["OVC", "BKN"] and re.search(f"{codigo_icao}00[1-5]", mensagem_upper):
                    alertas_encontrados.append(f"{descricao} (TETO BAIXO < 600FT)")
                elif codigo_icao == "FG":
                    vis_match = re.search(r'\s(\d{4})\s', mensagem_upper)
                    if vis_match and int(vis_match.group(1)) < 1000:
                        alertas_encontrados.append(f"{descricao} (VISIBILIDADE < 1000M)")
                    elif "FG" in mensagem_upper: # Se FG está presente mas visibilidade não foi parsada/encontrada
                        alertas_encontrados.append(descricao)
                elif codigo_icao == "CB":
                    cb_match = re.search(r'(FEW|SCT|BKN|OVC)(\d{3})CB', mensagem_upper)
                    if cb_match:
                        cloud_height = int(cb_match.group(2)) * 100
                        alertas_encontrados.append(f"{descricao} a {cloud_height}FT")
                    else:
                        alertas_encontrados.append(descricao)
                else:
                    alertas_encontrados.append(descricao)

        if re.search(r'\bVA\b', mensagem_upper) and "VALID" not in mensagem_upper: # Para METAR/TAF, VA fora de contexto de validade de aviso
            alertas_encontrados.append("Cinzas Vulcânicas (VA)")

        wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
        if wind_match:
            sustained_wind = int(wind_match.group(2))
            gust_wind_str = wind_match.group(4)
            wind_desc = []
            if sustained_wind >= 20:
                wind_desc.append(f"Vento Médio de {sustained_wind}KT")
            if gust_wind_str and int(gust_wind_str) >= 20:
                wind_desc.append(f"Rajadas de {int(gust_wind_str)}KT")
            if wind_desc:
                alertas_encontrados.append(" e ".join(wind_desc))

        if "TAF" in tipo_mensagem.upper():
            for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
                pattern_base = r'(?:PROB\d{2}|TEMPO|BECMG)\s+.*?\b' + re.escape(codigo_icao) + r'\b'
                if re.search(pattern_base, mensagem_upper):
                    prefixo_tendencia = re.search(r'(PROB\d{2}|TEMPO|BECMG)', mensagem_upper)
                    prefixo_str = prefixo_tendencia.group(1).upper() + ": " if prefixo_tendencia else "PREVISÃO: "

                    if codigo_icao in ["OVC", "BKN"] and re.search(pattern_base.replace(r'\b' + re.escape(codigo_icao) + r'\b', re.escape(codigo_icao) + r'00[1-5]'), mensagem_upper):
                        alertas_encontrados.append(f"{prefixo_str}{descricao} (TETO BAIXO < 600FT)")
                    elif codigo_icao == "FG":
                        # Tenta encontrar a visibilidade após o código dentro da seção de tendência
                        vis_match_taf = re.search(pattern_base.replace(r'\b' + re.escape(codigo_icao) + r'\b', re.escape(codigo_icao) + r'\s*(\d{4})'), mensagem_upper)
                        if vis_match_taf and int(vis_match_taf.group(1)) < 1000: # O grupo 1 será \d{4}
                             alertas_encontrados.append(f"{prefixo_str}{descricao} (VISIBILIDADE < 1000M)")
                        else: # Se FG está na tendência mas sem visibilidade específica < 1000M ou não parsável aqui
                            alertas_encontrados.append(f"{prefixo_str}{descricao}")
                    else:
                        alertas_encontrados.append(f"{prefixo_str}{descricao}")

            if re.search(r'(?:PROB\d{2}|TEMPO|BECMG)\s+.*?VA\b', mensagem_upper): # VA em tendência
                 alertas_encontrados.append("PREVISÃO: Cinzas Vulcânicas (VA)")

            # Análise de vento em seções de tendência no TAF
            # A regex original é complexa para isolar o prefixo por grupo de vento. Simplificando a abordagem:
            # Se já detectou vento forte na análise geral do TAF, isso pode ser suficiente.
            # Se precisar de vento forte *específico* por TEMPO/BECMG/PROB:
            taf_sections = re.split(r'(PROB\d{2}|TEMPO|BECMG)', mensagem_upper)
            current_prefix = "PREVISÃO (parte principal)"
            for i, section_text in enumerate(taf_sections):
                if section_text in ["PROB30", "PROB40", "TEMPO", "BECMG"]:
                    current_prefix = section_text
                    continue # Próxima iteração terá o conteúdo da seção

                # Analisa o vento para a seção atual (section_text) com seu prefixo (current_prefix)
                wind_match_taf_section = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', section_text)
                if wind_match_taf_section:
                    sustained_wind_taf = int(wind_match_taf_section.group(2))
                    gust_wind_taf_str = wind_match_taf_section.group(4)
                    wind_desc_taf_section = []
                    if sustained_wind_taf >= 20:
                        wind_desc_taf_section.append(f"Vento Médio de {sustained_wind_taf}KT")
                    if gust_wind_taf_str and int(gust_wind_taf_str) >= 20:
                        wind_desc_taf_section.append(f"Rajadas de {int(gust_wind_taf_str)}KT")
                    
                    if wind_desc_taf_section:
                        # Adiciona o prefixo apenas se não for da parte principal e já não estiver no alerta
                        prefix_to_add = f"{current_prefix.upper()}: " if current_prefix != "PREVISÃO (parte principal)" else "PREVISÃO: "
                        full_wind_alert = f"{prefix_to_add}{' e '.join(wind_desc_taf_section)}"
                        # Evitar duplicar alertas de vento se a análise geral já pegou
                        is_new_alert = True
                        for alr in alertas_encontrados:
                            if wind_match_taf_section.group(0) in alr: # se o grupo de vento exato já foi reportado
                                is_new_alert = False
                                break
                        if is_new_alert:
                             alertas_encontrados.append(full_wind_alert)
                
                if i > 0 and taf_sections[i-1] in ["PROB30", "PROB40", "TEMPO", "BECMG"]: # Reseta o prefixo após usar o conteúdo da seção
                    current_prefix = "PREVISÃO (parte principal)"


    elif "AD WRNG" in tipo_mensagem.upper() or "AVISO DE AERÓDROMO" in tipo_mensagem.upper():
        aviso_fenomenos_desc = []
        if "TS" in mensagem_upper: aviso_fenomenos_desc.append("Trovoada")
        
        wind_warning_match = re.search(r'SFC WSPD (\d+)KT(?: MAX (\d+)KT)?', mensagem_upper) # Adicionado KT ao MAX
        if wind_warning_match:
            min_wind = int(wind_warning_match.group(1))
            max_wind_str = wind_warning_match.group(2)
            wind_parts = []
            if min_wind >= 15: wind_parts.append(f"Vento de Superfície de {min_wind}KT")
            if max_wind_str and int(max_wind_str) >= 25: wind_parts.append(f"Rajadas de {int(max_wind_str)}KT")
            if wind_parts: aviso_fenomenos_desc.append(" e ".join(wind_parts))

        if "GRANIZO" in mensagem_upper: aviso_fenomenos_desc.append("Granizo")
        
        if "FG" in mensagem_upper or "NEVOEIRO" in mensagem_upper:
            vis_match_aviso = re.search(r'VIS\s*<\s*(\d+)([MK])', mensagem_upper) # VIS < 1000M ou VIS < 1K
            if vis_match_aviso:
                vis_value = int(vis_match_aviso.group(1))
                vis_unit = vis_match_aviso.group(2).upper()
                vis_meters = vis_value * 1000 if vis_unit == 'K' else vis_value
                if vis_meters < 1000:
                    aviso_fenomenos_desc.append(f"Nevoeiro (VISIBILIDADE < {vis_value}{vis_unit})")
            else: # Se FG/NEVOEIRO presente sem especificação de visibilidade < X
                aviso_fenomenos_desc.append("Nevoeiro")
        
        if "CHUVA FORTE" in mensagem_upper or re.search(r'\+RA\b', mensagem_upper): aviso_fenomenos_desc.append("Chuva Forte")
        if "VISIBILIDADE REDUZIDA" in mensagem_upper: aviso_fenomenos_desc.append("Visibilidade Reduzida")
        if "WIND SHEAR" in mensagem_upper or re.search(r'\bWS\b', mensagem_upper): aviso_fenomenos_desc.append("Tesoura de Vento (Wind Shear)")
        if re.search(r'\bVA\b', mensagem_upper): aviso_fenomenos_desc.append("Cinzas Vulcânicas (VA)") # VA em avisos
        if "FUMAÇA" in mensagem_upper or re.search(r'\bFU\b', mensagem_upper): aviso_fenomenos_desc.append("Fumaça")
        
        if aviso_fenomenos_desc:
            alertas_encontrados.extend(aviso_fenomenos_desc) # Deduplicação final cuidará disso
    
    return list(set(alertas_encontrados)) # Retorna alertas únicos


def verificar_e_alertar():
    """Verifica as condições meteorológicas e envia alertas."""
    print(f"[{datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Iniciando verificação de condições meteorológicas...")

    if not REDEMET_API_KEY:
        print("Erro: REDEMET_API_KEY não configurada. Defina a secret 'REDEMET_API_KEY' no GitHub.")
        return

    agora_utc = datetime.now(pytz.utc)

    for aerodromo in AERODROMOS_INTERESSE:
        endpoints_e_tipos = {
            "aviso": "AVISO DE AERÓDROMO",
            "taf": "TAF",
            "metar": "METAR/SPECI" # Tratamento de METAR/SPECI será feito abaixo
        }

        for endpoint, tipo_base_mensagem in endpoints_e_tipos.items():
            print(f"Processando {endpoint.upper()} para {aerodromo}...")
            mensagens_api_data = obter_mensagens_redemet(endpoint, aerodromo) # Espera {"data": [...]}

            if mensagens_api_data and isinstance(mensagens_api_data.get('data'), list):
                lista_mensagens = mensagens_api_data['data']
                if not lista_mensagens:
                    print(f"Nenhuma mensagem em 'data' para {tipo_base_mensagem} de {aerodromo}.")
                    continue

                for item_msg in lista_mensagens:
                    mensagem_real = ""
                    if isinstance(item_msg, dict) and 'mensagem' in item_msg:
                        mensagem_real = item_msg['mensagem']
                    elif isinstance(item_msg, str): # Fallback se a API retornar string diretamente
                        mensagem_real = item_msg
                    else:
                        print(f"Item de mensagem em formato inesperado para {aerodromo} ({endpoint}): {str(item_msg)[:100]}")
                        continue
                    
                    if not mensagem_real.strip():
                        print(f"Mensagem {tipo_base_mensagem} vazia para {aerodromo}. Item: {item_msg}")
                        continue

                    # Determinar tipo específico para METAR/SPECI
                    tipo_atual_mensagem = tipo_base_mensagem
                    if endpoint == "metar":
                        tipo_atual_mensagem = "SPECI" if mensagem_real.upper().startswith("SPECI") else "METAR"

                    msg_hash = calcular_hash_mensagem(mensagem_real)

                    if msg_hash not in alertas_enviados_cache:
                        condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_real, tipo_atual_mensagem)
                        if condicoes_perigosas:
                            emoji_alerta = "🚨" # Aviso
                            if tipo_atual_mensagem == "TAF": emoji_alerta = "⚠️"
                            elif tipo_atual_mensagem in ["METAR", "SPECI"]: emoji_alerta = "⚡️"
                            
                            titulo_condicao = "Condições Reportadas" if tipo_atual_mensagem in ["METAR", "SPECI"] else "Condições Previstas"

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
                print(f"Falha ao obter ou processar dados para {endpoint.upper()} de {aerodromo}. Resposta: {mensagens_api_data}")
        print(f"Processamento de {aerodromo} concluído.")

    # Limpeza do cache
    for msg_hash in list(alertas_enviados_cache.keys()):
        if agora_utc - alertas_enviados_cache[msg_hash] > timedelta(hours=24):
            del alertas_enviados_cache[msg_hash]
            print(f"Hash {msg_hash} removido do cache (expirado).")
    print("Limpeza de cache concluída.")

# --- Execução Principal ---
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erro: Variáveis de ambiente TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configuradas.")
    elif not REDEMET_API_KEY:
        print("Erro: REDEMET_API_KEY não configurada.")
    else:
        # Para rodar localmente em loop (descomente as linhas abaixo):
        # while True:
        # verificar_e_alertar()
        # print(f"Aguardando {INTERVALO_VERIFICACAO // 60} minutos para a próxima verificação...")
        # time.sleep(INTERVALO_VERIFICACAO)
        
        # Execução única para GitHub Actions:
        print("Executando verificação de alertas REDEMET (execução única para GitHub Actions).")
        verificar_e_alertar()
        print(f"[{datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Verificação concluída.")
