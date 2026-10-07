# Integrar `league_bot` a outro bot do Telegram

Este guia conecta a biblioteca `league_bot` a um bot Telegram que já existe. O exemplo usa `python-telegram-bot` 21.9 e registra comandos em um `Application` existente; o host continua responsável pelo token, pela autorização e pelo ciclo de vida do bot.

## Onde o código precisa rodar

O jogo e a biblioteca precisam estar no mesmo PC Windows interativo e na mesma sessão de usuário do Google Play Games. O backend Win32 lê a janela e envia cliques nessa sessão; um processo em VPS, serviço sem desktop ou outra máquina não consegue controlar essa janela.

Instale a biblioteca no mesmo ambiente Python que executa o bot:

```powershell
python -m pip install -e C:\Bots\league-bot
```

O pacote requer Python 3.9 ou mais recente e não adiciona dependências Python. O host instala as dependências próprias; para reproduzir este exemplo, use `python-telegram-bot==21.9` no ambiente do host. Configure `SLAYER_WINDOW_TITLE` com o título da janela do jogo. As demais opções `SLAYER_*` são lidas da configuração do processo, como `SLAYER_MACROS_DIR`, `SLAYER_DATA_DIR` e `SLAYER_FOREGROUND_INPUT`.

Se ainda não usa `python-telegram-bot` e quer reproduzir esse exemplo, instale a versão usada na validação:

```powershell
python -m pip install python-telegram-bot==21.9
```

Se seu bot usa outra biblioteca Telegram, mantenha essa biblioteca e adapte os handlers usando a tabela de API abaixo. A instalação do bot próprio não precisa de `python-telegram-bot`.

O token pertence ao host. Ao chamar `load_settings`, passe somente variáveis `SLAYER_*` e `env_file=None`: assim o arquivo `.env` do league-bot e o token do bot host não entram na configuração da biblioteca. `ALLOWED_USER_IDS` é usado pelo executável independente; a biblioteca não aplica autorização Telegram.

## API do núcleo

Crie uma instância `SlayerGame` por processo e reutilize-a nos handlers. As chamadas abaixo são síncronas, exceto a gravação: em handlers `async`, execute-as em uma thread para manter o loop Telegram disponível.

| API | Comportamento |
| --- | --- |
| `load_settings(environ=..., env_file=None)` | Cria `Settings` usando o mapa fornecido; inclua apenas opções `SLAYER_*`. |
| `SlayerGame(settings, Win32Backend(), input_guard=None, log=None)` | Constrói o controlador Win32 e sua biblioteca local de macros. `input_guard` é uma função opcional que cria um context manager para liberar um bloqueio externo de mouse/teclado durante entrada real. |
| `game.start()` / `game.stop()` | Inicia o jogo e executa a macro inicial / encerra os processos configurados. Síncronos. |
| `game.status()` | Retorna `GameStatus(running, window_found, busy, recording)`. Síncrono. |
| `game.screenshot()` | Retorna um `Frame`; use `frame.to_png()` para obter bytes PNG. Síncrono. |
| `game.list_macros()` / `game.run_macro(name)` | Lista nomes / executa uma macro. `run_macro` é síncrono e pode demorar. |
| `game.start_recording(name, anchors=False, shots=False, overwrite=False, on_done=...)` | Inicia a gravação em uma thread interna e retorna imediatamente. `on_done(RecordingResult)` também roda nessa thread. O resultado inclui `path`, `clicks`, `warnings`, `error`, `shots_path` e `image_count`. |
| `game.stop_recording()` / `game.cancel()` | Pede para salvar a gravação atual / cancela a macro em execução. Retornam `bool`. São síncronos e rápidos. |
| `build_runner(game, settings, log=...)` | Opcional: constrói o executor da lista diária local, armazenada sob `settings.data_dir`. |

