#!/usr/bin/env python3
"""
watch_video.py - "Assiste" um vídeo e gera um DOSSIÊ que o Claude consegue ler.

Entrada: link (YouTube etc.) ou arquivo de vídeo local.
Saída (pasta dossie_<id>/):
  dossie.md          resumo: metadados, capítulos, transcrição com horários, lista de quadros
  transcricao.srt    transcrição (Whisper local ou legenda do YouTube)
  quadros/*.jpg      quadros-chave (mudanças de cena + amostragem uniforme)
  folha_01.jpg ...   folhas de miniaturas (grade de quadros com horário) para olhar rápido
  video.mp4          só quando a entrada é link (apague depois se quiser)

Requisitos: ffmpeg/ffprobe no PATH, pillow; yt-dlp para links; faster-whisper para transcrever.
Uso:
  python scripts/watch_video.py https://youtu.be/ID
  python scripts/watch_video.py meu_video.mp4 --frames 30 --lang pt
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v"}


def fail(msg):
    sys.exit(f"\nERRO: {msg}")


def run(cmd, check=True):
    cmd = [str(c) for c in cmd]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        fail(f"falhou:\n  {' '.join(cmd)}\n\n{(r.stderr or r.stdout)[-1500:]}")
    return r


def fmt_t(sec, sep=":"):
    sec = int(sec)
    return f"{sec // 3600:02d}{sep}{sec % 3600 // 60:02d}{sep}{sec % 60:02d}"


def default_out():
    """Pasta Autoedit do OneDrive (se existir); senão autoedit_out/watch."""
    for nome in ("Documentos", "Documents"):
        p = Path.home() / "OneDrive" / nome / "Autoedit"
        if p.parent.exists():
            return p
    return Path("autoedit_out") / "watch"


# ------------------------------------------------------------------ download
def yt_dlp_cmd():
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        fail("yt-dlp não encontrado. Instale: winget install yt-dlp.yt-dlp  (ou pip install yt-dlp)")


def video_id(url):
    m = re.search(r"(?:youtu\.be/|v=|shorts/|embed/)([\w-]{6,})", url)
    return m.group(1) if m else re.sub(r"\W+", "_", url)[-24:]


def download(url, pasta, altura, navegador):
    cmd = yt_dlp_cmd() + ["--no-playlist", "--restrict-filenames", "--write-info-json",
                          "--write-auto-subs", "--write-subs", "--sub-langs", "pt.*,en.*",
                          "--convert-subs", "srt",
                          "-f", f"bv*[height<={altura}]+ba/b[height<={altura}]",
                          "--merge-output-format", "mp4",
                          "-o", str(pasta / "video.%(ext)s")]
    if navegador:
        cmd += ["--cookies-from-browser", navegador]
    r = run(cmd + [url], check=False)
    video = pasta / "video.mp4"
    if r.returncode != 0 or not video.exists():
        err = (r.stderr or "")[-800:]
        dica = ""
        if "not a bot" in err or "Sign in" in err:
            dica = ("\nO YouTube pediu login. Rode de novo com  --navegador chrome  "
                    "(ou edge/firefox). Os cookies ficam só no seu PC.")
        fail(f"não consegui baixar o vídeo.{dica}\n\n{err}")
    return video


# ------------------------------------------------------------------- quadros
def probe(video):
    info = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json",
                           "-show_format", "-show_streams", video]).stdout)
    dur = float(info["format"].get("duration") or 0)
    vs = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if not dur or not vs:
        fail("não achei vídeo/duração no arquivo.")
    return dur, f"{vs['width']}x{vs['height']}"


def scene_times(video, limiar):
    """Horários de mudança de cena (ffmpeg, em baixa resolução para ser rápido)."""
    r = run(["ffmpeg", "-hide_banner", "-i", video, "-an",
             "-vf", f"scale=320:-2,select='gt(scene,{limiar})',showinfo", "-f", "null", "-"],
            check=False)
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]


def pick_times(dur, n, cenas):
    """Mistura amostragem uniforme + mudanças de cena, sem quadros colados, no máximo n."""
    passo = dur / n
    cand = [passo * (i + 0.5) for i in range(n)] + [t for t in cenas if 0.5 < t < dur - 0.5]
    cand.sort()
    gap = passo / 2
    keep = []
    for t in cand:
        if not keep or t - keep[-1] >= gap:
            keep.append(t)
    if len(keep) > n:  # afina de forma uniforme até n quadros
        keep = [keep[round(i * (len(keep) - 1) / max(n - 1, 1))] for i in range(n)]
    return keep


def extract_frames(video, tempos, pasta):
    pasta.mkdir(parents=True, exist_ok=True)
    out = []
    for i, t in enumerate(tempos, 1):
        f = pasta / f"quadro_{i:03d}_{fmt_t(t, '-')}.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
             "-vf", "scale=-2:540", "-q:v", "3", f])
        if f.exists():
            out.append((t, f))
    return out


def contact_sheets(quadros, pasta, cols=3, rows=3):
    """Grades de quadros com o horário escrito: poucas imagens para o Claude olhar."""
    w, h = 640, 360
    folhas = []
    por_folha = cols * rows
    for k in range(0, len(quadros), por_folha):
        grupo = quadros[k:k + por_folha]
        folha = Image.new("RGB", (cols * w, rows * h), (16, 16, 16))
        d = ImageDraw.Draw(folha)
        for j, (t, f) in enumerate(grupo):
            im = Image.open(f).convert("RGB")
            im.thumbnail((w, h))
            x, y = (j % cols) * w, (j // cols) * h
            folha.paste(im, (x, y))
            d.rectangle([x, y, x + 110, y + 22], fill=(0, 0, 0))
            d.text((x + 6, y + 5), fmt_t(t), fill=(255, 255, 0))
        dest = pasta / f"folha_{k // por_folha + 1:02d}.jpg"
        folha.save(dest, quality=85)
        folhas.append((dest, grupo[0][0], grupo[-1][0]))
    return folhas


# ------------------------------------------------------------- transcrição
def transcribe(video, pasta, modelo, lang):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None, "faster-whisper não instalado (pip install faster-whisper)"
    try:
        m = WhisperModel(modelo, device="auto", compute_type="int8")
        segs, info = m.transcribe(str(video), language=lang or None, vad_filter=True)
        linhas = [(s.start, s.end, s.text.strip()) for s in segs if s.text.strip()]
    except Exception as e:  # ex.: sem internet para baixar o modelo
        return None, f"Whisper falhou: {e}"
    return linhas, f"Whisper '{modelo}' (idioma: {info.language})"


def read_srt(path):
    linhas = []
    for bloco in re.split(r"\n\s*\n", path.read_text(encoding="utf-8", errors="replace")):
        m = re.search(r"(\d+):(\d+):(\d+)[,.]\d+ --> (\d+):(\d+):(\d+)[,.]\d+\s*\n(.*)", bloco, re.S)
        if m:
            g = [int(x) for x in m.groups()[:6]]
            txt = re.sub(r"<[^>]+>", "", m.group(7)).replace("\n", " ").strip()
            if txt and (not linhas or linhas[-1][2] != txt):  # legenda auto repete linhas
                linhas.append((g[0] * 3600 + g[1] * 60 + g[2], g[3] * 3600 + g[4] * 60 + g[5], txt))
    return linhas


def write_srt(linhas, dest):
    def ts(s):
        return f"{fmt_t(s)},{int(s % 1 * 1000):03d}"
    dest.write_text("\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n" for i, (a, b, t) in enumerate(linhas, 1)),
                    encoding="utf-8")


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Gera um dossiê (transcrição + quadros) de um vídeo.")
    ap.add_argument("fonte", help="link do vídeo ou arquivo local")
    ap.add_argument("--out", help="pasta de saída (padrão: Documentos\\Autoedit do OneDrive, se existir)")
    ap.add_argument("--frames", type=int, default=24, help="máx. de quadros-chave (padrão 24)")
    ap.add_argument("--scene-threshold", type=float, default=0.25, help="sensibilidade de mudança de cena (0-1)")
    ap.add_argument("--altura", type=int, default=720, help="altura máx. ao baixar (padrão 720)")
    ap.add_argument("--navegador", help="navegador com login do YouTube (chrome, edge, firefox...)")
    ap.add_argument("--whisper-model", default="small", help="modelo Whisper (padrão small)")
    ap.add_argument("--lang", help="idioma do áudio (pt, en...); padrão: detectar")
    ap.add_argument("--no-transcribe", action="store_true", help="não transcreve (só quadros/legenda do site)")
    a = ap.parse_args()

    for exe in ("ffmpeg", "ffprobe"):
        if not shutil.which(exe):
            fail(f"{exe} não encontrado no PATH (winget install Gyan.FFmpeg).")

    base = Path(a.out) if a.out else default_out()
    eh_link = re.match(r"https?://", a.fonte) is not None
    if eh_link:
        pasta = base / f"dossie_{video_id(a.fonte)}"
        pasta.mkdir(parents=True, exist_ok=True)
        print(f"[1/4] Baixando para {pasta} ...")
        video = download(a.fonte, pasta, a.altura, a.navegador)
    else:
        video = Path(a.fonte)
        if not video.is_file() or video.suffix.lower() not in VIDEO_EXT:
            fail(f"arquivo de vídeo não encontrado: {video}")
        pasta = base / f"dossie_{video.stem}"
        pasta.mkdir(parents=True, exist_ok=True)
        print("[1/4] Usando arquivo local.")

    dur, res = probe(video)
    info = {}
    ij = next(iter(pasta.glob("*.info.json")), None)
    if ij:
        info = json.loads(ij.read_text(encoding="utf-8"))

    print(f"[2/4] Quadros-chave (duração {fmt_t(dur)}, {res}) ...")
    tempos = pick_times(dur, max(1, a.frames), scene_times(video, a.scene_threshold))
    quadros = extract_frames(video, tempos, pasta / "quadros")
    folhas = contact_sheets(quadros, pasta)

    print("[3/4] Transcrição ...")
    linhas, fonte_txt = (None, "desligada (--no-transcribe)")
    if not a.no_transcribe:
        linhas, fonte_txt = transcribe(video, pasta, a.whisper_model, a.lang)
    if not linhas:  # plano B: legenda baixada do site
        srt = next(iter(sorted(pasta.glob("video*.srt"))), None)
        if srt:
            linhas, fonte_txt = read_srt(srt), f"legenda do site ({srt.name}); Whisper: {fonte_txt}"
    if linhas:
        write_srt(linhas, pasta / "transcricao.srt")
    elif not a.no_transcribe and fonte_txt.startswith("Whisper '"):
        fonte_txt += " - nenhuma fala detectada"

    print("[4/4] Escrevendo dossie.md ...")
    md = [f"# Dossiê: {info.get('title') or video.stem}", "",
          f"- Fonte: {a.fonte}", f"- Duração: {fmt_t(dur)} | Resolução: {res}",
          f"- Canal: {info.get('uploader', '?')} | Publicado: {info.get('upload_date', '?')}",
          f"- Transcrição: {fonte_txt}", f"- Quadros: {len(quadros)} em {len(folhas)} folha(s)", ""]
    if info.get("chapters"):
        md += ["## Capítulos"] + [f"- {fmt_t(c['start_time'])} {c['title']}" for c in info["chapters"]] + [""]
    if info.get("description"):
        md += ["## Descrição do vídeo", info["description"][:3000], ""]
    md += ["## Folhas de miniaturas (olhe estas primeiro)"]
    md += [f"- {f.name}: {fmt_t(i)} → {fmt_t(j)}" for f, i, j in folhas] + [""]
    md += ["## Quadros-chave"] + [f"- {fmt_t(t)}  quadros/{f.name}" for t, f in quadros] + [""]
    md += ["## Transcrição"]
    md += [f"[{fmt_t(s)}] {t}" for s, _, t in linhas] if linhas else ["(sem transcrição disponível)"]
    (pasta / "dossie.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"\nPronto: {pasta / 'dossie.md'}")


if __name__ == "__main__":
    main()
