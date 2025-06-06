import os
import requests
import json
import time
from datetime import datetime, timedelta, timezone
import pytz
import re

# --- Configurações ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
REDEMET_API_KEY = os.getenv('REDEMET_API_KEY')

# Aeródromo de interesse
AERODROMOS_INTERESSE = ["SBTA"]

# Fenômenos significativos para METAR/TAF/SPECI, conforme solicitado
SIGNIFICANT_PHENOMENA_METAR_TAF = {
    "TS": "Trovoada",
    "FG": "Nevoeiro",
    "GR": "Granizo", # Adicionado
}

# --- Lógica de Cache Persistente ---
CACHE_FILE_PATH = "persistent_alert_cache.json"
alertas_enviados_cache = {}

def calcular_hash_mensagem_str(mensagem):
    return str(hash(mensagem))

def load_persistent_cache():
    global alertas_enviados_cache
    alertas_enviados_cache = {}
    try:
        if os.path.exists(CACHE_FILE_PATH):
            with open(CACHE_FILE_PATH, 'r') as f:
                loaded_data = json.load(f)
                for msg_hash_str, ts_iso_str in loaded_data.items():
                    try:
                        alertas_enviados_cache[msg_hash_str] = datetime.fromisoformat(ts_iso_str).replace(tzinfo=timezone.utc)
                    except ValueError as e:
                        print(f"Erro ao parsear entrada do cache ({msg_hash_str}: {ts_iso_str}): {e}. Pulando entrada.")
                print(f"Cache persistente carregado de {CACHE_FILE_PATH}. {len(alertas_enviados_cache)} itens.")
        else:
            print(f"Arquivo de cache persistente {CACHE_FILE_PATH} não encontrado. Iniciando com cache vazio.")
    except Exception as e:
        print(f"Erro crítico ao carregar cache persistente de {CACHE_FILE_PATH}: {e}. Iniciando com cache vazio.")

def save_persistent_cache():
    global alertas_enviados_cache
    serializable_cache = {}
    for msg_hash_str, dt_obj in alertas_enviados_cache.items():
        if isinstance(dt_obj, datetime):
            serializable_cache[msg_hash_str] = dt_obj.astimezone(timezone.utc).isoformat()
        else:
            print(f"Aviso: Objeto não-datetime encontrado no cache para o hash {msg_hash_str}. Tipo: {type(dt_obj)}. Pulando.")

    try:
        with open(CACHE_FILE_PATH, 'w') as f:
            json.dump(serializable_cache, f, indent=4)
        print(f"Cache persistente salvo em {CACHE_FILE_PATH}. {len(serializable_cache)} itens.")
    except Exception as e:
        print(f"Erro crítico ao salvar cache persistente em {CACHE_FILE_PATH}: {e}")

