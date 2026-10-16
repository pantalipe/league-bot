# Calibracao local de telas

## Catalogo global e resolucao

`calibrate all` amplia o fluxo inicial de presenca/menu para os grupos de anchors
dos arquivos de perfis, os `screen_flow` gravados, os `wait_for_pixel` e os
`click_if_pixel`. Tambem lista os cliques para revisao. Catalogar um ponto nao
significa valida-lo. Contadores que usam mascaras de texto continuam exigindo
uma amostra rotulada de cada valor/formato; cores de anchors nao substituem esses
leitores.

```powershell
python -m league_bot calibrate all catalog --output state/calibration/catalog.json
python -m league_bot calibrate all status --output state/calibration/coverage.json
python -m league_bot calibrate all tour
python -m league_bot calibrate all tour --resume
python -m league_bot calibrate all guide --macro montar_besta
python -m league_bot calibrate all capture --entry ID_DO_CATALOGO
python -m league_bot calibrate all capture --entry ID_DO_CATALOGO --label negative
python -m league_bot calibrate all add --entry ID_DO_CATALOGO --images captura1.png captura2.png
python -m league_bot calibrate all propose
python -m league_bot calibrate all validate
python -m league_bot calibrate all apply
python -m league_bot calibrate all rollback
```

A sessao global padrao fica em `state/calibration/global-session`. Cada detector
precisa de duas capturas positivas e uma negativa explicita. A negativa deve ser
uma tela/estado em que aquele detector nao pode autorizar a continuacao. O guia
captura o rotulo escolhido por `--label`; ele nao infere o estado correto nem
navega automaticamente. Pontos sem evidencias continuam pendentes. O relatorio
por macro descreve os arquivos gravados, inclusive variantes locais; os executores
especializados podem substituir partes dessas gravacoes. Portanto esse relatorio
nao certifica a execucao completa da daily.

`tour` percorre dez destinos de navegacao conhecidos: scrolls, Equipment, mapa,
Dungeon, Guild, Shop, Goods, Character, loja da guilda e missoes diarias. Coleta
capturas e volta ao menu entre destinos, sem usar a confirmacao de recompensas
do recovery. Somente telas reconhecidas recebem cliques de navegacao, com no
maximo uma repeticao apos tres segundos. Um destino desconhecido fica pendente; se o retorno tambem nao for
reconhecido, o tour para. As capturas desconhecidas ficam sem rotulo para revisao
em `tour.json`. Os valores dos contadores e as etapas de combate/recompensa que
so surgem durante as macros exigem evidencias adicionais pelo guia/captura.

As propostas mantem tolerancias, raios e destinos de clique. Rejeitam mudancas
incompativeis de fonte e cores instaveis. O perfil global ativo fica em
`state/calibration/global-active.json`; sua aplicacao cobre os fluxos aninhados,
os guards de pixels e os reconhecedores chamados diretamente durante a rotina.
Falhas novas salvam uma imagem e um JSON com o passo que estava sendo observado.

Os anchors ja usam coordenadas normalizadas. Macros tambem aceitam
`{"relative": 0.5}` como coordenada: o motor calcula
`round(fracao * (dimensao - 1))`, preservando os pixels extremos. As porcentagens
antigas continuam aceitas. Para os cliques absolutos presentes nos executores,
o adaptador de geometria converte todos os pontos da referencia para a area
visivel atual do jogo e normaliza a captura para a mesma referencia.

Meça a referencia uma vez com a janela em **434x810 de area cliente**, usando:

```powershell
python -m league_bot calibrate all geometry
```

Isso salva `state/calibration/geometry.json`. Reinicie o bot para carregar a
geometria. A partir dai o motor preserva o tamanho fisico da janela; mede a area
do emulador novamente ao capturar/clicar, desconta a barra superior e adapta a
escala. A referencia medida nesta maquina tem area visivel `[0, 36, 434, 774]`.
A superficie filha pode ultrapassar a janela em ate 8 pixels nas bordas direita
e inferior; somente sua intersecao visivel e usada. Mudancas de proporcao de 1%
ou mais interrompem a operacao. A escala nao corrige reorganizacao de botoes,
fontes diferentes nem garante que mascaras de contadores sobrevivam a outra
resolucao. Esses casos continuam aparecendo como pendencias de calibracao.

Quando uma daily chega ao painel correto mas rejeita um contador ou botao,
use o PNG e o JSON de `state/diagnostics/screen-failure-*` para identificar
o estado observado. A calibracao de anchors nao adiciona mascaras de digitos
aos leitores de Orb, scrolls ou invocacoes. Esses leitores precisam de uma
variante rotulada do raster atual e de verificacao contra estados negativos;
aumentar tolerancias de navegacao nao resolve a leitura dos contadores.

Para desativar a geometria relativa, mova o arquivo `geometry.json` para um
backup e reinicie o bot. A gravacao nova converte tambem a posicao fisica do mouse
para a referencia, mantendo cliques gravados e capturas no mesmo espaco.

## Fluxo inicial de presenca (compatibilidade)

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
