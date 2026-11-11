# autoedit-youtube

Edição automática para YouTube (gameplay, vídeos, fotos): Python + FFmpeg + PySceneDetect + Whisper.

Pipeline em Python + FFmpeg: acha as melhores partes com PySceneDetect, monta o vídeo,
adiciona música, legenda automática (Whisper) e, se o vídeo for grande, intro + miniatura.

## Instalação
1. Instale o FFmpeg e deixe no PATH (`ffmpeg -version` deve funcionar).
2. `pip install -r requirements.txt`

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

## Limitações conhecidas
- A nota dos trechos usa só áudio + movimento; não "entende" o jogo (kills, vitória).
- Legendas dependem do modelo Whisper (`--whisper-model small` por padrão; `medium` é mais preciso).
- Fotos viram slideshow com cortes secos (sem transição).
