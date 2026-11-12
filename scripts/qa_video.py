#!/usr/bin/env python3
"""
qa_video.py - Revisa o vídeo FINAL antes de publicar (o passo "o modelo assistiu ao próprio vídeo").

Confere: volume (LUFS / pico), silêncios longos, quadros pretos, quadros-chave + folhas de miniaturas
(para olhar se algum texto cobriu algo), e, com --roteiro, compara a fala do áudio final com o texto esperado.

Saída: <out>/qa_<video>/qa_report.md  (+ quadros/ e folha_NN.jpg para o Claude/você olharem)

Uso:
  python scripts/qa_video.py autoedit_out/meu_final.mp4
  python scripts/qa_video.py final.mp4 --roteiro roteiro.txt --lang pt --lufs-alvo -14
"""
import argparse
import difflib
import re
import shutil
import sys
from pathlib import Path

import watch_video as wv  # mesmo diretório (scripts/)


def medir_volume(video):
    """LUFS integrado, LRA e pico real via filtro ebur128."""
    r = wv.run(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-vn",
                "-af", "ebur128=peak=true", "-f", "null", "-"], check=False)
    resumo = r.stderr.rsplit("Summary:", 1)[-1]
    pega = lambda rx: (float(m.group(1)) if (m := re.search(rx, resumo)) else None)  # noqa: E731
    return {"lufs": pega(r"I:\s+(-?[\d.]+)\s+LUFS"), "lra": pega(r"LRA:\s+(-?[\d.]+)\s+LU"),
            "pico": pega(r"Peak:\s+(-?[\d.]+)\s+dBFS")}


def achar_silencios(video, db, minimo):
    r = wv.run(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-vn",
                "-af", f"silencedetect=noise={db}dB:d={minimo}", "-f", "null", "-"], check=False)
    ini = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", r.stderr)]
    dur = [float(x) for x in re.findall(r"silence_duration:\s*([\d.]+)", r.stderr)]
    return [(max(i, 0.0), d) for i, d in zip(ini, dur)]


def achar_pretos(video, minimo):
    r = wv.run(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-an",
                "-vf", f"blackdetect=d={minimo}:pix_th=0.10", "-f", "null", "-"], check=False)
    return [(float(a), float(d)) for a, d in
            re.findall(r"black_start:([\d.]+).*?black_duration:([\d.]+)", r.stderr)]


def palavras(texto):
    return re.findall(r"\w+", texto.lower())


def comparar_roteiro(roteiro, falado):
    """Compara palavra a palavra. Devolve (similaridade 0-1, faltaram, sobraram)."""
    a, b = palavras(roteiro), palavras(falado)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    faltou, sobrou = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("delete", "replace"):
            faltou.append(" ".join(a[i1:i2]))
        if op in ("insert", "replace"):
            sobrou.append(" ".join(b[j1:j2]))
    return sm.ratio(), faltou, sobrou