`start`, `run_macro` e gravação usam o mesmo controlador e podem levantar `GameBusy` quando outra operação está ativa. Trate também `GameError`, `LibraryError` e `MacroError`. Não use `game.stop()` para encerrar uma gravação; use `stop_recording()`.

## Adaptador copiável

Salve como, por exemplo, `league_adapter.py` dentro do projeto do bot host. O conjunto de IDs autorizados deve vir da configuração segura do host e conter ao menos um ID. Os comandos têm prefixo `sl` para reduzir colisões com os comandos existentes.

```python
import asyncio
import io
import logging
import os
from datetime import datetime, timezone

from telegram.ext import CommandHandler

from league_bot.config import load_settings
from league_bot.game import GameBusy, GameError, SlayerGame
from league_bot.library import LibraryError
from league_bot.macro import MacroError
from league_bot.winapi import Win32Backend

log = logging.getLogger(__name__)


def register_league_handlers(app, authorized_user_ids, *, input_guard=None):
    """Adiciona os handlers ao Application existente; não inicia outro bot/poller."""
    user_ids = frozenset(int(value) for value in authorized_user_ids)
    if not user_ids:
        raise ValueError("authorized_user_ids não pode estar vazio")

    # Não passe os.environ inteiro: TELEGRAM_TOKEN e ALLOWED_USER_IDS são do host.
    settings_env = {key: value for key, value in os.environ.items()
                    if key.startswith("SLAYER_")}
    settings = load_settings(environ=settings_env, env_file=None)
    game = SlayerGame(settings, Win32Backend(), input_guard=input_guard,
                      log=log.info)
    app.bot_data["league_game"] = game

    async def in_thread(fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def reply(update, text):
        message = update.effective_message
        if message is not None:
            await message.reply_text(text)

    def handler(fn):
        async def guarded(update, context):
            user = update.effective_user
            if user is None or user.id not in user_ids:
                await reply(update, "Acesso não autorizado.")
                return
            message = update.effective_message
            if message is not None and settings.max_command_age:
                age = (datetime.now(timezone.utc) - message.date).total_seconds()
                if age > settings.max_command_age:
                    await reply(update, "Comando expirado; envie novamente.")
                    return
            try:
                await fn(update, context)
            except (GameBusy,):
                await reply(update, "⏳ Já existe uma operação do jogo em andamento.")
            except (GameError, LibraryError, MacroError) as exc:
                # Erros conhecidos são mensagens de configuração/uso do núcleo.
                await reply(update, f"❌ {exc}")
            except Exception:
                log.exception("Falha inesperada no adaptador league_bot")
                await reply(update, "❌ Erro inesperado; consulte o log local do bot.")
        return guarded

    @handler
    async def slstatus(update, context):
        status = await in_thread(game.status)
        await reply(update, f"Jogo: {'rodando' if status.running else 'parado'}; "
                           f"janela: {'encontrada' if status.window_found else 'ausente'}; "
                           f"ocupado: {status.busy}; gravando: {status.recording}.")

    @handler
    async def slshot(update, context):
        png = await in_thread(lambda: game.screenshot().to_png())
        if len(png) <= 9_000_000:
            await update.effective_message.reply_photo(photo=io.BytesIO(png))
        else:
            await update.effective_message.reply_document(
                document=io.BytesIO(png), filename="slayer.png")

    @handler
    async def slmacro(update, context):
        if len(context.args) != 1:
            await reply(update, "Uso: /slmacro <nome>")
            return
        await reply(update, f"▶️ Rodando macro '{context.args[0]}'...")
        result = await in_thread(game.run_macro, context.args[0])
        await reply(update, "✅ " + result)

    @handler
    async def slcancel(update, context):
        cancelled = await in_thread(game.cancel)
        await reply(update, "🛑 Cancelando a macro..." if cancelled
                    else "Nenhuma macro em execução.")

    @handler
    async def slrecstop(update, context):
        stopped = await in_thread(game.stop_recording)
        await reply(update, "⏹️ Finalizando a gravação..." if stopped
                    else "Nenhuma gravação em andamento.")

    @handler
    async def slrec(update, context):
        if not context.args:
            await reply(update, "Uso: /slrec <nome> [anchor] [shots] [force]")
            return
        name, raw_flags = context.args[0], context.args[1:]
        flags = {flag.lower() for flag in raw_flags}
        if len(flags) != len(raw_flags) or flags - {"anchor", "shots", "force"}:
            await reply(update, "Flags aceitas: anchor, shots, force.")
            return
        chat_id = update.effective_chat.id
        bot = context.bot
        loop = asyncio.get_running_loop()

        def notify_done(result):
            # Este callback roda na thread do gravador, fora do event loop do Telegram.
            async def send_result():
                if result.error:
                    log.warning("Gravação %r não salva: %s", result.name, result.error)
                    text = "❌ Gravação sem resultado salvo; consulte o log local do bot."
                else:
                    text = (f"✅ Macro '{result.name}' salva: {result.clicks} clique(s), "
                            f"{result.duration:.0f}s. Rode /slmacro {result.name}.")
                    if result.skipped_gestures:
                        text += f"\n⚠️ {result.skipped_gestures} gesto(s) foram ignorados."
                    if result.shots_path is not None:
                        text += (f"\n📸 {result.image_count} captura(s) local(is): "
                                 f"{result.shots_path}")
                    text += "".join(f"\n⚠️ {warning}" for warning in result.warnings)
                await bot.send_message(chat_id=chat_id, text=text)

            future = asyncio.run_coroutine_threadsafe(send_result(), loop)
            def report_send_failure(done):
                try:
                    done.result()
                except Exception:
                    log.exception("Não foi possível enviar o resultado da gravação")
            future.add_done_callback(report_send_failure)

        await in_thread(
            game.start_recording, name,
            anchors="anchor" in flags,
            shots="shots" in flags,
            overwrite="force" in flags,
            on_done=notify_done,
        )
        await reply(update, f"🔴 Gravando '{name}'. Termine com F10 ou /slrecstop "
                           "(limite de 15 minutos).")

    # block=False deixa o polling receber /slcancel enquanto uma macro longa executa.
    for name, callback in (("slstatus", slstatus), ("slshot", slshot),
                           ("slmacro", slmacro), ("slcancel", slcancel),
                           ("slrecstop", slrecstop), ("slrec", slrec)):
        app.add_handler(CommandHandler(name, callback, block=(name != "slmacro")))

    return game
```

