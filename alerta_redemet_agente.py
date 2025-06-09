name: Agente Inteligência Artificial de Alerta Meteorológico SBTA

on:
  schedule:
    # Executa a cada 5 minutos.
    - cron: '*/5 * * * *'
  workflow_dispatch: # Permite que você execute este workflow manualmente

jobs:
  run_alert_agent:
    runs-on: ubuntu-latest
    
    # Adiciona permissões de escrita para o token do job
    permissions:
      contents: write
      
    steps:
      - name: Checar o código do repositório
        uses: actions/checkout@v4
        with:
          # É necessário um token com permissões para fazer push
          token: ${{ secrets.ACTIONS_PAT }}

      - name: Configurar Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Instalar dependências
        run: |
          python -m pip install --upgrade pip
          pip install requests pytz

      - name: Executar o script de alerta
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          REDEMET_API_KEY: ${{ secrets.REDEMET_API_KEY }}
        run: python alerta_redemet_agente.py

      # --- NOVO PASSO PARA SALVAR O CACHE NO REPOSITÓRIO ---
      - name: Fazer Commit e Push do cache atualizado
        run: |
          git config --global user.name 'GitHub Actions Bot'
          git config --global user.email 'github-actions-bot@users.noreply.github.com'
          # Adiciona o arquivo de cache ao stage
          git add persistent_alert_cache.json
          # Faz o commit apenas se houver mudanças no arquivo
          if ! git diff --staged --quiet; then
            git commit -m "Chore: Atualiza cache de alertas"
            git push
            echo "Cache de alertas atualizado e enviado para o repositório."
          else
            echo "Nenhuma alteração no cache. Nenhum commit necessário."
          fi
