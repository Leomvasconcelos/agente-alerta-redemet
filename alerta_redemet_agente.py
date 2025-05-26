import os # Importamos a biblioteca 'os' para acessar as variáveis de ambiente (nossos Secrets)
import requests # Importamos a biblioteca 'requests' para fazer requisições HTTP (para o Telegram API)
import datetime # Para pegar a data e hora atual

# --- Configurações Importantes ---
# NUNCA coloque seus tokens diretamente aqui!
# Nós os pegamos de variáveis de ambiente (Secrets do GitHub) para segurança.

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Se alguma das variáveis de ambiente não for encontrada, avisamos e encerramos.
if not TELEGRAM_BOT_TOKEN:
    print("Erro: TELEGRAM_BOT_TOKEN não encontrado nas variáveis de ambiente.")
    exit() # Encerra o script se não houver o token

if not TELEGRAM_CHAT_ID:
    print("Erro: TELEGRAM_CHAT_ID não encontrado nas variáveis de ambiente.")
    exit() # Encerra o script se não houver o chat ID


def enviar_mensagem_telegram(mensagem):
    """
    Função que envia uma mensagem para o seu bot do Telegram.
    """
    print(f"Tentando enviar mensagem para o Telegram: {mensagem[:50]}...") # Log para ver o que está acontecendo

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown" # Isso permite usar negrito, itálico, etc. nas mensagens do Telegram
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status() # Lança um erro se a requisição não foi bem-sucedida (ex: 404, 500)
        print("Mensagem enviada para o Telegram com sucesso!")
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar mensagem para o Telegram: {e}")
        print(f"Resposta da API (se houver): {response.text if 'response' in locals() else 'N/A'}")


# --- A Lógica Principal do Nosso Agente (para Teste) ---
if __name__ == "__main__":
    print("Iniciando o script de teste de alerta Telegram...")

    agora = datetime.datetime.now()
    
    # Esta será a mensagem de teste que seu bot vai enviar
    mensagem_teste = f"""
*ALERTA DE TESTE DO SEU AGENTE DE IA!* 🤖
        
Olá, meteorologista!
Esta é uma mensagem de teste enviada pelo seu agente de IA.
Se você está lendo isso no Telegram, significa que a integração está funcionando perfeitamente! 🎉

*Hora do teste:* `{agora.strftime('%Y-%m-%d %H:%M:%S')}`
        
_Em breve, aqui virão os alertas da REDEMET!_
    """
    
    enviar_mensagem_telegram(mensagem_teste)
    print("Script de teste concluído.")
