# Daily Slayer da guild

O pacote `league_bot.slayer` oferece uma seleção padrão de 20 macros para Slayer Legend. A daily é executada somente quando alguém pede; o pacote não agenda execuções. Os nomes das macros incluídas estão em `league_bot/slayer/macros/` e a seleção e suas dependências são descritas em `league_bot/slayer/plan.py`.

## O que a execução faz

1. Confere a seleção, dependências e o estado salvo. Verifica presença primeiro e, se necessário, inicia o jogo. Avisos de ativação dos bônus de scrolls e montaria são enviados antes das respectivas macros.
2. Black Orb reconhece a coleta gratuita e as duas coletas com vídeo pelos contadores e botões observados. Cada tentativa usa um único clique e só registra uma coleta após confirmar o incremento do contador. O intervalo mínimo entre coletas confirmadas é de cinco minutos; um temporizador ativo deixa a coleta pendente para a próxima daily. O estado que oferece penas após as duas coletas com vídeo encerra a tarefa sem compra. WPACS executa três vezes, com intervalo mínimo de dez minutos. Essas coletas começam cedo para que os intervalos avancem durante outras tarefas. A coleta de diárias final fica para depois de suas dependências.
3. As demais macros seguem os estágios e dependências do plano. O fluxo visual do Cubo da Melhora usa até três entradas gratuitas; não clica em uma entrada que exija penas.
4. O pet tem uma limpeza gratuita e quatro pagas: 100, 200, 300 e 400 diamantes (1.000 no total). Antes de cada limpeza paga, exige duas leituras iguais do saldo e orçamento para **todas** as limpezas restantes. Se faltar saldo, preserva o progresso, avisa e continua a daily. Se a tela, o custo ou o saldo forem desconhecidos, interrompe a daily sem novo gasto. O contador visual seguinte confirma cada limpeza.
5. O progresso de tarefas é salvo em disco no diretório `SLAYER_DATA_DIR` da instalação e é carregado novamente nas próximas consultas/execuções. O ciclo diário troca às 02:00 no fuso UTC−03:00. Essa troca é lazy: ocorre quando a aplicação lê ou atualiza o estado, sem timer ou ação de jogo em segundo plano.

Na loja Goods, cada oferta gratuita tem seu próprio contador de até dez anúncios.
O fluxo lê os dois contadores, clica uma vez no anúncio gratuito reconhecido e
exige incremento de um somente na oferta escolhida. Não usa os botões com preço
em reais. Contador desconhecido ou anúncio indisponível deixa a tarefa pendente.

O refinamento de habilidade demora dez minutos. A coleta do refinamento fica
depois das missões e das esperas de coletas repetidas; se ainda estiver dentro
desse intervalo, fica pendente. A tela de refinamento e a aba Skill são
reconhecidas para permitir a recuperação por seus controles de navegação.

A entrada da guilda reconhece as abas fixas do mapa de aventura antes de
selecionar Guild. O pet e a loja da guilda usam essa mesma navegação, confirmando
seus painéis antes das ações de coleta.

As entradas de WPACS e das missões de Dungeon selecionam explicitamente sua
subaba antes de executar a gravação conhecida. A seleção anterior fica salva no
jogo; abrir Shop ou Adventure não garante que Summon ou Dungeon esteja aberto.
Entradas personalizadas com outro padrão permanecem preservadas.

`/cancel` cancela a macro atual e interrompe as esperas da daily. Uma nova `/daily` retoma os contadores do mesmo ciclo. `python -m league_bot daily status` mostra o estado; `python -m league_bot daily set "Caverna" 1 3` registra uma missão pelo nome. No Telegram, use `/dailystatus` e `/dailyset "Caverna" 1 3`. Presença, espadas, acessórios e habilidades também aceitam aliases. A conclusão de uma gravação registra execução; somente os fluxos visuais de presença, cubo e pet conferem seus estados específicos no jogo.

As coletas incluem collect_familiar e mailbox. O Mailbox vazio exige duas observações iguais e é fechado sem acionar coleta. Quando há recompensas, mantém os passos gravados e não repete os cliques de claim.

