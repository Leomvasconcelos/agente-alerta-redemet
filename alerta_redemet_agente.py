import os
import requests
import json
from datetime import datetime, timedelta, timezone
import pytz
import re
import hashlib

# =========================
# CONFIGURAÇÕES
# =========================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
REDEMET_API_KEY = os.getenv('REDEMET_API_KEY')

AERODROMOS_INTERESSE = ["SBTA"]

SIGNIFICANT_PHENOMENA = {
    "TS": "Trovoada",
    "FG": "Nevoeiro",
    "GR": "Granizo"
}

ALERT_CACHE_FILE = "persistent_alert_cache.json"
API_STATUS_FILE = "api_status.json"

alertas_enviados_cache = {}
api_status = {"consecutive_failures": 0, "failure_notified": False}

# =========================
# FUNÇÕES AUXILIARES
# =========================
def calcular_hash_mensagem_str(mensagem):
    return hashlib.sha256(mensagem.encode("utf-8")).hexdigest()

def formatar_mensagem_original_bloco(texto):
    linhas = texto.splitlines()
    return "\n".join([f"> {linha}" for linha in linhas])

def load_alert_cache():
    global alertas_enviados_cache
    if os.path.exists(ALERT_CACHE_FILE):
        with open(ALERT_CACHE_FILE, "r") as f:
            data = json.load(f)
            alertas_enviados_cache = {
                h: datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
                for h, ts in data.items()
            }

def save_alert_cache():
    with open(ALERT_CACHE_FILE, "w") as f:
        json.dump(
            {h: ts.isoformat() for h, ts in alertas_enviados_cache.items()},
            f,
            indent=4
        )

def load_api_status():
    global api_status
    if os.path.exists(API_STATUS_FILE):
        with open(API_STATUS_FILE, "r") as f:
            api_status = json.load(f)

def save_api_status():
    with open(API_STATUS_FILE, "w") as f:
        json.dump(api_status, f, indent=4)

def enviar_mensagem_telegram(chat_id, texto):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload, timeout=10)

def obter_mensagens_redemet(endpoint, aerodromo):
    url = f"https://api-redemet.decea.mil.br/mensagens/{endpoint}/{aerodromo}"
    headers = {"x-api-key": REDEMET_API_KEY}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", {})
        if isinstance(data, dict):
            return True, data.get("data", [])
        return True, data
    except requests.RequestException:
        return False, []

# =========================
# ANÁLISES METEOROLÓGICAS
# =========================
def analisar_condicoes_significativas(texto):
    condicoes = set()

    for codigo, desc in SIGNIFICANT_PHENOMENA.items():
        if re.search(rf"\b{codigo}\b", texto):
            condicoes.add(desc)

    if re.search(r"\bVA\b", texto):
        condicoes.add("Cinzas Vulcânicas")

    if re.search(r"(BKN|OVC)00[0-5]", texto):
        condicoes.add("Teto Baixo (< 600 ft)")

    vento = re.search(r"(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT", texto)
    if vento:
        sustentado = int(vento.group(2))
        rajada = vento.group(4)
        if sustentado >= 20 or (rajada and int(rajada) >= 20):
            condicoes.add("Vento Forte (≥ 20kt)")

    cb = re.findall(r"(FEW|SCT|BKN|OVC)(\d{3})CB", texto)
    for camada, altura in cb:
        condicoes.add(f"CB a {int(altura) * 100} ft")

    return condicoes

def analisar_mensagem_meteorologica(texto, tipo):
    texto = texto.upper()
    alertas = set()

    if tipo == "AVISO DE AERÓDROMO":
        if "TS" in texto:
            alertas.add("Trovoada")
        if "FG" in texto:
            alertas.add("Nevoeiro")
    else:
        alertas.update(analisar_condicoes_significativas(texto))

    return sorted(alertas)

