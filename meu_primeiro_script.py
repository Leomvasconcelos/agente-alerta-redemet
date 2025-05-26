import datetime

# Pegamos a data e hora atual
agora = datetime.datetime.now()

# Criamos uma mensagem simples
mensagem = f"Olá, mundo! Meu agente de IA está funcionando. Hora atual: {agora}"

# Imprimimos a mensagem (isso vai aparecer nos logs do GitHub Actions)
print(mensagem)

# Se você quiser simular um erro para ver o que acontece (opcional)
# raise Exception("Simulando um erro para teste!")