Registre uma vez, depois de criar o `Application` que o host já usa e antes de iniciar o recebimento de mensagens. A variável `application` abaixo representa essa instância existente; substitua `HOST_AUTHORIZED_USER_IDS` pelo conjunto de IDs configurados no seu bot:

```python
from league_adapter import register_league_handlers

register_league_handlers(application, HOST_AUTHORIZED_USER_IDS)
# Mantenha em seguida a inicialização e o polling/webhook que seu bot já usa.
```

Não crie um segundo `run_polling()` nem outro processo consumidor com o mesmo token. No polling, dois consumidores para o mesmo bot disputam as atualizações: alguns comandos deixam de chegar ao handler esperado. O exemplo segue o modelo async do PTB 21.9 documentado em [Application](https://docs.python-telegram-bot.org/en/v21.9/telegram.ext.application.html).

O próprio bot host deve carregar seu `.env` antes do registro: `env_file=None` não lê esse arquivo. Por exemplo, configure `SLAYER_WINDOW_TITLE=Slayer Legend` no ambiente do host e use caminhos absolutos para `SLAYER_MACROS_DIR` e `SLAYER_DATA_DIR` se eles não forem os padrões da instalação. Confirme o ambiente com `python -c "import league_bot; print(league_bot.__file__)"`.

Após reiniciar o seu bot, teste `/slstatus`, `/slshot`, `/slrec teste shots`, `/slrecstop` e `/slmacro teste`. Volte à tela de partida antes de repetir a macro. Os prefixos podem ser alterados no registro e nas mensagens; registre-os antes de handlers genéricos que aceitam qualquer comando no mesmo grupo. O exemplo verifica ID de usuário; se seu bot também restringe o chat, aplique essa verificação em `guarded`.

### Entrada e capturas

`input_guard` é o ponto de integração para um host que bloqueia entrada local. Passe uma função context manager que pause o bloqueio e sempre o restaure no `finally`; o núcleo a usa em torno de cliques e durante toda a gravação. Sem bloqueio externo, deixe `input_guard=None`.

`shots` salva as imagens antes/depois dos cliques no computador do bot, em uma pasta local apontada pelo `RecordingResult.shots_path`. O adaptador envia o caminho e a contagem, não os arquivos. Se for compartilhar uma macro, compartilhe o JSON da macro e revise/calibre as coordenadas para a janela, resolução e escala de destino; a biblioteca valida a janela, mas não ajusta automaticamente uma macro para outro layout.

## Integração existente com panda-home-bot

O [panda-home-bot](https://github.com/pantalipe/panda-home-bot) tem um `league_adapter.py` próprio, que usa os módulos internos `lock_manager` e a autorização do `bot.py`. Você não precisa dele para usar league-bot. Se já usa esse host, instale league-bot no ambiente Python do homebot ou configure `LEAGUE_BOT_DIR` como alternativa de importação. Exemplo com as pastas em `C:/Bots`:

```powershell
C:/Bots/panda-home-bot/.venv/Scripts/python.exe -m pip install -e C:/Bots/league-bot
```

No `.env` que o homebot carrega:

```dotenv
LEAGUE_BOT_DIR=C:/Bots/league-bot
SLAYER_WINDOW_TITLE=Slayer Legend
```

Adapte os caminhos à sua instalação. Quando o pacote já está instalado, a importação tem prioridade sobre `LEAGUE_BOT_DIR`. O adaptador já filtra `SLAYER_*` e chama `load_settings(..., env_file=None)`; `Slayer Legend` é o título padrão nesse host. Após instalar ou atualizar, reinicie o homebot.

Os comandos desse host existente são `/rec <nome> [anchor] [shots] [force]`, `/recstop`, `/runmacro <nome>` e `/runcancel`. Não copie esse módulo para outro bot sem adaptar suas dependências `lock_manager`, `authorized` e `deny`; use o exemplo genérico acima.

Esse adaptador também oferece `/macros`, `/daily`, `/dailylist`, `/dailyadd <macro>` e `/dailyremove <macro>`. Para adicionar daily a outro host, mantenha uma instância de `build_runner(game, settings)` e execute `daily.run()` em thread; `daily.cancel()` cancela a daily e a macro atual, enquanto `game.cancel()` sozinho não encerra toda a lista.

## Problemas comuns

- **Janela ausente:** confirme que o Google Play Games e o jogo estão abertos na mesma sessão, e ajuste `SLAYER_WINDOW_TITLE` para o título real da janela.
- **`GameBusy`:** outra gravação ou execução já ocupa o controlador. Capturar uma janela minimizada também exige restaurá-la e pode ser recusado durante outra operação. Aguarde ou envie `/slcancel` para macro e `/slrecstop` para gravação.
- **Captura preta ou vazia:** janela minimizada pode parar de renderizar. O núcleo tenta restaurá-la por cerca de um segundo para capturar e depois minimiza de novo; mantenha a janela visível se a captura continuar vazia.
- **Macro falha em outra máquina/layout:** coordenadas dependem do tamanho da janela e do layout. Regrave ou calibre a macro no destino; enviar somente o JSON não inclui nem resolve dependências de screenshots.
- **Comando não chega:** confirme que existe apenas um consumidor de updates para aquele token e que o handler foi registrado no `Application` do host.
