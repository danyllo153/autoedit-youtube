# autoedit-youtube

Edição automática para YouTube (gameplay, vídeos, fotos): Python + FFmpeg + PySceneDetect + Whisper.

Pipeline em Python + FFmpeg: acha as melhores partes com PySceneDetect, monta o vídeo,
adiciona música, legenda automática (Whisper) e, se o vídeo for grande, intro + miniatura.

## Instalação
1. Instale o FFmpeg e deixe no PATH (`ffmpeg -version` deve funcionar).
2. `pip install -r requirements.txt`

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
| `--min-motion X` | descarta trechos parados (menus/inventário) abaixo de X × mediana de movimento (padrão 0.5) |
| `--gpu` | exporta com NVENC (placa NVIDIA) |

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

## Limitações conhecidas
- A nota dos trechos usa só áudio + movimento; não "entende" o jogo (kills, vitória).
- Legendas dependem do modelo Whisper (`--whisper-model small` por padrão; `medium` é mais preciso).
- `watch` vê só a transcrição e quadros espaçados, não o vídeo inteiro.
- Fotos viram slideshow com cortes secos (sem transição).
