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
REDEMET_API_KEY = os.getenv('REDEMET_API_KEY') # Nova variável de ambiente para a chave API

# Aeródromos de interesse (SBTA para testes iniciais)
AERODROMOS_INTERESSE = ["SBTA"]

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
    # "VA" removido do map para detecção mais precisa via regex em 'analisar_mensagem_meteorologica'
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
    return hash(mensagem)

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
        print(f"Mensagem enviada com sucesso para o Telegram.") # Removido o texto para não logar chaves/dados sensíveis
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
        response = requests.get(url, headers=headers)
        response.raise_for_status() # Lança exceção para erros HTTP
        data = response.json()
        
        # A estrutura da resposta da REDEMET é {'data': [...]}
        # E dentro de 'data', cada item pode ser {'mensagem': 'texto_da_mensagem'}
        # A API pode retornar mais de uma mensagem, especialmente para METAR/SPECI
        # e para histórico de TAFs ou Avisos.
        # Queremos apenas a(s) mensagem(ns) mais recente(s).

        mensagens_filtradas = []
        if data and 'data' in data and data['data']:
            # Para METAR/SPECI, geralmente queremos a mais recente.
            # Para TAF/Aviso, pode haver mais de um válido.
            
            # A API da REDEMET retorna a lista de mensagens ordenadas da mais antiga para a mais recente.
            # Se a resposta 'data' for uma lista, pegamos a última mensagem para METAR/TAF/Aviso
            # Se for uma lista de dicionários, pegamos o 'mensagem' de cada um.

            # A documentação mostra que as mensagens estão dentro de um dicionário com a chave 'mens'
            # Exemplo: {'data': [{'mens': 'METAR SBGL...'}, {'mens': 'METAR SBGL...'}]}

            if endpoint_tipo == "metar":
                # Para METAR/SPECI, pegamos apenas a mais recente (última da lista)
                if isinstance(data['data'], list) and data['data']:
                    # Verifica se o último elemento da lista tem a chave 'mens'
                    if 'mens' in data['data'][-1]:
                        mensagens_filtradas.append({"mensagem": data['data'][-1]['mens']})
            elif endpoint_tipo == "taf":
                # Para TAF, pegamos a(s) última(s) mensagem(ns) válida(s)
                # A lógica aqui pode ser mais complexa dependendo de como TAFs são "válidos"
                # Por simplicidade, vamos pegar a última mensagem completa que não seja um TAF de cancelamento
                if isinstance(data['data'], list) and data['data']:
                    for msg_data in reversed(data['data']): # Começa do mais recente
                        if 'mens' in msg_data and "CNL" not in msg_data['mens'].upper():
                            mensagens_filtradas.append({"mensagem": msg_data['mens']})
                            break # Pega apenas o TAF mais recente válido
            elif endpoint_tipo == "aviso":
                # Para Aviso, a API pode retornar vários avisos válidos simultaneamente.
                # Vamos pegar todos os avisos presentes no último retorno.
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
        print(f"Erro ao decodificar JSON para {endpoint_tipo} de {aerodromo}. Resposta: {response.text}")
    
    return {"data": []} # Retorna lista vazia em caso de erro ou sem dados