O plano embaralha coletas, missões e ativações dentro de seus grupos, preservando presença primeiro, bônus antes das missões, refinamento antes de sua coleta e quests concluídas por último. O host pode configurar uma espera aleatória adicional antes de cada clique; o panda-home-bot usa 0,15 a 0,65 segundo, com cancelamento durante a espera. As esperas visuais e os intervalos mínimos de anúncios continuam obrigatórios.

## Escolha e instalação

Por padrão, a seleção inclui as 20 macros da guild. `daily add/remove` e `/dailyadd` e `/dailyremove` alteram essa seleção; `daily set` e `/dailyset` atualizam os contadores. A seleção fica em `daily.json` e o acompanhamento em `daily-status.json`, sob `SLAYER_DATA_DIR`. O padrão é `state/` no checkout; na distribuição instalada, é `~/.league-bot/state`. Cada instalação mantém seu próprio estado, sem executar a daily automaticamente às 02:00.

Para usar a mesma lógica em um bot Telegram existente, instale o projeto no ambiente Python do host e integre `SlayerDailyGame` e o factory da daily Slayer ao handler do host. O adaptador fornece seu armazenamento de estado opcional e qualquer política de posicionamento da janela; autorização, token, envio de mensagens e thread de execução permanecem responsabilidade do host. Consulte [a integração Telegram](telegram-integration.md) para o exemplo e a API pública do pacote.

Instale a distribuição em cada PC Windows interativo que controla o jogo. No checkout do projeto:

```powershell
python -m pip install -e .
python -m league_bot windows
python -m league_bot check
python -m league_bot daily status
python -m league_bot daily set --help
python -m pip install -e ".[test]"
python -m unittest discover -s tests -t .
```

O núcleo de runtime não exige Pillow nem outras dependências externas. Pillow é usado somente pelas ferramentas de calibração e por verificações que comparam imagens. O comando de testes não controla uma janela real; a validação de uma gravação exige o jogo aberto no PC de destino.

## Gravações e validação

Uma falha visual interrompe aquela tarefa e salva o diagnóstico. A daily tenta
voltar à tela principal usando somente controles de navegação em telas
reconhecidas, incluindo Equipment e os painéis Black Orb. Se confirmar a
recuperação, continua as tarefas independentes e informa as pendências no
resultado final. Se não reconhecer uma saída segura, encerra a daily.
Dependências pendentes impedem suas tarefas dependentes. Cancelamento nunca
aciona recuperação. Tentativas adiadas não incrementam contadores nem mudam
o horário da última coleta confirmada.

A retomada reconhece o painel Equipment (armas ou acessórios) e fecha-o pela
própria aba, confirmando a tela principal antes de verificar a presença.
Na gravação conhecida de `colheita_arma_alma`, a abertura de Equipment exige
confirmação visual. Um clique de navegação sem efeito pode ser repetido uma
vez, após três segundos e duas observações da tela principal. Telas
desconhecidas interrompem o fluxo; os cliques e condições de coleta da
gravação permanecem preservados. Essa repetição é exclusiva da navegação,
e os demais fluxos mantêm o comportamento de não repetir um clique sem
transição de tela.

As macros são gravações de cliques, esperas e condições visuais. Uma gravação precisa ser validada ao vivo antes de entrar na seleção executada: confira a tela inicial, as telas intermediárias, a tela final, os tempos de carregamento, o layout da janela, o idioma e os custos em diamantes. Teste uma macro por vez no PC de destino e use `/cancel` ou o cancelamento de macro disponível no host se o fluxo sair do esperado.

Coordenadas em porcentagem não tornam uma gravação universal. Resolução, escala, idioma, avisos e progresso da conta variam. Calibre novamente no destino e não compartilhe screenshots de gravação ou arquivos de estado pessoal. A existência de uma macro no catálogo ou de testes com frames de fixture não significa que ela foi validada ao vivo nem publicada como segura para toda a guild.

## Daily customizada legada

Se `SLAYER_MACROS_DIR` aponta para uma biblioteca personalizada que não contém o catálogo completo, a CLI mantém a lista genérica e seu executor em ordem aleatória. Para o fluxo da guild, mantenha o diretório padrão ou disponibilize as 20 macros nessa biblioteca. `league_bot.daily.build_runner` continua como API genérica; o fluxo Slayer usa `league_bot.slayer.create_daily`.
