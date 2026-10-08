# league-bot

Controle o **Slayer Legend no Google Play Games para PC** pelo Telegram: abra o jogo, veja a tela, grave sequências de cliques, repita missões e organize uma daily. Projeto aberto feito para os membros da guild, com **Python e biblioteca padrão**, sem dependências externas no bot próprio.

Você pode usar o bot pronto ou incorporar a biblioteca `league_bot` ao seu bot do Telegram. Cada instalação controla o jogo **no computador em que o Python está rodando**.

> **Aviso:** o bot move o mouse e fecha processos no seu PC. Automatizar cliques pode ir contra os termos do jogo ou da plataforma. Use por sua conta e risco. Este projeto não é afiliado ao jogo, à desenvolvedora nem ao Google.

## Escolha como usar

| Você quer… | Siga… |
|---|---|
| Criar um bot dedicado ao Slayer Legend | [Instalação do bot próprio](#instalação-do-bot-próprio) |
| Usar o jogo no bot do Telegram que já possui | [Guia de integração](docs/telegram-integration.md) |
| Gravar e executar sem Telegram | [Primeira macro](#gravando-sua-primeira-macro) e [linha de comando](#linha-de-comando) |

## Requisitos

- Windows 10/11, com Google Play Games para PC e Slayer Legend instalado e logado.
- Python 3.9 ou mais novo. O bot próprio roda direto do repositório, sem `pip install`.
- Para o Telegram: internet e um bot criado no [@BotFather](https://t.me/BotFather), ou um bot existente para a integração.
- O Python deve rodar na sessão de desktop do Windows em que o jogo está aberto. O computador precisa permanecer ligado e acordado. Durante a gravação, mantenha o jogo visível e o mouse disponível.

O Telegram pode ser usado no celular, mas o jogo e a automação ficam no PC. Para usar na guild, cada pessoa configura sua própria instalação, seu bot e os IDs que autoriza a controlar esse PC.

## Instalação do bot próprio

### 1. Baixe o projeto

Baixe o ZIP em **Code → Download ZIP** na [página do projeto](https://github.com/pantalipe/league-bot) e extraia, ou use Git:

```powershell
git clone https://github.com/pantalipe/league-bot.git
cd league-bot
python --version
```

Abra o terminal na pasta que contém este README e `pyproject.toml`. Todos os comandos abaixo partem dessa pasta.

### 2. Crie o bot e configure o acesso

1. Fale com o [@BotFather](https://t.me/BotFather), use `/newbot` e guarde o token.
2. Copie o arquivo de configuração:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Abra `.env` num editor e preencha `TELEGRAM_TOKEN`. Mantenha `SLAYER_WINDOW_TITLE=Slayer Legend` inicialmente.
4. Inicie o bot:

   ```powershell
   python -m league_bot run
   ```

5. Abra a conversa com **seu bot** no Telegram e mande `/id`. Esse comando funciona antes da autorização.
6. Pare o processo com `Ctrl+C`, coloque o ID recebido em `ALLOWED_USER_IDS` e inicie novamente. Para vários usuários, separe os IDs por vírgula. Todos poderão controlar o mesmo PC.

Exemplo — substitua o token e o ID pelos seus:

```dotenv
TELEGRAM_TOKEN=123456789:COLE_SEU_TOKEN_AQUI
ALLOWED_USER_IDS=123456789
SLAYER_WINDOW_TITLE=Slayer Legend
```

Sem IDs autorizados, nenhum comando de controle fica liberado. Guarde o `.env` somente no seu computador; ele já é ignorado pelo Git.

### 3. Confira o jogo e a configuração

Com o jogo aberto manualmente, em outro terminal na pasta do projeto:

```powershell
python -m league_bot windows
python -m league_bot check
python -m league_bot shot teste.png
```

Abra `teste.png` e confira se é a janela do jogo. No Telegram, teste `/status` e `/shot`.

`SLAYER_WINDOW_TITLE` precisa corresponder a parte do título da janela. Se uma aba do navegador também tiver “Slayer Legend” no título, use o título completo exibido por `windows`. Reinicie o bot depois de alterar o `.env`.

Para abrir automaticamente, use `/startgame`. A macro incluída passa pelas telas iniciais e termina minimizando a janela. Se a interface ou os tempos forem diferentes no seu PC, [calibre uma cópia local](#editando-e-calibrando-macros).

O terminal do bot precisa continuar aberto. `Ctrl+C` encerra o processo; enquanto estiver desligado, os comandos não serão executados.

Os cliques usam segundo plano por padrão, pela janela interna do emulador, sem mover o cursor. O [início guiado por reconhecimento de tela](docs/screen-startup.md) é o padrão: reconhece a entrada, confirma o save quando aparece e só conclui após reconhecer a tela principal. Avisos desconhecidos interrompem o fluxo ao atingir o limite de espera e geram uma captura para diagnóstico.

## Comandos do bot próprio

| Comando | O que faz |
|---|---|
| `/help` ou `/start` | Mostra a ajuda; `/start` não abre o jogo |
| `/startgame` | Abre o jogo e roda a macro de início |
| `/stopgame` | Fecha os processos configurados do Google Play Games |
| `/status` | Informa processo, janela e operação/gravação em andamento |
| `/shot` | Envia um screenshot da janela do jogo |
| `/macro <nome>` | Executa uma macro; sem nome, lista as disponíveis |
| `/cancel` | Interrompe a macro ou daily em andamento |
| `/rec <nome> [anchor] [shots] [force]` | Grava cliques; as opções podem ser combinadas |
| `/recstop` | Termina a gravação e salva a macro |
| `/daily` | Executa todas as macros da daily, em ordem sorteada |
| `/dailylist` | Mostra as macros da daily |
| `/dailyadd <macro>` | Acrescenta uma macro à daily |
| `/dailyremove <macro>` | Tira uma macro da daily |
| `/id` | Informa seu ID de usuário; disponível sem autorização |

**`/stopgame` fecha o Google Play Games inteiro**, inclusive outros jogos abertos nele. Os processos padrão são `client.exe` e `crosvm.exe`.

Esses são os nomes do bot próprio. Um bot integrado pode usar outros; no panda-homebot, a execução é `/runmacro` e o cancelamento é `/runcancel`. Veja o [guia de integração](docs/telegram-integration.md).

## Gravando sua primeira macro

Uma macro repete cliques e esperas gravados. Comece numa tela de partida que você consiga reproduzir depois, por exemplo o menu principal.

### Pelo Telegram

1. Com o jogo aberto, mande `/rec minha_quest`.
2. Volte à janela e faça a missão normalmente. A gravação começa quando o comando é recebido.
3. Termine com **F10** ou `/recstop`. O bot confirma o salvamento e a quantidade de cliques.
4. Volte à mesma tela de partida e mande `/macro minha_quest` para testar.

Cliques fora da janela são ignorados. Arrastar e segurar ainda não são suportados; esses gestos são ignorados e contabilizados no aviso final. Sem cliques, nenhuma macro é salva. A gravação pelo Telegram tem limite de 15 minutos.

### Pelo terminal

```powershell
python -m league_bot record minha_quest -d "Missão da daily" -t daily
```

Há uma contagem de 3 segundos para ir à janela. Termine com **F10** ou `Ctrl+C`. Depois:

```powershell
python -m league_bot macro minha_quest
python -m league_bot show minha_quest
```

A macro vai para `macros/local/minha_quest.json`. Os cliques ficam em porcentagens da área da janela; isso ajuda quando a interface mantém as mesmas proporções, mas mudanças de layout podem exigir nova gravação ou calibração.

### Opções da gravação

| Telegram | Terminal | Comportamento |
|---|---|---|
| Sem opção | Sem opção | Guarda cliques e esperas |
| `anchor` | `--anchor` | Guarda a cor média perto do clique e espera essa cor antes de clicar na repetição |
| `shots` | `--shots` | Salva imagens locais vinculadas aos cliques, além da macro |
| `force` | `--force` | Substitui uma macro de mesmo nome por uma cópia local |

```text
/rec minha_quest anchor shots
/rec minha_quest shots force
```

```powershell
python -m league_bot record minha_quest --anchor --shots
python -m league_bot record minha_quest --shots --force --delay 5 --stop-key F9 --max-seconds 600
```

Use `anchor` quando o carregamento varia e o ponto clicado tem uma cor consistente. Botões animados podem fazer a espera estourar. A opção verifica uma cor numa posição; não identifica a tela inteira nem procura o botão em outros lugares.

Para **terminar uma gravação**, use F10 ou `/recstop`; `/cancel` interrompe a execução de macros/daily.

## Prints associados aos cliques

Com `shots`, a sessão fica em:

```text
macros/local/recordings/minha_quest/<sessão>/
  manifest.json
  0001_before.png
  0001_after.png
  0002_before.png
  ...
```

O `manifest.json` liga cliques às imagens, coordenadas em pixels e porcentagens, resolução e horários relativos ao início da gravação. Também informa o índice do passo correspondente no JSON da macro, contando a partir de zero.

- A imagem **anterior** vem de uma captura recente concluída antes do clique, com no máximo 1 segundo e tamanho compatível com a janela.
- A **posterior** vem de uma captura iniciada pelo menos 0,5 segundo após soltar o mouse. Isso não garante que animações e carregamentos terminaram.
- Um novo clique pode cancelar a imagem posterior pendente. Imagens ausentes e seus motivos ficam no manifesto e geram aviso.
- Os PNGs são gravados em segundo plano, numa fila limitada. Falhas de gravação em disco ou fila cheia não impedem salvar a macro; as imagens omitidas são informadas.
- Cada gravação cria uma sessão, inclusive com `force`. Renomear ou apagar a macro não renomeia nem apaga essas sessões.

Os prints **ficam no computador do bot e não são enviados ao Telegram**. A mensagem final informa o caminho do manifesto e a quantidade de imagens. Abra os PNGs normalmente e consulte o JSON num editor. `shots` coleta imagens; não muda as decisões durante a execução.

## Editando e calibrando macros

Uma macro é um JSON com uma lista de passos. O arquivo inteiro é validado antes de executar. Veja [macros/start_game.json](macros/start_game.json).

| Passo | Campos e comportamento |
|---|---|
| `wait_window` | Espera a janela aparecer; `timeout` em segundos, padrão 30 |
| `wait` | Espera `seconds`, padrão 1 |
| `click` | Clica em `x`, `y` |
| `wait_for_pixel` | Espera `color` `[R,G,B]` em `x`, `y`; falha se não aparecer no `timeout` |
| `click_if_pixel` | Espera a mesma condição e clica nesse ponto; continua sem clicar se não aparecer |
| `move_resize` | Ajusta `width`, `height`; `x`, `y` opcionais definem a posição da janela |
| `minimize` | Minimiza a janela |

Nos passos de cor, `tolerance` é a diferença permitida por canal (padrão 20), `radius` usa a média da área ao redor do ponto (padrão 0), `poll_seconds` é o intervalo de consulta (padrão 1) e `timeout` limita a espera (padrão 20). Os valores gerados por `anchor` podem ser diferentes desses padrões.

Coordenadas aceitam `"center"`, porcentagens como `"47.8%"` ou números de pixels. `(0, 0)` é o canto superior esquerdo da área de conteúdo da janela. Chaves começando por `_`, como `_comment`, são ignoradas.

Para consultar uma cor:

```powershell
python -m league_bot shot tela.png
python -m league_bot pixel 47.8% 82.5%
```

Uma cópia em `macros/local/` tem prioridade sobre a macro compartilhada de mesmo nome. Para ajustar a inicialização somente no seu PC:

```powershell
New-Item -ItemType Directory -Force macros/local
Copy-Item macros/start_game.json macros/local/start_game.json
```

Edite a cópia local. Os cliques são reais e podem mover o mouse ou trazer a janela para frente. Evite usar o mouse em paralelo; `/cancel` interrompe uma macro em andamento.

## Organizando a daily

A daily roda **todas** as macros cadastradas, uma após outra, em ordem sorteada. Com duas ou mais entradas, evita repetir a ordem anterior. Ela roda quando você pede, sem agendamento automático.

Teste cada macro sozinha. Como a ordem muda, faça as macros começarem e terminarem numa tela compatível, como o menu principal; não faça uma depender da missão anterior.

```text
/dailyadd quest_1
/dailyadd quest_2
/dailylist
/daily
```

```powershell
python -m league_bot daily add quest_1
python -m league_bot daily add quest_2
python -m league_bot daily list
python -m league_bot daily run
```

Se o jogo estiver fechado, a daily tenta abri-lo com a macro de início. Se uma macro falhar, para e informa quais terminaram. `/cancel` interrompe a daily e a macro atual. Ao fim, o bot próprio envia o resultado e tenta capturar a tela do jogo.

A lista fica em `state/daily.json`, ou na pasta `SLAYER_DATA_DIR`. Remover uma entrada da daily não apaga a macro.

## Compartilhando com a guild

Compartilhe somente o JSON da macro desejada. A outra pessoa pode colocá-lo em `macros/local/`, voltar à tela de partida e testar antes de incluí-lo na daily. Layout, idioma, avisos e progresso da conta podem exigir adaptações mesmo com coordenadas em porcentagem.

`macros/local/` e `state/` são pessoais e ignorados pelo Git. Os prints também ficam na pasta local. O `.env` contém credenciais e não deve ser compartilhado. Para contribuir uma macro, coloque uma cópia revisada em `macros/` com descrição da tela de partida e do que ela faz.

## Configuração

O bot próprio lê `.env` na raiz do projeto; variáveis de ambiente têm prioridade. Use `--env-file` antes do comando para outro arquivo:

```powershell
python -m league_bot --env-file C:/Bots/slayer.env run
```

Comentários no `.env` devem ocupar uma linha própria, começando por `#`; comentários depois de valores não são suportados.

| Variável | Uso / padrão |
|---|---|
| `TELEGRAM_TOKEN` | Token do bot próprio; obrigatório para `run` |
| `ALLOWED_USER_IDS` | IDs de usuário separados por vírgula; vazio bloqueia o controle |
| `SLAYER_WINDOW_TITLE` | Trecho do título; `.env.example` usa `Slayer Legend` |
| `SLAYER_LAUNCH_URI` | URI de abertura; já há um padrão para Slayer Legend |
| `SLAYER_PLAY_GAMES_EXE` | Executável usado se a URI estiver vazia |
| `SLAYER_PROCESS_NAMES` | Processos consultados/fechados; `client.exe,crosvm.exe` |
| `SLAYER_START_MACRO` | Nome da macro de início; `start_game_recognized`. `start_game` conserva a sequência antiga |
| `SLAYER_MACROS_DIR` | Macros compartilhadas; padrão `macros/` na instalação, com subpasta `local/` |
| `SLAYER_DATA_DIR` | Estado da daily; padrão `state/` na instalação |
| `SLAYER_FOREGROUND_INPUT` | `0` (padrão) envia cliques à janela interna do emulador sem foco; `1` usa o mouse real. Não há fallback automático |
| `SLAYER_MAX_COMMAND_AGE` | Bot próprio ignora comandos com mais de 300 segundos; `0` desativa o limite |
| `SLAYER_LOG_FILE` | Arquivo opcional de log; padrão sem arquivo |

Na integração, token e autorização pertencem ao bot que recebe os comandos. A biblioteca não aplica automaticamente `ALLOWED_USER_IDS` nem o limite de idade; o adaptador deve fazê-lo. Veja o [guia](docs/telegram-integration.md).

## Linha de comando

Os seguintes comandos funcionam sem iniciar o bot do Telegram:

| Após `python -m league_bot` | Uso |
|---|---|
| `check` / `windows` / `status` | Confere configuração / lista janelas / consulta o jogo |
| `start` / `stop` | Abre com a macro de início / fecha os processos configurados |
| `shot [arquivo.png]` | Salva a tela; aceita `.bmp` também |
| `pixel <x> <y>` | Lê a cor de um ponto |
| `record <nome>` | Grava macro; veja `record --help` |
| `macro <nome>` | Executa macro |
| `macros` / `show <nome>` | Lista macros / mostra passos numerados |
| `rename <antigo> <novo>` / `delete <nome>` | Renomeia/apaga somente macros locais |
| `daily list`, `daily add <nome>`, `daily remove <nome>`, `daily run` | Consulta, edita ou executa a daily |

`run` é o padrão se você omitir o comando. `python -m league_bot --help` mostra a ajuda completa. `/cancel` cancela execuções no processo do bot; não cancela um comando `macro` num terminal separado.

## Problemas comuns

| Sintoma | O que conferir |
|---|---|
| `python` não é reconhecido | Instale Python e habilite seu uso no terminal; confira `python --version` |
| `No module named league_bot` | Entre na pasta do repositório ou, na integração, instale no mesmo Python do bot |
| “Não autorizado” | Confira `/id`, `ALLOWED_USER_IDS` e reinicie o bot próprio; no integrado, confira o adaptador |
| Janela não encontrada / screenshot de outra janela | Abra o jogo e confira `windows`; use um título mais específico |
| Screenshot falha ou fica sem conteúdo | Confira se o jogo está renderizando; tente com a janela visível. `/shot` pode restaurar temporariamente uma janela minimizada |
| Espera de cor estoura | Confira tela de partida, resolução e cor; use `pixel` para recalibrar, especialmente em botões animados |
| Cliques vão para lugares errados | Volte à tela de partida e confira layout; regrave ou edite as coordenadas |
| “Já existe uma operação em andamento” | `/recstop` termina gravações; `/cancel` interrompe execução de macro/daily no bot próprio |
| Macro de mesmo nome já existe | Use outro nome ou `force` / `--force` para substituí-la localmente |
| Faltam prints em `shots` | Leia o `manifest.json`; deixe mais tempo entre cliques e confira espaço/permissão no disco |
| Conflito no recebimento de mensagens | Não rode dois processos consumindo o mesmo token; na integração, use somente o receptor existente |

## Estrutura e contribuição

```text
league_bot/
  bot.py           comandos do bot próprio e autorização
  telegram_api.py  cliente da Bot API com urllib
  game.py          controlador do jogo e gravação em segundo plano
  macro.py         validação e execução de macros
  recorder.py      gravação de cliques e capturas associadas
  evidence.py      PNGs e manifesto da sessão
  library.py       biblioteca de macros compartilhadas e locais
  daily.py         lista e execução da daily
  winapi.py        janelas, captura e cliques do Windows com ctypes
  backend.py       interface do backend
  imaging.py       pixels e codificação PNG/BMP
  config.py        .env e configurações
docs/              guia de integração com outros bots
macros/            macros compartilhadas
tests/             testes com backend falso
```

Para validar sem controlar janelas reais:

```powershell
python -m unittest discover -s tests -t .
```

- Preserve a biblioteca principal sem dependências externas; a integração usa as dependências do bot que a hospeda.
- Toda lógica nova precisa de teste. Use `FakeBackend` de `tests/fakes.py`.
- Use commits em inglês, como `feat(macro): ...` ou `fix(bot): ...`.
- Ao contribuir uma macro, explique tela inicial/final e condições de calibração.

## Licença

MIT. Veja [LICENSE](LICENSE).
