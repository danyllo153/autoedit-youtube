#!/usr/bin/env python3
"""
autoedit.py - Edição automática de gameplay / vídeos / fotos para o YouTube.

O que faz:
  1. Detecta cenas com PySceneDetect e pontua cada trecho (energia do áudio + movimento).
  2. Escolhe os melhores trechos até a duração-alvo e monta o vídeo em ordem cronológica.
  3. (opcional) Música de fundo com "ducking" (abaixa quando você fala) + loudnorm -16 LUFS.
  4. (opcional) Legendas automáticas com Whisper, gravadas no vídeo.
  5. Se o vídeo final for "grande" (>= --long-min segundos): intro + miniatura (thumbnail).
  6. (opcional) Versão vertical 9:16 para Shorts com os melhores momentos.

Entrada: um vídeo, uma pasta de vídeos, ou uma pasta de fotos (vira slideshow).

Requisitos: ffmpeg no PATH, e  pip install scenedetect[opencv] faster-whisper pillow numpy
"""
import argparse
import json
import math
import random
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import numpy as np

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
FPS = 30
AUDIO_ENC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


# ----------------------------------------------------------------- utilidades
def run(cmd, cwd=None):
    cmd = [str(c) for c in cmd]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"\nERRO ao rodar:\n  {' '.join(cmd)}\n\n{r.stderr[-2000:]}")
    return r.stdout


def probe(path):
    info = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json",
                           "-show_format", "-show_streams", path]))
    dur = float(info["format"].get("duration") or 0)
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    return dur, has_audio


