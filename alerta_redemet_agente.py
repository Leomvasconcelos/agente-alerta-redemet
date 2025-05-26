import os
import requests
import datetime
import json
import re

# --- Configurações Importantes ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
REDEMET_API_KEY = os.getenv("REDEMET_API_KEY")

# Verifica se os tokens essenciais estão configurados
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("Erro: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não encontrados nas variáveis de ambiente.")
    print("Certifique-se de configurar TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID como GitHub Secrets.")
    exit()

# --- Sua Lista de Códigos de Tempo Severo e Critérios ---
# Refinada com seus requisitos específicos!
CODIGOS_SEVEROS = [
    "TS",     # Tempestade
    "GR",     # Granizo
    "VA",     # Cinzas Vulcânicas
    "VCTS",   # Tempestade Próxima
    "VCFG",   # Nevoeiro Próximo
    "VV",     # Visibilidade Vertical (Céu Obscurecido, Teto Ilimitado)
    "OVC",    # Coberto (com critério de teto)
    "BKN",    # Quebrado (com critério de teto)
    "FG",     # Nevoeiro (com critério de visibilidade)
    "FU",     # Fumaça
    "SHGR",   # Pancada de Granizo (GR pequeno)
    "RA",     # Chuva (com critério de +RA)
    "WS",     # Tesoura de Vento (Wind Shear)
    # Ventos e Rajadas serão tratados separadamente por sua natureza numérica.
]

# Lista de aeródromos a serem monitorados (AGORA APENAS SBTA!)
AERODROMOS_INTERESSE = ["SBTA"] 

# --- Funções de Comunicação e Análise ---

