import os
import requests
import datetime

# --- Configurações Importantes ---
# NUNCA coloque seus tokens diretamente aqui!
# Nós os pegamos de variáveis de ambiente (Secrets do GitHub) para segurança.

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# REDEMET_API_KEY ainda não é usado neste script, mas o Secret já está lá no GitHub.

# Se alguma das variáveis de ambiente do Telegram não for encontrada, avisamos e encerramos.
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
    print(f"Tentando enviar mensagem para o Telegram: {mensagem[:100]}...") # Log para ver o que está acontecendo

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown" # Isso permite usar negrito, itálico, etc. nas mensagens do Telegram
    }
    
    try:
        response = requests.post(url, json=payload, timeout=15) # Adicionado timeout
        response.raise_for_status() # Lança um erro se a requisição não foi bem-sucedida (ex: 404, 500)
        print("Mensagem enviada para o Telegram com sucesso!")
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar mensagem para o Telegram: {e}")
        print(f"Resposta da API (se houver): {response.text if 'response' in locals() else 'N/A'}")


# --- A Lógica Principal do Nosso Agente (para Teste) ---
# Esta função 'main' será executada a cada 10 minutos pelo GitHub Actions.
if __name__ == "__main__":
    print(f"[{datetime.datetime.now()}] Iniciando o script de teste de alerta Telegram agendado...")

    agora = datetime.datetime.now()
    
    # Esta será a mensagem de teste que seu bot vai enviar a cada 10 minutos
    mensagem_teste = f"""
*ALERTA DE TESTE AGENDADO DO SEU AGENTE DE IA!* 🤖
        
Olá, meteorologista!
Esta é uma mensagem de teste AGENDADA enviada pelo seu agente de IA.
Se você está lendo isso no Telegram a cada 10 minutos, significa que o agendamento está funcionando! 🎉

*Hora do teste (UTC):* `{agora.strftime('%Y-%m-%d %H:%M:%S')}`
        
_Aguardando a liberação da API da REDEMET para os alertas reais!_
    """
    
    enviar_mensagem_telegram(mensagem_teste)
    print(f"[{datetime.datetime.now()}] Script de teste concluído.")
