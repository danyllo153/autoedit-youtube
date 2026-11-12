# autoedit-youtube

Edição automática para YouTube (gameplay, vídeos, fotos): Python + FFmpeg + PySceneDetect + Whisper.

Pipeline em Python + FFmpeg: acha as melhores partes com PySceneDetect, monta o vídeo,
adiciona música, legenda automática (Whisper) e, se o vídeo for grande, intro + miniatura.

## Instalação
1. Instale o FFmpeg e deixe no PATH (`ffmpeg -version` deve funcionar).
2. `pip install -r requirements.txt`
3. (opcional) `pip install -r requirements-ocr.txt` (`--ocr`), `requirements-visao.txt` (recorte de pessoa e rastreamento) e
   `requirements-animacao.txt` + `python -m playwright install chromium` (animação HTML)

Atalhos: `./scripts/setup_sessao.sh` (Linux/nuvem) ou `.\scripts\setup_windows.ps1` (Windows) instalam tudo de uma vez.

## Uso
```bash
# Melhores momentos (duração automática = 25% do original, entre 30 s e 10 min)
python autoedit.py gameplay.mp4

# Completo: 8 min, música (arquivo ou pasta), legendas em pt, título/canal, versão Shorts, GPU NVIDIA
python autoedit.py gameplay.mp4 --target 480 --music musicas/ --subs --lang pt \
    --title "Clutch insano no ranked" --channel "Meu Canal" --shorts --gpu

# Pasta de fotos -> slideshow com zoom suave
python autoedit.py fotos/ --music musicas/ --photo-secs 3.5

# Só ver quais trechos seriam escolhidos (não renderiza)
python autoedit.py gameplay.mp4 --plan-only

# Gameplay: dá nota extra a trechos em que aparece texto-chave na tela (OCR; só para o que o jogo escreve)
python autoedit.py gameplay.mp4 --ocr --target 480

# Gravação falada: tira os silêncios e salva a lista de cortes (EDL) para abrir no Resolve/Premiere
python autoedit.py gravacao.mp4 --cut-silences --subs --lang pt

# Slideshow com transição entre as fotos
python autoedit.py fotos/ --photo-transition mix --transition-secs 0.6
```

Saída (pasta `autoedit_out/`): `*_final.mp4`, `*_miniatura.jpg` (só vídeo grande),
`*_shorts.mp4` (com `--shorts`) e `*_trechos.json` (tempos escolhidos).