def enviar_mensagem_telegram(mensagem):
    """
    Função que envia uma mensagem para o seu bot do Telegram.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Tokens do Telegram não configurados. Não é possível enviar alerta.")
        return

    print(f"Tentando enviar mensagem para o Telegram: {mensagem[:100]}...")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status() 
        print("Mensagem enviada para o Telegram com sucesso!")
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar mensagem para o Telegram: {e}")
        if 'response' in locals() and hasattr(response, 'text'):
            print(f"Resposta da API do Telegram: {response.text}")

def obter_mensagens_redemet_real(endpoint, aerodromo=None):
    """
    Esta função fará a chamada REAL para a API da REDEMET.
    VOCÊ PRECISA AJUSTAR ESTA FUNÇÃO CONFORME A DOCUMENTAÇÃO DA REDEMET.
    """
    if not REDEMET_API_KEY:
        print("REDEMET_API_KEY não configurado. Não é possível chamar a API real.")
        return None
    
    URL_BASE = "https://api.redemet.aer.mil.br/v1" # Exemplo, CONFIRME NA DOCUMENTAÇÃO!
    
    if "METAR" in endpoint:
        url_completa = f"{URL_BASE}/metar/latest"
    elif "TAF" in endpoint:
        url_completa = f"{URL_BASE}/taf/forecast"
    elif "AVISO" in endpoint:
         url_completa = f"{URL_BASE}/avisos_aerodromo" # Exemplo, CONFIRME NA DOCUMENTAÇÃO!
    else:
        print(f"Endpoint desconhecido: {endpoint}")
        return None

    headers = {
        "x-api-key": REDEMET_API_KEY # Exemplo, CONFIRME NA DOCUMENTAÇÃO!
    }
    params = {
        "localidade": aerodromo # Exemplo, CONFIRME NA DOCUMENTAÇÃO!
    }

    print(f"Buscando dados reais da REDEMET: {url_completa} (Aeródromo: {aerodromo})")

    try:
        response = requests.get(url_completa, headers=headers, params=params, timeout=30)
        response.raise_for_status() 
        dados = response.json() 
        return dados
    except requests.exceptions.RequestException as e:
        print(f"Erro ao acessar a API real da REDEMET ({url_completa}): {e}")
        if 'response' in locals() and hasattr(response, 'text'):
            print(f"Resposta da API da REDEMET: {response.text}")
        return None

def obter_mensagens_redemet_simulada(endpoint, aerodromo=None):
    """
    Função de simulação para testar a lógica SEM a API real.
    Retorna dados de exemplo como se viessem da API da REDEMET.
    """
    print(f"Simulando busca de dados da REDEMET para {endpoint} em {aerodromo}...")
    
    # EXEMPLOS DE MENSAGENS REAIS PARA TESTE para SBTA!
    metar_simulado = {
        "SBTA": "SBTA 261800Z 12025G35KT 5000 VCTS BR SCT008 BKN005 23/20 Q1012 RMK", # Exemplo: Vento > 20KT, Rajada > 20KT, VCTS, BKN005
    }
    taf_simulado = {
        "SBTA": "TAF SBTA 261700Z 2618/2718 12015G28KT 9999 SCT020 PROB40 2700/2703 2000 TSRA BKN008CB", # Exemplo: Rajada > 20KT, PROB40 TSRA
    }
    aviso_simulado = {
        "SBTA": "AVISO DE AERODROMO: SBTA VISIBILIDADE REDUZIDA DEVIDO A NEVOEIRO FORTE ESPERADO ENTRE 02Z E 05Z.",
    }

    if "METAR" in endpoint:
        mensagem = metar_simulado.get(aerodromo)
        return {"data": [{"mensagem": mensagem}]} if mensagem else {"data": []}
    elif "TAF" in endpoint:
        mensagem = taf_simulado.get(aerodromo)
        return {"data": [{"mensagem": mensagem}]} if mensagem else {"data": []}
    elif "AVISO" in endpoint:
        mensagem = aviso_simulado.get(aerodromo)
        return {"data": [{"mensagem": mensagem}]} if mensagem else {"data": []}
    
    return {"data": []}

# Mude para `obter_mensagens_redemet_real` quando tiver a chave da API e ajustado a função.
obter_mensagens_redemet = obter_mensagens_redemet_simulada


def processar_mensagens_redemet(tipo_mensagem, dados_api):
    """
    Processa os dados retornados pela API (real ou simulada) e extrai as mensagens de texto.
    ESTA FUNÇÃO É CRÍTICA E PRECISA SER AJUSTADA COM BASE NA ESTRUTURA REAL DO JSON DA API DA REDEMET.
    """
    mensagens_encontradas = []

    if isinstance(dados_api, dict) and 'data' in dados_api and isinstance(dados_api['data'], list):
        for item in dados_api['data']:
            if isinstance(item, dict) and 'mensagem' in item:
                mensagens_encontradas.append(item['mensagem'])
        
    elif isinstance(dados_api, list) and all(isinstance(item, str) for item in dados_api):
        mensagens_encontradas.extend(dados_api)

    return mensagens_encontradas


def analisar_mensagem_meteorologica(mensagem_texto):
    """
    Função para o robô 'ler' a mensagem e procurar por códigos severos e contexto.
    Retorna uma lista dos alertas de texto encontrados, com base nos seus critérios.
    """
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    # --- Análise de Fenômenos Específicos (METAR/TAF/Aviso) ---
    for codigo in CODIGOS_SEVEROS:
        if codigo in mensagem_upper:
            # Lógica para "OVC" e "BKN" abaixo de 600 pés (006)
            if codigo in ["OVC", "BKN"]:
                # Expressão regular para encontrar OVC/BKN seguido de 001 a 005 (100 a 500 pés)
                if re.search(f"{codigo}00[1-5]", mensagem_upper): 
                    alertas_encontrados.append(f"{codigo} (TETO BAIXO < 600FT)")
            # Lógica para "FG" (Nevoeiro) - verificar visibilidade < 1000m
            elif codigo == "FG":
                # Procura por FG e se a visibilidade está abaixo de 1000m (0800, 0500 etc.)
                vis_match = re.search(r'\s(\d{4})\s', mensagem_upper) # Busca 4 dígitos cercados por espaços
                if vis_match:
                    visibility_meters = int(vis_match.group(1))
                    if visibility_meters < 1000:
                        alertas_encontrados.append(f"{codigo} (NEVOEIRO < 1000M VIS)")
                elif "FG" in mensagem_upper: # Alerta mesmo sem a visibilidade explícita, se FG estiver presente
                     alertas_encontrados.append(f"{codigo} (NEVOEIRO)") 
            # Lógica para "+RA" (Chuva Forte)
            elif codigo == "RA" and "+RA" in mensagem_upper:
                alertas_encontrados.append("CHUVA FORTE (+RA)")
            # Outros códigos que são diretos
            elif codigo in ["TS", "GR", "VA", "VCTS", "VCFG", "VV", "FU", "SHGR", "WS"]:
                alertas_encontrados.append(codigo)
        
    # --- Lógica para ventos acima de 20KT e rajadas acima de 20KT ---
    # Regex para pegar o grupo de vento: DDDSS(GSS)KT
    # OVRB para vento variável
    wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
    if wind_match:
        sustained_wind_str = wind_match.group(2)
        gust_wind_str = wind_match.group(4) # Pode ser None se não houver rajada

        sustained_wind = int(sustained_wind_str)
        
        if sustained_wind > 20:
            alertas_encontrados.append(f"VENTO SUSTENTADO > 20KT ({sustained_wind}KT)")
        
        if gust_wind_str:
            gust_wind = int(gust_wind_str)
            if gust_wind > 20:
                alertas_encontrados.append(f"RAJADA DE VENTO > 20KT ({gust_wind}KT)")

    # Lógica para TAF (previsão) - procurar por fenômenos e condições em TEMPO/BECMG/PROB30/40
    if "TAF" in mensagem_upper:
        for codigo in CODIGOS_SEVEROS:
            # Fenômenos com PROB30/40
            if f"PROB30 {codigo}" in mensagem_upper or f"PROB40 {codigo}" in mensagem_upper:
                 alertas_encontrados.append(f"PREVISÃO: PROB {codigo}")
            # Fenômenos com TEMPO ou BECMG
            if f"TEMPO {codigo}" in mensagem_upper:
                alertas_encontrados.append(f"PREVISÃO: TEMPO {codigo}")
            if f"BECMG {codigo}" in mensagem_upper:
                alertas_encontrados.append(f"PREVISÃO: BECMG {codigo}")
            
            # Regras específicas para TAF que são semelhantes ao METAR para teto e visibilidade
            if codigo in ["OVC", "BKN"]:
                if re.search(f"{codigo}00[1-5]", mensagem_upper): 
                    alertas_encontrados.append(f"PREVISÃO: {codigo} (TETO BAIXO < 600FT)")
            if codigo == "FG":
                 if re.search(r'\s(\d{4})\s', mensagem_upper) and int(re.search(r'\s(\d{4})\s', mensagem_upper).group(1)) < 1000:
                    alertas_encontrados.append(f"PREVISÃO: {codigo} (NEVOEIRO < 1000M VIS)")
                 elif "FG" in mensagem_upper:
                     alertas_encontrados.append(f"PREVISÃO: {codigo} (NEVOEIRO)")

        # Análise de vento em TAF (TEMPO/BECMG/PROB)
        # Regex para encontrar grupos de vento dentro de TEMPO/BECMG/PROB
        wind_groups_in_taf = re.findall(r'(TEMPO|BECMG|PROB\d{2})\s.*?(VRB|\d{3})(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
        for group in wind_groups_in_taf:
            prefix = group[0]
            sustained_wind_str = group[2]
            gust_wind_str = group[4] # Pode ser None
            
            sustained_wind = int(sustained_wind_str)
            
            if sustained_wind > 20:
                alertas_encontrados.append(f"PREVISÃO {prefix}: VENTO SUSTENTADO > 20KT ({sustained_wind}KT)")
            
            if gust_wind_str:
                gust_wind = int(gust_wind_str)
                if gust_wind > 20:
                    alertas_encontrados.append(f"PREVISÃO {prefix}: RAJADA DE VENTO > 20KT ({gust_wind}KT)")


    # Lógica para Avisos de Aeródromo (geralmente já são alertas por natureza)
    if "AVISO DE AERODROMO" in mensagem_upper or "ADVISORY" in mensagem_upper:
        aviso_fenomenos = []
        # Para avisos, a busca é por palavras-chave mais descritivas, além dos códigos
        for palavra_chave in ["TS", "GR", "VA", "FG", "FU", "SHGR", "+RA", "WS", 
                              "TEMPESTADE", "GRANIZO", "CINZAS", "NEVOEIRO", "FUMAÇA", 
                              "VISIBILIDADE REDUZIDA", "VENTO FORTE", "RAJADA", "CHUVA FORTE"]:
            if palavra_chave in mensagem_upper:
                aviso_fenomenos.append(palavra_chave)
        
        if aviso_fenomenos:
            alertas_encontrados.append(f"AVISO: {', '.join(aviso_fenomenos)}")
        else: # Se o aviso não contiver os códigos específicos, ainda é um aviso.
            alertas_encontrados.append("AVISO DE AERÓDROMO (GENÉRICO)")


    return list(set(alertas_encontrados)) # Retorna apenas alertas únicos

# --- Lógica Principal do Agente ---
def main():
    print(f"[{datetime.datetime.now()}] Iniciando o agente de alerta meteorológico da REDEMET...")

    endpoints_para_verificar = {
        "METAR": "METAR",
        "TAF": "TAF",
        "AVISO": "AVISO"
    }

    # Para evitar enviar o mesmo alerta repetidamente NA MESMA EXECUÇÃO do workflow,
    # usamos um set que armazena os hashes das mensagens que já geraram um alerta.
    mensagens_com_alerta_enviado_nesta_execucao = set()

    for aerodromo in AERODROMOS_INTERESSE: # Agora apenas SBTA
        for tipo, endpoint_chave in endpoints_para_verificar.items():
            print(f"Verificando {tipo} para aeródromo {aerodromo}...")
            
            dados_brutos_api = obter_mensagens_redemet(endpoint_chave, aerodromo) # Chamará a função simulada

            if dados_brutos_api:
                mensagens_texto = processar_mensagens_redemet(tipo, dados_brutos_api)

                if mensagens_texto:
                    for mensagem_individual in mensagens_texto:
                        hash_mensagem = hash(mensagem_individual)

                        if hash_mensagem in mensagens_com_alerta_enviado_nesta_execucao:
                            print(f"  Mensagem {tipo} para {aerodromo} já alertada nesta execução: {mensagem_individual[:50]}...")
                            continue 

                        alertas = analisar_mensagem_meteorologica(mensagem_individual)

                        if alertas:
                            alerta_final = f"🚨 *ALERTA REDEMET - TEMPO SEVERO!* 🚨\n\n"
                            alerta_final += f"**Aeródromo:** {aerodromo.upper()} - **Tipo:** {tipo}\n"
                            alerta_final += f"**Condições Encontradas:** {', '.join(alertas)}\n\n"
                            alerta_final += f"**Mensagem Original:**\n```\n{mensagem_individual}\n```\n"
                            alerta_final += f"_(Hora do Agente: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC)_"
                            
                            print("\n" + alerta_final + "\n")
                            enviar_mensagem_telegram(alerta_final)
                            mensagens_com_alerta_enviado_nesta_execucao.add(hash_mensagem)
                        else:
                            print(f"  Mensagem {tipo} para {aerodromo} sem alertas severos: {mensagem_individual[:50]}...")
                else:
                    print(f"Nenhuma mensagem de texto extraída para {tipo} em {aerodromo}. Verifique 'processar_mensagens_redemet'.")
            else:
                print(f"Não foi possível obter dados para {tipo} em {aerodromo}.")

    print(f"[{datetime.datetime.now()}] Verificação de alerta concluída.")

if __name__ == "__main__":
    main()
