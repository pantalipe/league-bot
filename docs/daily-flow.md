# Daily Slayer da guild

O pacote `league_bot.slayer` oferece uma seleção padrão de 18 macros para Slayer Legend. A daily é executada somente quando alguém pede; o pacote não agenda execuções. Os nomes das macros incluídas estão em `league_bot/slayer/macros/` e a seleção e suas dependências são descritas em `league_bot/slayer/plan.py`.

## O que a execução faz

1. Confere a seleção, dependências e o estado salvo. Verifica presença primeiro e, se necessário, inicia o jogo. Avisos de ativação dos bônus de scrolls e montaria são enviados antes das respectivas macros.
2. Executa Blorb três vezes, com intervalo mínimo de cinco minutos, e WPACS três vezes, com intervalo mínimo de dez minutos. Essas coletas começam cedo para que os intervalos avancem enquanto as outras tarefas selecionadas são executadas. A coleta de diárias final fica para depois de suas dependências.
3. As demais macros seguem os estágios e dependências do plano. O fluxo visual do Cubo da Melhora usa até três entradas gratuitas; não clica em uma entrada que exija penas.
4. O pet tem uma limpeza gratuita e quatro pagas: 100, 200, 300 e 400 diamantes (1.000 no total). Antes de cada limpeza paga, exige duas leituras iguais do saldo e orçamento para **todas** as limpezas restantes. Se faltar saldo, preserva o progresso, avisa e continua a daily. Se a tela, o custo ou o saldo forem desconhecidos, interrompe a daily sem novo gasto. O contador visual seguinte confirma cada limpeza.
5. O progresso de tarefas é salvo em disco no diretório `SLAYER_DATA_DIR` da instalação e é carregado novamente nas próximas consultas/execuções. O ciclo diário troca às 02:00 no fuso UTC−03:00. Essa troca é lazy: ocorre quando a aplicação lê ou atualiza o estado, sem timer ou ação de jogo em segundo plano.

`/cancel` cancela a macro atual e interrompe as esperas da daily. Uma nova `/daily` retoma os contadores do mesmo ciclo. `python -m league_bot daily status` mostra o estado; `python -m league_bot daily set "Caverna" 1 3` registra uma missão pelo nome. No Telegram, use `/dailystatus` e `/dailyset "Caverna" 1 3`. Presença, espadas, acessórios e habilidades também aceitam aliases. A conclusão de uma gravação registra execução; somente os fluxos visuais de presença, cubo e pet conferem seus estados específicos no jogo.

## Escolha e instalação

Por padrão, a seleção inclui as 18 macros da guild. `daily add/remove` e `/dailyadd` e `/dailyremove` alteram essa seleção; `daily set` e `/dailyset` atualizam os contadores. A seleção fica em `daily.json` e o acompanhamento em `daily-status.json`, sob `SLAYER_DATA_DIR`. O padrão é `state/` no checkout; na distribuição instalada, é `~/.league-bot/state`. Cada instalação mantém seu próprio estado, sem executar a daily automaticamente às 02:00.

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

As macros são gravações de cliques, esperas e condições visuais. Uma gravação precisa ser validada ao vivo antes de entrar na seleção executada: confira a tela inicial, as telas intermediárias, a tela final, os tempos de carregamento, o layout da janela, o idioma e os custos em diamantes. Teste uma macro por vez no PC de destino e use `/cancel` ou o cancelamento de macro disponível no host se o fluxo sair do esperado.

Coordenadas em porcentagem não tornam uma gravação universal. Resolução, escala, idioma, avisos e progresso da conta variam. Calibre novamente no destino e não compartilhe screenshots de gravação ou arquivos de estado pessoal. A existência de uma macro no catálogo ou de testes com frames de fixture não significa que ela foi validada ao vivo nem publicada como segura para toda a guild.

## Daily customizada legada

Se `SLAYER_MACROS_DIR` aponta para uma biblioteca personalizada que não contém o catálogo completo, a CLI mantém a lista genérica e seu executor em ordem aleatória. Para o fluxo da guild, mantenha o diretório padrão ou disponibilize as 18 macros nessa biblioteca. `league_bot.daily.build_runner` continua como API genérica; o fluxo Slayer usa `league_bot.slayer.create_daily`.
