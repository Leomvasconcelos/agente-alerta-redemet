import os
import requests
import json
import time
from datetime import datetime, timedelta, timezone
import pytz
import re
import hashlib

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

def calcular_hash_mensagem_str(mensagem):
    mensagem_bytes = mensagem.encode('utf-8')
    return hashlib.sha256(mensagem_bytes).hexdigest()

def load_alert_cache():
    global alertas_enviados_cache
    if os.path.exists(ALERT_CACHE_FILE):
        try:
            with open(ALERT_CACHE_FILE, 'r') as f:
                loaded_data = json.load(f)
                alertas_enviados_cache = {h: datetime.fromisoformat(ts).replace(tzinfo=timezone.utc) for h, ts in loaded_data.items()}
        except Exception as e:
            print(f"Erro ao carregar cache: {e}")

def save_alert_cache():
    serializable_cache = {h: dt.isoformat() for h, dt in alertas_enviados_cache.items()}
    try:
        with open(ALERT_CACHE_FILE, 'w') as f:
            json.dump(serializable_cache, f, indent=4)
    except Exception as e:
        print(f"Erro ao salvar cache: {e}")

def load_api_status():
    global api_status
    if os.path.exists(API_STATUS_FILE):
        try:
            with open(API_STATUS_FILE, 'r') as f:
                api_status = json.load(f)
        except Exception: pass

def save_api_status():
    try:
        with open(API_STATUS_FILE, 'w') as f:
            json.dump(api_status, f, indent=4)
    except Exception: pass

def enviar_mensagem_telegram(chat_id, texto):
    if not TELEGRAM_BOT_TOKEN or not chat_id: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Erro Telegram: {e}")

def obter_mensagens_redemet(endpoint, aerodromo):
    url = f"https://api-redemet.decea.mil.br/mensagens/{endpoint}/{aerodromo}"
    headers = {"x-api-key": REDEMET_API_KEY}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data_json = response.json()
        if data_json and 'data' in data_json:
            data_principal = data_json['data']
            return True, data_principal.get('data', []) if isinstance(data_principal, dict) else data_principal
        return True, []
    except Exception as e:
        return False, []

def analisar_condicoes_significativas(texto_analise):
    condicoes = set()
    for codigo, descricao in SIGNIFICANT_PHENOMENA.items():
        if re.search(r'\b\+?' + re.escape(codigo), texto_analise):
            condicoes.add(descricao)
    if re.search(r'\bVA\b', texto_analise): condicoes.add("Cinzas Vulcânicas")
    if re.search(r'\b(BKN|OVC)00[0-5]', texto_analise): condicoes.add("Teto Baixo (< 600ft)")
    
    wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', texto_analise)
    if wind_match:
        sustained = int(wind_match.group(2))
        gust = wind_match.group(4)
        if sustained >= 20 or (gust and int(gust) >= 20):
            condicoes.add("Vento Forte (>= 20kt)")
            
    cb_matches = re.findall(r'(FEW|SCT|BKN|OVC)(\d{3})(CB)', texto_analise)
    for match in cb_matches:
        condicoes.add(f"Presença de CB a {int(match[1]) * 100}ft")
    return sorted(list(condicoes))

def analisar_aviso_aerodromo(mensagem_upper):
    """Lógica específica para formatar as condições do Aviso de Aeródromo."""
    componentes = []
    
    if "TS" in mensagem_upper or "TROVOADA" in mensagem_upper:
        componentes.append("Trovoada")
        
    wind_match = re.search(r'SFC WSPD (\d+)KT(?: MAX (\d+))?', mensagem_upper)
    if wind_match:
        sustained = wind_match.group(1)
        max_wind = wind_match.group(2)
        frase_vento = f"velocidade de vento à superfície de {sustained}KT"
        if max_wind:
            frase_vento += f" com máxima de {max_wind}KT"
        componentes.append(frase_vento)
        
    if re.search(r'\bVA\b', mensagem_upper):
        componentes.append("Cinzas Vulcânicas (VA)")
        
    if not componentes:
        return "Aviso de Aeródromo Emitido (verificar detalhes)"
    
    return " e ".join(componentes)

def verificar_e_alertar():
    global alertas_enviados_cache, api_status
    load_alert_cache()
    load_api_status()
    agora_utc = datetime.now(pytz.utc)
    
    for aerodromo in AERODROMOS_INTERESSE:
        for endpoint in ["aviso", "taf", "metar"]:
            sucesso, data = obter_mensagens_redemet(endpoint, aerodromo)
            if not sucesso: continue
            
            for item_msg in data:
                msg_real = (item_msg.get('mens') or item_msg.get('mensagem')) if isinstance(item_msg, dict) else item_msg
                if not msg_real: continue
                
                tipo_msg = "AVISO DE AERÓDROMO" if endpoint == 'aviso' else ("SPECI" if "SPECI" in msg_real.upper() else endpoint.upper())
                msg_hash = calcular_hash_mensagem_str(msg_real)

                if msg_hash not in alertas_enviados_cache:
                    msg_upper = msg_real.upper()
                    
                    if tipo_msg == "AVISO DE AERÓDROMO":
                        condicoes = analisar_aviso_aerodromo(msg_upper)
                        
                        # Extração da validade: VALID DDHHHH/DDHHHH
                        valid_match = re.search(r'VALID \d{2}(\d{4})/\d{2}(\d{4})', msg_upper)
                        validade_str = ""
                        if valid_match:
                            validade_str = f"Das: {valid_match.group(1)}Z às {valid_match.group(2)}Z\n"

                        alert_text = (
                            f"🚨 *NOVO ALERTA MET {aerodromo}!* 🚨\n\n"
                            f"Aeródromo: *{aerodromo}* – Tipo: *{tipo_msg}*\n\n"
                            f"Condições Previstas/Alertadas:\n"
                            f"*{condicoes}.*\n\n"
                            f"{validade_str}\n"
                            f"Mensagem Original:\n`{msg_real}`\n\n"
                            f"(Hora do Agente: {agora_utc.strftime('%Y-%m-%d %H:%M:%S UTC')})"
                        )
                    else:
                        # Lógica padrão para METAR/TAF
                        condicoes_list = analisar_condicoes_significativas(msg_upper)
                        if not condicoes_list: continue
                        
                        emoji = "⚠️" if tipo_msg == "TAF" else "⚡️"
                        alert_text = (
                            f"{emoji} *NOVO ALERTA MET {aerodromo}!* {emoji}\n\n"
                            f"Aeródromo: *{aerodromo}* - Tipo: *{tipo_msg}*\n"
                            f"Condições: *{', '.join(condicoes_list)}*\n\n"
                            f"Mensagem Original:\n`{msg_real}`\n\n"
                            f"(Hora do Agente: {agora_utc.strftime('%Y-%m-%d %H:%M:%S UTC')})"
                        )

                    enviar_mensagem_telegram(TELEGRAM_CHAT_ID, alert_text)
                    alertas_enviados_cache[msg_hash] = agora_utc
    
    # Limpeza de cache (24h) e salvamento
    alertas_enviados_cache = {h: ts for h, ts in alertas_enviados_cache.items() if agora_utc - ts < timedelta(hours=24)}
    save_alert_cache()

if __name__ == "__main__":
    if all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, REDEMET_API_KEY]):
        verificar_e_alertar()
