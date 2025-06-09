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
AERODROMOS_INTERESSE = ["SBTA"]

# Fenômenos significativos para METAR/TAF/SPECI
SIGNIFICANT_PHENOMENA = {
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
                    except ValueError: pass
                print(f"Cache persistente carregado de {CACHE_FILE_PATH}. Itens: {len(alertas_enviados_cache)}")
        else:
            print(f"Arquivo de cache persistente não encontrado. Iniciando com cache vazio.")
    except Exception as e:
        print(f"Erro crítico ao carregar cache persistente: {e}. Iniciando com cache vazio.")

def save_persistent_cache():
    global alertas_enviados_cache
    serializable_cache = {}
    for msg_hash_str, dt_obj in alertas_enviados_cache.items():
        if isinstance(dt_obj, datetime):
            serializable_cache[msg_hash_str] = dt_obj.astimezone(timezone.utc).isoformat()
    try:
        with open(CACHE_FILE_PATH, 'w') as f:
            json.dump(serializable_cache, f, indent=4)
        print(f"Cache persistente salvo em {CACHE_FILE_PATH}. Itens: {len(serializable_cache)}")
    except Exception as e:
        print(f"Erro crítico ao salvar cache persistente: {e}")

# --- Funções de Comunicação e Coleta ---
def enviar_mensagem_telegram(chat_id, texto):
    if not TELEGRAM_BOT_TOKEN or not chat_id: return
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
                return {"data": data_principal.get('data', [])}
            elif isinstance(data_principal, list):
                return {"data": data_principal}
    except requests.exceptions.RequestException as e:
        print(f"Erro na requisição para {endpoint} de {aerodromo}: {e}")
    return {"data": []}

# --- NÚCLEO DE ANÁLISE ---
def analisar_condicoes_significativas(texto_analise):
    """Analisa um texto e retorna um set de condições significativas encontradas."""
    condicoes = set()
    
    for codigo, descricao in SIGNIFICANT_PHENOMENA.items():
        if re.search(r'\b\+?' + re.escape(codigo), texto_analise):
            condicoes.add(descricao)
            
    if re.search(r'\bVA\b', texto_analise):
        condicoes.add("Cinzas Vulcânicas")

    if re.search(r'\b(BKN|OVC)00[0-5]', texto_analise):
         condicoes.add("Teto Baixo (< 600ft)")

    wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', texto_analise)
    if wind_match:
        sustained_wind = int(wind_match.group(2))
        gust_wind_str = wind_match.group(4)
        if sustained_wind >= 20 or (gust_wind_str and int(gust_wind_str) >= 20):
            condicoes.add("Vento Forte (>= 20kt)")
    
    cb_matches = re.findall(r'(FEW|SCT|BKN|OVC)(\d{3})(CB)', texto_analise)
    for match in cb_matches:
        altitude_ft = int(match[1]) * 100
        condicoes.add(f"Presença de CB a {altitude_ft}ft")
        
    return condicoes

def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """Analisa a mensagem com base nas regras de alerta definidas."""
    alertas_encontrados = set()
    mensagem_upper = mensagem_texto.upper()

    if "AD WRNG" in tipo_mensagem.upper() or "AVISO DE AERÓDROMO" in tipo_mensagem.upper():
        if "TS" in mensagem_upper or "TROVOADA" in mensagem_upper: alertas_encontrados.add("Trovoada")
        wind_warning_match = re.search(r'SFC WSPD (\d+)KT(?: MAX (\d+)(?:KT)?)?', mensagem_upper)
        if wind_warning_match:
            sustained_wind, max_wind_str = wind_warning_match.group(1), wind_warning_match.group(2)
            wind_text = f"Vento de Superfície de {sustained_wind}KT"
            if max_wind_str: wind_text += f" com máximo de {max_wind_str}KT"
            alertas_encontrados.add(wind_text)
        if "GRANIZO" in mensagem_upper: alertas_encontrados.add("Granizo")
        if "FG" in mensagem_upper or "NEVOEIRO" in mensagem_upper: alertas_encontrados.add("Nevoeiro")
        if "CHUVA FORTE" in mensagem_upper or re.search(r'\+RA\b', mensagem_upper): alertas_encontrados.add("Chuva Forte")
        if "WIND SHEAR" in mensagem_upper or re.search(r'\bWS\b', mensagem_upper): alertas_encontrados.add("Tesoura de Vento (Wind Shear)")
        
        # --- CORREÇÃO APLICADA AQUI ---
        # Usa regex com fronteira de palavra (\b) para evitar falso positivo em "VALID"
        if re.search(r'\bVA\b', mensagem_upper): 
            alertas_encontrados.add("Cinzas Vulcânicas (VA)")
            
        if "FUMAÇA" in mensagem_upper or "FU" in mensagem_upper: alertas_encontrados.add("Fumaça")
        if not alertas_encontrados: alertas_encontrados.add("Aviso de Aeródromo Emitido (ver detalhes)")
    
    else: # Lógica Unificada para METAR, SPECI e TAF
        alertas_encontrados.update(analisar_condicoes_significativas(mensagem_upper))

    return sorted(list(alertas_encontrados))

# --- Lógica Principal de Execução ---
def verificar_e_alertar():
    global alertas_enviados_cache
    load_persistent_cache()
    timestamp_inicio = datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"[{timestamp_inicio}] Iniciando verificação...")
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
                for item_msg in mensagens_api_data['data']:
                    mensagem_real = ""
                    if isinstance(item_msg, dict):
                        mensagem_real = item_msg.get('mens') or item_msg.get('mensagem')
                    elif isinstance(item_msg, str):
                        mensagem_real = item_msg
                    if not mensagem_real:
                        print(f"Não foi possível extrair texto da mensagem: {str(item_msg)[:150]}")
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
                            print(f"{tipo_atual_mensagem} para {aerodromo} sem condições perigosas detectadas.")
                    else:
                        print(f"{tipo_atual_mensagem} para {aerodromo} já alertado recentemente (cache).")
            else:
                print(f"Nenhuma mensagem em '{endpoint}' para {tipo_base_mensagem} de {aerodromo} ou falha na API.")
        print(f"--- Fim do processamento para Aeródromo: {aerodromo} ---")

    chaves_para_remover = [h for h, ts in alertas_enviados_cache.items() if isinstance(ts, datetime) and (agora_utc - ts > timedelta(hours=24))]
    for h in chaves_para_remover: del alertas_enviados_cache[h]
    if chaves_para_remover: print(f"Limpeza de cache concluída. {len(chaves_para_remover)} itens removidos.")
    else: print("Nenhum item expirado no cache para limpar.")
    save_persistent_cache()

if __name__ == "__main__":
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, REDEMET_API_KEY]):
        print("Erro Crítico: Uma ou mais variáveis de ambiente não estão configuradas.")
    else:
        print("Executando verificação de alertas REDEMET...")
        verificar_e_alertar()
        timestamp_fim = datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"[{timestamp_fim}] Verificação concluída.")