def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """
    Função para o robô 'ler' a mensagem e procurar por códigos severos e contexto.
    Retorna uma lista dos alertas de texto encontrados, com base nos seus critérios.
    """
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    # --- Análise de Fenômenos Específicos (METAR/TAF/Aviso) ---

    # Regex para capturar fenômenos com e sem prefixos (ex: SHRA, FZRA)
    # Garante que o código é uma "palavra" completa (borda de palavra \b) ou parte de um prefixo/sufixo comum
    for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
        # Lógica para códigos como "+RA", "-RA", "FZRA", que não são palavras completas sozinhas mas são parte de outros códigos
        if (codigo_icao == "+RA" and "+RA" in mensagem_upper) or \
           (codigo_icao == "-RA" and "-RA" in mensagem_upper) or \
           (codigo_icao == "FZRA" and "FZRA" in mensagem_upper):
            if codigo_icao not in [a.split('(')[0].strip() for a in alertas_encontrados]: # Evita duplicatas se já adicionado por outra regra
                alertas_encontrados.append(descricao)
        # Para outros códigos, usamos bordas de palavra para evitar falsos positivos (ex: "VALID" detectando "VA")
        elif re.search(r'\b' + re.escape(codigo_icao) + r'\b', mensagem_upper):
            if codigo_icao in ["OVC", "BKN"]:
                if re.search(f"{codigo_icao}00[1-5]", mensagem_upper): 
                    alertas_encontrados.append(f"{descricao} (TETO BAIXO < 600FT)")
            elif codigo_icao == "FG":
                vis_match = re.search(r'\s(\d{4})\s', mensagem_upper) 
                if vis_match:
                    visibility_meters = int(vis_match.group(1))
                    if visibility_meters < 1000:
                        alertas_encontrados.append(f"{descricao} (VISIBILIDADE < 1000M)")
                elif "FG" in mensagem_upper: # Se FG está presente, mas a visibilidade não foi capturada ou é maior
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
        
    # DETECÇÃO ESPECÍFICA PARA CINZAS VULCÂNICAS (VA)
    # Garante que 'VA' está como um código isolado ou em um contexto meteorológico
    # e que NÃO seja parte da palavra "VALID".
    if re.search(r'\bVA\b', mensagem_upper) and "VALID" not in mensagem_upper: 
        if "Cinzas Vulcânicas (VA)" not in alertas_encontrados:
            alertas_encontrados.append("Cinzas Vulcânicas (VA)")

    # --- Lógica para ventos acima de 20KT e rajadas acima de 20KT (para METAR/SPECI/TAF) ---
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
            if gust_wind >= 20: 
                wind_desc.append(f"Rajadas de {gust_wind}KT")

        if wind_desc: 
            alertas_encontrados.append(" e ".join(wind_desc))

    # Lógica para TAF (previsão) - procurar por fenômenos e condições em TEMPO/BECMG/PROB30/40
    if "TAF" in tipo_mensagem.upper(): 
        # Reforçar a detecção de fenômenos com prefixos de TAF
        for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
            if re.search(r'(PROB\d{2}|TEMPO|BECMG)\s+' + re.escape(codigo_icao) + r'\b', mensagem_upper):
                 if codigo_icao in ["OVC", "BKN"]:
                    if re.search(f"(PROB\d{{2}}|TEMPO|BECMG)\\s+{codigo_icao}00[1-5]", mensagem_upper): 
                        alertas_encontrados.append(f"PREVISÃO {codigo_icao}: {descricao} (TETO BAIXO < 600FT)")
                    else:
                        alertas_encontrados.append(f"PREVISÃO {codigo_icao}: {descricao}")
                 elif codigo_icao == "FG":
                    vis_match_taf = re.search(r'(PROB\d{2}|TEMPO|BECMG)\s+FG\s+(\d{4})', mensagem_upper)
                    if vis_match_taf:
                        visibility_meters_taf = int(vis_match_taf.group(2))
                        if visibility_meters_taf < 1000:
                            alertas_encontrados.append(f"PREVISÃO FG: {descricao} (VISIBILIDADE < 1000M)")
                    elif re.search(r'(PROB\d{2}|TEMPO|BECMG)\s+FG', mensagem_upper):
                        alertas_encontrados.append(f"PREVISÃO FG: {descricao}")
                 else:
                    alertas_encontrados.append(f"PREVISÃO {descricao}") # Ex: PREVISÃO Trovoada

        # DETECÇÃO ESPECÍFICA PARA CINZAS VULCÂNICAS (VA) EM TAF
        if re.search(r'(?:PROB\d{2}|TEMPO|BECMG)\s+VA\b', mensagem_upper): 
            if "PREVISÃO: Cinzas Vulcânicas (VA)" not in alertas_encontrados:
                alertas_encontrados.append("PREVISÃO: Cinzas Vulcânicas (VA)")

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
                alertas_encontrados.append(f"PREVISÃO {prefix}: {' e '.join(wind_desc_taf)}")


    # --- Lógica para Avisos de Aeródromo (Refinada) ---
    if "AD WRNG" in tipo_mensagem.upper() or "AVISO DE AERÓDROMO" in tipo_mensagem.upper(): 
        aviso_fenomenos_desc = []
        
        if "TS" in mensagem_upper:
            aviso_fenomenos_desc.append("Trovoada")

        wind_warning_match = re.search(r'SFC WSPD (\d+KT)(?: MAX (\d+))?', mensagem_upper)
        if wind_warning_match:
            min_wind_str = re.search(r'(\d+)KT', wind_warning_match.group(1)).group(1) 
            min_wind = int(min_wind_str)
            max_wind = wind_warning_match.group(2)
            
            wind_parts = []
            if min_wind >= 15: 
                wind_parts.append(f"Vento de Superfície de {min_wind}KT")

            if max_wind:
                max_wind_val = int(max_wind)
                if max_wind_val >= 25: 
                    wind_parts.append(f"Rajadas de {max_wind_val}KT")
            
            if wind_parts:
                aviso_fenomenos_desc.append(" e ".join(wind_parts))

        if "GRANIZO" in mensagem_upper:
            aviso_fenomenos_desc.append("Granizo")
        if "FG" in mensagem_upper or "NEVOEIRO" in mensagem_upper: 
            vis_match_aviso = re.search(r'VIS < (\d+)([MK])', mensagem_upper)
            if vis_match_aviso:
                vis_value = int(vis_match_aviso.group(1))
                vis_unit = vis_match_aviso.group(2)
                if (vis_unit == 'M' and vis_value < 1000) or (vis_unit == 'K' and vis_value < 1): 
                    alertas_encontrados.append(f"Nevoeiro (VISIBILIDADE < {vis_value}{vis_unit})")
            else:
                alertas_encontrados.append("Nevoeiro")
        
        if "CHUVA FORTE" in mensagem_upper or "+RA" in mensagem_upper:
            aviso_fenomenos_desc.append("Chuva Forte")
        if "VISIBILIDADE REDUZIDA" in mensagem_upper:
            aviso_fenomenos_desc.append("Visibilidade Reduzida")
        if "WIND SHEAR" in mensagem_upper or "WS" in mensagem_upper:
            aviso_fenomenos_desc.append("Tesoura de Vento (Wind Shear)")
            
        # CORREÇÃO PARA CINZAS VULCÂNICAS (VA) EM AVISOS: verifica se VA é uma palavra separada
        # e não é parte da palavra "VALID"
        if re.search(r'\bVA\b', mensagem_upper) and "VALID" not in mensagem_upper: 
            if "Cinzas Vulcânicas (VA)" not in aviso_fenomenos_desc: # Evita adicionar duplicado
                aviso_fenomenos_desc.append("Cinzas Vulcânicas (VA)")
            
        if "FUMAÇA" in mensagem_upper or "FU" in mensagem_upper:
            aviso_fenomenos_desc.append("Fumaça")
            
        if aviso_fenomenos_desc:
            alertas_encontrados.extend(list(set(aviso_fenomenos_desc)))
        else: 
            alertas_encontrados.append("Conteúdo não mapeado")


    return list(set(alertas_encontrados)) 


