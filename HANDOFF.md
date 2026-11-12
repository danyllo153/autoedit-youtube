# HANDOFF - estado do projeto autoedit-youtube

Atualizado em 11/11/2026 (fim da sessão da nuvem). Branch: `claude/gifted-ptolemy-utozea` (PR para `main`).
Leia também: `CLAUDE.md` (regras do projeto, lido sozinho pelas sessões) e `README.md` (uso e tabela de opções).

## 1. Para retomar em uma sessão nova (copiar e colar)
```bash
git checkout claude/gifted-ptolemy-utozea   # ou main, depois que o PR for mergeado
./scripts/setup_sessao.sh                   # ffmpeg + dependências Python + OCR + yt-dlp (idempotente)
./scripts/make_test_footage.sh              # material sintético em test_footage/
python autoedit.py test_footage/gameplay_test.mp4 --target 80 --extras on --shorts
```
Windows: `.\scripts\setup_windows.ps1` (não testado em máquina limpa). Use `py`, não `python` (atalho da Store).
Instalações feitas só dentro de uma sessão da nuvem somem com ela; o que importa está em `requirements*.txt` e nos
scripts de setup.

## 2. O que existe (ferramentas)
**`autoedit.py`** (arquivo único) - pipeline de edição. Modos e opções novas desta rodada (tabela completa no README):
| Recurso | Opção | Para quê |
|---|---|---|
| Melhores momentos (já existia) | `--target`, `--audio-weight`, `--min-motion`... | cenas + pontuação áudio/movimento |
| Volume final configurável | `--lufs` | padrão -16; YouTube normaliza perto de -14 |
| Cortar gravação falada | `--cut-silences`, `--silence-db`, `--min-silence`, `--pad` | remove silêncios e grava `*.edl` (CMX 3600, ~30 fps) |
| Slideshow com easing e transições | `--photo-transition`, `--transition-secs` | zoom suave por padrão; xfade entre fotos |
| OCR de texto na tela | `--ocr`, `--ocr-keywords`, `--ocr-weight`, `--ocr-every`, `--ocr-region` | nota extra por palavras escritas; grava `*_ocr.json` |
| Whisper | (correção) | cai para CPU se faltar `cublas64_12.dll` |

**`scripts/`**
- `qa_video.py` - revisão do vídeo FINAL: LUFS/pico, silêncios, telas pretas, quadros + folhas, fala x `--roteiro`.
- `watch_video.py` - gera o **dossiê** (transcrição com horários + quadros + folhas) de um link ou arquivo.
- `watch_fila.py` - **vigia** que roda num PC do usuário e processa pedidos `.txt` em `OneDrive\Documentos\Autoedit\fila`.
- `baixar_video.ps1` - baixa vídeo/legenda com yt-dlp no Windows.
- `setup_sessao.sh` / `setup_windows.ps1` - preparam o ambiente. `make_test_footage.sh` - material sintético.

**Skill `watch`** (`.claude/skills/watch/SKILL.md`): aprender com um vídeo (link ou arquivo). Também manda rodar o
`qa_video.py` depois de editar qualquer vídeo.