# --- Funções Auxiliares (Restantes) ---
def enviar_mensagem_telegram(chat_id, texto):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        print("Token do Telegram ou Chat ID não configurados. Não é possível enviar mensagem.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print(f"Mensagem enviada com sucesso para o Telegram: {texto[:100]}...")
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar mensagem para o Telegram: {e}")

def obter_mensagens_redemet(endpoint, aerodromo):
    url = f"https://api-redemet.decea.mil.br/mensagens/{endpoint}/{aerodromo}"
    headers = {"x-api-key": REDEMET_API_KEY}
    print(f"Buscando dados da REDEMET para {endpoint.upper()} em {aerodromo.upper()}...")
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data_json = response.json()
        if data_json and 'data' in data_json:
            data_principal = data_json['data']
            if isinstance(data_principal, dict):
                lista_mensagens_aninhada = data_principal.get('data')
                if isinstance(lista_mensagens_aninhada, list):
                    print(f"Dados da REDEMET (estrutura aninhada) obtidos com sucesso para {aerodromo.upper()}. {len(lista_mensagens_aninhada)} mensagens.")
                    return {"data": lista_mensagens_aninhada}
                else:
                    conteudo_data_principal = str(data_principal)[:200]
                    if not lista_mensagens_aninhada and 'data' in data_principal and data_principal['data'] is not None and not data_principal['data'] :
                         print(f"Dados da REDEMET (estrutura aninhada) obtidos para {aerodromo.upper()}, mas a lista de mensagens está vazia.")
                         return {"data": []}
                    print(f"Chave 'data' principal é um dicionário, mas a chave 'data' aninhada não é uma lista ou não foi encontrada como esperado.")
                    return {"data": []}
            elif isinstance(data_principal, list):
                print(f"Dados da REDEMET (estrutura direta) obtidos com sucesso para {aerodromo.upper()}. {len(data_principal)} mensagens.")
                return {"data": data_principal}
            else:
                print(f"Chave 'data' principal encontrada, mas seu conteúdo não é um dicionário (esperado) nem uma lista.")
                return {"data": []}
        else:
            resposta_api_str = str(data_json)[:200] if data_json else "Resposta vazia ou inválida"
            print(f"Nenhuma chave 'data' principal encontrada para {aerodromo.upper()}. Resposta da API: {resposta_api_str}")
            return {"data": []}
    except requests.exceptions.HTTPError as http_err: print(f"Erro HTTP ao acessar REDEMET API para {aerodromo.upper()} ({endpoint.upper()}): {http_err}")
    except requests.exceptions.ConnectionError as conn_err: print(f"Erro de conexão com a REDEMET API para {aerodromo.upper()}: {conn_err}")
    except requests.exceptions.Timeout as timeout_err: print(f"Timeout ao acessar REDEMET API para {aerodromo.upper()}: {timeout_err}")
    except requests.exceptions.RequestException as req_err: print(f"Erro geral ao acessar REDEMET API para {aerodromo.upper()}: {req_err}")
    except json.JSONDecodeError as json_err: print(f"Erro ao decodificar JSON da REDEMET API para {aerodromo.upper()}: {json_err}")
    return {"data": []}

def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """
    Analisa a mensagem com base nas novas regras de alerta.
    """
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    # --- Lógica para METAR, SPECI, TAF ---
    if "METAR" in tipo_mensagem.upper() or "SPECI" in tipo_mensagem.upper() or "TAF" in tipo_mensagem.upper():
        
        # 1. Checar Fenômenos Significativos (TS, FG, GR)
        for codigo, descricao in SIGNIFICANT_PHENOMENA_METAR_TAF.items():
            if re.search(r'\b' + re.escape(codigo) + r'\b', mensagem_upper):
                alertas_encontrados.append(descricao)

        # 2. Checar Cinzas Vulcânicas (VA)
        if re.search(r'\bVA\b', mensagem_upper):
            alertas_encontrados.append("Cinzas Vulcânicas")

        # 3. Checar Teto Baixo (BKN ou OVC abaixo de 600ft)
        match_teto = re.search(r'\b(BKN|OVC)00([1-5])\b', mensagem_upper.replace("OVC000", "OVC001"))
        if match_teto:
             teto_tipo = "Parcialmente Nublado" if match_teto.group(1) == "BKN" else "Nublado"
             alertas_encontrados.append(f"Teto Baixo ({teto_tipo} < 600ft)")

        # 4. Checar Vento Forte
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

        # Se for TAF, verificar condições nos blocos de tendência também
        if "TAF" in tipo_mensagem.upper():
            trend_blocks = re.findall(r'((?:PROB\d{2}|TEMPO|BECMG).*?)(?=PROB\d{2}|TEMPO|BECMG|RMK|$)', mensagem_upper)
            for block in trend_blocks:
                prefix_match = re.match(r'(PROB\d{2}|TEMPO|BECMG)', block)
                if not prefix_match: continue
                prefix = prefix_match.group(1)
                
                # Checa fenômenos no bloco
                for codigo, descricao in SIGNIFICANT_PHENOMENA_METAR_TAF.items():
                    if re.search(r'\b' + re.escape(codigo) + r'\b', block):
                        alertas_encontrados.append(f"{prefix}: {descricao}")
                # Checa VA no bloco
                if re.search(r'\bVA\b', block):
                    alertas_encontrados.append(f"{prefix}: Cinzas Vulcânicas")
                # Checa teto baixo no bloco
                if re.search(r'\b(BKN|OVC)00[1-5]\b', block):
                     alertas_encontrados.append(f"{prefix}: Teto Baixo (< 600ft)")
                # Checa vento forte no bloco
                wind_match_block = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', block)
                if wind_match_block:
                    sustained_wind_block = int(wind_match_block.group(2))
                    gust_wind_str_block = wind_match_block.group(4)
                    if sustained_wind_block >= 20 or (gust_wind_str_block and int(gust_wind_str_block) >= 20):
                         alertas_encontrados.append(f"{prefix}: Vento Forte")

    # --- Lógica para Avisos de Aeródromo ---
    elif "AD WRNG" in tipo_mensagem.upper() or "AVISO DE AERÓDROMO" in tipo_mensagem.upper():
        if "TS" in mensagem_upper or "TROVOADA" in mensagem_upper: alertas_encontrados.append("Trovoada")
        wind_warning_match = re.search(r'SFC WSPD (\d+)KT(?: MAX (\d+)KT)?', mensagem_upper)
        if wind_warning_match:
            min_wind, max_wind_str = int(wind_warning_match.group(1)), wind_warning_match.group(2)
            wind_parts = []
            if min_wind > 0: wind_parts.append(f"Vento de Superfície de {min_wind}KT")
            if max_wind_str: wind_parts.append(f"Rajadas de {max_wind_str}KT")
            if wind_parts: alertas_encontrados.append(" e ".join(wind_parts))
        if "GRANIZO" in mensagem_upper: alertas_encontrados.append("Granizo")
        if "FG" in mensagem_upper or "NEVOEIRO" in mensagem_upper: alertas_encontrados.append("Nevoeiro")
        if "CHUVA FORTE" in mensagem_upper or re.search(r'\+RA\b', mensagem_upper): alertas_encontrados.append("Chuva Forte")
        if "WIND SHEAR" in mensagem_upper or re.search(r'\bWS\b', mensagem_upper): alertas_encontrados.append("Tesoura de Vento (Wind Shear)")
        if re.search(r'\bVA\b', mensagem_upper): alertas_encontrados.append("Cinzas Vulcânicas (VA)")
        if "FUMAÇA" in mensagem_upper or "FU" in mensagem_upper: alertas_encontrados.append("Fumaça")

        if not alertas_encontrados:
            alertas_encontrados.append("Aviso de Aeródromo Emitido (ver detalhes)")

    return list(set(alertas_encontrados))


def verificar_e_alertar():
    global alertas_enviados_cache
    load_persistent_cache()

    timestamp_inicio = datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"[{timestamp_inicio}] Iniciando verificação de condições meteorológicas...")
    if not REDEMET_API_KEY:
        print("Erro: REDEMET_API_KEY não configurada.")
        return
    agora_utc = datetime.now(pytz.utc)

    for aerodromo in AERODROMOS_INTERESSE:
        endpoints_e_tipos = {"aviso": "AVISO DE AERÓDROMO", "taf": "TAF", "metar": "METAR/SPECI"}
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
                    if isinstance(item_msg, dict):
                        if 'mens' in item_msg: mensagem_real = item_msg['mens']
                        elif 'mensagem' in item_msg: mensagem_real = item_msg['mensagem']
                        else:
                            print(f"Nenhuma chave de mensagem conhecida ('mens', 'mensagem') encontrada no item para {aerodromo} ({endpoint}). Item: {str(item_msg)[:150]}")
                            continue 
                    elif isinstance(item_msg, str): mensagem_real = item_msg
                    else:
                        print(f"Item de mensagem em formato totalmente inesperado para {aerodromo} ({endpoint}): {str(item_msg)[:100]}")
                        continue 
                    if not mensagem_real.strip():
                        print(f"Mensagem {tipo_base_mensagem} vazia ou inválida para {aerodromo}. Item: {str(item_msg)[:100]}")
                        continue
                    tipo_atual_mensagem = tipo_base_mensagem
                    if endpoint == "metar": tipo_atual_mensagem = "SPECI" if mensagem_real.upper().startswith("SPECI") else "METAR"
                    
                    msg_hash_str = calcular_hash_mensagem_str(mensagem_real)

                    if msg_hash_str not in alertas_enviados_cache:
                        condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_real, tipo_atual_mensagem)
                        if condicoes_perigosas:
                            emoji_alerta = "🚨" 
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
                            alertas_enviados_cache[msg_hash_str] = agora_utc
                            print(f"Alerta de {tipo_atual_mensagem} enviado para {aerodromo}: {', '.join(condicoes_perigosas)}")
                        else:
                            print(f"{tipo_atual_mensagem} para {aerodromo} sem condições perigosas detectadas: {mensagem_real[:70]}...")
                    else:
                        print(f"{tipo_atual_mensagem} para {aerodromo} já alertado recentemente (cache): {mensagem_real[:70]}...")
            else:
                print(f"Falha ao obter ou processar dados para {endpoint.upper()} de {aerodromo}.")
        print(f"--- Fim do processamento para Aeródromo: {aerodromo} ---")

    chaves_para_remover = [
        msg_hash for msg_hash, timestamp_envio in alertas_enviados_cache.items()
        if isinstance(timestamp_envio, datetime) and (agora_utc - timestamp_envio > timedelta(hours=24))
    ]
    for msg_hash in chaves_para_remover:
        del alertas_enviados_cache[msg_hash]
    if chaves_para_remover: print(f"Limpeza de cache concluída. {len(chaves_para_remover)} itens removidos.")
    else: print("Nenhum item expirado no cache para limpar.")
    
    save_persistent_cache()

# --- Execução Principal ---
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erro Crítico: Variáveis de ambiente TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configuradas.")
    elif not REDEMET_API_KEY:
        print("Erro Crítico: REDEMET_API_KEY não configurada.")
    else:
        print("Executando verificação de alertas REDEMET (configurado para execução única).")
        verificar_e_alertar()
        timestamp_fim = datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"[{timestamp_fim}] Verificação concluída.")

