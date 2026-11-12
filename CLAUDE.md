# autoedit-youtube - guia para sessões do Claude

Pipeline em Python + FFmpeg que edita vídeos de gameplay para o YouTube (principalmente Arc Raiders):
PySceneDetect divide em cenas e pontua (energia do áudio + movimento), escolhe os melhores trechos, monta o
vídeo, música com ducking, legendas com Whisper; vídeo grande (>= 180 s) ganha intro + miniatura; `--shorts`
gera 9:16; pasta de fotos vira slideshow. Arquivos: `autoedit.py` (tudo), `requirements.txt`, `README.md`,
`scripts/`, `examples/`, `.claude/skills/watch/`.

> Estado atual, pendências e o que foi testado: leia o `HANDOFF.md`.

## Começar uma sessão
```bash
./scripts/setup_sessao.sh        # Linux/nuvem: ffmpeg + pip install -r requirements.txt + yt-dlp (idempotente)
# Windows: .\scripts\setup_windows.ps1   (não testado em máquina limpa)
./scripts/make_test_footage.sh   # material sintético em test_footage/
python autoedit.py test_footage/gameplay_test.mp4 --target 80 --extras on --shorts
```
Instalações feitas só na sessão da nuvem somem com ela: tudo que for necessário deve estar em
`requirements.txt` ou nos scripts de setup. Ao adicionar uma dependência/ferramenta, atualize esses arquivos.

## Como trabalhar
- Antes de mexer, leia `autoedit.py` e o README.
- Teste sempre com material sintético e **confira o resultado de verdade** (ffprobe, extrair frames e olhar),
  não só "rodou sem erro".
- Mudanças pequenas e focadas; mantenha `autoedit.py` em um único arquivo, salvo pedido de modularizar
  (os auxiliares ficam em `scripts/`).
- Todo parâmetro novo vai para o argparse **e** para a tabela de opções do README.
- Windows é o sistema do usuário: use `pathlib`, evite caminhos/comandos só de Linux.

## Convenções
- Commits em Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`), um assunto por commit.
  Código e README em português; mensagens de commit em inglês.
- Nunca commitar vídeos grandes, `test_footage/`, `autoedit_out/`, `dossie_*/` nem chaves/tokens (ver `.gitignore`).

## Skill `watch`: aprender com um vídeo (link ou arquivo)
Claude não vê vídeo; `scripts/watch_video.py` gera um dossiê (transcrição com horários + quadros-chave + folhas de
miniaturas) e a análise é feita em cima dele. Detalhes e passo a passo em `.claude/skills/watch/SKILL.md`.
- **O YouTube bloqueia download a partir da nuvem** (anti-robô). Quem baixa é um PC do usuário, pelo vigia
  `scripts/watch_fila.py`, que lê pedidos `.txt` em `OneDrive\Documentos\Autoedit\fila` e grava `dossie_<id>`.
  Claude grava o pedido e lê o dossiê pelo conector **Microsoft 365** (OneDrive); esse conector é da conta do
  usuário no claude.ai, não vem no repositório. Não tente contornar o bloqueio do YouTube.
- O vigia só funciona com o PC ligado; `fila\_status.log` mostra se está vivo (atualiza a cada ~30 s).

## Ferramentas do projeto (resumo)
- `autoedit.py`: pipeline principal. Modos: melhores momentos (cenas + pontuação), `--cut-silences` (gravação falada + EDL),
  fotos (slideshow com `--photo-transition`), `--shorts`/`--shorts-only`. `--lufs` ajusta o volume final.
- `--ocr` (RapidOCR, `requirements-ocr.txt`): pontua trechos por TEXTO escrito na tela; grava `<nome>_ocr.json` para calibrar.
  **No Arc Raiders o abate ao vivo é só visual (sem texto): o OCR não detecta kills lá** (informado pelo usuário: só Call of Duty escreve o abate; o OCR serve para esse tipo de jogo).
  Recortes finos precisam de preenchimento (já feito no código): o detector não lê faixas com menos de ~200 px.
  As palavras padrão são palpites, não conferidos com o jogo.
- `--sub-mode group/word` (legenda palavra a palavra, ASS), `--short-crop face/facecam` (YuNet), `--broll` (Pexels ou Pixabay, chaves em
  `PEXELS_API_KEY`/`PIXABAY_API_KEY`, nunca no repositório; o Pexels pausou chaves novas): ver README.
- `scripts/pessoa_fundo.py` (título atrás da pessoa / troca de fundo), `scripts/rastrear.py` (rastreio de objeto),
  `scripts/animar_html.py` (animação HTML/GSAP -> vídeo): ver README. Modelos baixam sozinhos para `~/.cache/autoedit`.
- `scripts/qa_video.py`: revisão do vídeo FINAL (LUFS/pico, silêncios, telas pretas, quadros, fala x roteiro). Rode antes de entregar.
- `scripts/watch_video.py` / `watch_fila.py`: dossiê de um vídeo de referência (skill `watch`).
- Mapa do que o vídeo de referência cita e ainda falta (rosto, OCR, Pexels, TTS...): seção "Mapa" do README.

## Armadilhas já encontradas
- `av` 17+ quebra o `faster-whisper` (`metadata_errors`): manter `av<17` no `requirements.txt`.
- Whisper com `device="auto"` tenta a GPU NVIDIA e falha sem `cublas64_12.dll`: o código já recarrega na CPU.
- Windows: `python` pode ser o atalho da Microsoft Store ("Python não foi encontrado"); use `py`.
- Windows: `winget` só atualiza o PATH em janela nova do PowerShell (ou recarregar `$env:Path`).
- O conector do OneDrive não entrega vídeo binário grande; por isso o dossiê (arquivos pequenos) existe.
- `scenedetect[opencv]` avisa que o extra não existe na 0.7.x; é inofensivo (o OpenCV vem instalado).
- OpenCV 5 (o que o pip instala hoje) NÃO tem mais `CascadeClassifier`/Haar: rosto usa `cv2.FaceDetectorYN` (YuNet, baixado do Hugging Face).
- `raw.githubusercontent.com/opencv/opencv_zoo/...*.onnx` devolve um ponteiro Git LFS (131 bytes), não o modelo: use o Hugging Face.

## Limitações conhecidas (candidatas a melhorias)
- A pontuação não enxerga abates/vitórias só visuais (Arc Raiders): usa áudio + movimento (+ `--ocr` para texto escrito).
- Legenda depende do download do modelo Whisper.
- Slideshow: transições só com `--photo-transition` (padrão é corte seco).
