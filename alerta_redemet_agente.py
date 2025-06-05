import os
import requests
import json
import time
from datetime import datetime, timedelta
import pytz
import re

# --- Configurações ---
# Use o token do seu bot no Telegram
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
# ID do chat para onde as mensagens serão enviadas (pode ser um grupo ou um usuário)
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# SUA CHAVE DA API DA REDEMET - AGORA DESCOMENTADO E OBRIGATÓRIO
REDEMET_API_KEY = os.getenv('REDEMET_API_KEY')

# Aeródromos de interesse
AERODROMOS_INTERESSE = ["SBTA", "SBBR", "SBGL", "SBGR"] # Adicione outros aeródromos aqui se desejar

# Intervalo de verificação em segundos (5 minutos) - Este será o intervalo de sleep SE rodar localmente
# No GitHub Actions, o agendamento é feito pelo cron no .yml
INTERVALO_VERIFICACAO = 300 

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
    "CB": "Cumulunimbus", 
    "TCU": "Cumulus Castellanus", 
    "WS": "Tesoura de Vento (Wind Shear)", 
}

# Armazenamento em memória para evitar alertas duplicados
alertas_enviados_cache = {} # {hash_da_mensagem: timestamp_envio}

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
        response.raise_for_status() # Lança exceção para erros HTTP
        print(f"Mensagem enviada com sucesso para o Telegram: {texto}")
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar mensagem para o Telegram: {e}")

def obter_mensagens_redemet(endpoint, aerodromo):
    """
    Obtém dados meteorológicos da API real da REDEMET.
    """
    url = f"https://api-redemet.decea.mil.br/mensagens/{endpoint}/{aerodromo}"
    headers = {
        "x-api-key": REDEMET_API_KEY
    }
    params = {
        "api_key": REDEMET_API_KEY # Conforme a documentação, a chave também pode ir como param
    }
    
    print(f"Buscando dados da REDEMET para {endpoint.upper()} em {aerodromo.upper()} da API real...")
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status() # Levanta um erro para códigos de status HTTP 4xx/5xx
        data = response.json()
        
        # CORREÇÃO CRÍTICA AQUI: Retornar APENAS o conteúdo da chave 'data'
        if data and 'data' in data and data['data']:
            print(f"Dados da REDEMET obtidos com sucesso para {aerodromo.upper()}.")
            return {"data": data['data']} # Retorna apenas a lista de mensagens
        else:
            print(f"Nenhum dado encontrado para {aerodromo.upper()} no endpoint {endpoint.upper()}. Resposta: {data}")
            return {"data": []} # Retorna estrutura vazia consistente
    except requests.exceptions.HTTPError as http_err:
        print(f"Erro HTTP ao acessar REDEMET API para {aerodromo.upper()} ({endpoint.upper()}): {http_err}")
        print(f"Status Code: {http_err.response.status_code}")
        print(f"Response Body: {http_err.response.text}")
        if http_err.response.status_code == 403:
            print("Verifique se a sua REDEMET_API_KEY está correta e ativa.")
        return {"data": []}
    except requests.exceptions.ConnectionError as conn_err:
        print(f"Erro de conexão com a REDEMET API para {aerodromo.upper()}: {conn_err}")
        return {"data": []}
    except requests.exceptions.Timeout as timeout_err:
        print(f"Timeout ao acessar REDEMET API para {aerodromo.upper()}: {timeout_err}")
        return {"data": []}
    except requests.exceptions.RequestException as req_err:
        print(f"Erro geral ao acessar REDEMET API para {aerodromo.upper()}: {req_err}")
        return {"data": []}
    except json.JSONDecodeError as json_err:
        print(f"Erro ao decodificar JSON da REDEMET API para {aerodromo.upper()}: {json_err}")
        print(f"Response text: {response.text}")
        return {"data": []}