def main():
    ap = argparse.ArgumentParser(description="Revisão do vídeo final (volume, silêncios, quadros, roteiro).")
    ap.add_argument("video")
    ap.add_argument("--out", default="autoedit_out", help="pasta de saída (padrão autoedit_out)")
    ap.add_argument("--roteiro", help="arquivo .txt com a fala esperada (compara com o áudio final)")
    ap.add_argument("--lufs-alvo", type=float, default=-16.0, help="volume esperado em LUFS (padrão -16)")
    ap.add_argument("--max-silencio", type=float, default=3.0, help="avisa silêncio maior que X s (padrão 3)")
    ap.add_argument("--frames", type=int, default=12, help="quadros para revisar (padrão 12)")
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--lang", help="idioma da fala (pt, en...)")
    ap.add_argument("--no-transcribe", action="store_true", help="pula a transcrição")
    a = ap.parse_args()

    video = Path(a.video)
    if not video.is_file():
        sys.exit(f"Arquivo não encontrado: {video}")
    for exe in ("ffmpeg", "ffprobe"):
        if not shutil.which(exe):
            sys.exit(f"{exe} não encontrado no PATH.")

    try:
        dur, res = wv.probe(video)
    except wv.Falha as e:
        sys.exit(f"ERRO: {e}")
    pasta = Path(a.out) / f"qa_{video.stem}"
    pasta.mkdir(parents=True, exist_ok=True)
    avisos, ok = [], []

    print("[1/4] Volume ...")
    vol = medir_volume(video)
    if vol["lufs"] is None:
        avisos.append("Sem áudio (ou não consegui medir o volume).")
    else:
        if abs(vol["lufs"] - a.lufs_alvo) > 2:
            avisos.append(f"Volume {vol['lufs']:.1f} LUFS está longe do alvo {a.lufs_alvo:.0f} (±2).")
        else:
            ok.append(f"Volume {vol['lufs']:.1f} LUFS (alvo {a.lufs_alvo:.0f}).")
        if vol["pico"] is not None and vol["pico"] > -1.0:
            avisos.append(f"Pico {vol['pico']:.1f} dBFS: risco de estourar/clipar (ideal <= -1).")

    print("[2/4] Silêncios e quadros pretos ...")
    sil = [(t, d) for t, d in achar_silencios(video, -50, a.max_silencio)]
    pretos = achar_pretos(video, 1.0)
    avisos += [f"Silêncio de {d:.1f}s em {wv.fmt_t(t)}." for t, d in sil]
    avisos += [f"Tela preta de {d:.1f}s em {wv.fmt_t(t)}." for t, d in pretos]
    if not sil and not pretos:
        ok.append(f"Sem silêncios > {a.max_silencio:.0f}s nem telas pretas > 1s.")

    print("[3/4] Quadros-chave ...")
    tempos = wv.pick_times(dur, max(1, a.frames), wv.scene_times(video, 0.25))
    quadros = wv.extract_frames(video, tempos, pasta / "quadros")
    folhas = wv.contact_sheets(quadros, pasta)

    print("[4/4] Fala do áudio final ...")
    linhas, fonte = (None, "desligada (--no-transcribe)")
    if not a.no_transcribe:
        linhas, fonte = wv.transcribe(video, pasta, a.whisper_model, a.lang)
    falado = " ".join(t for _, _, t in linhas) if linhas else ""
    comp = None
    if a.roteiro:
        rot = Path(a.roteiro)
        if not rot.is_file():
            sys.exit(f"Roteiro não encontrado: {rot}")
        if not falado:
            avisos.append("Não consegui transcrever o áudio para comparar com o roteiro.")
        else:
            comp = comparar_roteiro(rot.read_text(encoding="utf-8-sig"), falado)
            (ok if comp[0] >= 0.9 else avisos).append(
                f"Fala x roteiro: {comp[0] * 100:.0f}% igual" + ("" if comp[0] >= 0.9 else " (< 90%)."))

    md = [f"# Revisão: {video.name}", "",
          f"- Duração: {wv.fmt_t(dur)} | Resolução: {res}",
          f"- Volume: {vol['lufs'] if vol['lufs'] is not None else '?'} LUFS | "
          f"LRA: {vol['lra'] if vol['lra'] is not None else '?'} LU | "
          f"Pico: {vol['pico'] if vol['pico'] is not None else '?'} dBFS",
          f"- Transcrição: {fonte}", ""]
    md += ["## Resultado", f"**{'OK' if not avisos else str(len(avisos)) + ' aviso(s)'}**", ""]
    md += [f"- ✔ {x}" for x in ok] + [f"- ⚠ {x}" for x in avisos] + [""]
    if comp and (comp[1] or comp[2]):
        md += ["## Diferenças entre roteiro e fala"]
        md += [f"- faltou: {x}" for x in comp[1][:30]] + [f"- sobrou: {x}" for x in comp[2][:30]] + [""]
    md += ["## Quadros para olhar (confira se algum texto cobriu algo importante)"]
    md += [f"- {f.name}: {wv.fmt_t(i)} → {wv.fmt_t(j)}" for f, i, j in folhas] + [""]
    md += ["## Transcrição do áudio final"]
    md += [f"[{wv.fmt_t(s)}] {t}" for s, _, t in linhas] if linhas else ["(sem transcrição)"]
    rel = pasta / "qa_report.md"
    rel.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"\n{'OK' if not avisos else str(len(avisos)) + ' aviso(s)'}  ->  {rel}")
    for x in avisos:
        print("  ⚠", x)


if __name__ == "__main__":
    main()