def video_encoder(gpu):
    if gpu:  # placa NVIDIA: exporta bem mais rápido
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "22", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def fit_graph(w, h):
    """Encaixa qualquer vídeo/foto em w x h com fundo desfocado (sem barras pretas)."""
    sw, sh = (w // 16) * 2, (h // 16) * 2
    return (f"split[a][b];[a]scale={sw}:{sh}:force_original_aspect_ratio=increase,"
            f"crop={sw}:{sh},boxblur=3:2,scale={w}:{h}[bg];"
            f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2")


def ts(t):
    ms = int(round(max(t, 0) * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


# ------------------------------------------------------- detecção e pontuação
def detect_chunks(path, dur, min_clip, max_clip):
    """Cenas via PySceneDetect; cenas muito longas são divididas em blocos."""
    scenes = []
    try:
        from scenedetect import AdaptiveDetector, SceneManager, open_video
        video = open_video(str(path))
        sm = SceneManager()
        sm.add_detector(AdaptiveDetector())
        sm.detect_scenes(video, show_progress=False)
        sec = lambda x: x.seconds if hasattr(x, "seconds") else x.get_seconds()  # noqa: E731
        scenes = [(sec(s), sec(e)) for s, e in sm.get_scene_list()]
    except Exception as exc:  # noqa: BLE001
        print(f"  ! PySceneDetect falhou ({exc}); usando blocos fixos.")
    if not scenes:
        scenes = [(0.0, dur)]
    chunks = []
    for s, e in scenes:
        length = e - s
        if length < min_clip:
            continue
        if length <= max_clip * 1.5:
            chunks.append((s, e))
            continue
        n = max(1, round(length / max_clip))
        step = length / n
        chunks += [(s + i * step, s + (i + 1) * step) for i in range(n)]
    return chunks


def audio_rms(path, win=0.5, sr=8000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                          "-ar", str(sr), "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    n = int(sr * win)
    k = len(a) // n
    if k == 0:
        return np.zeros(1), win
    return np.sqrt((a[:k * n].reshape(k, n) ** 2).mean(axis=1)), win


def motion_score(cap, s, e, samples=4):
    import cv2
    vals = []
    for i in range(samples):
        t = s + (e - s) * (i + 0.5) / samples
        frames = []
        for dt in (0.0, 0.3):
            cap.set(cv2.CAP_PROP_POS_MSEC, (t + dt) * 1000)
            ok, f = cap.read()
            if not ok:
                break
            g = cv2.cvtColor(cv2.resize(f, (160, 90)), cv2.COLOR_BGR2GRAY)
            frames.append(g.astype(np.float32))
        if len(frames) == 2:
            vals.append(float(np.abs(frames[1] - frames[0]).mean()))
    return float(np.mean(vals)) if vals else 0.0


def percentile_rank(x):
    x = np.asarray(x, dtype=float)
    if len(x) < 2 or np.ptp(x) < 1e-9:
        return np.zeros_like(x)
    return x.argsort().argsort() / (len(x) - 1)


def score_video(path, args):
    import cv2
    dur, has_audio = probe(path)
    print(f"• {Path(path).name}: {dur / 60:.1f} min — detectando cenas...")
    chunks = detect_chunks(path, dur, args.min_clip, args.max_clip)
    print(f"  {len(chunks)} trechos candidatos — pontuando áudio e movimento...")
    rms, win = audio_rms(path) if has_audio else (np.zeros(1), 0.5)
    cap = cv2.VideoCapture(str(path))
    a_sc, m_sc = [], []
    for s, e in chunks:
        seg = rms[int(s / win): max(int(s / win) + 1, int(e / win))]
        a_sc.append(0.6 * seg.mean() + 0.4 * seg.max() if len(seg) else 0.0)
        m_sc.append(motion_score(cap, s, e))
    cap.release()
    return dur, has_audio, chunks, np.array(a_sc), np.array(m_sc)


def select_clips(items, target, aw):
    """items: lista de dicts (src, s, e, a, m). Retorna os melhores até 'target' s."""
    a_all = percentile_rank([i["a"] for i in items])
    m_all = percentile_rank([i["m"] for i in items])
    if np.ptp([i["a"] for i in items]) < 1e-9:
        aw = 0.0  # sem áudio útil: só movimento
    for i, (a, m) in zip(items, zip(a_all, m_all)):
        i["score"] = float(aw * a + (1 - aw) * m)
    chosen, total = [], 0.0
    for it in sorted(items, key=lambda i: -i["score"]):
        d = it["e"] - it["s"]
        if total + d > target * 1.05:
            continue
        chosen.append(it)
        total += d
        if total >= target * 0.95:
            break
    chosen.sort(key=lambda i: (i["order"], i["s"]))
    return chosen, total


# ----------------------------------------------------------------- renderização
def render_clip(src, s, e, out, has_audio, enc, w, h, cwd):
    d = e - s
    vf = fit_graph(w, h) + f",fps={FPS},setsar=1,format=yuv420p"
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{s:.3f}", "-t", f"{d:.3f}", "-i", src]
    if has_audio:
        af = (f"aresample=48000,afade=t=in:d=0.04,"
              f"afade=t=out:st={max(d - 0.04, 0):.3f}:d=0.04")
        cmd += ["-vf", vf, "-af", af]
    else:
        cmd += ["-f", "lavfi", "-t", f"{d:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                "-vf", vf, "-map", "0:v:0", "-map", "1:a:0"]
    run(cmd + enc + AUDIO_ENC + ["-t", f"{d:.3f}", out], cwd=cwd)


def render_photo(img, out, secs, enc, w, h, cwd):
    n = int(secs * FPS)
    vf = (fit_graph(w * 2, h * 2) +
          f",zoompan=z='min(zoom+0.0007,1.1)':d={n}:x='iw/2-(iw/zoom/2)':"
          f"y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS},setsar=1,format=yuv420p")
    run(["ffmpeg", "-y", "-v", "error", "-i", img, "-f", "lavfi", "-t", f"{secs}",
         "-i", "anullsrc=r=48000:cl=stereo", "-vf", vf, "-map", "0:v:0", "-map", "1:a:0"]
        + enc + AUDIO_ENC + ["-t", f"{secs}", out], cwd=cwd)


def concat(names, out, cwd):
    lst = Path(cwd) / "list.txt"
    lst.write_text("".join(f"file '{n}'\n" for n in names))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
         "-c", "copy", out], cwd=cwd)


# ---------------------------------------------------------------------- legendas
def transcribe(video, model_name, lang):
    from faster_whisper import WhisperModel
    print("  transcrevendo (Whisper)...")
    model = WhisperModel(model_name, device="auto", compute_type="int8")
    segs, info = model.transcribe(str(video), language=lang, vad_filter=True, beam_size=5)
    out = []
    for s in segs:
        if s.no_speech_prob > 0.6 or s.avg_logprob < -1.2 or not s.text.strip():
            continue
        out.append((s.start, s.end, s.text.strip()))
    print(f"  {len(out)} falas detectadas (idioma: {info.language})")
    return out


def write_srt(segs, offset, path, width):
    lines = []
    for i, (s, e, text) in enumerate(segs, 1):
        lines.append(f"{i}\n{ts(s + offset)} --> {ts(e + offset)}\n"
                     + "\n".join(textwrap.wrap(text, width)) + "\n")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# ------------------------------------------------------- miniatura e intro (Pillow)
def pick_font(size, custom=None):
    from PIL import ImageFont
    cands = [custom] if custom else []
    cands += ["C:/Windows/Fonts/impact.ttf", "C:/Windows/Fonts/arialbd.ttf",
              "/System/Library/Fonts/Supplemental/Impact.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
    for c in cands:
        if c and Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default(size)


def draw_title(img, text, box, color, font_path, max_lines=2, start=140, anchor="left"):
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    text = text.upper()
    for size in range(start, 40, -6):
        font = pick_font(size, font_path)
        for width in (14, 18, 24, 32):
            lines = textwrap.wrap(text, width)
            if len(lines) > max_lines:
                continue
            lh = int(size * 1.08)
            if (max(d.textlength(l, font=font) for l in lines) <= x1 - x0
                    and lh * len(lines) <= y1 - y0):
                y = y1 - lh * len(lines) if anchor == "left" else y0 + (y1 - y0 - lh * len(lines)) // 2
                for l in lines:
                    tw = d.textlength(l, font=font)
                    x = x0 if anchor == "left" else x0 + (x1 - x0 - tw) / 2
                    d.text((x, y), l, font=font, fill=color, stroke_width=max(4, size // 14),
                           stroke_fill=(0, 0, 0))
                    y += lh
                return
    d.text((x0, y0), text[:30], font=pick_font(50, font_path), fill=color)


def best_frame(candidates):
    """candidates: [(src, t)] -> melhor frame (nítido, colorido, nem escuro nem estourado)."""
    import cv2
    best, best_sc = None, -1
    caps = {}
    for src, t in candidates:
        if Path(src).suffix.lower() in IMAGE_EXT:
            f = cv2.imread(str(src))
            ok = f is not None
        else:
            cap = caps.setdefault(src, cv2.VideoCapture(str(src)))
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, f = cap.read()
        if not ok:
            continue
        small = cv2.resize(f, (640, 360))
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        sharp = cv2.Laplacian(g, cv2.CV_64F).var()
        sat = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[..., 1].mean() / 255
        bright = g.mean() / 255
        sc = math.log1p(sharp) * (0.5 + sat) * (1.0 if 0.25 < bright < 0.8 else 0.5)
        if sc > best_sc:
            best, best_sc = f, sc
    for c in caps.values():
        c.release()
    return best


def make_thumbnail(frame_bgr, title, out, font_path):
    import cv2
    from PIL import Image, ImageEnhance, ImageOps
    img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    img = ImageOps.fit(img, (1280, 720), Image.LANCZOS)
    img = ImageEnhance.Contrast(ImageEnhance.Color(img).enhance(1.35)).enhance(1.15)
    grad = Image.new("L", (1, 720))
    for y in range(720):
        grad.putpixel((0, y), int(max(0, y - 280) / 440 * 215))
    img = Image.composite(Image.new("RGB", (1280, 720), (0, 0, 0)), img, grad.resize((1280, 720)))
    draw_title(img, title, (50, 380, 1230, 680), (255, 222, 30), font_path)
    img.save(out, quality=92)


def make_intro_card(frame_bgr, title, channel, out, w, h, font_path):
    import cv2
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    img = ImageOps.fit(img, (w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(14))
    img = ImageEnhance.Brightness(img).enhance(0.45)
    draw_title(img, title, (int(w * .08), int(h * .25), int(w * .92), int(h * .72)),
               (255, 255, 255), font_path, start=150, anchor="center")
    if channel:
        from PIL import ImageDraw
        d = ImageDraw.Draw(img)
        f = pick_font(int(h * .045), font_path)
        tw = d.textlength(channel.upper(), font=f)
        d.text(((w - tw) / 2, h * .78), channel.upper(), font=f, fill=(255, 222, 30))
    img.save(out)


# ------------------------------------------------------------------- montagem final
def final_pass(video, out, dur, music, music_vol, srt, sub_style, enc, cwd):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", video]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
    fc, vmap = [], "0:v"
    if srt:
        fc.append(f"[0:v]subtitles={srt}:force_style='{sub_style}'[v]")
        vmap = "[v]"
    norm = "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000"
    if music:
        fc += [f"[1:a]volume={music_vol},atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,"
               f"afade=t=out:st={max(dur - 3, 0):.3f}:d=3[m]",
               "[0:a]asplit=2[o][sc]",
               "[m][sc]sidechaincompress=threshold=0.03:ratio=10:attack=30:release=500[md]",
               f"[o][md]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,{norm}[a]"]
    else:
        fc.append(f"[0:a]{norm}[a]")
    cmd += ["-filter_complex", ";".join(fc), "-map", vmap, "-map", "[a]"]
    cmd += (enc if srt else ["-c:v", "copy"]) + AUDIO_ENC + ["-t", f"{dur:.3f}", out]
    run(cmd, cwd=cwd)


def produce(clips, out, tmp, args, w, h, *, vertical=False, allow_extras=True, title=""):
    """clips: itens com src/s/e/has_audio ou 'photo'. Gera o vídeo final em 'out'."""
    enc = video_encoder(args.gpu)
    work = Path(tmp) / ("short" if vertical else "main")
    work.mkdir(exist_ok=True)
    names = []
    for i, c in enumerate(clips):
        name = f"c{i:04d}.mp4"
        if c.get("photo"):
            render_photo(c["photo"], name, args.photo_secs, enc, w, h, work)
        else:
            render_clip(str(c["src"]), c["s"], c["e"], name, c["has_audio"], enc, w, h, work)
        names.append(name)
    concat(names, "cut.mp4", work)
    cut_dur, _ = probe(work / "cut.mp4")

    segs = []
    if args.subs and not args.photos_mode:
        try:
            segs = transcribe(work / "cut.mp4", args.whisper_model, args.lang)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! legendas puladas ({exc})")

    base, offset = "cut.mp4", 0.0
    is_long = cut_dur >= args.long_min
    want_extras = allow_extras and (args.extras == "on" or (args.extras == "auto" and is_long))
    thumb_frame = None
    if want_extras:
        thumb_frame = best_frame(clips_to_candidates(clips))
        if args.intro_video:
            d, ha = probe(args.intro_video)
            render_clip(str(args.intro_video), 0, min(d, 8), "intro.mp4", ha, enc, w, h, work)
        elif thumb_frame is not None:
            make_intro_card(thumb_frame, title, args.channel, work / "card.png", w, h, args.font)
            run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-t", "3",
                 "-i", "card.png", "-f", "lavfi", "-t", "3", "-i", "anullsrc=r=48000:cl=stereo",
                 "-vf", f"scale={w}:{h},fade=t=in:st=0:d=0.5,fade=t=out:st=2.5:d=0.5,"
                        f"setsar=1,format=yuv420p", "-map", "0:v:0", "-map", "1:a:0"]
                + enc + AUDIO_ENC + ["-t", "3", "intro.mp4"], cwd=work)
        if (work / "intro.mp4").exists():
            offset, _ = probe(work / "intro.mp4")
            concat(["intro.mp4", "cut.mp4"], "full.mp4", work)
            base = "full.mp4"

    srt = None
    if segs:
        write_srt(segs, offset, work / "subs.srt", 22 if vertical else 40)
        srt = "subs.srt"
    total, _ = probe(work / base)
    style = ("FontName=Arial,FontSize=11,Bold=1,Outline=2.5,Shadow=0,MarginV=55,Alignment=2"
             if vertical else
             "FontName=Arial,FontSize=14,Bold=1,Outline=2.5,Shadow=0,MarginV=45,Alignment=2")
    final_pass(base, str(Path(out).resolve()), total, args.music, args.music_vol,
               srt, style, enc, work)
    return thumb_frame, total, is_long


def clips_to_candidates(clips):
    photos = [(c["photo"], 0) for c in clips if c.get("photo")]
    if photos:
        return photos[:12]
    ranked = sorted(clips, key=lambda c: -c.get("score", 0))
    return [(c["src"], (c["s"] + c["e"]) / 2) for c in ranked[:12]]


# ------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="Edição automática para YouTube")
    ap.add_argument("input", help="vídeo, pasta de vídeos, ou pasta de fotos")
    ap.add_argument("-o", "--out", default="autoedit_out", help="pasta de saída")
    ap.add_argument("--name", help="nome base dos arquivos de saída")
    ap.add_argument("--title", help="título (intro e miniatura). Padrão: nome do arquivo")
    ap.add_argument("--channel", default="", help="nome do canal (aparece na intro)")
    ap.add_argument("--target", type=float, help="duração do vídeo final em segundos "
                    "(padrão: 25%% do original, entre 30 s e 10 min)")
    ap.add_argument("--min-clip", type=float, default=2.0)
    ap.add_argument("--max-clip", type=float, default=10.0)
    ap.add_argument("--audio-weight", type=float, default=0.6,
                    help="peso do áudio (0-1) vs movimento na escolha dos trechos")
    ap.add_argument("--music", help="arquivo de música (ou pasta: sorteia uma)")
    ap.add_argument("--music-vol", type=float, default=0.22)
    ap.add_argument("--subs", action="store_true", help="legendas automáticas (Whisper)")
    ap.add_argument("--lang", default=None, help="idioma da fala, ex.: pt (padrão: auto)")
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--extras", choices=["auto", "on", "off"], default="auto",
                    help="intro + miniatura: auto = só se o vídeo final for grande")
    ap.add_argument("--long-min", type=float, default=180, help="segundos p/ considerar 'grande'")
    ap.add_argument("--intro-video", help="sua própria intro (usa no lugar da gerada)")
    ap.add_argument("--shorts", action="store_true", help="gera também versão vertical (<=58 s)")
    ap.add_argument("--photo-secs", type=float, default=3.5)
    ap.add_argument("--gpu", action="store_true", help="usar NVENC (placa NVIDIA)")
    ap.add_argument("--font", help="arquivo .ttf para títulos")
    ap.add_argument("--plan-only", action="store_true", help="só mostra/salva os trechos")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg não encontrado no PATH.")
    src = Path(args.input).resolve()
    if not src.exists():
        sys.exit(f"Não achei: {src}")
    files = [src] if src.is_file() else sorted(p for p in src.iterdir())
    videos = [p for p in files if p.suffix.lower() in VIDEO_EXT]
    photos = [p for p in files if p.suffix.lower() in IMAGE_EXT]
    args.photos_mode = not videos and bool(photos)
    if not videos and not photos:
        sys.exit("Nenhum vídeo ou foto encontrado.")

    if args.music:
        m = Path(args.music)
        if m.is_dir():
            tracks = [p for p in m.iterdir() if p.suffix.lower() in AUDIO_EXT]
            if not tracks:
                sys.exit("Pasta de música vazia.")
            m = random.choice(tracks)
        args.music = str(m.resolve())
        print(f"♪ música: {m.name}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.name or (src.stem if src.is_file() else src.name)
    title = args.title or re.sub(r"[_\-]+", " ", stem).strip()
    tmp = Path(tempfile.mkdtemp(prefix="autoedit_"))
    plan = []
    try:
        if args.photos_mode:
            from PIL import Image, ImageOps
            clips = []
            for i, p in enumerate(photos):
                im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
                im.thumbnail((3840, 3840))
                tp = tmp / f"photo{i:04d}.jpg"
                im.save(tp, quality=95)
                clips.append({"photo": str(tp), "s": 0, "e": args.photo_secs})
            if args.target:
                clips = clips[: max(1, int(args.target / args.photo_secs))]
            print(f"• slideshow com {len(clips)} fotos")
        else:
            items, total_dur = [], 0.0
            for order, v in enumerate(videos):
                dur, has_audio, chunks, a_sc, m_sc = score_video(v, args)
                total_dur += dur
                items += [{"src": str(v), "order": order, "s": s, "e": e, "a": a, "m": m,
                           "has_audio": has_audio}
                          for (s, e), a, m in zip(chunks, a_sc, m_sc)]
            if not items:
                sys.exit("Nenhum trecho encontrado (vídeo muito curto?).")
            target = args.target or min(max(total_dur * 0.25, 30), 600)
            clips, got = select_clips(items, target, args.audio_weight)
            print(f"→ {len(clips)} trechos escolhidos, {got:.0f}s (alvo {target:.0f}s)")
            plan = [{"src": Path(c["src"]).name, "start": round(c["s"], 2),
                     "end": round(c["e"], 2), "score": round(c["score"], 3)} for c in clips]
            (out_dir / f"{stem}_trechos.json").write_text(json.dumps(plan, indent=2))
            if args.plan_only:
                print(json.dumps(plan, indent=2))
                return

        W, H = 1920, 1080
        out_main = out_dir / f"{stem}_final.mp4"
        print("• montando vídeo principal...")
        thumb, total, is_long = produce(clips, out_main, tmp, args, W, H, title=title)
        if thumb is not None:
            make_thumbnail(thumb, title, out_dir / f"{stem}_miniatura.jpg", args.font)
            print("  miniatura + intro adicionadas (vídeo grande)")
        elif not args.photos_mode and args.extras == "auto" and not is_long:
            print(f"  vídeo curto ({total:.0f}s < {args.long_min:.0f}s): sem intro/miniatura")

        if args.shorts and not args.photos_mode:
            print("• montando Shorts vertical...")
            sh, _ = select_clips(items, 58, args.audio_weight)
            produce(sh, out_dir / f"{stem}_shorts.mp4", tmp, args, 1080, 1920,
                    vertical=True, allow_extras=False, title=title)
        print(f"\n✔ pronto! Arquivos em: {out_dir.resolve()}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
