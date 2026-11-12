---
name: watch
description: "Assiste" um vídeo (link do YouTube ou arquivo) lendo a transcrição e os quadros-chave, e extrai dele funcionalidades, técnicas e ideias para o autoedit. Use quando o usuário colar um link de vídeo ou pedir para "assistir/analisar/aprender com" um vídeo.
---

# watch - aprender com um vídeo

Claude não vê vídeo direto. O `scripts/watch_video.py` gera um **dossiê** (transcrição com horários +
quadros-chave + folhas de miniaturas) e a análise é feita em cima dele. O YouTube bloqueia download a partir
da nuvem ("Sign in to confirm you're not a bot"): **não tente baixar aqui nem contornar o bloqueio**.
Quem baixa é um PC do usuário, pelo vigia `scripts/watch_fila.py`, usando a pasta `Documentos\Autoedit` do OneDrive.

## 1. Pedir o dossiê (usuário colou um link)
1. `sharepoint_folder_search` por "Autoedit" (guarde o `driveId`/id da pasta) e depois por "fila".
2. Se a pasta `fila` existir, leia `fila/_status.log` (`read_resource`). Vigia vivo = `atualizado:` com menos
   de ~3 minutos (ele escreve a cada ~30 s). Se `fila` não existir ou o log estiver velho, o vigia não está
   rodando: vá para "Plano B".
3. Vigia vivo: avise o usuário e grave o pedido com `sharepoint_upload_file` na pasta `fila`, arquivo
   `<id-do-video>.txt`, conteúdo (uma entrada por linha; `lang=pt`, `frames=30`, `navegador=chrome` são opcionais):
   ```
   https://youtu.be/ID
   lang=pt
   ```
4. Espere (o download + Whisper levam alguns minutos; confira a cada ~1-2 min, sem insistir em loop curto):
   `fila/feitos/<id>.txt` (ok; diz qual `dossie_*`) ou `fila/erros/<id>.txt` (mostre o motivo ao usuário).
5. Se aparecer "Sign in to confirm you're not a bot", regrave o pedido com `navegador=chrome`.

**Plano B (sem vigia):** peça ao usuário para rodar no PC dele, dentro do clone do repositório:
```powershell
python scripts\watch_video.py "LINK" --lang pt        # (--navegador chrome se pedir login)
```
Requisitos no PC: `winget install yt-dlp.yt-dlp Gyan.FFmpeg DenoLand.Deno` e `pip install -r requirements.txt`.
Para um vídeo já baixado em `Autoedit`, passe o caminho do arquivo no lugar do link.
Se o Claude Code estiver rodando no próprio PC do usuário, ou o link não for do YouTube, pode rodar direto.

## 2. Ler o dossiê (`Autoedit/dossie_<id>/`)
1. `dossie.md`: título, capítulos, descrição e transcrição com horários (leia inteiro; use `startPage` se paginar).
2. As `folha_NN.jpg` (grade 3x3 com horário): olhe todas. Abra `quadros/` só nos trechos em que a transcrição
   fala de algo visual (tela de programa, comando, resultado).
3. Diga o que NÃO deu para saber (sem transcrição, sem áudio, só quadros espaçados) em vez de inventar.

## 3. Extrair o que importa para o projeto
Relacione com o `autoedit.py` (pipeline único em Python + FFmpeg; veja README). Entregue uma lista curta:
- funcionalidade/técnica, **onde no vídeo** (horário), e como entraria no projeto (parâmetro novo? passo do pipeline?);
- o que já existe no `autoedit.py` e o que é novo; esforço (P/M/G) e dependências extras (Windows-friendly).
Mostre a lista ao usuário **antes de codar**. Depois implemente uma por commit, seguindo as convenções do projeto
(argparse + tabela do README, testes com `scripts/make_test_footage.sh`, conferir com ffprobe/frames).

Depois de editar um vídeo, **revise o resultado** com `python scripts/qa_video.py arquivo_final.mp4` (e olhe as
`folha_NN.jpg` geradas) antes de dizer que está pronto.

Nunca commite `dossie_*`, vídeos nem `autoedit_out/`.
