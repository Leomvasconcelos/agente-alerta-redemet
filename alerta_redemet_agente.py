import os
import requests
import datetime
import json
import re # Importar para usar expressões regulares na análise

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
# A ordem aqui não importa tanto quanto a lógica em analisar_mensagem_meteorologica.
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

# Lista de aeródromos a serem monitorados (Adicione os que você quer!)
AERODROMOS_INTERESSE = ["SBBR", "SBGR", "SBGL", "SBSP", "SBKP", "SBCT"]

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
    
    # EXEMPLOS DE MENSAGENS REAIS PARA TESTE (AJUSTE OU ADICIONE MAIS!)
    # Estas mensagens são cruciais para testar sua lógica de análise!
    metar_simulado = {
        "SBBR": "SBBR 261800Z 09005KT 9999 FEW030 SCT080 25/18 Q1015 NOSIG RMK",
        "SBGR": "SBGR 261800Z 12025G35KT 5000 VCTS BR SCT008 BKN020 23/20 Q1012 RMK", # Exemplo: Vento > 20KT, Rajada > 20KT, VCTS
        "SBGL": "SBGL 261800Z 08012KT 9999 TS FEW025CB BKN060 26/22 Q1010 TEMPO +RA RMK", # Exemplo: TS, +RA
        "SBSP": "SBSP 261800Z 27003KT 0800 FG OVC005 20/20 Q1018 RMK", # Exemplo: FG, OVC005 (abaixo de 006)
        "SBKP": "SBKP 261800Z 20015G25KT 9999 SHGR BKN004CB 24/21 Q1014 RMK", # Exemplo: Rajada > 20KT, SHGR, BKN004
        "SBCT": "SBCT 261800Z 27005KT 9999 VV001 15/15 Q1020 NOSIG RMK", # Exemplo: VV001
        "SBFL": "SBFL 261800Z 18022KT 9999 FEW030 20/10 Q1010 NOSIG RMK", # Exemplo: Vento > 20KT
        "SBRJ": "SBRJ 261800Z 27010KT 9999 BKN005 25/18 Q1012 RMK" # Exemplo: BKN005 (abaixo de 006)
    }
    taf_simulado = {
        "SBBR": "TAF SBBR 261700Z 2618/2718 10005KT 9999 SCT030 TX30/2716Z TN20/2708Z TEMPO 2700/2704 5000 SHRA BKN015",
        "SBGR": "TAF SBGR 261700Z 2618/2718 12015G28KT 9999 SCT020 PROB40 2700/2703 2000 TSRA BKN008CB", # Exemplo: Rajada > 20KT, PROB40 TSRA
        "SBGL": "TAF SBGL 261700Z 2618/2718 09008KT 9999 FEW020 BKN070 TX29/2715Z TN23/2706Z",
        "SBSP": "TAF SBSP 261700Z 2618/2718 28003KT 2000 BR OVC005 BECMG 2700/2702 0800 FG OVC001", # Exemplo: OVC005 e FG em BECMG
        "SBKP": "TAF SBKP 261700Z 2618/2718 20010KT 9999 SCT030 TEMPO 2620/2622 1000 WS BKN020CB", # Exemplo: WS
        "SBCT": "TAF SBCT 261700Z 2618/2718 27005KT 9999 OVC005 BECMG 2700/2703 0800 FG OVC001"
    }
    aviso_simulado = {
        "SBGR": "AVISO DE AERODROMO: SBGR VISIBILIDADE REDUZIDA DEVIDO A NEVOEIRO FORTE ESPERADO ENTRE 02Z E 05Z.",
        "SBBR": None,
        "SBGL": None,
        "SBSP": "AVISO DE AERODROMO: SBSP ALERTA DE FORTE CHUVA E POSSIVEL GRANIZO ENTRE 20Z E 22Z.",
        "SBKP": "AVISO DE AERODROMO: SBKP FORTE VENTO ACIMA DE 30KT ESPERADO ATE 23Z.", # Exemplo de vento em aviso
        "SBCT": "AVISO DE AERODROMO: SBCT CINZAS VULCANICAS (VA) PROVAVELMENTE AFETARÃO A AREA." # Exemplo de VA em aviso
    }

    if "METAR" in endpoint:
        mensagem = metar_simulado.get(aerodromo)
        # Formato de retorno que simula a API (poderia ser uma lista direta de strings também)
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
                # Expressão regular para encontrar OVC/BKN seguido de 001 a 005
                # OVC001, OVC002, OVC003, OVC004, OVC005
                # BKN001, BKN002, BKN003, BKN004, BKN005
                if re.search(f"{codigo}00[1-5]", mensagem_upper): 
                    alertas_encontrados.append(f"{codigo} (TETO BAIXO < 600FT)")
            # Lógica para "FG" (Nevoeiro) - verificar visibilidade < 1000m
            elif codigo == "FG":
                # Procura por FG e se a visibilidade está abaixo de 1000m (0800, 0500 etc.)
                # O formato de visibilidade no METAR/TAF é 4 dígitos para metros.
                # Ex: 0800 = 800m, 0500 = 500m
                vis_match = re.search(r'\s(\d{4})\s', mensagem_upper)
                if vis_match:
                    visibility_meters = int(vis_match.group(1))
                    if visibility_meters < 1000:
                        alertas_encontrados.append(f"{codigo} (NEVOEIRO < 1000M VIS)")
                else: # Se não encontrou visibilidade numérica, mas FG está presente
                     alertas_encontrados.append(f"{codigo} (NEVOEIRO)") # Alerta mesmo sem a visibilidade explícita
            # Lógica para "+RA" (Chuva Forte)
            elif codigo == "RA" and "+RA" in mensagem_upper:
                alertas_encontrados.append("CHUVA FORTE (+RA)")
            # Outros códigos que são diretos
            elif codigo in ["TS", "GR", "VA", "VCTS", "VCFG", "VV", "FU", "SHGR", "WS"]:
                alertas_encontrados.append(codigo)
        
        # Lógica para ventos acima de 20KT
        # Ex: 09025KT (vento de 25 nós), 27018G30KT (vento de 18 nós, rajada de 30 nós)
        # Regex para pegar o grupo de vento: DDDSS(GSS)KT
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
    # Reutiliza a lógica dos códigos severos, mas com prefixos de previsão.
    if "TAF" in mensagem_upper:
        for codigo in CODIGOS_SEVEROS:
            # Atenção: para OVC/BKN e FG em TAF, a lógica pode ser mais complexa.
            # Aqui, estamos buscando apenas a presença do código.
            # Se você quiser analisar visibilidade/teto baixo em TAF com regex, seria similar ao METAR.
            
            # Fenômenos com PROB30/40
            if f"PROB30 {codigo}" in mensagem_upper or f"PROB40 {codigo}" in mensagem_upper:
                 alertas_encontrados.append(f"PREVISÃO: PROB {codigo}")
            # Fenômenos com TEMPO ou BECMG
            if f"TEMPO {codigo}" in mensagem_upper:
                alertas_encontrados.append(f"PREVISÃO: TEMPO {codigo}")
            if f"BECMG {codigo}" in mensagem_upper:
                alertas_encontrados.append(f"PREVISÃO: BECMG {codigo}")
            
            # Regras específicas para TAF que são semelhantes ao METAR
            if codigo in ["OVC", "BKN"]:
                if re.search(f"{codigo}00[1-5]", mensagem_upper): # Teto baixo em TAF
                    alertas_encontrados.append(f"PREVISÃO: {codigo} (TETO BAIXO < 600FT)")
            if codigo == "FG":
                 if re.search(r'\s(\d{4})\s', mensagem_upper) and int(re.search(r'\s(\d{4})\s', mensagem_upper).group(1)) < 1000:
                    alertas_encontrados.append(f"PREVISÃO: {codigo} (NEVOEIRO < 1000M VIS)")
                 elif "FG" in mensagem_upper: # Alerta mesmo sem visibilidade explícita
                     alertas_encontrados.append(f"PREVISÃO: {codigo} (NEVOEIRO)")

        # Análise de vento em TAF (TEMPO/BECMG/PROB)
        # O grupo de vento em TAF pode estar em seções como TEMPO ou BECMG
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
    # Apenas verifica se é um aviso e pode procurar por palavras-chave dos fenômenos desejados
    if "AVISO DE AERODROMO" in mensagem_upper or "ADVISORY" in mensagem_upper:
        aviso_fenomenos = []
        for codigo in ["TS", "GR", "VA", "FG", "FU", "SHGR", "RA", "WS", "VENTO"]: # Vento é uma palavra-chave comum em avisos
            if codigo in mensagem_upper:
                if codigo == "RA" and "+RA" not in mensagem_upper: # Para avisos, 'RA' sozinho pode ser relevante
                    if "CHUVA FORTE" in mensagem_upper: # Procura por texto explicativo
                         aviso_fenomenos.append("CHUVA FORTE (AVISO)")
                elif codigo == "VENTO":
                    if "FORTE VENTO" in mensagem_upper or "RAJADA" in mensagem_upper:
                        aviso_fenomenos.append("VENTO FORTE/RAJADA (AVISO)")
                else:
                    aviso_fenomenos.append(f"{codigo} (AVISO)")
        
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
    # IMPORTANTE: Em cada nova execução do GitHub Actions (a cada 10 minutos), este set é zerado.
    # Ou seja, se a mesma mensagem de alerta persistir por várias execuções, ela será enviada novamente.
    # Para evitar isso, precisaríamos de um mecanismo de persistência externo (banco de dados, GitHub Gist etc.).
    mensagens_com_alerta_enviado_nesta_execucao = set()

    for aerodromo in AERODROMOS_INTERESSE:
        for tipo, endpoint_chave in endpoints_para_verificar.items():
            print(f"Verificando {tipo} para aeródromo {aerodromo}...")
            
            dados_brutos_api = obter_mensagens_redemet(endpoint_chave, aerodromo)

            if dados_brutos_api:
                # Descomente a linha abaixo para inspecionar a estrutura do JSON da API real
                # print(f"DEBUG - Dados brutos da API para {tipo} {aerodromo}: {json.dumps(dados_brutos_api, indent=2)}") 

                mensagens_texto = processar_mensagens_redemet(tipo, dados_brutos_api)

                if mensagens_texto:
                    for mensagem_individual in mensagens_texto:
                        # Criar um hash da mensagem para verificar se já foi processada
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
                            mensagens_com_alerta_enviado_nesta_execucao.add(hash_mensagem) # Adiciona à lista de processados
                        else:
                            print(f"  Mensagem {tipo} para {aerodromo} sem alertas severos: {mensagem_individual[:50]}...")
                else:
                    print(f"Nenhuma mensagem de texto extraída para {tipo} em {aerodromo}. Verifique 'processar_mensagens_redemet'.")
            else:
                print(f"Não foi possível obter dados para {tipo} em {aerodromo}.")

    print(f"[{datetime.datetime.now()}] Verificação de alerta concluída.")

if __name__ == "__main__":
    main()