## 3. Como o fluxo "colar um link e o Claude aprende" funciona
O YouTube bloqueia download a partir da nuvem ("Sign in to confirm you're not a bot"); não tente contornar.
1. Usuário cola o link. Claude grava `fila/<id>.txt` (link + `lang=`/`frames=`/`navegador=` opcionais) no OneDrive.
2. O vigia (`py scripts\watch_fila.py`, PC ligado) baixa, transcreve (Whisper na CPU) e grava `dossie_<id>/`.
3. Claude lê `dossie.md` e as `folha_NN.jpg` pelo conector **Microsoft 365** (OneDrive).
Resultados: `fila\feitos\` (ok), `fila\erros\` (motivo), `fila\_status.log` (vigia vivo = atualizado há < 3 min).
O conector é da conta do usuário no claude.ai (não vem no repositório) e **não entrega vídeo binário grande**.
Para iniciar o vigia com o Windows: comando `schtasks` no README ("Fila de vídeos"), usando o caminho completo do
`pythonw.exe` (não testado).

## 4. O que foi aprendido do vídeo de referência
Vídeo "Claude cria e edita vídeo com um único prompt" (7min35), analisado via dossiê (`dossie_video_referencia` no OneDrive).
Técnicas citadas e situação (detalhe na seção "Mapa" do README):
- Já tínhamos: ducking. Passamos a ter: loudness configurável, revisão do vídeo final, corte de silêncio + EDL,
  easing/transições, OCR de texto.
- Faltam: detecção de rosto (recorte do Short), recorte de fundo, rastreamento, legenda palavra a palavra,
  animação por código (Remotion/GSAP/Three.js), Pexels (chave gratuita), ElevenLabs/HeyGen (pagos).
O vídeo é demonstração e divulgação; as afirmações dele não foram verificadas.

## 5. O que foi testado e o que NÃO foi
Testado (material sintético, conferido com ffprobe e quadros extraídos): `--cut-silences` (cortou os silêncios esperados e
gerou EDL), `--lufs` (-15,9 e -22,9 medidos), transições (duração e mistura conferidas), `qa_video.py` (caso bom e ruim),
`--ocr` (achou textos conhecidos, ignorou texto isca, regiões da tela), comando de teste do projeto sem regressão,
vigia da fila e dossiê rodando de verdade no PC do usuário.
**Não testado:** `setup_windows.ps1`, `baixar_video.ps1`, o `schtasks`, o download de link do YouTube pelo vigia
(o usuário baixou à mão), a EDL aberta num editor, qualquer coisa com gameplay real do Arc Raiders.

## 6. Pendências e decisões abertas
1. **Kills/vitórias no Arc Raiders são só visuais** (sem texto): `--ocr` não os detecta. O usuário disse que só Call of Duty
   escreve o abate. Ideia adiada: comparar quadros com uma imagem de referência do indicador (`cv2.matchTemplate`, sem
   dependência nova). Precisa de 1-2 capturas do momento do abate e de dizer onde na tela aparece (podem ir na pasta
   `Autoedit` do OneDrive; imagens o Claude consegue abrir).
2. Palavras padrão do `--ocr` (`victory`, `extracted`...) são palpites, não conferidos com o jogo.
3. Próximas técnicas do mapa, em ordem de custo/benefício: legenda palavra a palavra (Whisper `word_timestamps`),
   detecção de rosto para o Short, Pexels (precisa de chave).
4. Rodar `autoedit.py` e `qa_video.py` num trecho de gameplay real e ajustar `--audio-weight`, `--min-motion` e `--ocr-*`.

## 7. Armadilhas (resumo; lista completa no `CLAUDE.md`)
- `av` 17+ quebra o `faster-whisper`: manter `av<17`.
- Windows: `python` pode ser o atalho da Store (use `py`); `winget` só atualiza o PATH em janela nova do PowerShell.
- OCR: recortes finos da tela precisam de preenchimento (já feito); `--ocr-every` menor acha textos curtos, mas demora mais.
- Nunca commitar vídeos, `test_footage/`, `autoedit_out/`, `dossie_*/` nem chaves/tokens.

## 8. Ambiente e pessoas
- Ambiente da nuvem: "Autoeditor - videos/shorts/reels" (pessoal, rede irrestrita nesta sessão). O usuário decidiu **não** criar
  script de setup no ambiente; só o que está no repositório vale.
- O PC do usuário é Windows com placa NVIDIA (sem as DLLs CUDA do Whisper, por isso a CPU). Pasta de trabalho no OneDrive:
  `Documentos\Autoedit` (contém `video_referencia.mp4`, `dossie_video_referencia/` e `fila/`).
- Nenhuma tarefa agendada ficou ativa no fim desta sessão.