def verificar_e_alertar():
    """Verifica as condições meteorológicas e envia alertas."""
    print("Verificando condições meteorológicas...")
    
    agora_utc = datetime.now(pytz.utc)

    for aerodromo in AERODROMOS_INTERESSE:
        # --- Avisos de Aeródromo ---
        # Agora usando a função REAL para buscar dados
        avisos_data = obter_mensagens_redemet_real("aviso", aerodromo) 
        if avisos_data and avisos_data['data']:
            for aviso in avisos_data['data']:
                mensagem_aviso = aviso.get('mensagem', '') # Usar .get para segurança
                if not mensagem_aviso: continue # Pular se a mensagem estiver vazia
                
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
        # Agora usando a função REAL para buscar dados
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
        # Agora usando a função REAL para buscar dados
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

    for msg_hash in list(alertas_enviados_cache.keys()):
        if agora_utc - alertas_enviados_cache[msg_hash] > timedelta(hours=24):
            del alertas_enviados_cache[msg_hash]

# --- Execução Principal (para GitHub Actions) ---
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not REDEMET_API_KEY:
        print("Erro: Variáveis de ambiente TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID ou REDEMET_API_KEY não configuradas.")
        print("Por favor, defina-as antes de executar o script.")
    else:
        print("Executando verificação de alertas REDEMET (execução única para GitHub Actions).")
        verificar_e_alertar() 
        print("Verificação concluída.")
