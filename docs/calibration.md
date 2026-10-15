# Calibracao local de telas

O fluxo `calibrate` coleta capturas rotuladas, compara anchors e prepara uma proposta local para revisao. Ele nunca navega nem clica no jogo. `capture` fotografa apenas a tela que ja esta visivel; se a janela estiver minimizada, a rotina de screenshot pode restaura-la brevemente para capturar. Em `guide`, voce muda cada tela manualmente.

Instale o suporte opcional de imagens antes de usar capturas ou diagnosticos:

```powershell
python -m pip install -e ".[calibration]"
```

Por padrao, a sessao fica em `SLAYER_DATA_DIR/calibration/session` (normalmente `state/calibration/session`), que e ignorada pelo Git. Cada classe deve ter pelo menos duas capturas. Use `unknown` para telas que nao pertencem a nenhuma classe catalogada; amostras negativas ajudam a detectar falsos positivos.

Uma coleta guiada descreve cada estado. Mostre manualmente o menu principal fechado, o menu aberto com a engrenagem visivel, Settings na aba Attendance Reward, a presenca com Claim disponivel, a presenca apos coleta com Claim desabilitado e a presenca aberta por Settings depois de ja coletada. Pressione Enter para capturar, `s` para pular ou `q` para encerrar. Ao final, tambem pode capturar uma tela diferente como `unknown`, uma amostra negativa opcional:

```powershell
python -m league_bot calibrate guide --count 3 --interval 0.3
```

Tambem e possivel capturar uma tela ja preparada ou importar imagens existentes:

```powershell
python -m league_bot calibrate capture attendance_claim_ready --count 3
python -m league_bot calibrate add attendance_claimed .\captures\attendance-claimed-1.png .\captures\attendance-claimed-2.png
```

Os estados aceitos sao `main`, `menu_open`, `settings_open`, `attendance_claim_ready`, `attendance_claimed`, `attendance_claimed_settings` e `unknown`. `main_entry` e `attendance_open` sao rotulos derivados pelo reconhecimento e nao classes de captura.

Diagnostique uma imagem contra um estado para ver o tamanho da imagem e, por anchor, a posicao em pixels, a cor esperada, a cor observada, a diferenca e o resultado:

```powershell
python -m league_bot calibrate diagnose .\captures\attendance-ready.png --state attendance_claim_ready
```

Gere e valide uma proposta sem alterar nenhum perfil ativo:

```powershell
python -m league_bot calibrate propose --search-radius 12
python -m league_bot calibrate validate
```

A proposta gera `candidate.json` e um relatorio anotado `report.html` na sessao. Abra e revise o relatorio antes de ativar; ele tambem e salvo quando o candidato e rejeitado depois de ser criado. A validacao usa todas as amostras rotuladas da sessao e as referencias historicas sanitizadas que acompanham o pacote. Ela precisa aprovar antes da ativacao; uma validacao reprovada retorna codigo de saida diferente de zero. O raio de busca limita o deslocamento de cada anchor e nao corrige sozinho uma mudanca completa de layout, escala ou estrutura da tela.

Somente o comando explicito `apply` ativa uma proposta aprovada. O motor guarda a versao anterior para permitir reversao:

```powershell
python -m league_bot calibrate apply
python -m league_bot calibrate rollback
```

Capturas de tela podem conter informacao privada. O destino padrao fica dentro de `state/`, ignorado pelo Git; para outra localizacao, informe `--session CAMINHO` em cada comando da sessao. Os comandos `diagnose`, `propose` e `validate` trabalham apenas com arquivos locais e nao criam backend nem conectam ao jogo. `apply` e `rollback` escrevem somente no diretorio local de dados.

Depois que a versao atualizada do codigo estiver instalada, reinicie o bot uma vez para carregar o suporte de calibracao. A partir dai, `SlayerDailyGame._run_steps` recarrega o perfil ativo em cada operacao; novas ativacoes sao usadas na proxima operacao sem reiniciar o bot.
