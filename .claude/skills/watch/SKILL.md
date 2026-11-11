---
name: watch
description: "Assiste" um vídeo (link do YouTube ou arquivo) lendo a transcrição e os quadros-chave, e extrai dele funcionalidades, técnicas e ideias para o autoedit. Use quando o usuário colar um link de vídeo ou pedir para "assistir/analisar/aprender com" um vídeo.
---

# watch - aprender com um vídeo

Claude não vê vídeo direto. O `scripts/watch_video.py` gera um **dossiê** (transcrição com horários +
quadros-chave + folhas de miniaturas) e a análise é feita em cima dele.

## 1. Conseguir o dossiê

**Se o usuário colou um link:** o YouTube bloqueia download a partir da nuvem ("Sign in to confirm you're not a bot"),
então não tente baixar aqui nem contornar o bloqueio. Devolva ao usuário este comando para rodar no PC dele
(Windows/PowerShell), com o link já preenchido. A saída vai para `Documentos\Autoedit` do OneDrive:

```powershell
python scripts\watch_video.py "LINK" --lang pt
# se pedir login:  --navegador chrome      (cookies ficam só no PC dele)
```
(Se o Claude Code estiver rodando no próprio PC do usuário, ou o link não for do YouTube, pode rodar direto.)

Requisitos no PC: `winget install yt-dlp.yt-dlp Gyan.FFmpeg DenoLand.Deno` e `pip install -r requirements.txt`
(o Deno evita "formatos faltando" no YouTube). Depois que ele avisar que terminou, ache a pasta `dossie_<id>`
no OneDrive (`sharepoint_folder_search` por "dossie", depois `read_resource` na pasta e nos arquivos).

**Se o usuário passou arquivo local ou do Drive/OneDrive pequeno:** rode `python scripts/watch_video.py ARQUIVO`.

## 2. Ler o dossiê
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

Nunca commite `dossie_*`, vídeos nem `autoedit_out/`.