## Opções principais
| Opção | O que faz |
|---|---|
| `--target S` | duração final em segundos |
| `--max-clip / --min-clip` | tamanho máximo/mínimo de cada trecho (padrão 10 s / 2 s) |
| `--audio-weight 0-1` | peso do áudio (gritos, tiros) vs movimento na escolha (padrão 0.6) |
| `--music ARQ/PASTA` | música de fundo; abaixa sozinha quando você fala |
| `--subs --lang pt` | legendas automáticas gravadas no vídeo |
| `--sub-mode line/group/word` | estilo da legenda: `line` = frase inteira (padrão); `group` = bloco de poucas palavras com a palavra falada destacada; `word` = uma palavra por vez, grande (estilo Shorts). Usa os tempos por palavra do Whisper |
| `--sub-words N` / `--sub-color #RRGGBB` | palavras por bloco no modo `group` (padrão 3) e cor da palavra destacada (padrão `#FFDE1E`) |
| `--extras auto/on/off` | intro + miniatura (auto = só se final >= `--long-min`, padrão 180 s) |
| `--intro-video ARQ` | usa sua intro em vez da gerada |
| `--shorts` | gera versão vertical 9:16 de até 58 s |
| `--shorts-only` | gera só o Short vertical |
| `--short-crop square` | Short: recorta o centro 1:1 (gameplay maior; perde bordas/HUD) |
| `--short-crop face` | Short: recorte 9:16 que segue o rosto (YuNet/OpenCV; baixa um modelo de ~230 KB para `~/.cache/autoedit` na 1ª vez). Trecho sem rosto cai no enquadramento normal |
| `--short-crop facecam` | Short: webcam (recorte em volta do rosto) em cima e o gameplay inteiro embaixo |
| `--ocr` | lê o texto escrito na tela (RapidOCR) e dá nota extra a trechos com palavras-chave; grava `*_ocr.json` com o que leu. Não detecta abates só visuais |
| `--ocr-keywords "a=1,b=0.7"` | palavras escritas na tela que marcam bons momentos, com peso 0-1 (o padrão são palpites: calibre com o `*_ocr.json`) |
| `--ocr-weight X` | quanto da nota vem do OCR, 0-1 (padrão 0,5: trecho com palavra-chave passa à frente dos demais) |
| `--ocr-every S` | lê 1 quadro a cada S segundos do trecho (padrão 1,5; menor = acha textos curtos, mas demora mais) |
| `--ocr-region x0,y0,x1,y1` | área da tela lida, em frações (padrão tela toda; `0,0.6,1,1` = faixa de baixo) |
| `--min-motion X` | descarta trechos parados (menus/inventário) abaixo de X × mediana de movimento (padrão 0.5) |
| `--lufs X` | volume final em LUFS (padrão -16; o YouTube costuma normalizar perto de -14) |
| `--cut-silences` | gravação falada: corta os silêncios e salva `*.edl` (ignora `--target` e a pontuação por cenas) |
| `--silence-db X` | abaixo de X dB é silêncio (padrão -35; com ruído de fundo alto use -30) |
| `--min-silence S` | só corta silêncios com pelo menos S segundos (padrão 0,6) |
| `--pad S` | folga mantida em volta da fala (padrão 0,15 s) |
| `--photo-transition T` | slideshow: `none` (corte seco, padrão), `fade`, `dissolve`, `slideleft`, `wipeleft`, `circleopen`, `smoothleft`, `zoomin` ou `mix` |
| `--transition-secs S` | duração da transição entre fotos (padrão 0,6 s) |
| `--broll "a,b"` | vídeos de apoio gratuitos (Pexels ou Pixabay) como corte de cobertura: cobrem a imagem e mantêm o áudio original. Precisa de chave (abaixo) |
| `--broll-fonte auto/pexels/pixabay` | de onde buscar (padrão `auto`: a que tiver chave, Pexels primeiro) |
| `--pexels-key` / `--pixabay-key` | chaves das APIs; ou deixe nas variáveis `PEXELS_API_KEY` / `PIXABAY_API_KEY` (não vão para o repositório) |
| `--broll-every S` / `--broll-secs S` | 1 b-roll a cada S s de vídeo (padrão 25) e duração de cada um (padrão 4 s) |
| `--broll-color on/off` | ajusta média e contraste de cada canal de cor do b-roll para o vídeo principal (padrão on) |
| `--gpu` | exporta com NVENC (placa NVIDIA) |

## OCR: textos escritos na tela (`--ocr`)
**Atenção:** o OCR só enxerga o que o jogo ESCREVE. No Arc Raiders o abate ao vivo é só visual (não há texto de kill),
então o `--ocr` **não detecta kills** ali. Ele serve para jogos que escrevem o abate/vitória (o usuário citou Call of Duty como o caso que faz isso) ou para telas de resultado com texto. Para sinais
visuais sem texto, o caminho é outro (ver "Limitações conhecidas").
O `--ocr` lê o texto em alguns quadros de cada trecho e dá nota extra a quem tem palavra-chave. Trechos com palavra-chave nunca são descartados pelo filtro de cena parada
(`--min-motion`), porque a tela de vitória costuma ser parada.

**Calibre com o seu jogo:** as palavras padrão são palpites genéricos, ainda não conferidos com o jogo. Rode uma vez com `--ocr --plan-only`, abra `autoedit_out/<nome>_ocr.json` (o texto que o OCR leu em cada
trecho), veja como o seu HUD escreve os avisos e passe as palavras certas em `--ocr-keywords`. Se o aviso aparece
sempre no mesmo canto, `--ocr-region` deixa a leitura mais rápida e evita falsos positivos.

Custo: cerca de 0,2 s por quadro lido na CPU (medido em 1280x720). Com o padrão (1 quadro a cada 1,5 s), uma hora de
gameplay leva alguns minutos a mais na pontuação. Limites: letras pequenas, fundo muito poluído ou fontes
estilizadas podem não ser lidas; `--ocr-region` com a área do aviso e `--ocr-every` menor ajudam.

