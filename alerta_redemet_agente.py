import os
import requests
import json
import time
from datetime import datetime, timedelta, timezone
import pytz
import re
import hashlib  # Importa a biblioteca de hash estável

# --- Configurações ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
REDEMET_API_KEY = os.getenv('REDEMET_API_KEY')
AERODROMOS_INTERESSE = ["SBTA"]
SIGNIFICANT_PHENOMENA = {"TS": "Trovoada", "FG": "Nevoeiro", "GR": "Granizo"}

# --- Lógica de Cache e Status ---
ALERT_CACHE_FILE = "persistent_alert_cache.json"
API_STATUS_FILE = "api_status.json"
alertas_enviados_cache = {}
api_status = {"consecutive_failures": 0, "failure_notified": False}

# --- FUNÇÃO DE HASH ATUALIZADA ---
def calcular_hash_mensagem_str(mensagem):
    """Calcula um hash SHA-256 estável para uma mensagem string."""
    mensagem_bytes = mensagem.encode('utf-8')
    sha256_hash = hashlib.sha256(mensagem_bytes)
    return sha256_hash.hexdigest()

def load_alert_cache():
    global alertas_enviados_cache
    alertas_enviados_cache = {}
    if os.path.exists(ALERT_CACHE_FILE):
        try:
            with open(ALERT_CACHE_FILE, 'r') as f:
                loaded_data = json.load(f)
                for h, ts in loaded_data.items():
                    alertas_enviados_cache[h] = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
            print(f"Cache de alertas carregado. Itens: {len(alertas_enviados_cache)}")
        except Exception as e:
            print(f"Erro ao carregar cache de alertas: {e}")

def save_alert_cache():
    serializable_cache = {h: dt.isoformat() for h, dt in alertas_enviados_cache.items()}
    try:
        with open(ALERT_CACHE_FILE, 'w') as f:
            json.dump(serializable_cache, f, indent=4)
        print(f"Cache de alertas salvo. Itens: {len(serializable_cache)}")
    except Exception as e:
        print(f"Erro ao salvar cache de alertas: {e}")

def load_api_status():
    global api_status
    if os.path.exists(API_STATUS_FILE):
        try:
            with open(API_STATUS_FILE, 'r') as f:
                api_status = json.load(f)
            print(f"Status da API carregado: {api_status}")
        except Exception as e:
            print(f"Erro ao carregar status da API: {e}")

def save_api_status():
    try:
        with open(API_STATUS_FILE, 'w') as f:
            json.dump(api_status, f, indent=4)
        print(f"Status da API salvo: {api_status}")
    except Exception as e:
        print(f"Erro ao salvar status da API: {e}")

def enviar_mensagem_telegram(chat_id, texto):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("Mensagem enviada com sucesso.")
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
                return True, data_principal.get('data', [])
            elif isinstance(data_principal, list):
                return True, data_principal
        return True, []
    except requests.exceptions.RequestException as e:
        print(f"FALHA na requisição para {endpoint} de {aerodromo}: {e}")
        return False, []

def analisar_condicoes_significativas(texto_analise):
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
        condicoes.add(f"Presença de CB a {int(match[1]) * 100}ft")
    return condicoes

def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    alertas_encontrados = set()
    mensagem_upper = mensagem_texto.upper()
    if "AD WRNG" in tipo_mensagem.upper() or "AVISO DE AERÓDROMO" in tipo_mensagem.upper():
        if "TS" in mensagem_upper or "TROVOADA" in mensagem_upper:
            alertas_encontrados.add("Trovoada")
        wind_warning_match = re.search(r'SFC WSPD (\d+)KT(?: MAX (\d+)(?:KT)?)?', mensagem_upper)
        if wind_warning_match:
            sustained_wind = wind_warning_match.group(1)
            max_wind_str = wind_warning_match.group(2)
            wind_text = f"Vento de Superfície de {sustained_wind}KT"
            if max_wind_str:
                wind_text += f" com máximo de {max_wind_str}KT"
            alertas_encontrados.add(wind_text)
        if re.search(r'\bVA\b', mensagem_upper):
            alertas_encontrados.add("Cinzas Vulcânicas (VA)")
        if not alertas_encontrados:
            alertas_encontrados.add("Aviso de Aeródromo Emitido (ver detalhes)")
    else:
        alertas_encontrados.update(analisar_condicoes_significativas(mensagem_upper))
    return sorted(list(alertas_encontrados))

