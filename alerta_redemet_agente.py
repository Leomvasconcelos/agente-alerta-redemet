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

# Substitua pela sua chave da API da REDEMET (quando disponível)
# REDEMET_API_KEY = os.getenv('REDEMET_API_KEY') 

# Aeródromos de interesse (SBTA para testes iniciais)
AERODROMOS_INTERESSE = ["SBTA"]

# Intervalo de verificação em segundos (5 minutos)
INTERVALO_VERIFICACAO = 300 

# Dicionário de códigos METAR/TAF e suas descrições
CODIGOS_METAR_TAF_MAP = {
    "TS": "Trovoada",
    "RA": "Chuva",
    "+RA": "Chuva Forte", # Adicionado para detecção específica
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
    "HZ": "Névoa Seca (Haze)",
    "FU": "Fumaça",
    "VA": "Cinzas Vulcânicas",
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
    "SH": "Pancada (Shower)", # Para SHRA, SHSN, etc.
    "OVC": "Nublado (Overcast)", # Teto Baixo
    "BKN": "Parcialmente Nublado (Broken)", # Teto Baixo
    "CB": "Cumulunimbus", # Nuvem de Trovoada
    "TCU": "Cumulus Castellanus", # Nuvem convectiva significante
    "WS": "Tesoura de Vento (Wind Shear)", # Adicionado para Avisos de Aeródromo
}

# Armazenamento em memória para evitar alertas duplicados
# Em um ambiente de produção, isso seria um banco de dados ou cache persistente
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

def obter_mensagens_redemet_simulada(endpoint, aerodromo=None):
    """
    Função de simulação para testar a lógica SEM a API real.
    Retorna dados de exemplo como se viessem da API da REDEMET.
    """
    print(f"Simulando busca de dados da REDEMET para {endpoint} em {aerodromo}...")
    
    # NOVOS EXEMPLOS DE MENSAGENS PARA TESTE SBTA (28 de maio de 2025):
    # As horas foram ajustadas para o dia atual para parecerem "frescas"
    
    # AVISOS DE AERÓDROMO
    avisos_simulados = [
        # Aviso de Trovoada e Vento Forte
        "SBGL SBSJ/SBTA AD WRNG 1 VALID 281400/281800 TS SFC WSPD 15KT MAX 30 FCST NC=", 
        # Aviso de Vento de Superfície e Rajada
        "SBGR SBBP/SBTA AD WRNG 2 VALID 281530/281930 SFC WSPD 20KT MAX 35 FCST NC=",
        # Aviso de Visibilidade Reduzida por Nevoeiro
        "SBSP SBTA AD WRNG 3 VALID 280200/280600 FG VIS < 500M FCST NC=",
        # Aviso de Wind Shear
        "SBTA WS WRNG 4 VALID 281600/281730 MOD WS IN APCH RWY28 REP AT 1545Z A320=",
        # Outro Aviso de Trovoada, com vento mais forte
        "SBRJ SBTA AD WRNG 5 VALID 281700/282100 TS SFC WSPD 25KT MAX 45 FCST NC=",
        # Aviso de Chuva Forte
        "SBGO SBTA AD WRNG 6 VALID 281100/281400 +RA FCST NC=",
    ]

    # TAFs
    tafs_simulados = [
        # TAF com previsão de TS e rajadas, teto baixo
        "TAF SBTA 281200Z 2812/2912 33010KT 9999 SCT015 BKN030 TX25/2815Z TN18/2903Z TEMPO 2814/2818 30020G35KT 4000 TSRA BKN008 FEW030CB BECMG 2818/2820 27010KT 9999 NSW SCT020 RMK PBZ=",
        # TAF com previsão de nevoeiro e visibilidade reduzida
        "TAF SBTA 280000Z 2800/2824 00000KT 9999 SKC TX28/2817Z TN15/2806Z PROB40 2803/2808 0800 FG OVC002 BECMG 2810/2812 9999 NSW RMK PST=",
        # TAF com chuva forte e vento moderado
        "TAF SBTA 280600Z 2806/2906 18008KT 9999 FEW025 SCT040 TEMPO 2808/2812 20015KT 3000 +RA BKN010 RMK PQL=",
        # TAF com condição CAVOK
        "TAF SBTA 281800Z 2818/2918 27005KT CAVOK TX26/2819Z TN16/2907Z RMK PRS=",
    ]

    # SPECIs
    specis_simulados = [
        # SPECI com Trovoada e Vento Médio forte
        "SPECI SBTA 281245Z 25022KT 9000 TS SCT030 FEW040CB BKN100 22/18 Q1015=",
        # SPECI com Chuva Forte e Rajadas
        "SPECI SBTA 281310Z 18015G30KT 3000 +RA BR BKN010 OVC020 20/19 Q1016=",
        # SPECI com teto muito baixo e nevoeiro
        "SPECI SBTA 280330Z 00000KT 0500 FG OVC001 15/15 Q1020=",
        # SPECI com Visibilidade Reduzida por Haze
        "SPECI SBTA 281015Z 09005KT 4000 HZ SKC 28/20 Q1012=",
        # SPECI com Wind Shear (mesmo código do aviso, para testar a detecção)
        "SPECI SBTA 281605Z VRB02KT 9999 WS RWY28 25/20 Q1015=",
    ]

    # METARs
    metars_simulados = [
        # METAR normal, sem alerta crítico (deve ser ignorado)
        "METAR SBTA 281200Z 18005KT 9999 SCT025 24/18 Q1017=",
        # METAR com Chuva Fraca e Vento moderado
        "METAR SBTA 281300Z 15012KT 9999 -RA BKN030 23/19 Q1016=",
        # METAR com Vento forte e rajadas, mas sem outro fenômeno crítico
        "METAR SBTA 281400Z 29025G38KT 9999 FEW040 25/17 Q1014=",
        # METAR com BKN005 (teto baixo)
        "METAR SBTA 281500Z VRB03KT 9999 BKN005 20/19 Q1018=",
        # METAR com TS e CB em altura
        "METAR SBTA 281600Z 12007KT 9999 TS SCT030 FEW040CB 26/20 Q1015=",
    ]


    # Distribui as mensagens de acordo com o endpoint e o aeródromo
    mensagens_para_aerodromo = []
    
    if aerodromo and aerodromo.upper() == "SBTA":
        if "AVISO" in endpoint.upper():
            for msg in avisos_simulados:
                if aerodromo.upper() in msg.upper():
                    mensagens_para_aerodromo.append({"mensagem": msg})
        elif "TAF" in endpoint.upper():
            for msg in tafs_simulamos:
                if aerodromo.upper() in msg.upper():
                    mensagens_para_aerodromo.append({"mensagem": msg})
        elif "METAR" in endpoint.upper():
            for msg in metars_simulados + specis_simulados: # Concatena METAR e SPECI aqui
                if aerodromo.upper() in msg.upper():
                    mensagens_para_aerodromo.append({"mensagem": msg})
        else:
            print(f"Endpoint desconhecido para simulação: {endpoint}")

    return {"data": mensagens_para_aerodromo}