## Animação em HTML (`scripts/animar_html.py`: GSAP, Three.js, canvas)
Renderiza uma página HTML/CSS/JS quadro a quadro num Chromium sem janela (Playwright) e grava vídeo com FFmpeg, com fundo
transparente se quiser. É a mesma ideia do Remotion/HyperFrames, sem Node e sem licença de empresa (o Remotion é grátis só
para pessoas, ONGs e empresas com até 3 funcionários; acima disso é pago). Precisa de `pip install -r requirements-animacao.txt`
e `python -m playwright install chromium` (os scripts de setup fazem isso).
```bash
python scripts/animar_html.py titulo --dados '{"titulo":"CLUTCH INSANO","subtitulo":"@meucanal"}' -o titulo.mov   # transparente
python scripts/animar_html.py titulo --dados '{"titulo":"RANKED"}' --fundo "#0b1020" -o intro.mp4               # opaco
python autoedit.py gameplay.mp4 --extras on --intro-video intro.mp4                                             # usa como intro
python scripts/animar_html.py terco_inferior --dados '{"nome":"Danyllo","cargo":"Gameplay"}' --sobre video.mp4 --em 3 -o com_nome.mp4
```
Modelos prontos em `scripts/animacoes/` (`titulo`, `terco_inferior`). Para criar o seu: um `.html` que lê `window.DADOS`, define
`window.seek(t)` (com GSAP: `tl.pause(); window.seek = t => tl.time(t)`) e, se quiser, `window.DURACAO`. Qualquer biblioteca
serve (Three.js, canvas...), desde que o quadro dependa só de `t`. O GSAP é baixado uma vez para `~/.cache/autoedit`.
Opções: `--duracao S`, `--fps N` (30), `--res LxA` (1920x1080; Shorts 1080x1920), `--fundo #RRGGBB`, `--sobre VIDEO --em S` (renderiza no
tamanho do vídeo), saída `.mov`/`.webm` (transparentes) ou `.mp4`. Custo: ~7 s para 2,8 s de animação 1080p. Fonte padrão é
Impact/Arial Black (no Linux cai para DejaVu).

## Recorte de pessoa e rastreamento (`scripts/pessoa_fundo.py`, `scripts/rastrear.py`)
Ferramentas separadas (não passam por `autoedit.py`); rodam na CPU e baixam os modelos sozinhas na 1ª vez para `~/.cache/autoedit`.
Precisam de `pip install -r requirements-visao.txt` (os scripts de setup já instalam).
```bash
# Título grande ATRÁS da pessoa (como no vídeo de referência), entrando aos 0,2 s e saindo aos 4 s
python scripts/pessoa_fundo.py eu.mp4 --titulo "CLUTCH INSANO" --de 0.2 --ate 4 --modelo humano
# Trocar o fundo sem tela verde: blur | escuro | cor:#RRGGBB | imagem.jpg
python scripts/pessoa_fundo.py eu.mp4 --fundo blur
# Seguir um objeto: marca (anel/caixa + texto) que acompanha, ou recorte vertical que o acompanha
python scripts/rastrear.py clipe.mp4 --ver                                   # salva o 1º quadro com grade p/ achar a caixa
python scripts/rastrear.py clipe.mp4 --caixa 100,200,300,300 --texto "OLHA"  # também grava <saida>.json com a posição por quadro
python scripts/rastrear.py clipe.mp4 --caixa 0.1,0.3,0.2,0.2 --seguir -o vertical.mp4
```
`--modelo leve` (padrão, 4,6 MB) é rápido mas a borda sai grosseira; `--modelo humano` (176 MB, baixado uma vez) recorta bem melhor.
O recorte pega "o que está em destaque": funciona melhor com uma pessoa sozinha e separada do fundo. Custo medido: ~20 s para
4 s de vídeo 720p na CPU (use `--cada 2` para acelerar). O rastreador (VitTrack) perde o objeto se ele sai da tela ou é coberto;
o JSON marca esses quadros com `perdido: true`.

## Vídeos de apoio gratuitos (`--broll`: Pexels ou Pixabay)
Use a fonte que lhe der chave. **O Pexels pausou a emissão de chaves novas** (visto na página em 12/11/2026): só serve se você já tiver uma.
- **Pixabay:** crie conta em pixabay.com e procure a chave na documentação da API (pixabay.com/api/docs); ela aparece logada, na hora (de memória, não conferido).
- **Pexels:** pexels.com/api, quando voltarem a emitir chaves.
1. Guarde a chave fora do repositório: `setx PIXABAY_API_KEY "sua_chave"` (Windows, vale em janelas novas) ou `export PIXABAY_API_KEY=...`.
2. `python autoedit.py gravacao.mp4 --cut-silences --subs --broll "city night,keyboard typing" --broll-every 20`
Os vídeos baixados ficam em `~/.cache/autoedit/broll`; os créditos vão para `creditos_broll.txt` na pasta de saída.
Os dois sites permitem uso comercial pelas licenças deles (confira os termos atuais antes de monetizar). O Pixabay não filtra orientação:
no Short o código prefere vídeos verticais e, se não houver, usa os horizontais recortados.
Limites das APIs (de memória, não conferidos agora; veja na sua conta): Pexels ~200 pedidos/hora; Pixabay ~100 pedidos/minuto.

