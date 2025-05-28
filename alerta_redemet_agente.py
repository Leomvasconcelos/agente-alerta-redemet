import os
import requests
import datetime
import json
import re
import time 

# --- Configurações Importantes ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
REDEMET_API_KEY = os.getenv("REDEMET_API_KEY")
GIST_TOKEN = os.getenv("GIST_TOKEN") 
GIST_ID = os.getenv("GIST_ID")       

# Verifica se os tokens essenciais estão configurados
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("Erro: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não encontrados nas variáveis de ambiente.")
    print("Certifique-se de configurar TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID como GitHub Secrets.")
    exit()

if not GIST_TOKEN or not GIST_ID:
    print("Erro: GIST_TOKEN ou GIST_ID não encontrados nas variáveis de ambiente.")
    print("Certifique-se de configurar GIST_TOKEN e GIST_ID como GitHub Secrets.")
    exit()

# --- Sua Lista de Códigos de Tempo Severo e Critérios ---
# Mapeamento de códigos METAR/TAF para descrições amigáveis
CODIGOS_METAR_TAF_MAP = {
    "TS": "Trovoada",
    "GR": "Granizo",
    "VA": "Cinzas Vulcânicas",
    "VCTS": "Trovoada na Vizinhança",
    "VCFG": "Nevoeiro na Vizinhança",
    "VV": "Céu Obscurecido (Visibilidade Vertical)",
    "FU": "Fumaça",
    "SHGR": "Pancada de Granizo",
    "WS": "Tesoura de Vento (Wind Shear)",
    # "RA" e "FG" serão tratados separadamente pela visibilidade/intensidade
    # "OVC", "BKN" serão tratados separadamente pela altura
    "CB": "Cumulunimbus", # Adicionado para mapeamento
}

# Lista de aeródromos a serem monitorados (APENAS SBTA)
AERODROMOS_INTERESSE = ["SBTA"] 

# --- Funções de Comunicação (Telegram e Gist) e Análise ---

def enviar_mensagem_telegram(mensagem):
    """
    Função que envia uma mensagem para o seu bot do Telegram.
    """
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


def ler_alertas_enviados_do_gist():
    """
    Lê a lista de hashes de alertas já enviados do GitHub Gist.
    Retorna um set com os hashes lidos.
    """
    gist_url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        "Authorization": f"token {GIST_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        response = requests.get(gist_url, headers=headers, timeout=10)
        response.raise_for_status()
        gist_data = response.json()
        
        file_content = gist_data['files']['alertas_enviados.txt']['content']
        
        alertas_lidos = set()
        for line in file_content.splitlines():
            stripped_line = line.strip()
            if stripped_line and not stripped_line.startswith('#'): 
                try:
                    alertas_lidos.add(int(stripped_line))
                except ValueError:
                    print(f"Aviso: Ignorando linha inválida no Gist (não é um número): '{stripped_line[:50]}...'")

        print(f"Alertas lidos do Gist: {len(alertas_lidos)} itens.")
        return alertas_lidos
    except requests.exceptions.RequestException as e:
        print(f"Erro ao ler Gist {GIST_ID}: {e}")
        return set()
    except KeyError:
        print(f"Arquivo 'alertas_enviados.txt' não encontrado no Gist {GIST_ID} ou Gist vazio. Criando um novo.")
        return set()


def atualizar_alertas_enviados_no_gist(novos_alertas_hashes):
    """
    Atualiza o GitHub Gist com a nova lista de hashes de alertas.
    """
    gist_url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        "Authorization": f"token {GIST_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    alertas_existentes = ler_alertas_enviados_do_gist()
    todos_alertas = alertas_existentes.union(novos_alertas_hashes)

    content_to_write = "\n".join(str(h) for h in todos_alertas)

    payload = {
        "description": "IDs de Alertas REDEMET (Gerado por Agente GitHub Actions)",
        "public": True,
        "files": {
            "alertas_enviados.txt": {
                "content": content_to_write
            }
        }
    }

    try:
        response = requests.patch(gist_url, headers=headers, json=payload, timeout=10) 
        response.raise_for_status()
        print(f"Gist {GIST_ID} atualizado com {len(todos_alertas)} alertas.")
    except requests.exceptions.RequestException as e:
        print(f"Erro ao atualizar Gist {GIST_ID}: {e}")
        if 'response' in locals() and hasattr(response, 'text'):
            print(f"Resposta da API do GitHub Gist: {response.text}")


# --- Funções de Obtenção de Mensagens (Real ou Simulada) ---