def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """
    Função para o robô 'ler' a mensagem e procurar por códigos severos e contexto.
    Retorna uma lista dos alertas de texto encontrados, com base nos seus critérios.
    """
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    # --- Análise de Fenômenos Específicos (METAR/TAF/Aviso) ---

    # Lógica principal para METAR e TAF (Mantida como estava e funciona bem)
    if "METAR" in tipo_mensagem.upper() or "SPECI" in tipo_mensagem.upper() or "TAF" in tipo_mensagem.upper():
        for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
            if codigo_icao in mensagem_upper:
                # Lógica para "OVC" e "BKN" abaixo de 600 pés (006)
                if codigo_icao in ["OVC", "BKN"]:
                    if re.search(f"{codigo_icao}00[1-5]", mensagem_upper): 
                        alertas_encontrados.append(f"{descricao} (TETO BAIXO < 600FT)")
                # Lógica para "FG" (Nevoeiro) - verificar visibilidade < 1000m
                elif codigo_icao == "FG":
                    vis_match = re.search(r'\s(\d{4})\s', mensagem_upper) 
                    if vis_match:
                        visibility_meters = int(vis_match.group(1))
                        if visibility_meters < 1000:
                            alertas_encontrados.append(f"{descricao} (VISIBILIDADE < 1000M)")
                    elif "FG" in mensagem_upper: 
                         alertas_encontrados.append(descricao) 
                # Lógica para "+RA" (Chuva Forte)
                elif codigo_icao == "RA" and "+RA" in mensagem_upper:
                    alertas_encontrados.append("Chuva Forte")
                # Lógica para CB (Cumulunimbus) com altura
                elif codigo_icao == "CB":
                    cb_match = re.search(r'(FEW|SCT|BKN|OVC)(\d{3})CB', mensagem_upper)
                    if cb_match:
                        cloud_height = int(cb_match.group(2)) * 100
                        alertas_encontrados.append(f"{descricao} a {cloud_height}FT")
                    else: # Se CB está, mas sem altura específica na formação
                        alertas_encontrados.append(descricao)
                # Outros códigos que são diretos
                else: 
                    alertas_encontrados.append(descricao)
            
        # --- Lógica para ventos acima de 20KT e rajadas acima de 20KT (para METAR/SPECI/TAF) ---
        wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
        if wind_match:
            sustained_wind_str = wind_match.group(2)
            gust_wind_str = wind_match.group(4) 

            sustained_wind = int(sustained_wind_str)
            
            wind_desc = []
            if sustained_wind >= 20: # Alterado para >= 20 para ser mais inclusivo
                wind_desc.append(f"Vento Médio de {sustained_wind}KT")
            
            if gust_wind_str:
                gust_wind = int(gust_wind_str)
                if gust_wind >= 20: # Alterado para >= 20 para ser mais inclusivo
                    wind_desc.append(f"Rajadas de {gust_wind}KT")

            if wind_desc: 
                alertas_encontrados.append(" e ".join(wind_desc))

        # Lógica para TAF (previsão) - procurar por fenômenos e condições em TEMPO/BECMG/PROB30/40
        if "TAF" in tipo_mensagem.upper(): # Verifica novamente, caso a mensagem seja TAF
            for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
                # Fenômenos em PROB, TEMPO, BECMG
                if f"PROB30 {codigo_icao}" in mensagem_upper or f"PROB40 {codigo_icao}" in mensagem_upper:
                    alertas_encontrados.append(f"PREVISÃO PROB: {descricao}")
                if f"TEMPO {codigo_icao}" in mensagem_upper:
                    alertas_encontrados.append(f"PREVISÃO TEMPO: {descricao}")
                if f"BECMG {codigo_icao}" in mensagem_upper:
                    alertas_encontrados.append(f"PREVISÃO BECMG: {descricao}")
                
                # Teto baixo em TAF
                if codigo_icao in ["OVC", "BKN"]:
                    if re.search(f"{codigo_icao}00[1-5]", mensagem_upper): 
                        alertas_encontrados.append(f"PREVISÃO: {descricao} (TETO BAIXO < 600FT)")
                # Nevoeiro em TAF
                if codigo_icao == "FG":
                    if re.search(r'\s(\d{4})\s', mensagem_upper) and int(re.search(r'\s(\d{4})\s', mensagem_upper).group(1)) < 1000:
                        alertas_encontrados.append(f"PREVISÃO: {descricao} (VISIBILIDADE < 1000M)")
                    elif "FG" in mensagem_upper:
                        alertas_encontrados.append(f"PREVISÃO: {descricao}")

            # Ventos e rajadas em TAF (revisado para usar a lógica comum)
            # Adaptei esta regex para capturar a parte do vento mesmo sem o prefixo (TEMPO/BECMG/PROB)
            # E adicionado a captura de prefixo se presente para inclusão no alerta
            wind_groups_in_taf = re.findall(r'(?:(TEMPO|BECMG|PROB\d{2})\s)?(?:.*?)(VRB|\d{3})(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
            for group in wind_groups_in_taf:
                prefix = group[0] if group[0] else "Previsão" # Se não tiver TEMPO/BECMG/PROB, usa "Previsão"
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
    if "AD WRNG" in tipo_mensagem.upper() or "AVISO DE AERÓDROMO" in tipo_mensagem.upper(): # Ajustado para "AD WRNG" como base
        aviso_fenomenos_desc = []
        
        # 1. Detectar TS (Trovoada) explicitamente
        if "TS" in mensagem_upper:
            aviso_fenomenos_desc.append("Trovoada")

        # 2. Detectar Vento de Superfície e Rajada (SFC WSPD 15KT MAX 25)
        wind_warning_match = re.search(r'SFC WSPD (\d+KT)(?: MAX (\d+))?', mensagem_upper)
        if wind_warning_match:
            min_wind_str = re.search(r'(\d+)KT', wind_warning_match.group(1)).group(1) # Extrai só o número
            min_wind = int(min_wind_str)
            max_wind = wind_warning_match.group(2)
            
            wind_parts = []
            if min_wind >= 15: # Considerar como alerta se o vento base já for significativo
                wind_parts.append(f"Vento de Superfície de {min_wind}KT")

            if max_wind:
                max_wind_val = int(max_wind)
                if max_wind_val >= 25: # Considerar rajada forte
                    wind_parts.append(f"Rajadas de {max_wind_val}KT")
            
            if wind_parts:
                aviso_fenomenos_desc.append(" e ".join(wind_parts))


        # 3. Detectar outros termos relevantes de Avisos (se necessário, adicione aqui de forma explícita)
        if "GRANIZO" in mensagem_upper:
            aviso_fenomenos_desc.append("Granizo")
        # Ajustado para pegar "FG" ou "NEVOEIRO" e verificar visibilidade
        if "FG" in mensagem_upper or "NEVOEIRO" in mensagem_upper: 
            vis_match_aviso = re.search(r'VIS < (\d+)([MK])', mensagem_upper)
            if vis_match_aviso:
                vis_value = int(vis_match_aviso.group(1))
                vis_unit = vis_match_aviso.group(2)
                if (vis_unit == 'M' and vis_value < 1000) or (vis_unit == 'K' and vis_value < 1): # <1km
                    alertas_encontrados.append(f"Nevoeiro (VISIBILIDADE < {vis_value}{vis_unit})")
            else:
                alertas_encontrados.append("Nevoeiro")
        
        if "CHUVA FORTE" in mensagem_upper or "+RA" in mensagem_upper:
            aviso_fenomenos_desc.append("Chuva Forte")
        if "VISIBILIDADE REDUZIDA" in mensagem_upper:
            aviso_fenomenos_desc.append("Visibilidade Reduzida")
        if "WIND SHEAR" in mensagem_upper or "WS" in mensagem_upper:
            aviso_fenomenos_desc.append("Tesoura de Vento (Wind Shear)")
        if "CINZAS VULCÂNICAS" in mensagem_upper or "VA" in mensagem_upper:
            aviso_fenomenos_desc.append("Cinzas Vulcânicas")
        if "FUMAÇA" in mensagem_upper or "FU" in mensagem_upper:
            aviso_fenomenos_desc.append("Fumaça")
            
        # Adiciona os fenômenos detectados à lista final, garantindo que não há duplicatas
        if aviso_fenomenos_desc:
            alertas_encontrados.extend(list(set(aviso_fenomenos_desc)))
        else: 
            alertas_encontrados.append("Conteúdo não mapeado")


    return list(set(alertas_encontrados)) # Retorna a lista de alertas únicos no final


def verificar_e_alertar():
    """Verifica as condições meteorológicas e envia alertas."""
    print("Verificando condições meteorológicas...")
    
    agora_utc = datetime.now(pytz.utc)

    for aerodromo in AERODROMOS_INTERESSE:
        # --- Avisos de Aeródromo ---
        avisos_data = obter_mensagens_redemet_simulada("avisos", aerodromo) # Usando a função simulada
        if avisos_data and avisos_data['data']:
            for aviso in avisos_data['data']:
                mensagem_aviso = aviso['mensagem']
                aviso_hash = calcular_hash_mensagem(mensagem_aviso)

                if aviso_hash not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_aviso, "AVISO DE AERÓDROMO") # Passando tipo completo
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
        tafs_data = obter_mensagens_redemet_simulada("taf", aerodromo) # Usando a função simulada
        if tafs_data and tafs_data['data']:
            for taf in tafs_data['data']:
                mensagem_taf = taf['mensagem']
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
        # A API da REDEMET tem um endpoint para "metar" que geralmente inclui SPECI.
        # Estamos concatenando as listas simuladas de METAR e SPECI na função `obter_mensagens_redemet_simulada`.
        metars_data = obter_mensagens_redemet_simulada("metar", aerodromo) # Usando a função simulada
        if metars_data and metars_data['data']:
            for metar_speci in metars_data['data']:
                mensagem_metar_speci = metar_speci['mensagem']
                metar_speci_hash = calcular_hash_mensagem(mensagem_metar_speci)

                # Determinar se é METAR ou SPECI
                tipo = "SPECI" if mensagem_metar_speci.startswith("SPECI") else "METAR"

                if metar_speci_hash not in alertas_enviados_cache:
                    condicoes_perigosas = analisar_mensagem_meteorologica(mensagem_metar_speci, tipo)
                    if condicoes_perigosas and "Conteúdo não mapeado" not in condicoes_perigosas:
                        # Ajustando o texto para METAR/SPECI
                        alert_message = (
                            f"⚡️ *NOVO ALERTA MET {aerodromo}!* ⚡️\n\n"
                            f"Aeródromo: {aerodromo} - Tipo: {tipo}\n"
                            f"Condições Reportadas: {', '.join(condicoes_perigosas)}\n" # Usar "Reportadas" para METAR/SPECI
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

    # Limpar cache de alertas antigos (opcional, para evitar que o cache cresça indefinidamente)
    # Por exemplo, remover alertas com mais de 24 horas
    for msg_hash in list(alertas_enviados_cache.keys()):
        if agora_utc - alertas_enviados_cache[msg_hash] > timedelta(hours=24):
            del alertas_enviados_cache[msg_hash]

# --- Loop Principal ---
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erro: Variáveis de ambiente TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configuradas.")
        print("Por favor, defina-as antes de executar o script.")
    else:
        print(f"Iniciando monitoramento. Verificando a cada {INTERVALO_VERIFICACAO} segundos.")
        while True:
            verificar_e_alertar()
            time.sleep(INTERVALO_VERIFICACAO)