## Como escolhe os trechos
Cada cena (PySceneDetect) é pontuada por energia do áudio e movimento da imagem; cenas longas
são fatiadas em blocos. Entram os de maior nota até a duração-alvo, em ordem cronológica.
Ajuste `--audio-weight` se o jogo for silencioso (use menos) ou cheio de gritos (use mais).

## Exemplos (gerados com material sintético de teste)
- `examples/exemplo_video_final.mp4` — vídeo final com intro, cortes e música
- `examples/exemplo_shorts_legenda.mp4` — Short vertical 9:16 com legenda
- `examples/exemplo_miniatura.jpg` — miniatura gerada

## Testar sem gameplay
```bash
./scripts/make_test_footage.sh
python autoedit.py test_footage/gameplay_test.mp4 --target 80 --music test_footage/music --extras on --shorts
```

## Baixar o seu vídeo do YouTube
Vídeos próprios: YouTube Studio → Conteúdo → ⋮ → *Fazer download*. Ou use a gravação original (OBS, GeForce).

No Windows, o script `scripts/baixar_video.ps1` faz o download com o `yt-dlp` (`winget install yt-dlp.yt-dlp Gyan.FFmpeg`):
```powershell
.\scripts\baixar_video.ps1 https://youtu.be/ID_DO_VIDEO                 # 720p em Documentos\Autoedit (OneDrive) ou Downloads
.\scripts\baixar_video.ps1 https://youtu.be/ID_DO_VIDEO -Altura 480     # arquivo menor
.\scripts\baixar_video.ps1 https://youtu.be/ID_DO_VIDEO -SoLegenda      # só a legenda (.srt)
.\scripts\baixar_video.ps1 https://youtu.be/ID_DO_VIDEO -Navegador chrome   # se pedir "confirmar que não é robô"
```
Se der erro de política de execução, rode antes: `Set-ExecutionPolicy -Scope Process Bypass`.
Use só com vídeos seus ou que você tenha direito de usar.

## Aprender com um vídeo (skill `watch`)
`scripts/watch_video.py` "assiste" um vídeo e gera um **dossiê** (`dossie_<id>/dossie.md` com transcrição e horários,
`quadros/*.jpg` e `folha_NN.jpg` com miniaturas) que o Claude lê para extrair funcionalidades. A skill
`.claude/skills/watch` descreve o fluxo: cole o link no chat, rode o comando que ele devolver no seu PC e o dossiê
cai em `Documentos\Autoedit` (OneDrive).
```powershell
winget install yt-dlp.yt-dlp Gyan.FFmpeg DenoLand.Deno
python scripts\watch_video.py "https://youtu.be/ID_DO_VIDEO" --lang pt
python scripts\watch_video.py meu_video.mp4 --frames 30 --no-transcribe     # arquivo local, sem Whisper
```
| Opção | O que faz |
|---|---|
| `--out PASTA` | onde gravar (padrão: `Documentos\Autoedit` do OneDrive, senão `autoedit_out/watch`) |
| `--frames N` | máximo de quadros-chave (padrão 24; mistura mudanças de cena + amostragem uniforme) |
| `--scene-threshold X` | sensibilidade de mudança de cena, 0-1 (padrão 0.25) |
| `--altura H` | altura máxima ao baixar (padrão 720) |
| `--navegador chrome` | usa o login do navegador se o YouTube pedir "confirmar que não é robô" |
| `--whisper-model M` / `--lang L` | modelo (padrão `small`) e idioma da transcrição |
| `--no-transcribe` | pula o Whisper (usa a legenda do site, se houver) |

O download de links do YouTube não funciona a partir de servidores na nuvem (bloqueio anti-robô); rode no seu PC.

