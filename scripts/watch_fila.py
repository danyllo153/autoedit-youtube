#!/usr/bin/env python3
"""
watch_fila.py - Vigia uma pasta "fila" no OneDrive e gera o dossiê de cada link que cair nela.

Fluxo: você (ou o Claude) grava um .txt com o link em  Autoedit\\fila\\  -> este vigia, rodando num PC
seu que fica ligado, baixa e gera  Autoedit\\dossie_<id>\\  -> o Claude lê o dossiê pelo OneDrive.
Assim dá para pedir de qualquer aparelho (celular, notebook) sem rodar nada nele.

Formato do .txt (uma entrada por linha; # comenta):
    https://youtu.be/ID                 link (ou nome de um vídeo que já está na pasta Autoedit)
    lang=pt                             opcional: idioma do áudio
    frames=30                           opcional: máx. de quadros-chave
    navegador=chrome                    opcional: usa o login desse navegador (se o YouTube pedir)

Pastas: fila\\ (pendentes) | fila\\feitos\\ (ok) | fila\\erros\\ (com o motivo) | fila\\_status.log (vivo?)

Uso:    python scripts\\watch_fila.py            (fica rodando; Ctrl+C para parar)
        python scripts\\watch_fila.py --once     (processa o que houver e sai)
Iniciar com o Windows:  veja README ("Fila de vídeos").
"""
import argparse
import platform
import re
import time
import traceback
from datetime import datetime
from pathlib import Path

import watch_video as wv  # mesmo diretório (scripts/)

STATUS = "_status.log"
CHAVES = {"lang", "frames", "navegador"}


def agora():
    return datetime.now().isoformat(timespec="seconds")


def status(fila, msg):
    try:
        (fila / STATUS).write_text(f"{msg}\nhost: {platform.node()}\natualizado: {agora()}\n", encoding="utf-8")
    except OSError:
        pass  # OneDrive pode estar sincronizando o arquivo; tenta de novo no próximo ciclo


def ler_pedido(arq, base):
    """Devolve (fontes, opcoes) a partir de um .txt da fila."""
    fontes, opts = [], {}
    for linha in arq.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        m = re.match(r"(\w+)\s*=\s*(.+)$", linha)
        if m and m.group(1).lower() in CHAVES:
            opts[m.group(1).lower()] = m.group(2).strip()
        elif re.match(r"https?://", linha):
            fontes.append(linha)
        else:  # nome de arquivo já presente na pasta Autoedit (ou caminho completo)
            p = Path(linha)
            fontes.append(str(p if p.is_absolute() else base / p))
    return fontes, opts


def processar(arq, base, fila, args):
    fontes, opts = ler_pedido(arq, base)
    if not fontes:
        raise wv.Falha("nenhum link ou arquivo encontrado no .txt")
    resultados = []
    for fonte in fontes:
        kw = wv.opcoes_dossie(args)
        kw["out"] = str(base)
        if "lang" in opts:
            kw["lang"] = opts["lang"]
        if "frames" in opts:
            kw["frames"] = int(opts["frames"])
        if "navegador" in opts:
            kw["navegador"] = opts["navegador"]
        destino = wv.gerar_dossie(fonte, log=lambda m: status(fila, f"processando {arq.name}: {m}"), **kw)
        resultados.append(f"{fonte} -> {destino.parent.name}/dossie.md")
    return resultados


def ciclo(base, fila, args):
    feitos, erros = fila / "feitos", fila / "erros"
    for d in (feitos, erros):
        d.mkdir(parents=True, exist_ok=True)
    n = 0
    for arq in sorted(fila.glob("*.txt")):
        if time.time() - arq.stat().st_mtime < 3:  # ainda sincronizando
            continue
        trabalho = arq.with_suffix(".processando")
        try:
            arq.rename(trabalho)  # "reserva" o pedido
        except OSError:
            continue
        n += 1
        print(f"[{agora()}] {arq.name}")
        try:
            res = processar(trabalho, base, fila, args)
            destino, texto = feitos / arq.name, "OK " + agora() + "\n" + "\n".join(res) + "\n"
        except wv.Falha as e:
            destino, texto = erros / arq.name, f"ERRO {agora()}\n{e}\n"
        except Exception:  # bug inesperado: registra e segue vivo
            destino, texto = erros / arq.name, f"ERRO {agora()}\n{traceback.format_exc()[-1500:]}\n"
        original = trabalho.read_text(encoding="utf-8-sig", errors="replace")
        destino.write_text(texto + "\n--- pedido original ---\n" + original, encoding="utf-8")
        trabalho.unlink()
        print(texto.strip().splitlines()[0], "|", destino.parent.name)
    return n


def main():
    ap = argparse.ArgumentParser(description="Vigia a fila de links e gera dossiês.")
    wv.add_opcoes(ap)
    ap.add_argument("--intervalo", type=int, default=30, help="segundos entre verificações (padrão 30)")
    ap.add_argument("--once", action="store_true", help="processa a fila uma vez e sai")
    a = ap.parse_args()

    base = Path(a.out) if a.out else wv.default_out()
    fila = base / "fila"
    fila.mkdir(parents=True, exist_ok=True)
    print(f"Vigiando {fila}  (Ctrl+C para parar)")
    while True:
        status(fila, "ativo - aguardando pedidos")
        ciclo(base, fila, a)
        if a.once:
            break
        time.sleep(a.intervalo)
    status(fila, "parado (--once)")


if __name__ == "__main__":
    main()
