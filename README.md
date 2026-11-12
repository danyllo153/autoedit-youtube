# autoedit-youtube

Edição automática para YouTube (gameplay, vídeos, fotos): Python + FFmpeg + PySceneDetect + Whisper.

Pipeline em Python + FFmpeg: acha as melhores partes com PySceneDetect, monta o vídeo,
adiciona música, legenda automática (Whisper) e, se o vídeo for grande, intro + miniatura.

## Instalação
1. Instale o FFmpeg e deixe no PATH (`ffmpeg -version` deve funcionar).
2. `pip install -r requirements.txt`
3. (opcional, para `--ocr`) `pip install -r requirements-ocr.txt`

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

# Gameplay: dá nota extra a trechos em que aparece kill/vitória na tela (OCR)
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
| `--extras auto/on/off` | intro + miniatura (auto = só se final >= `--long-min`, padrão 180 s) |
| `--intro-video ARQ` | usa sua intro em vez da gerada |
| `--shorts` | gera versão vertical 9:16 de até 58 s |
| `--shorts-only` | gera só o Short vertical |
| `--short-crop square` | Short: recorta o centro 1:1 (gameplay maior; perde bordas/HUD) |
| `--ocr` | lê o texto da tela (RapidOCR) e dá nota extra a trechos com palavras de kill/vitória; grava `*_ocr.json` com o que leu |
| `--ocr-keywords "a=1,b=0.7"` | palavras que marcam bons momentos, com peso 0-1 (o padrão são palpites: calibre com o `*_ocr.json`) |
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
| `--gpu` | exporta com NVENC (placa NVIDIA) |

## OCR: pontuar kills e vitórias (`--ocr`)
O jogo avisa na tela ("VICTORY", "ELIMINATED"...); o `--ocr` lê esses textos em alguns quadros de cada trecho e
dá nota extra a quem tem palavra-chave. Trechos com palavra-chave nunca são descartados pelo filtro de cena parada
(`--min-motion`), porque a tela de vitória costuma ser parada.

**Calibre com o seu jogo:** as palavras padrão são palpites genéricos, ainda não conferidos com gameplay real de
Arc Raiders. Rode uma vez com `--ocr --plan-only`, abra `autoedit_out/<nome>_ocr.json` (o texto que o OCR leu em cada
trecho), veja como o seu HUD escreve os avisos e passe as palavras certas em `--ocr-keywords`. Se o aviso aparece
sempre no mesmo canto, `--ocr-region` deixa a leitura mais rápida e evita falsos positivos.

Custo: cerca de 0,2 s por quadro lido na CPU (medido em 1280x720). Com o padrão (1 quadro a cada 1,5 s), uma hora de
gameplay leva alguns minutos a mais na pontuação. Limites: letras pequenas, fundo muito poluído ou fontes
estilizadas podem não ser lidas; `--ocr-region` com a área do aviso e `--ocr-every` menor ajudam.

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
| Legendas a partir da transcrição | tem (por trecho; falta palavra a palavra) |
| Revisão do vídeo final (quadros, volume, roteiro) | tem: `scripts/qa_video.py` |
| Cortar gravação falada, tirar silêncios, EDL | tem: `--cut-silences` (não remove "erros" de fala, só silêncio) |
| Easing e transições | tem no slideshow (`--photo-transition`, zoom suave) |
| Detecção de rosto (recorte do Short seguindo o rosto) | falta; viável com OpenCV, precisa de gravação com rosto para testar |
| Recorte de pessoa/fundo (título atrás de você), rastreamento de objetos | falta; exige modelos de visão (segmentação/tracking) |
| OCR (achar "VICTORY", kills etc. na tela e dar nota ao trecho) | tem: `--ocr` (RapidOCR; testado com vídeo sintético, falta calibrar as palavras com gameplay real) |
| Legenda palavra a palavra / cortes em cima de palavras | falta; viável com `word_timestamps` do Whisper |
| Animação por código (Remotion, HyperFrames, GSAP, Three.js: navegador sem janela + FFmpEG) | falta; stack JS/Chromium |
| Vídeos de apoio (Pexels API) + acerto de cor | falta; precisa de chave da API (gratuita) |
| Voz (ElevenLabs), avatar (HeyGen), efeitos sonoros e trilha por texto | falta; serviços pagos com conta/chave |
Chaves e contas nunca entram no repositório.

## Limitações conhecidas
- Sem `--ocr`, a nota dos trechos usa só áudio + movimento; com `--ocr` ela também lê avisos na tela (palavras a calibrar).
- Legendas dependem do modelo Whisper (`--whisper-model small` por padrão; `medium` é mais preciso).
- `watch` vê só a transcrição e quadros espaçados, não o vídeo inteiro.
- Fotos viram slideshow com cortes secos por padrão (use `--photo-transition`).