### Fila de vídeos (pedir de qualquer aparelho)
`scripts/watch_fila.py` fica rodando num PC seu que fica ligado e vigia `Documentos\Autoedit\fila` no OneDrive.
Cada `.txt` com um link que cair ali vira um dossiê em `Autoedit\dossie_<id>`. O Claude grava o `.txt` para você
quando você cola o link no chat (pelo celular, notebook, onde estiver) e depois lê o dossiê.
```powershell
python scripts\watch_fila.py                 # deixa rodando (Ctrl+C para parar)
python scripts\watch_fila.py --once          # processa o que houver e sai
```
Para iniciar junto com o Windows (rode dentro da pasta do repositório; `pythonw` não abre janela):
```powershell
$py = (Get-Command pythonw).Source
schtasks /Create /TN "AutoeditFila" /SC ONLOGON /TR "`"$py`" `"$PWD\scripts\watch_fila.py`"" /F
# remover depois:  schtasks /Delete /TN "AutoeditFila" /F
```
Formato do `.txt` (uma entrada por linha): o link, ou o nome de um vídeo já presente em `Autoedit`, mais `lang=pt`,
`frames=30` e `navegador=chrome` (opcionais). Resultados: `fila\feitos\` (ok), `fila\erros\` (com o motivo) e
`fila\_status.log` (mostra se o vigia está vivo). Aceita as mesmas opções de `watch_video.py` (`--whisper-model`...),
mais `--intervalo S` (padrão 30). O PC precisa estar ligado e sem suspender; senão o pedido espera na fila.

## Revisar o vídeo final (`scripts/qa_video.py`)
Antes de publicar, confira o resultado de verdade, como no vídeo de referência ("o modelo assistiu ao próprio vídeo"):
```bash
python scripts/qa_video.py autoedit_out/meu_final.mp4                       # volume, silêncios, telas pretas, quadros
python scripts/qa_video.py final.mp4 --roteiro roteiro.txt --lang pt        # compara a fala do áudio final com o texto esperado
```
Gera `autoedit_out/qa_<video>/qa_report.md` com avisos, `folha_NN.jpg` (grades de quadros com horário, para olhar se
algum texto cobriu algo) e a transcrição do áudio final. Opções: `--lufs-alvo` (padrão -16), `--max-silencio` (padrão 3 s),
`--frames` (padrão 12), `--whisper-model`, `--lang`, `--no-transcribe`, `--out`.

## Mapa: técnicas do vídeo de referência x este projeto
Fonte: vídeo "Claude cria e edita vídeo com um único prompt" (analisado com a skill `watch`).
| Técnica citada | Situação |
|---|---|
| Ducking, loudness nos padrões das plataformas | tem (`--lufs` ajusta o alvo) |
| Legendas a partir da transcrição | tem: por frase e palavra a palavra (`--sub-mode`) |
| Revisão do vídeo final (quadros, volume, roteiro) | tem: `scripts/qa_video.py` |
| Cortar gravação falada, tirar silêncios, EDL | tem: `--cut-silences` (não remove "erros" de fala, só silêncio) |
| Easing e transições | tem no slideshow (`--photo-transition`, zoom suave) |
| Detecção de rosto (recorte do Short seguindo o rosto) | tem: `--short-crop face/facecam` (testado com foto de rosto em vídeo sintético; não testado com webcam real) |
| Recorte de pessoa/fundo (título atrás de você), rastreamento de objetos | tem: `scripts/pessoa_fundo.py` e `scripts/rastrear.py` (testados com uma foto de rosto em vídeo sintético; não testados com gravação real) |
| OCR (ler texto na tela e dar nota ao trecho) | tem: `--ocr` (RapidOCR), mas só para texto escrito; kills do Arc Raiders são só visuais, então não servem |
| Legenda palavra a palavra | tem: `--sub-mode group/word` (testado com fala sintética em inglês; não testado em pt) |
| Cortes em cima de palavras | falta |
| Animação por código (Remotion, HyperFrames, GSAP, Three.js: navegador sem janela + FFmpeg) | tem: `scripts/animar_html.py` (GSAP em 2 modelos prontos; Three.js não testado; no Windows não testado) |
| Vídeos de apoio (Pexels/Pixabay) + acerto de cor | tem: `--broll` (testado com servidor de mentira e com chave real do Pixabay no PC do usuário; Pexels está sem emitir chaves; serve para vídeo falado, não para gameplay) |
| Voz (ElevenLabs), avatar (HeyGen), efeitos sonoros e trilha por texto | falta; serviços pagos com conta/chave |
Chaves e contas nunca entram no repositório.

## Limitações conhecidas
- A nota usa áudio + movimento. Abates e vitórias que são só visuais (Arc Raiders) não são detectados; `--ocr` só lê texto escrito. Falta um sinal visual (ex.: comparar com uma imagem de referência do indicador).
- Legendas dependem do modelo Whisper (`--whisper-model small` por padrão; `medium` é mais preciso).
- `watch` vê só a transcrição e quadros espaçados, não o vídeo inteiro.
- Fotos viram slideshow com cortes secos por padrão (use `--photo-transition`).
