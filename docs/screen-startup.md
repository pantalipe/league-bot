# Inicio guiado pelo reconhecimento de tela

O executor tem uma base de reconhecimento por cores em varios pontos. Cada tela
precisa de pelo menos dois pontos calibrados; todos devem corresponder. Isso ainda
nao e OCR nem busca de botoes por imagem. A gravacao de macros continua disponivel.

O novo fluxo fica preparado antes de substituir `start_game`: faltam referencias
das telas de entrada, confirmacao de save e principal. O modelo
[start-game-recognized.template.json](start-game-recognized.template.json) contem
anchors vazios de proposito e falha na validacao antes de abrir o jogo. Nao possui
coordenadas de reconhecimento inventadas. A macro antiga permanece selecionada
ate a calibracao; seus cliques e esperas fixas ainda existem.

## Funcionamento

`prepare_window` restaura uma janela minimizada sem ativa-la e a deixa atras das
outras. `screen_flow` observa as telas conhecidas ate reconhecer a tela terminal
em duas capturas consecutivas (configuravel por `stable_frames`, minimo 2).
Os cliques dessa acao sempre usam segundo plano, mesmo quando macros antigas
estao configuradas para cliques reais.

O fluxo clica uma vez em cada tela reconhecida e aguarda uma transicao. Se ela
continuar visivel, nao repete o clique. Frames desconhecidos de carregamento ou
animacao sao observados ate o timeout, sem clicar. Correspondencias ambiguas
interrompem imediatamente. `max_clicks` limita o total por tela; o modelo usa 1.
Uma tela reconhecida sem `click` apenas aguarda.

O aviso de save e opcional no percurso, mas sua politica e sempre confirmar
quando reconhecido. Nao e preciso reproduzi-lo no jogo agora: testes simulados
cobrem o percurso com e sem esse aviso. Outros avisos devem receber detectores
e cliques especificos, calibrados antes de serem acrescentados.

Erros preservam a ultima captura disponivel em `SLAYER_DATA_DIR/diagnostics`.
O caminho aparece na mensagem de erro. Captura ausente nao cria imagem; falha ao
gravar a evidencia nao oculta o erro original. O cancelamento interrompe o fluxo.

## Calibracao posterior

1. Obter capturas da entrada e principal numa abertura acompanhada. Para o save,
   abrir no celular e depois no PC quando for conveniente, conforme o fluxo do jogo.
2. Escolher pontos estaveis que distingam cada tela, inclusive de menus e avisos.
   Um botao laranja sozinho nao basta para identificar a confirmacao de save.
3. Preencher os `anchors` e ajustar os cliques no modelo. `x` e `y` dos anchors
   sao fracoes de 0 a 1: pixels `round(x * (largura - 1))` e
   `round(y * (altura - 1))`. Cliques usam pixels, `"center"` ou `"NN%"`.
   `color` e RGB; `tolerance` padrao 20 e `radius` padrao 0. Radius calcula a media
   da regiao, portanto calibrar a media, nao a cor de um pixel isolado.

   Exemplo de formato de anchor, com valores apenas ilustrativos:

   ```json
   {"x": 0.25, "y": 0.5, "color": [230, 230, 230], "tolerance": 15, "radius": 2}
   ```

4. Revisar o perfil contra capturas reais e carregamentos. Os pontos precisam
   corresponder ao mesmo layout usado na abertura; percentuais nao corrigem
   mudancas de layout. `move_resize` permanece depois da confirmacao final.
5. Salvar a versao calibrada como `macros/local/start_game_recognized.json` e
   selecionar `SLAYER_START_MACRO=start_game_recognized`. Reiniciar o bot.
6. Fazer uma abertura real acompanhada, verificando foco, cursor, transicoes e
   conclusao. O launcher do Google Play Games pode ativar janelas por conta propria;
   a automacao nao consegue prometer ausencia de foco durante a abertura completa.

## Cliques sem foco

O padrao de configuracao passou a ser `SLAYER_FOREGROUND_INPUT=0`. Um valor `1`
explicito no `.env` continua selecionando cliques reais para macros antigas.
Nenhum `.env` existente e alterado automaticamente.

O backend encontra a janela interna `CROSVM_1` em cada clique e converte as
coordenadas para ela. Se o destino nao existir, houver mais de um, a coordenada
estiver fora da area ou o envio falhar, o bot para. Nao ha fallback para o mouse
real. O retorno do envio nao comprova o resultado no jogo; `screen_flow` exige
a mudanca de tela e a observacao final.

O modo real confere foco e o ponto do clique antes de pressionar o botao, mas
essas verificacoes nao tornam seguro compartilhar o mouse durante a automacao.
Capturas de janela minimizada usam restauracao e minimizacao sem ativacao.