def verificar_e_alertar():
    global alertas_enviados_cache, api_status
    load_alert_cache()
    load_api_status()
    agora_utc = datetime.now(pytz.utc)
    print(f"[{agora_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}] Iniciando verificação...")
    total_requests, failed_requests = 0, 0

    for aerodromo in AERODROMOS_INTERESSE:
        print(f"--- Processando Aeródromo: {aerodromo} ---")
        for endpoint in ["aviso", "taf", "metar"]:
            total_requests += 1
            sucesso, data = obter_mensagens_redemet(endpoint, aerodromo)
            if not sucesso:
                failed_requests += 1
                continue
            for item_msg in data:
                mensagem_real = item_msg.get('mens') or item_msg.get('mensagem') if isinstance(item_msg, dict) else item_msg
                if not mensagem_real:
                    continue
                tipo_msg = "AVISO DE AERÓDROMO" if endpoint == 'aviso' else ("SPECI" if "SPECI" in mensagem_real.upper() else endpoint.upper())
                msg_hash_str = calcular_hash_mensagem_str(mensagem_real)

                if msg_hash_str not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_real, tipo_msg)
                    if condicoes_perigosas:
                        emoji_alerta = "🚨"
                        if tipo_msg == "TAF":
                            emoji_alerta = "⚠️"
                        elif tipo_msg in ["METAR", "SPECI"]:
                            emoji_alerta = "⚡️"
                        titulo_condicao = "Condições Reportadas" if tipo_msg in ["METAR", "SPECI"] else "Condições Previstas/Alertadas"
                        alert_text = (
                            f"{emoji_alerta} *NOVO ALERTA MET {aerodromo}!* {emoji_alerta}\n\n"
                            f"Aeródromo: *{aerodromo}* - Tipo: *{tipo_msg}*\n"
                            f"{titulo_condicao}: *{', '.join(condicoes_perigosas)}*\n"
                            f"Mensagem Original:\n`{mensagem_real}`\n\n"
                            f"(Hora do Agente: {agora_utc.strftime('%Y-%m-%d %H:%M:%S UTC')})"
                        )
                        enviar_mensagem_telegram(TELEGRAM_CHAT_ID, alert_text)
                        alertas_enviados_cache[msg_hash_str] = agora_utc
                        print(f"ALERTA ENVIADO para {tipo_msg} em {aerodromo}.")
                    else:
                        print("Nenhuma condição perigosa detectada nesta nova mensagem.")
                else:
                    print(f"Mensagem para {tipo_msg} já se encontra no cache. Ignorando.")

    if total_requests > 0 and failed_requests == total_requests:
        api_status["consecutive_failures"] += 1
        if api_status["consecutive_failures"] >= 3 and not api_status.get("failure_notified", False):
            enviar_mensagem_telegram(
                TELEGRAM_CHAT_ID,
                "🚨 *ALERTA DE SISTEMA* 🚨\n\nAPI DA REDEMET INDISPONÍVEL NO MOMENTO"
            )
            api_status["failure_notified"] = True
    else:
        if api_status.get("failure_notified", False):
            enviar_mensagem_telegram(
                TELEGRAM_CHAT_ID,
                "✅ *ALERTA DE SISTEMA* ✅\n\nBOAS NOTÍCIAS! O API DA REDEMET VOLTOU A NORMALIDADE"
            )
        api_status["consecutive_failures"] = 0
        api_status["failure_notified"] = False

    chaves_para_remover = [
        h for h, ts in alertas_enviados_cache.items()
        if isinstance(ts, datetime) and (agora_utc - ts > timedelta(hours=24))
    ]
    for h in chaves_para_remover:
        del alertas_enviados_cache[h]

    save_alert_cache()
    save_api_status()

if __name__ == "__main__":
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, REDEMET_API_KEY]):
        print("Erro Crítico: Uma ou mais variáveis de ambiente não estão configuradas.")
    else:
        verificar_e_alertar()
        print(f"[{datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Verificação concluída.")