def obter_mensagens_redemet_real(endpoint, aerodromo=None):
    """
    Esta função fará a chamada REAL para a API da REDEMET.
    VOCÊ PRECISA AJUSTAR ESTA FUNÇÃO CONFORME A DOCUMENTAÇÃO DA REDEMET.
    """
    if not REDEMET_API_KEY:
        print("REDEMET_API_KEY não configurado. Não é possível chamar a API real.")
        return None
    
    URL_BASE = "https://api.redemet.aer.mil.br/v1" 
    
    if "METAR" in endpoint or "SPECI" in endpoint: # SPECI é tratado como METAR
        url_completa = f"{URL_BASE}/metar/latest"
    elif "TAF" in endpoint:
        url_completa = f"{URL_BASE}/taf/forecast"
    elif "AVISO" in endpoint:
         url_completa = f"{URL_BASE}/avisos_aerodromo" 
    else:
        print(f"Endpoint desconhecido: {endpoint}")
        return None

    headers = {
        "x-api-key": REDEMET_API_KEY 
    }
    params = {
        "localidade": aerodromo 
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
    
    # EXEMPLOS DE MENSAGENS PARA TESTE SBTA:
    metar_simulado = {
        "SBTA": "METAR SBTA 222200Z 17025KT 9999 TS SCT030 FEW040CB BKN100 21/17 Q1019=" # Exemplo METAR com TS, CB, Vento
    }
    speci_simulado = {
        "SBTA": "SPECI SBTA 222230Z 27030G45KT 9999 VCTS SCT030 FEW020CB BKN100 21/17 Q1019=" # Exemplo SPECI com VCTS, CB, Vento+Rajada
    }
    taf_simulado = {
        "SBTA": "TAF SBTA 261700Z 2618/2718 12015G28KT 9999 SCT020 PROB40 2700/2703 2000 TSRA BKN008CB", # Rajada > 20KT, PROB40 TSRA
    }
    # Exemplo de Aviso de Aeródromo com o formato que você forneceu:
    aviso_simulado = {
        "SBTA": "AVISO DE AERODROMO: SBGL SBSJ/SBTA AD WRNG 1 VALID 222240/230210 TS SFC WSPD 15KT MAX 25 FCST NC=", # Exemplo AVISO
    }

    if "METAR" in endpoint: # Inclui SPECI
        mensagem = metar_simulado.get(aerodromo)
        return {"data": [{"mensagem": mensagem}]} if mensagem else {"data": []}
    elif "SPECI" in endpoint: # Para simular SPECI separadamente, se precisar
        mensagem = speci_simulado.get(aerodromo)
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


def processar_mensagens_redemet(tipo_mensagem_solicitada, dados_api):
    """
    Processa os dados retornados pela API (real ou simulada) e extrai as mensagens de texto.
    Atribui o tipo de mensagem correto (METAR, SPECI, TAF, AVISO).
    """
    mensagens_encontradas = []

    if isinstance(dados_api, dict) and 'data' in dados_api and isinstance(dados_api['data'], list):
        for item in dados_api['data']:
            if isinstance(item, dict) and 'mensagem' in item:
                msg_texto = item['mensagem']
                # Detecta SPECI pelo texto da mensagem, se for o caso
                if "SPECI" in msg_texto.upper() and tipo_mensagem_solicitada == "METAR": # Se foi solicitado METAR, mas é SPECI
                    mensagens_encontradas.append({"tipo": "SPECI", "texto": msg_texto})
                else:
                    mensagens_encontradas.append({"tipo": tipo_mensagem_solicitada, "texto": msg_texto})
    return mensagens_encontradas


def analisar_mensagem_meteorologica(mensagem_texto, tipo_mensagem):
    """
    Função para o robô 'ler' a mensagem e procurar por códigos severos e contexto.
    Retorna uma lista dos alertas de texto encontrados, com base nos seus critérios.
    """
    alertas_encontrados = []
    mensagem_upper = mensagem_texto.upper()

    # --- Análise de Fenômenos Específicos (METAR/TAF/Aviso) ---
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
                elif "FG" in mensagem_upper: # Se FG está presente, mas visibilidade não foi especificada ou é maior.
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
            else: # Para códigos como TS, GR, VA, VCTS, VCFG, VV, FU, SHGR, WS
                alertas_encontrados.append(descricao)
        
    # --- Lógica para ventos acima de 20KT e rajadas acima de 20KT ---
    wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
    if wind_match:
        sustained_wind_str = wind_match.group(2)
        gust_wind_str = wind_match.group(4) 

        sustained_wind = int(sustained_wind_str)
        
        wind_desc = []
        if sustained_wind > 20:
            wind_desc.append(f"Vento Médio de {sustained_wind}KT")
        
        if gust_wind_str:
            gust_wind = int(gust_wind_str)
            if gust_wind > 20:
                wind_desc.append(f"Rajadas de {gust_wind}KT")

        if wind_desc: # Se houve vento ou rajada acima do limite
            alertas_encontrados.append(" e ".join(wind_desc))

    # Lógica para TAF (previsão) - procurar por fenômenos e condições em TEMPO/BECMG/PROB30/40
    if "TAF" in tipo_mensagem.upper():
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

        # Ventos e rajadas em TAF
        wind_groups_in_taf = re.findall(r'(TEMPO|BECMG|PROB\d{2})\s.*?(VRB|\d{3})(\d{2,3})(G(\d{2,3}))?KT', mensagem_upper)
        for group in wind_groups_in_taf:
            prefix = group[0]
            sustained_wind_str = group[2]
            gust_wind_str = group[4] 
            
            sustained_wind = int(sustained_wind_str)
            
            wind_desc_taf = []
            if sustained_wind > 20:
                wind_desc_taf.append(f"Vento Médio de {sustained_wind}KT")
            
            if gust_wind_str:
                gust_wind = int(gust_wind_str)
                if gust_wind > 20:
                    wind_desc_taf.append(f"Rajadas de {gust_wind}KT")

            if wind_desc_taf:
                alertas_encontrados.append(f"PREVISÃO {prefix}: {' e '.join(wind_desc_taf)}")


    # Lógica para Avisos de Aeródromo (geralmente já são alertas por natureza)
    if "AVISO" in tipo_mensagem.upper():
        aviso_fenomenos_desc = []
        # Exemplo: TS SFC WSPD 15KT MAX 25 FCST NC=
        
        # Detectar TS (Trovoada)
        if "TS" in mensagem_upper:
            aviso_fenomenos_desc.append("Trovoada")

        # Detectar Vento de Superfície e Rajada (SFC WSPD 15KT MAX 25)
        wind_warning_match = re.search(r'SFC WSPD (\d+KT)(?: MAX (\d+))?', mensagem_upper)
        if wind_warning_match:
            min_wind = wind_warning_match.group(1)
            max_wind = wind_warning_match.group(2)
            if max_wind:
                aviso_fenomenos_desc.append(f"Vento de Superfície entre {min_wind} e {max_wind}KT")
            else:
                aviso_fenomenos_desc.append(f"Vento de Superfície de {min_wind}")

        # Outros termos específicos de Avisos, se houver
        for palavra_chave in ["GRANIZO", "CINZAS VULCÂNICAS", "NEVOEIRO", "FUMAÇA", 
                              "VISIBILIDADE REDUZIDA", "CHUVA FORTE", "TESOURA DE VENTO"]:
            if palavra_chave in mensagem_upper: # Verifica se a descrição já existe no aviso
                aviso_fenomenos_desc.append(palavra_chave)
        
        # Mapear códigos diretos que podem aparecer em avisos
        for codigo_icao, descricao in CODIGOS_METAR_TAF_MAP.items():
            if codigo_icao in mensagem_upper and codigo_icao not in ["TS", "FG", "RA", "OVC", "BKN", "CB"]: # Evitar duplicidade ou casos já tratados
                if descricao not in aviso_fenomenos_desc: # Garante que não adiciona descrições repetidas
                    aviso_fenomenos_desc.append(descricao)


        if aviso_fenomenos_desc:
            alertas_encontrados.append(", ".join(list(set(aviso_fenomenos_desc)))) # Remove duplicatas antes de juntar
        else: 
            alertas_encontrados.append("Conteúdo não mapeado") # Caso o aviso exista mas não detecte nada específico


    return list(set(alertas_encontrados)) # Retorna a lista de alertas únicos


# Função para extrair dados para o hash de Aviso de Aeródromo
def extrair_id_aviso(mensagem_texto, aerodromo_monitorado):
    """
    Extrai o ID único de um Aviso de Aeródromo para persistência.
    Formato esperado: SBGL SBSJ/SBTA AD WRNG 1 VALID 222240/230210 ...
    Retorna uma string única (aeródromo_alvo-tipo_aviso-numero_aviso-validade) ou None.
    """
    mensagem_upper = mensagem_texto.upper()
    
    # Regex para pegar: tipo de aviso (AD WRNG), número e validade
    # Usamos re.search para encontrar a primeira ocorrência
    match = re.search(r'(AD WRNG\s*(\d+)\s*VALID\s*(\d{6}/\d{6}))', mensagem_upper)
    
    if match:
        # A parte capturada da regex já inclui "AD WRNG 1 VALID 222240/230210"
        chave_aviso_completa = match.group(1)
        
        # Combina aeródromo que estamos monitorando e a chave do aviso para um ID único
        # Isso garante que se o mesmo aviso for feito para outro aeródromo, será um ID diferente
        unique_id = f"{aerodromo_monitorado}-{chave_aviso_completa}"
        return unique_id
    return None


# --- Lógica Principal do Agente ---
def main():
    print(f"[{datetime.datetime.now()}] Iniciando o agente de alerta meteorológico da REDEMET...")

    # Endpoints para verificar, incluindo SPECI (que será tratado como METAR pela API real)
    endpoints_para_verificar = {
        "METAR": "METAR", # Este endpoint irá retornar METAR ou SPECI
        "TAF": "TAF",
        "AVISO": "AVISO"
    }

    alertas_enviados_historico = ler_alertas_enviados_do_gist()
    novos_alertas_nesta_execucao = set()

    for aerodromo in AERODROMOS_INTERESSE: 
        for tipo_solicitado_api, endpoint_chave in endpoints_para_verificar.items():
            print(f"Verificando {tipo_solicitado_api} para aeródromo {aerodromo}...")
            
            dados_brutos_api = obter_mensagens_redemet(endpoint_chave, aerodromo)

            if dados_brutos_api:
                mensagens_processadas = processar_mensagens_redemet(tipo_solicitado_api, dados_brutos_api)

                if mensagens_processadas:
                    for item_mensagem in mensagens_processadas:
                        mensagem_tipo_real = item_mensagem["tipo"] # Pode ser METAR ou SPECI (se foi solicitado METAR)
                        mensagem_texto = item_mensagem["texto"]

                        hash_para_persistir = None
                        # --- Lógica de Hash Inteligente para persistência ---
                        if "AVISO" in mensagem_tipo_real.upper():
                            unique_aviso_id = extrair_id_aviso(mensagem_texto, aerodromo)
                            if unique_aviso_id:
                                hash_para_persistir = hash(unique_aviso_id)
                                print(f"  Aviso ID para persistência: {unique_aviso_id}")
                            else:
                                hash_para_persistir = hash(mensagem_texto)
                                print(f"  Aviso sem ID detectável, usando hash da mensagem completa.")
                        elif "METAR" in mensagem_tipo_real.upper() or "SPECI" in mensagem_tipo_real.upper() or "TAF" in mensagem_tipo_real.upper():
                            # Para METAR/SPECI/TAF, o hash é da mensagem completa.
                            # Isso significa que cada nova emissão (com nova hora) gerará um novo alerta se houver tempo severo.
                            hash_para_persistir = hash(mensagem_texto)


                        if hash_para_persistir is None:
                            print(f"  Erro: Não foi possível gerar hash para persistência da mensagem {mensagem_tipo_real}: {mensagem_texto[:50]}...")
                            continue # Pula esta mensagem se não conseguiu gerar o hash

                        # Verifica se o alerta já foi enviado anteriormente (usando o histórico do Gist)
                        if hash_para_persistir in alertas_enviados_historico:
                            print(f"  Mensagem {mensagem_tipo_real} para {aerodromo} já alertada anteriormente: {mensagem_texto[:50]}...")
                            continue 

                        alertas = analisar_mensagem_meteorologica(mensagem_texto, mensagem_tipo_real)

                        if alertas:
                            # --- Formatação da Mensagem de Alerta Aprimorada ---
                            condicoes_texto_label = "Condições Previstas" 
                            if "METAR" in mensagem_tipo_real or "SPECI" in mensagem_tipo_real:
                                condicoes_texto_label = "Condições Reportada"
                            
                            alerta_final = f"🚨 *NOVO ALERTAMET {aerodromo.upper()}!* 🚨\n\n"
                            alerta_final += f"**Aeródromo:** {aerodromo.upper()} - **Tipo:** {mensagem_tipo_real.upper()}\n"
                            alerta_final += f"**{condicoes_texto_label}:** {', '.join(alertas)}\n\n"
                            alerta_final += f"**Mensagem Original:**\n```\n{mensagem_texto}\n```\n\n"
                            alerta_final += f"_(Hora do Agente: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC)_"
                            
                            print("\n" + alerta_final + "\n")
                            enviar_mensagem_telegram(alerta_final)
                            
                            novos_alertas_nesta_execucao.add(hash_para_persistir)
                            
                            time.sleep(1) 
                        else:
                            print(f"  Mensagem {mensagem_tipo_real} para {aerodromo} sem alertas severos: {mensagem_texto[:50]}...")
                else:
                    print(f"Nenhuma mensagem de texto extraída para {tipo_solicitado_api} em {aerodromo}. Verifique 'processar_mensagens_redemet'.")
            else:
                print(f"Não foi possível obter dados para {tipo_solicitado_api} em {aerodromo}.")

    if novos_alertas_nesta_execucao:
        atualizar_alertas_enviados_no_gist(novos_alertas_nesta_execucao)
    else:
        print("Nenhum novo alerta para registrar no Gist nesta execução.")

    print(f"[{datetime.datetime.now()}] Verificação de alerta concluída.")

if __name__ == "__main__":
    main()
