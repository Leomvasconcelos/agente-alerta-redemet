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
AERODROMOS_INTERESSE = ["SBGR"]

# Fenômenos significativos para METAR/TAF/SPECI, conforme solicitado
SIGNIFICANT_PHENOMENA_METAR_TAF = {
    "TS": "Trovoada",
    "FG": "Nevoeiro",
    "GR": "Granizo",
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
                    return {"data": lista_mensagens_aninhada}
                else: return {"data": []}
            elif isinstance(data_principal, list):
                return {"data": data_principal}
            else: return {"data": []}
        else: return {"data": []}
    except requests.exceptions.RequestException:
        return {"data": []}

def analisar_condicoes_significativas(texto_analise):
    """Função auxiliar para analisar um trecho de texto e retornar uma lista de condições significativas únicas."""
    condicoes_encontradas = set() # Usar um set para evitar duplicatas desde o início
    
    # 1. Fenômenos (TS, FG, GR)
    for codigo, descricao in SIGNIFICANT_PHENOMENA_METAR_TAF.items():
        if re.search(r'\b' + re.escape(codigo) + r'\b', texto_analise):
            condicoes_encontradas.add(descricao)
            
    # 2. Cinzas Vulcânicas (VA)
    if re.search(r'\bVA\b', texto_analise):
        condicoes_encontradas.add("Cinzas Vulcânicas")

    # 3. Teto Baixo (< 600ft)
    match_teto = re.search(r'\b(BKN|OVC)00[0-5]', texto_analise)
    if match_teto:
         teto_tipo = "Parcialmente Nublado" if match_teto.group(1) == "BKN" else "Nublado"
         condicoes_encontradas.add(f"Teto Baixo ({teto_tipo} < 600ft)")

    # 4. Vento Forte (>= 20kt)
    wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', texto_analise)
    if wind_match:
        sustained_wind = int(wind_match.group(2))
        gust_wind_str = wind_match.group(4)
        wind_desc_parts = []
        if sustained_wind >= 20: wind_desc_parts.append(f"Vento Médio de {sustained_wind}KT")
        if gust_wind_str and int(gust_wind_str) >= 20: wind_desc_parts.append(f"Rajadas de {int(gust_wind_str)}KT")
        if wind_desc_parts: condicoes_encontradas.add(" e ".join(wind_desc_parts))
        
    return list(condicoes_encontradas)

def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """Analisa a mensagem com base nas novas regras de alerta."""
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    # --- Lógica para Avisos de Aeródromo ---
    if "AD WRNG" in tipo_mensagem.upper() or "AVISO DE AERÓDROMO" in tipo_mensagem.upper():
        if "TS" in mensagem_upper or "TROVOADA" in mensagem_upper: alertas_encontrados.append("Trovoada")
        wind_warning_match = re.search(r'SFC WSPD (\d+)KT(?: MAX (\d+)(?:KT)?)?', mensagem_upper)
        if wind_warning_match:
            sustained_wind, max_wind_str = wind_warning_match.group(1), wind_warning_match.group(2)
            wind_text = f"Vento de Superfície de {sustained_wind}KT"
            if max_wind_str: wind_text += f" com máximo de {max_wind_str}KT"
            alertas_encontrados.append(wind_text)
        if "GRANIZO" in mensagem_upper: alertas_encontrados.append("Granizo")
        if "FG" in mensagem_upper or "NEVOEIRO" in mensagem_upper: alertas_encontrados.append("Nevoeiro")
        if "CHUVA FORTE" in mensagem_upper or re.search(r'\+RA\b', mensagem_upper): alertas_encontrados.append("Chuva Forte")
        if "WIND SHEAR" in mensagem_upper or re.search(r'\bWS\b', mensagem_upper): alertas_encontrados.append("Tesoura de Vento (Wind Shear)")
        if re.search(r'\bVA\b', mensagem_upper): alertas_encontrados.append("Cinzas Vulcânicas (VA)")
        if "FUMAÇA" in mensagem_upper or "FU" in mensagem_upper: alertas_encontrados.append("Fumaça")
        if not alertas_encontrados: alertas_encontrados.append("Aviso de Aeródromo Emitido (ver detalhes)")
    
    # --- Lógica Unificada e Simplificada para METAR, SPECI e TAF ---
    else:
        alertas_encontrados = analisar_condicoes_significativas(mensagem_upper)

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
                            print(f"Nenhuma chave de mensagem conhecida ('mens', 'mensagem') encontrada no item. Item: {str(item_msg)[:150]}")
                            continue 
                    elif isinstance(item_msg, str): mensagem_real = item_msg
                    else:
                        print(f"Item de mensagem em formato totalmente inesperado. Item: {str(item_msg)[:100]}")
                        continue 
                    if not mensagem_real.strip():
                        print(f"Mensagem {tipo_base_mensagem} vazia ou inválida. Item: {str(item_msg)[:100]}")
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
                                f"{titulo_condicao}: *{', '.join(sorted(condicoes_perigosas))}*\n" # Adicionado sorted() para consistência
                                f"Mensagem Original:\n`{mensagem_real}`\n\n"
                                f"(Hora do Agente: {agora_utc.strftime('%Y-%m-%d %H:%M:%S UTC')})"
                            )
                            enviar_mensagem_telegram(TELEGRAM_CHAT_ID, alert_text)
                            alertas_enviados_cache[msg_hash_str] = agora_utc
                            print(f"Alerta de {tipo_atual_mensagem} enviado para {aerodromo}: {', '.join(sorted(condicoes_perigosas))}")
                        else:
                            print(f"{tipo_atual_mensagem} para {aerodromo} sem condições perigosas detectadas: {mensagem_real[:70]}...")
                    else:
                        print(f"{tipo_atual_mensagem} para {aerodromo} já alertado recentemente (cache): {mensagem_real[:70]}...")
            else:
                print(f"Falha ao obter ou processar dados para {endpoint.upper()} de {aerodromo}.")
        print(f"--- Fim do processamento para Aeródromo: {aerodromo} ---")

    # Limpeza do cache
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