# =========================
# FORMATAÇÃO AVISO AERÓDROMO
# =========================
def formatar_alerta_aviso_aerodromo(aerodromo, mensagem_real):
    texto = mensagem_real.upper()

    fenomenos = []
    if "TS" in texto:
        fenomenos.append("Trovoada")
    if "FG" in texto:
        fenomenos.append("Nevoeiro")

    vento_desc = ""
    vento = re.search(r"SFC WSPD (\d+)KT(?: MAX (\d+))?", texto)
    if vento:
        base = vento.group(1)
        raj = vento.group(2)
        vento_desc = f"velocidade de vento à superfície de {base}KT"
        if raj:
            vento_desc += f" com máxima de {raj}KT"

    condicoes = " e ".join(fenomenos + ([vento_desc] if vento_desc else []))

    periodo = "Não informado"
    valid = re.search(r"VALID \d{2}(\d{2})(\d{2})/\d{2}(\d{2})(\d{2})", texto)
    if valid:
        inicio = f"{valid.group(1)}{valid.group(2)}Z"
        fim = f"{valid.group(3)}{valid.group(4)}Z"
        periodo = f"{inicio} às {fim}"

    mensagem_original_formatada = formatar_mensagem_original_bloco(mensagem_real)

    return (
        f"🚨 *NOVO ALERTA MET {aerodromo}!* 🚨\n\n"
        f"Aeródromo: *{aerodromo}* - Tipo: *AVISO DE AERÓDROMO*\n\n"
        f"*Condições Previstas/Alertadas:*\n\n"
        f"{condicoes.capitalize()}.\n\n"
        f"*Das:* {periodo}\n\n"
        f"*Mensagem Original:*\n"
        f"{mensagem_original_formatada}"
    )

# =========================
# LOOP PRINCIPAL
# =========================
def verificar_e_alertar():
    load_alert_cache()
    load_api_status()

    agora = datetime.now(pytz.utc)
    total, falhas = 0, 0

    for aerodromo in AERODROMOS_INTERESSE:
        for endpoint in ["aviso", "taf", "metar"]:
            total += 1
            ok, mensagens = obter_mensagens_redemet(endpoint, aerodromo)
            if not ok:
                falhas += 1
                continue

            for item in mensagens:
                texto = item.get("mens") if isinstance(item, dict) else item
                if not texto:
                    continue

                tipo = "AVISO DE AERÓDROMO" if endpoint == "aviso" else endpoint.upper()
                msg_hash = calcular_hash_mensagem_str(texto)

                if msg_hash in alertas_enviados_cache:
                    continue

                condicoes = analisar_mensagem_meteorologica(texto, tipo)
                if not condicoes:
                    continue

                if tipo == "AVISO DE AERÓDROMO":
                    alerta = formatar_alerta_aviso_aerodromo(aerodromo, texto)
                else:
                    emoji = "⚡️" if tipo in ["METAR", "SPECI"] else "⚠️"
                    mensagem_original = formatar_mensagem_original_bloco(texto)
                    alerta = (
                        f"{emoji} *NOVO ALERTA MET {aerodromo}!* {emoji}\n\n"
                        f"Aeródromo: *{aerodromo}* - Tipo: *{tipo}*\n"
                        f"Condições: *{', '.join(condicoes)}*\n\n"
                        f"*Mensagem Original:*\n"
                        f"{mensagem_original}"
                    )

                enviar_mensagem_telegram(TELEGRAM_CHAT_ID, alerta)
                alertas_enviados_cache[msg_hash] = agora

    if total > 0 and falhas == total:
        api_status["consecutive_failures"] += 1
        if api_status["consecutive_failures"] >= 3 and not api_status["failure_notified"]:
            enviar_mensagem_telegram(
                TELEGRAM_CHAT_ID,
                "🚨 *ALERTA DE SISTEMA*\nAPI DA REDEMET INDISPONÍVEL"
            )
            api_status["failure_notified"] = True
    else:
        if api_status["failure_notified"]:
            enviar_mensagem_telegram(
                TELEGRAM_CHAT_ID,
                "✅ *ALERTA DE SISTEMA*\nAPI DA REDEMET NORMALIZADA"
            )
        api_status["consecutive_failures"] = 0
        api_status["failure_notified"] = False

    alertas_enviados_cache.update({
        h: ts for h, ts in alertas_enviados_cache.items()
        if agora - ts <= timedelta(hours=24)
    })

    save_alert_cache()
    save_api_status()

# =========================
# EXECUÇÃO
# =========================
if __name__ == "__main__":
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, REDEMET_API_KEY]):
        print("Variáveis de ambiente não configuradas.")
    else:
        verificar_e_alertar()