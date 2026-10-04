# league-bot

Bot do Telegram para controlar o **Slayer Legend** (Google Play Games para PC) à distância: iniciar o jogo (passando sozinho pelas telas iniciais), fechar e tirar screenshot da janela. Projeto aberto, feito para a guild — **sem dependências**, só Python.

> **Aviso:** o bot move o mouse e fecha processos no seu PC, e automatizar cliques pode ir contra os termos do jogo ou da plataforma. Use por sua conta e risco. Este projeto não é afiliado ao jogo, à desenvolvedora nem ao Google.

## Requisitos

- Windows 10/11 com o Google Play Games para PC e o Slayer Legend instalado e logado
- Python 3.9 ou mais novo (não precisa de `pip install`)

## Instalação

1. Clone o repositório e entre na pasta.
2. No Telegram, fale com o [@BotFather](https://t.me/BotFather), use `/newbot` e guarde o token.
3. Copie `.env.example` para `.env` e cole o token em `TELEGRAM_TOKEN`.
4. Rode `python -m league_bot run`, mande `/id` para o seu bot e coloque o número que ele responder em `ALLOWED_USER_IDS` (vários IDs separados por vírgula). Reinicie o bot.
5. Confira tudo com `python -m league_bot check`.

O título da janela é configurado em `SLAYER_WINDOW_TITLE` e basta conter o texto (no Windows do autor ela aparece como `Slayer Legend - <perfil>`, e o padrão `Slayer Legend` funciona). Se outra janela tiver esse mesmo texto (uma aba do navegador, por exemplo), rode `python -m league_bot windows` e use o título completo.

## Comandos do bot

| Comando | O que faz |
|---|---|
| `/startgame` | Abre o jogo e roda a macro de início (`macros/start_game.json`) |
| `/stopgame` | Fecha o Google Play Games (`client.exe` e `crosvm.exe`) |
| `/status` | Mostra se o jogo está rodando e se a janela foi encontrada |
| `/shot` | Envia um screenshot só da janela do jogo |
| `/macro <nome>` | Roda outra macro (sem nome, lista as disponíveis) |
| `/cancel` | Aborta a macro em andamento |
| `/id` | Mostra o seu ID do Telegram (único comando liberado para qualquer pessoa) |

`/stopgame` fecha o Google Play Games inteiro, inclusive outros jogos abertos nele.

## Linha de comando

`python -m league_bot <comando>`: `run` (padrão), `check`, `windows`, `status`, `start`, `stop`, `shot [arquivo.png]`, `macro <nome>`, `pixel <x> <y>`, `record <nome>`, `macros`, `show <nome>`, `rename <antigo> <novo>` e `delete <nome>`. Tudo funciona sem Telegram, o que ajuda a testar macros.

## Macros

Uma macro é um JSON com uma lista de passos (veja `macros/start_game.json`). Ela é validada antes de rodar, então um erro de digitação no passo 12 não deixa o jogo pela metade.

| Passo | Campos |
|---|---|
| `wait_window` | `timeout` (s, padrão 30) |
| `wait` | `seconds` |
| `click` | `x`, `y` |
| `wait_for_pixel` | `x`, `y`, `color` `[R,G,B]`, `tolerance`, `poll_seconds`, `timeout` — falha se a cor não aparecer |
| `click_if_pixel` | igual ao anterior, mas clica onde achou a cor e segue sem erro se não achar |
| `move_resize` | `width`, `height`, `x` e `y` opcionais |
| `minimize` | — |

Coordenadas podem ser `"center"`, uma porcentagem da área da janela (`"47.8%"`, funciona em qualquer tamanho de janela) ou pixels. Chaves que começam com `_` (como `_comment`) são ignoradas.

**Calibrando:** com o jogo aberto, use `python -m league_bot shot` para ver a tela e `python -m league_bot pixel 47.8% 82.5%` para ler a cor de um ponto. Para ajustes só da sua máquina, copie a macro para `macros/local/` (ignorada pelo git): uma macro com o mesmo nome lá tem prioridade.

Os cliques são reais (o mouse se move), porque o emulador do Play Games ignora cliques "em segundo plano". Use `/cancel` se algo sair do controle.

## Gravando macros

Em vez de escrever o JSON à mão, grave a quest jogando:

```
python -m league_bot record minha_quest -d "Daily 1" -t daily
```

1. Com o jogo aberto, rode o comando e, durante a contagem de 3 segundos, vá para a janela do jogo.
2. Jogue normalmente. Cada clique dado na janela do jogo é gravado, junto com a espera entre eles. Cliques fora da janela são ignorados.
3. Aperte **F10** (ou `Ctrl+C` no terminal) para terminar. A macro é salva em `macros/local/minha_quest.json`.

Depois, `python -m league_bot macro minha_quest` repete tudo. `python -m league_bot macros` lista as macros (compartilhadas e suas), `show <nome>` mostra os passos numerados para você editar o arquivo à mão, e `rename` e `delete` mexem só nas macros locais.

- Cada clique grava também a cor do ponto clicado. Na repetição, o bot espera o tempo gravado e depois espera essa cor aparecer antes de clicar, então um carregamento mais lento do que o da gravação não faz o clique cair na tela errada. Se um botão pisca ou muda de cor, grave com `--no-anchor` (cliques sem checagem de cor) ou edite o JSON.
- Arrastar e segurar ainda não são suportados: esses gestos são ignorados e o comando avisa quantos foram.
- Outras opções: `--stop-key F9`, `--delay 5`, `--max-seconds 600` e `--force` (sobrescreve uma macro local de mesmo nome).
- A gravação vale para qualquer tamanho de janela, porque as posições são salvas em porcentagem.

## Segurança

- Só quem está em `ALLOWED_USER_IDS` consegue usar o bot. Lista vazia significa que ninguém é autorizado.
- O `.env` tem o token do seu bot: nunca commite nem cole em chats. O token é removido das mensagens de erro e dos logs.
- Comandos mais antigos que `SLAYER_MAX_COMMAND_AGE` segundos (padrão 300) são ignorados, para o bot não executar o que ficou na fila enquanto o PC estava desligado.

## Estrutura

```
league_bot/
  bot.py           comandos do Telegram e autorização
  telegram_api.py  cliente da Bot API (urllib)
  game.py          iniciar, fechar, status, screenshot
  macro.py         validação e execução das macros
  recorder.py      gravação de cliques em macros
  library.py       macros compartilhadas e locais
  winapi.py        Windows: janelas, captura e cliques (ctypes)
  backend.py       interface que o winapi implementa
  imaging.py       pixels e PNG sem Pillow
  config.py        .env e configurações
macros/            macros compartilhadas
tests/             testes (rodam em qualquer sistema, com um backend falso)
```

## Contribuindo

```
python -m unittest discover -s tests -t .
```

- Sem dependências externas (só biblioteca padrão).
- Mensagens de commit em inglês, no estilo `feat(macro): ...` / `fix(bot): ...`.
- Toda lógica nova precisa de teste. Use o `FakeBackend` de `tests/fakes.py` em vez de mexer em janelas de verdade.
- Calibrações novas de macro (outras resoluções, outros avisos do jogo) são muito bem-vindas.

Ideias abertas: clique via `SendInput` para PCs onde o `mouse_event` não registra, macros para outras rotinas do jogo, uso em grupo do Telegram e mensagens em outros idiomas.

## Licença

MIT. Veja `LICENSE`.