def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """
    Função para o robô 'ler' a mensagem e procurar por códigos severos e contexto.
    Retorna uma lista dos alertas de texto encontrados, com base nos seus critérios.
    """
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    # --- Análise de Fenômenos Específicos (METAR/TAF/Aviso) ---

    if "METAR" in tipo_mensagem.upper() or "SPECI" in tipo_mensagem.upper() or "TAF" in tipo_mensagem.upper():
        for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
            # Usar regex para garantir que o código é uma palavra inteira (delimitações)
            # ou parte de um código composto relevante (ex: +RA, FZRA)
            # Adicionado re.escape para lidar com caracteres especiais em códigos como '+RA'
            if re.search(r'\b' + re.escape(codigo_icao) + r'\b', mensagem_upper):

                if codigo_icao in ["OVC", "BKN"]:
                    # Teto baixo: OVC ou BKN com altura de nuvem 001 a 005 (100 a 500 ft)
                    if re.search(f"{codigo_icao}00[1-5]", mensagem_upper): 
                        alertas_encontrados.append(f"{descricao} (TETO BAIXO < 600FT)")
                elif codigo_icao == "FG":
                    # Nevoeiro com visibilidade restrita
                    vis_match = re.search(r'\s(\d{4})\s', mensagem_upper) 
                    if vis_match:
                        visibility_meters = int(vis_match.group(1))
                        if visibility_meters < 1000:
                            alertas_encontrados.append(f"{descricao} (VISIBILIDADE < 1000M)")
                    elif "FG" in mensagem_upper: # Se FG está presente mas visibilidade não foi parsada
                        alertas_encontrados.append(descricao) 
                elif codigo_icao == "CB":
                    # Nuvens Cumulunimbus (CB) com altura
                    cb_match = re.search(r'(FEW|SCT|BKN|OVC)(\d{3})CB', mensagem_upper)
                    if cb_match:
                        cloud_height = int(cb_match.group(2)) * 100
                        alertas_encontrados.append(f"{descricao} a {cloud_height}FT")
                    else: 
                        alertas_encontrados.append(descricao)
                else: 
                    alertas_encontrados.append(descricao)
        
        # DETECÇÃO ESPECÍFICA PARA CINZAS VULCÂNICAS (VA) em METAR/TAF
        # Procura por 'VA' que não esteja diretamente associado a 'VALID' de um aviso
        if re.search(r'\bVA\b', mensagem_upper) and "VALID" not in mensagem_upper:
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
            # Reavaliar fenômenos dentro de seções de tendência
            for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
                # Regex para pegar o código com ou sem intensidade (+RA, -RA) dentro das seções
                pattern = r'(?:PROB\d{2}|TEMPO|BECMG)\s+.*?\b' + re.escape(codigo_icao) + r'\b'
                if re.search(pattern, mensagem_upper):
                    if codigo_icao in ["OVC", "BKN"]:
                        if re.search(pattern.replace(r'\b', r'') + r'00[1-5]', mensagem_upper): # Ajuste para pegar a altura
                            alertas_encontrados.append(f"PREVISÃO {descricao} (TETO BAIXO < 600FT)")
                    elif codigo_icao == "FG":
                        vis_match_taf = re.search(pattern.replace(r'\b', r'') + r'\s(\d{4})\s', mensagem_upper)
                        if vis_match_taf and int(vis_match_taf.group(1)) < 1000:
                             alertas_encontrados.append(f"PREVISÃO {descricao} (VISIBILIDADE < 1000M)")
                        elif re.search(pattern, mensagem_upper):
                            alertas_encontrados.append(f"PREVISÃO {descricao}")
                    else:
                        alertas_encontrados.append(f"PREVISÃO: {descricao}")
            
            # DETECÇÃO ESPECÍFICA PARA CINZAS VULCÂNICAS (VA) EM TAF (com prefixo de tendência)
            if re.search(r'(?:PROB\d{2}|TEMPO|BECMG)\s+VA\b', mensagem_upper):
                alertas_encontrados.append("PREVISÃO: Cinzas Vulcânicas (VA)")

            # Análise de vento em seções de tendência no TAF
            # Captura o prefixo (TEMPO, BECMG, PROBxx) e os dados de vento
            wind_groups_in_taf = re.findall(r'(PROB\d{2}|TEMPO|BECMG)?.*?(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
            for group in wind_groups_in_taf:
                prefix = group[0] if group[0] else "Previsão" # Se não tiver prefixo explícito, é da previsão principal
                sustained_wind_str = group[2]
                gust_wind_str = group[4] 
                
                if not sustained_wind_str: # Pular se não houver vento sustentado válido no grupo
                    continue

                sustained_wind = int(sustained_wind_str)
                
                wind_desc_taf = []
                if sustained_wind >= 20:
                    wind_desc_taf.append(f"Vento Médio de {sustained_wind}KT")
                
                if gust_wind_str:
                    gust_wind = int(gust_wind_str)
                    if gust_wind >= 20:
                        wind_desc_taf.append(f"Rajadas de {gust_wind}KT")

                if wind_desc_taf:
                    alertas_encontrados.append(f"{prefix.upper()}: {' e '.join(wind_desc_taf)}")


    # --- Lógica para Avisos de Aeródromo (Refinada) ---
    elif "AD WRNG" in tipo_mensagem.upper() or "AVISO DE AERÓDROMO" in tipo_mensagem.upper(): 
        aviso_fenomenos_desc = []
        
        if "TS" in mensagem_upper:
            aviso_fenomenos_desc.append("Trovoada")

        # Regex para capturar velocidade do vento e rajadas em AD WRNG
        wind_warning_match = re.search(r'SFC WSPD (\d+KT)(?: MAX (\d+))?', mensagem_upper)
        if wind_warning_match:
            min_wind_str = re.search(r'(\d+)KT', wind_warning_match.group(1)).group(1) 
            min_wind = int(min_wind_str)
            max_wind = wind_warning_match.group(2) # Pode ser None se MAX não estiver presente
            
            wind_parts = []
            if min_wind >= 15: # Ajustado para 15KT conforme seu critério anterior
                wind_parts.append(f"Vento de Superfície de {min_wind}KT")

            if max_wind:
                max_wind_val = int(max_wind)
                if max_wind_val >= 25: # Ajustado para 25KT conforme seu critério anterior
                    wind_parts.append(f"Rajadas de {max_wind_val}KT")
            
            if wind_parts:
                aviso_fenomenos_desc.append(" e ".join(wind_parts))


        if "GRANIZO" in mensagem_upper:
            aviso_fenomenos_desc.append("Granizo")
        
        # Nevoeiro em avisos
        if "FG" in mensagem_upper or "NEVOEIRO" in mensagem_upper: 
            vis_match_aviso = re.search(r'VIS < (\d+)([MK])', mensagem_upper)
            if vis_match_aviso:
                vis_value = int(vis_match_aviso.group(1))
                vis_unit = vis_match_aviso.group(2)
                # Converte para metros se for em quilômetros
                vis_meters = vis_value * 1000 if vis_unit == 'K' else vis_value
                if vis_meters < 1000: # Critério de visibilidade reduzida
                    aviso_fenomenos_desc.append(f"Nevoeiro (VISIBILIDADE < {vis_value}{vis_unit})")
            else: # Se FG está presente mas a visibilidade não foi especificada com "<"
                aviso_fenomenos_desc.append("Nevoeiro")
        
        if "CHUVA FORTE" in mensagem_upper or "+RA" in mensagem_upper:
            aviso_fenomenos_desc.append("Chuva Forte")
        
        if "VISIBILIDADE REDUZIDA" in mensagem_upper:
            aviso_fenomenos_desc.append("Visibilidade Reduzida")
        
        if "WIND SHEAR" in mensagem_upper or "WS" in mensagem_upper:
            aviso_fenomenos_desc.append("Tesoura de Vento (Wind Shear)")
            
        # CORREÇÃO PARA CINZAS VULCÂNICAS (VA) EM AVISOS: verifica se VA é uma palavra separada
        # Removido o filtro "VALID not in mensagem_upper" pois VA em avisos pode vir com VALID
        if re.search(r'\bVA\b', mensagem_upper): 
            aviso_fenomenos_desc.append("Cinzas Vulcânicas (VA)")
            
        if "FUMAÇA" in mensagem_upper or "FU" in mensagem_upper:
            aviso_fenomenos_desc.append("Fumaça")
            
        if aviso_fenomenos_desc:
            # Garante que não haja duplicatas na lista de alertas para um mesmo aviso
            alertas_encontrados.extend(list(set(aviso_fenomenos_desc)))
        else: 
            # Este 'Conteúdo não mapeado' é um fallback, pode ser removido após testes
            # para não alertar sobre coisas não relevantes se nenhum critério for batido.
            # alert_message.append("Conteúdo não mapeado") # Mantenha para debug, remova para produção.
            pass # Alterado para não adicionar se nada for detectado, evitando alertas vazios.


    return list(set(alertas_encontrados)) # Retorna alertas únicos

def verificar_e_alertar():
    """Verifica as condições meteorológicas e envia alertas."""
    print("Verificando condições meteorológicas...")
    
    # Verifica se a API Key está configurada
    if not REDEMET_API_KEY:
        print("Erro: REDEMET_API_KEY não configurada. Não é possível acessar a API real.")
        print("Certifique-se de que a secret 'REDEMET_API_KEY' está definida no GitHub.")
        return # Sai da função se a chave não estiver disponível

    agora_utc = datetime.now(pytz.utc)

    for aerodromo in AERODROMOS_INTERESSE:
        # --- Avisos de Aeródromo ---
        avisos_data = obter_mensagens_redemet("aviso", aerodromo) 
        if avisos_data and avisos_data['data']:
            for item in avisos_data['data']: 
                mensagem_aviso = ""
                # Prioriza dicionários com a chave 'mensagem', senão tenta como string direta
                if isinstance(item, dict) and 'mensagem' in item:
                    mensagem_aviso = item['mensagem'] # Acessa diretamente, pois a chave 'mensagem' deve existir
                elif isinstance(item, str):
                    mensagem_aviso = item
                
                if not mensagem_aviso:
                    # Melhorar a mensagem de log para mostrar o 'item' completo se for complexo
                    print(f"Mensagem de aviso vazia ou inválida para {aerodromo}. Item: {item}")
                    continue

                aviso_hash = calcular_hash_mensagem(mensagem_aviso)

                if aviso_hash not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_aviso, "AVISO DE AERÓDROMO") 
                    if condicoes_perigosas: # Se há condições perigosas (não vazia)
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
                        print(f"Aviso de Aeródromo para {aerodromo} sem condições perigosas detectadas: {mensagem_aviso}")
                else:
                    print(f"Aviso de Aeródromo para {aerodromo} já alertado (cache): {mensagem_aviso}")

        # --- TAFs ---
        tafs_data = obter_mensagens_redemet("taf", aerodromo) 
        if tafs_data and tafs_data['data']:
            for item in tafs_data['data']: 
                mensagem_taf = ""
                if isinstance(item, dict) and 'mensagem' in item:
                    mensagem_taf = item['mensagem']
                elif isinstance(item, str):
                    mensagem_taf = item
                
                if not mensagem_taf:
                    print(f"Mensagem TAF vazia ou inválida para {aerodromo}. Item: {item}")
                    continue

                taf_hash = calcular_hash_mensagem(mensagem_taf)

                if taf_hash not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_taf, "TAF")
                    if condicoes_perigosas:
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
                        print(f"TAF para {aerodromo} sem condições perigosas detectadas: {mensagem_taf}")
                else:
                    print(f"TAF para {aerodromo} já alertado (cache): {mensagem_taf}")

        # --- METARs e SPECI ---
        metars_data = obter_mensagens_redemet("metar", aerodromo) 
        if metars_data and metars_data['data']:
            for item in metars_data['data']:
                mensagem_metar_speci = ""
                if isinstance(item, dict) and 'mensagem' in item:
                    mensagem_metar_speci = item['mensagem']
                elif isinstance(item, str):
                    mensagem_metar_speci = item
                
                if not mensagem_metar_speci:
                    print(f"Mensagem METAR/SPECI vazia ou inválida para {aerodromo}. Item: {item}")
                    continue

                metar_speci_hash = calcular_hash_mensagem(mensagem_metar_speci)

                # Determina o tipo de mensagem para passar para a função de análise
                tipo = "SPECI" if mensagem_metar_speci.startswith("SPECI") else "METAR"

                if metar_speci_hash not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_metar_speci, tipo)
                    if condicoes_perigosas:
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
                        print(f"{tipo} para {aerodromo} sem condições perigosas detectadas: {mensagem_metar_speci}")
                else:
                    print(f"{tipo} para {aerodromo} já alertado (cache): {mensagem_metar_speci}")

    # Limpeza do cache: remove alertas mais antigos que 24 horas para evitar inchaço
    for msg_hash in list(alertas_enviados_cache.keys()):
        if agora_utc - alertas_enviados_cache[msg_hash] > timedelta(hours=24):
            del alertas_enviados_cache[msg_hash]

# --- Execução Principal (para GitHub Actions) ---
if __name__ == "__main__":
    # Verifica se as variáveis de ambiente essenciais estão configuradas
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erro: Variáveis de ambiente TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configuradas.")
        print("Por favor, defina-as como secrets no GitHub.")
    elif not REDEMET_API_KEY:
        print("Erro: REDEMET_API_KEY não configurada. Não é possível acessar a API real.")
        print("Certifique-se de que a secret 'REDEMET_API_KEY' está definida no GitHub.")
    else:
        print("Executando verificação de alertas REDEMET (execução única para GitHub Actions).")
        verificar_e_alertar() 
        print("Verificação concluída.")
