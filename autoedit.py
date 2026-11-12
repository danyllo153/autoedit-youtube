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
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unicodedata
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


def fit_graph(w, h, square=False, tag=""):
    """Encaixa qualquer vídeo/foto em w x h com fundo desfocado (sem barras pretas).
    square=True: recorta o centro em 1:1 antes de encaixar (gameplay maior no Short)."""
    sw, sh = (w // 16) * 2, (h // 16) * 2
    fg_crop = "crop='min(iw,ih)':'min(iw,ih)'," if square else ""
    a, b, bg, fg = (f"{n}{tag}" for n in ("a", "b", "bg", "fg"))
    return (f"split[{a}][{b}];[{a}]scale={sw}:{sh}:force_original_aspect_ratio=increase,"
            f"crop={sw}:{sh},boxblur=3:2,scale={w}:{h}[{bg}];"
            f"[{b}]{fg_crop}scale={w}:{h}:force_original_aspect_ratio=decrease[{fg}];"
            f"[{bg}][{fg}]overlay=(W-w)/2:(H-h)/2")


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


# ------------------------------------------------ OCR: textos que o jogo ESCREVE na tela
# Só serve para o que aparece escrito (telas de resultado, avisos). Abates ao vivo costumam ser só visuais
# (no Arc Raiders não há texto de kill): OCR NÃO detecta kill nesses jogos. Formato "palavra=peso".
# São palpites genéricos e não conferidos com o jogo: rode com --ocr, veja o que o OCR leu em
# <nome>_ocr.json e ajuste com --ocr-keywords.
DEFAULT_OCR_KEYWORDS = "victory=1,victorious=1,well played=1,extracted=1,extraction successful=1,vitoria=1,you won=1"


def norm_text(t):
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " " + re.sub(r"[^a-z0-9]+", " ", t).strip() + " "


def parse_keywords(spec):
    kws = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        word, _, w = part.partition("=")
        kws[norm_text(word).strip()] = float(w) if w.strip() else 1.0
    return kws


def parse_region(spec):
    try:
        x0, y0, x1, y1 = (float(v) for v in spec.split(","))
        assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
    except (ValueError, AssertionError):
        sys.exit("--ocr-region deve ser 'x0,y0,x1,y1' em frações de 0 a 1 (ex.: 0,0.6,1,1 = faixa de baixo).")
    return x0, y0, x1, y1


def make_ocr_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        sys.exit("--ocr precisa do RapidOCR:  pip install -r requirements-ocr.txt")
    return RapidOCR()


def ocr_chunk(cap, s, e, every, region, engine, kws):
    """Lê o texto de alguns quadros do trecho. Devolve nota 0-1 (soma dos pesos das palavras achadas)."""
    import cv2
    n = int(min(12, max(1, round((e - s) / every))))
    x0, y0, x1, y1 = region
    texts, matched = [], {}
    for i in range(n):
        cap.set(cv2.CAP_PROP_POS_MSEC, (s + (e - s) * (i + 0.5) / n) * 1000)
        ok, f = cap.read()
        if not ok:
            continue
        h, w = f.shape[:2]
        f = f[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]
        if f.shape[1] > 1280:
            f = cv2.resize(f, (1280, max(1, int(f.shape[0] * 1280 / f.shape[1]))))
        # o detector do RapidOCR não acha texto em recortes finos (testado: faixa de 144 px = 0 de 7
        # acertos, com 360 px = 7 de 7): completa com preto até 360 px em cada lado
        ph, pw = max(0, 360 - f.shape[0]), max(0, 360 - f.shape[1])
        if ph or pw:
            f = cv2.copyMakeBorder(f, ph // 2, ph - ph // 2, pw // 2, pw - pw // 2,
                                   cv2.BORDER_CONSTANT, value=(0, 0, 0))
        res, _ = engine(f)
        for _, txt, conf in (res or []):
            if float(conf) < 0.5:
                continue
            texts.append(txt)
            nt = norm_text(txt)
            for kw, wt in kws.items():
                if f" {kw} " in nt:
                    matched[kw] = wt
    return {"score": min(1.0, sum(matched.values())), "matched": sorted(matched),
            "texts": sorted(set(texts))}


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
    a_sc, m_sc, ocr_res = [], [], []
    engine = kws = region = None
    if args.ocr:
        engine, kws, region = make_ocr_engine(), parse_keywords(args.ocr_keywords), parse_region(args.ocr_region)
        print(f"  OCR (~{sum(e - s for s, e in chunks) / args.ocr_every:.0f} quadros) — procurando: "
              f"{', '.join(kws)}")
    for s, e in chunks:
        seg = rms[int(s / win): max(int(s / win) + 1, int(e / win))]
        a_sc.append(0.6 * seg.mean() + 0.4 * seg.max() if len(seg) else 0.0)
        m_sc.append(motion_score(cap, s, e))
        if engine:
            ocr_res.append(ocr_chunk(cap, s, e, args.ocr_every, region, engine, kws))
    cap.release()
    return dur, has_audio, chunks, np.array(a_sc), np.array(m_sc), ocr_res


def select_clips(items, target, aw, min_motion=0.5, ow=0.0):
    """items: lista de dicts (src, s, e, a, m). Retorna os melhores até 'target' s."""
    a_all = percentile_rank([i["a"] for i in items])
    m_all = percentile_rank([i["m"] for i in items])
    if np.ptp([i["a"] for i in items]) < 1e-9:
        aw = 0.0  # sem áudio útil: só movimento
    for i, (a, m) in zip(items, zip(a_all, m_all)):
        base = aw * a + (1 - aw) * m
        # ow > 0 (--ocr): trechos com palavras-chave na tela (kill, vitória) ganham ow de nota extra
        i["score"] = float((1 - ow) * base + ow * i.get("o", 0.0))
    # descarta trechos quase parados (menus, inventário, tela de loading), se sobrar material
    pool = items
    ms = np.array([i["m"] for i in items])
    if min_motion > 0 and np.ptp(ms) > 1e-9:
        # tela de vitória costuma ser parada: trecho com palavra-chave do OCR nunca é descartado
        keep = [i for i in items if i["m"] >= min_motion * float(np.median(ms)) or i.get("o", 0) > 0]
        if sum(i["e"] - i["s"] for i in keep) >= target:
            pool = keep
    chosen, total = [], 0.0
    for it in sorted(pool, key=lambda i: -i["score"]):
        d = it["e"] - it["s"]
        if total + d > target * 1.05:
            continue
        chosen.append(it)
        total += d
        if total >= target * 0.95:
            break
    chosen.sort(key=lambda i: (i["order"], i["s"]))
    return chosen, total


# ------------------------------------------------- gravação falada: cortar silêncios + EDL
def detect_speech(path, dur, db, min_silence, pad, min_speech=0.4):
    """Trechos COM som/fala: o que sobra entre os silêncios achados pelo silencedetect do ffmpeg."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                        f"silencedetect=noise={db:g}dB:d={min_silence:g}", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", r.stderr)]
    silences = [(max(st, 0.0), ends[i] if i < len(ends) else dur) for i, st in enumerate(starts)]
    speech, cur = [], 0.0
    for st, en in silences:
        if st - cur > 0:
            speech.append((cur, st))
        cur = en
    if dur - cur > 0:
        speech.append((cur, dur))
    merged = []
    for s_, e_ in speech:  # folga em volta da fala (não corta a respiração/consoante) e junta vizinhos
        s_, e_ = max(0.0, s_ - pad), min(dur, e_ + pad)
        if merged and s_ <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e_))
        else:
            merged.append((s_, e_))
    return [(a, b) for a, b in merged if b - a >= min_speech]


def speech_items(videos, args):
    items, total = [], 0.0
    for order, v in enumerate(videos):
        dur, has_audio = probe(v)
        total += dur
        if has_audio:
            segs = detect_speech(v, dur, args.silence_db, args.min_silence, args.pad)
        else:
            print(f"  ! {Path(v).name} sem áudio: mantido inteiro")
            segs = [(0.0, dur)]
        print(f"• {Path(v).name}: {len(segs)} trechos com fala")
        items += [{"src": str(v), "order": order, "s": s, "e": e, "a": 0.0, "m": 0.0,
                   "has_audio": has_audio, "score": 1.0} for s, e in segs]
    return items, total


def timecode(sec, fps=FPS):
    f = int(round(sec * fps))
    return f"{f // (fps * 3600):02}:{f // (fps * 60) % 60:02}:{f // fps % 60:02}:{f % fps:02}"


def write_edl(clips, path, title):
    """EDL CMX 3600 (aproximada: timecodes a 30 fps, sem timecode de origem) para abrir no Resolve/Premiere."""
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    rec = 0.0
    for i, c in enumerate(clips, 1):
        d = c["e"] - c["s"]
        reel = f"SRC{c['order'] + 1}"
        lines.append(f"{i:03d}  {reel:<8} AA/V  C        {timecode(c['s'])} {timecode(c['e'])} "
                     f"{timecode(rec)} {timecode(rec + d)}")
        lines.append(f"* FROM CLIP NAME: {Path(c['src']).name}")
        rec += d
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------ rosto (recorte do Short)
YUNET_URL = ("https://huggingface.co/opencv/face_detection_yunet/resolve/main/"
             "face_detection_yunet_2023mar.onnx")
_FACE = {}


def face_detector():
    """YuNet (OpenCV, ~230 KB, baixado uma vez para ~/.cache/autoedit). O OpenCV 5 não traz mais o Haar."""
    if "det" not in _FACE:
        import cv2
        import urllib.request
        model = Path.home() / ".cache" / "autoedit" / "face_detection_yunet_2023mar.onnx"
        if not model.exists():
            model.parent.mkdir(parents=True, exist_ok=True)
            print("  baixando o modelo de rosto (YuNet, ~230 KB)...")
            urllib.request.urlretrieve(YUNET_URL, model)
        _FACE["det"] = cv2.FaceDetectorYN.create(str(model), "", (320, 320), 0.7, 0.3, 50)
    return _FACE["det"]


def face_track(src, s, e, step=0.5, min_found=0.3):
    """Procura o rosto a cada 'step' s. Devolve [(t, cx, cy, largura)] (frações da imagem, t relativo a s)
    ou None se o rosto aparece em menos de 'min_found' das amostras (ex.: gameplay sem webcam)."""
    import cv2
    det = face_detector()
    cap = cv2.VideoCapture(str(src))
    pts, n = [], 0
    t = s + step / 2
    while t < e:
        n += 1
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, f = cap.read()
        if ok:
            fh, fw = f.shape[:2]
            sc = 640 / fw if fw > 640 else 1.0
            small = cv2.resize(f, (int(fw * sc), int(fh * sc))) if sc != 1.0 else f
            det.setInputSize((small.shape[1], small.shape[0]))
            _, faces = det.detect(small)
            if faces is not None and len(faces):
                x, y, bw, bh = max(faces, key=lambda r: r[2] * r[3])[:4]  # o maior rosto
                W, Hh = small.shape[1], small.shape[0]
                pts.append((t - s, (x + bw / 2) / W, (y + bh / 2) / Hh, bw / W))
        t += step
    cap.release()
    return pts if n and len(pts) / n >= min_found else None


def smooth_track(pts, dur, step=0.5):
    """Preenche as falhas por interpolação, suaviza (média móvel de 3) e, se o rosto mal se mexe,
    trava numa posição só (evita tremida). Devolve [(t, cx, cy, largura)] em intervalos de 'step'."""
    ts_ = [p[0] for p in pts]
    grid = [step / 2 + k * step for k in range(max(1, int(dur / step)))]
    cols = [np.interp(grid, ts_, [p[i] for p in pts]) for i in (1, 2, 3)]
    cols = [np.convolve(np.pad(c, 1, mode="edge"), np.ones(3) / 3, mode="valid") for c in cols]
    if np.ptp(cols[0]) < 0.06:  # quase parado: posição fixa
        cols = [np.full_like(c, np.median(c)) for c in cols]
    return list(zip(grid, *cols))


def lerp_expr(keys):
    """[(t, v)] -> expressão do ffmpeg que interpola linearmente entre os pontos (fora da faixa, segura o valor)."""
    if len(keys) == 1:
        return f"{keys[0][1]:.4f}"
    expr = f"{keys[-1][1]:.4f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(keys, keys[1:]))):
        expr = (f"if(lt(t,{t1:.3f}),{v0:.4f}+({v1 - v0:.4f})*(t-{t0:.3f})/{max(t1 - t0, 1e-3):.3f},{expr})")
    return f"if(lt(t,{keys[0][0]:.3f}),{keys[0][1]:.4f},{expr})"


def face_graph(w, h, track, mode):
    """Filtro do Short guiado pelo rosto.
    face    : recorte 9:16 do vídeo inteiro seguindo o rosto (tela cheia).
    facecam : webcam (recorte em volta do rosto) em cima + gameplay inteiro embaixo."""
    if mode == "face":
        cx = lerp_expr([(t, c) for t, c, *_ in track])
        return (f"crop=w='min(iw,ih*{w}/{h})':h=ih:x='max(0,min(iw-ow,({cx})*iw-ow/2))':y=0,"
                f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}")
    cx, cy, fw = (float(np.median([p[i] for p in track])) for i in (1, 2, 3))
    top_h = int(h * 0.38) // 2 * 2
    side = f"min(iw,{3.2 * fw:.4f}*iw)"  # recorte ~3x a largura do rosto, na proporção do painel
    cw = f"min(iw,min(ih*{w}/{top_h},{side}))"
    return (f"split[ta][tb];[ta]crop=w='{cw}':h='ow*{top_h}/{w}':"
            f"x='max(0,min(iw-ow,{cx:.4f}*iw-ow/2))':y='max(0,min(ih-oh,{cy:.4f}*ih-oh/2))',"
            f"scale={w}:{top_h}[top];[tb]{fit_graph(w, h - top_h, tag='g')}[bot];[top][bot]vstack")


# ----------------------------------------------------------------- renderização
def render_clip(src, s, e, out, has_audio, enc, w, h, cwd, square=False, face=None, broll=None):
    """broll = (arquivo, início, duração, filtro_de_cor): cobre a imagem a partir de 'início' s do trecho,
    mantendo o áudio original (corte de cobertura, como em vídeo falado)."""
    d = e - s
    base = (face if face else fit_graph(w, h, square)) + f",fps={FPS},setsar=1,format=yuv420p"
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{s:.3f}", "-t", f"{d:.3f}", "-i", src]
    n_in = 1
    if broll:
        bpath, b0, bd, grade = broll
        cmd += ["-t", f"{bd:.3f}", "-i", bpath]
        n_in = 2
        fc = (f"[0:v]{base}[m];[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
              f"fps={FPS},setsar=1{grade},format=yuv420p,setpts=PTS+{b0:.3f}/TB[br];"
              f"[m][br]overlay=enable='between(t,{b0:.3f},{b0 + bd:.3f})':eof_action=pass,format=yuv420p[v]")
        vopt, vmap = ["-filter_complex", fc], "[v]"
    else:
        vopt, vmap = ["-vf", base], "0:v:0"
    if has_audio:
        af = (f"aresample=48000,afade=t=in:d=0.04,"
              f"afade=t=out:st={max(d - 0.04, 0):.3f}:d=0.04")
        cmd += vopt + ["-af", af, "-map", vmap, "-map", "0:a:0"]
    else:
        cmd += ["-f", "lavfi", "-t", f"{d:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        cmd += vopt + ["-map", vmap, "-map", f"{n_in}:a:0"]
    run(cmd + enc + AUDIO_ENC + ["-t", f"{d:.3f}", out], cwd=cwd)


# ------------------------------------------------- vídeos de apoio (Pexels) + acerto de cor
PEXELS_API = "https://api.pexels.com"


def pexels_key(args):
    return args.pexels_key or os.environ.get("PEXELS_API_KEY", "")


def _http_json(url, key):
    import urllib.request
    req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": "autoedit"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def pexels_find(query, key, orientation, min_secs, per_page=15):
    """Busca vídeos no Pexels (API gratuita, chave em pexels.com/api). Devolve
    [{id, url, user, duration, file}] já com o melhor arquivo (<= 1080p, mp4) de cada um."""
    import urllib.parse
    base = os.environ.get("PEXELS_API_BASE", PEXELS_API)  # só para testes locais
    q = urllib.parse.urlencode({"query": query, "orientation": orientation, "per_page": per_page,
                                "size": "medium"})
    try:
        data = _http_json(f"{base}/videos/search?{q}", key)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! Pexels falhou para '{query}': {exc}")
        return []
    out = []
    for v in data.get("videos", []):
        if v.get("duration", 0) < min_secs:
            continue
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("link")]
        files = [f for f in files if (f.get("height") or 0) <= 1080 or (f.get("width") or 0) <= 1080]
        if not files:
            continue
        best = max(files, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
        out.append({"id": v["id"], "url": v.get("url", ""), "user": (v.get("user") or {}).get("name", ""),
                    "duration": v["duration"], "file": best["link"]})
    return out


def pexels_download(item):
    import urllib.request
    d = Path.home() / ".cache" / "autoedit" / "pexels"
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{item['id']}.mp4"
    if not dest.exists():
        tmpf = dest.with_suffix(".part")
        urllib.request.urlretrieve(item["file"], tmpf)
        tmpf.replace(dest)
    return dest


def frame_stats(img_bgr):
    """média e desvio por canal (R, G, B)."""
    rgb = img_bgr[..., ::-1].reshape(-1, 3).astype(np.float64)
    return rgb.mean(0), rgb.std(0) + 1e-6


def video_frame(path, t):
    import cv2
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, f = cap.read()
    cap.release()
    return f if ok else None


def color_match(host_frame, broll_frame, strength=0.7):
    """Filtro lutrgb que aproxima a cor do b-roll da do vídeo principal (média/contraste por canal)."""
    if host_frame is None or broll_frame is None:
        return ""
    ma, sa = frame_stats(host_frame)
    mb, sb = frame_stats(broll_frame)
    parts = []
    for ch, a_m, a_s, b_m, b_s in zip("rgb", ma, sa, mb, sb):
        gain = 1 + strength * (min(max(a_s / b_s, 0.6), 1.6) - 1)
        target = b_m + strength * (a_m - b_m)
        parts.append(f"{ch}='clip((val-{b_m:.1f})*{gain:.3f}+{target:.1f},0,255)'")
    return ",lutrgb=" + ":".join(parts)


def plan_broll(clips, args, vertical):
    """Escolhe quais trechos recebem b-roll: um a cada --broll-every s de vídeo montado.
    Devolve {índice_do_trecho: (arquivo, início, duração, filtro_de_cor)} e a lista de créditos."""
    key = pexels_key(args)
    if not args.broll or args.photos_mode:
        return {}, []
    if not key:
        print("  ! --broll pede uma chave do Pexels (gratuita): --pexels-key ou variável PEXELS_API_KEY")
        return {}, []
    queries = [q.strip() for q in args.broll.split(",") if q.strip()]
    orient = "portrait" if vertical else "landscape"
    pool = {q: pexels_find(q, key, orient, args.broll_secs) for q in queries}
    if not any(pool.values()):
        print("  ! nenhum vídeo do Pexels encontrado; seguindo sem b-roll")
        return {}, []
    plan, credits, acc, nxt, qi = {}, [], 0.0, args.broll_every, 0
    for i, c in enumerate(clips):
        d = c["e"] - c["s"]
        if c.get("photo") or acc < nxt or d < args.broll_secs + 1.0:
            acc += d
            continue
        q = queries[qi % len(queries)]
        qi += 1
        if not pool[q]:
            acc += d
            continue
        item = pool[q][(qi - 1) // len(queries) % len(pool[q])]
        try:
            path = pexels_download(item)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! download do Pexels falhou ({exc})")
            acc += d
            continue
        grade = ""
        if args.broll_color:
            grade = color_match(video_frame(c["src"], (c["s"] + c["e"]) / 2), video_frame(path, 1.0))
        plan[i] = (str(path), 0.5, min(args.broll_secs, d - 1.0), grade)
        credits.append(f"{item['url']}  (autor: {item['user']})")
        nxt = acc + d + args.broll_every
        acc += d
    return plan, credits


def render_photo(img, out, secs, enc, w, h, cwd):
    n = int(secs * FPS)
    # zoom com easing (smoothstep 3t²-2t³): começa e termina suave, em vez de linear
    vf = (fit_graph(w * 2, h * 2) +
          f",zoompan=z='1+0.1*(3*pow(on/{n},2)-2*pow(on/{n},3))':d={n}:x='iw/2-(iw/zoom/2)':"
          f"y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS},setsar=1,format=yuv420p")
    run(["ffmpeg", "-y", "-v", "error", "-i", img, "-f", "lavfi", "-t", f"{secs}",
         "-i", "anullsrc=r=48000:cl=stereo", "-vf", vf, "-map", "0:v:0", "-map", "1:a:0"]
        + enc + AUDIO_ENC + ["-t", f"{secs}", out], cwd=cwd)


def concat(names, out, cwd):
    lst = Path(cwd) / "list.txt"
    lst.write_text("".join(f"file '{n}'\n" for n in names))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
         "-c", "copy", out], cwd=cwd)


XFADES = ["fade", "dissolve", "slideleft", "wipeleft", "circleopen", "smoothleft", "zoomin"]


def join_xfade(names, out, secs, trans, fade, enc, cwd):
    """Junta clipes de 'secs' s com transição (xfade) de 'fade' s entre eles. trans='mix' alterna."""
    fade = min(fade, secs / 2)
    n = len(names)
    total = n * secs - (n - 1) * fade
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for nm in names:
        cmd += ["-i", nm]
    cmd += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    fc, prev = [], "0:v"
    for k in range(1, n):
        t = XFADES[(k - 1) % len(XFADES)] if trans == "mix" else trans
        fc.append(f"[{prev}][{k}:v]xfade=transition={t}:duration={fade:g}:"
                  f"offset={k * (secs - fade):.3f}[v{k}]")
        prev = f"v{k}"
    cmd += ["-filter_complex", ";".join(fc), "-map", f"[{prev}]", "-map", f"{n}:a"]
    run(cmd + enc + AUDIO_ENC + ["-t", f"{total:.3f}", out], cwd=cwd)


# ---------------------------------------------------------------------- legendas
def transcribe(video, model_name, lang, words=False):
    """Devolve [(início, fim, texto, palavras)]; 'palavras' = [(início, fim, palavra)] (vazio se words=False)."""
    from faster_whisper import WhisperModel
    print("  transcrevendo (Whisper)...")
    for device in ("auto", "cpu"):  # "auto" tenta a GPU; sem as DLLs CUDA (cublas) cai para a CPU
        try:
            model = WhisperModel(model_name, device=device, compute_type="int8")
            segs, info = model.transcribe(str(video), language=lang, vad_filter=True, beam_size=5,
                                          word_timestamps=words)
            out = []
            for s in segs:  # o erro de CUDA só aparece aqui, ao consumir o gerador
                if s.no_speech_prob > 0.6 or s.avg_logprob < -1.2 or not s.text.strip():
                    continue
                ws = [(w.start, w.end, w.word.strip()) for w in (s.words or []) if w.word.strip()]
                out.append((s.start, s.end, s.text.strip(), ws))
            break
        except Exception as e:
            if device == "cpu":
                raise
            print(f"  GPU indisponível para o Whisper ({e}); usando a CPU...")
    print(f"  {len(out)} falas detectadas (idioma: {info.language})")
    return out


def write_srt(segs, offset, path, width):
    lines = []
    for i, (s, e, text, *_) in enumerate(segs, 1):
        lines.append(f"{i}\n{ts(s + offset)} --> {ts(e + offset)}\n"
                     + "\n".join(textwrap.wrap(text, width)) + "\n")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def ass_ts(t):
    cs = int(round(max(t, 0) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def ass_color(hex_rgb):
    """'#FFDE1E' -> '&H001EDEFF' (o ASS usa BGR)."""
    h = hex_rgb.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def group_words(words, max_words, max_gap=0.6):
    """Agrupa palavras em blocos de até max_words, quebrando em pausa longa ou pontuação final."""
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w[0] - cur[-1][1] > max_gap
                    or cur[-1][2][-1:] in ".!?"):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def write_ass_words(segs, offset, path, w, h, mode, color, vertical, max_words=3):
    """Legenda palavra a palavra (ASS). mode='group': bloco de palavras com a atual destacada;
    mode='word': uma palavra por vez, grande. As palavras vêm do Whisper (word_timestamps)."""
    words = sorted((x for seg in segs for x in seg[3]), key=lambda x: x[0])
    size = int(h * (0.052 if vertical else 0.062)) if mode == "group" else int(h * (0.075 if vertical else 0.10))
    marg = int(h * (0.22 if vertical else 0.08))
    hi, base = ass_color(color), "&H00FFFFFF"
    head = ("[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
            f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
            "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
            "MarginL,MarginR,MarginV,Encoding\n"
            f"Style: Default,Arial,{size},{base},{base},&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,"
            f"{max(3, size // 12)},0,2,{int(w * .06)},{int(w * .06)},{marg},1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    ev = []

    def clean(x):
        return x.upper().replace("{", "(").replace("}", ")")

    groups = group_words(words, max_words if mode == "group" else 1)
    for gi, grp in enumerate(groups):
        after = groups[gi + 1][0][0] if gi + 1 < len(groups) else 1e9  # início do próximo bloco
        for k, (s, e, _) in enumerate(grp):
            nxt = grp[k + 1][0] if k + 1 < len(grp) else min(e + 0.15, after)
            end = max(nxt, s + 0.08)  # sem lacunas dentro do bloco: a palavra segue até a próxima começar
            if mode == "word":
                text = clean(grp[k][2])
            else:
                text = " ".join((f"{{\\c{hi}}}{clean(x[2])}{{\\c{base}}}" if j == k else clean(x[2]))
                                for j, x in enumerate(grp))
            ev.append(f"Dialogue: 0,{ass_ts(s + offset)},{ass_ts(end + offset)},Default,,0,0,0,,{text}")
    Path(path).write_text(head + "\n".join(ev) + "\n", encoding="utf-8")
    return len(ev)


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
def final_pass(video, out, dur, music, music_vol, srt, sub_style, enc, cwd, lufs=-16.0):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", video]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
    fc, vmap = [], "0:v"
    if srt:
        fs = f":force_style='{sub_style}'" if sub_style else ""
        fc.append(f"[0:v]subtitles={srt}{fs}[v]")
        vmap = "[v]"
    norm = f"loudnorm=I={lufs:g}:TP=-1.5:LRA=11,aresample=48000"
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
    brolls, credits = plan_broll(clips, args, vertical)
    if brolls:
        print(f"  b-roll do Pexels em {len(brolls)} trechos" + (" (cor ajustada)" if args.broll_color else ""))
        (Path(args.out) / "creditos_pexels.txt").write_text(
            "Vídeos de apoio: Pexels (pexels.com), licença gratuita; citar é opcional, mas é gentil.\n"
            + "\n".join(sorted(set(credits))) + "\n", encoding="utf-8")
    for i, c in enumerate(clips):
        name = f"c{i:04d}.mp4"
        if c.get("photo"):
            render_photo(c["photo"], name, args.photo_secs, enc, w, h, work)
        else:
            fg = None
            if vertical and args.short_crop in ("face", "facecam"):
                tr = face_track(c["src"], c["s"], c["e"])
                if tr:
                    fg = face_graph(w, h, smooth_track(tr, c["e"] - c["s"]), args.short_crop)
                else:
                    print(f"  (sem rosto em {Path(c['src']).name} {c['s']:.0f}-{c['e']:.0f}s: enquadramento normal)")
            render_clip(str(c["src"]), c["s"], c["e"], name, c["has_audio"], enc, w, h, work,
                        square=vertical and args.short_crop == "square", face=fg, broll=brolls.get(i))
        names.append(name)
    if args.photos_mode and args.photo_transition != "none" and len(names) > 1:
        join_xfade(names, "cut.mp4", args.photo_secs, args.photo_transition,
                   args.transition_secs, enc, work)
    else:
        concat(names, "cut.mp4", work)
    cut_dur, _ = probe(work / "cut.mp4")

    segs = []
    if args.subs and not args.photos_mode:
        try:
            segs = transcribe(work / "cut.mp4", args.whisper_model, args.lang,
                              words=args.sub_mode != "line")
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
    style = None
    if segs and args.sub_mode != "line" and any(s[3] for s in segs):
        n = write_ass_words(segs, offset, work / "subs.ass", w, h, args.sub_mode, args.sub_color, vertical,
                            args.sub_words)
        print(f"  legenda palavra a palavra: {n} eventos")
        srt = "subs.ass"
    elif segs:
        write_srt(segs, offset, work / "subs.srt", 22 if vertical else 40)
        srt = "subs.srt"
    total, _ = probe(work / base)
    if srt == "subs.ass":
        style = None
    else:
        style = ("FontName=Arial,FontSize=11,Bold=1,Outline=2.5,Shadow=0,MarginV=55,Alignment=2"
             if vertical else
             "FontName=Arial,FontSize=14,Bold=1,Outline=2.5,Shadow=0,MarginV=45,Alignment=2")
    final_pass(base, str(Path(out).resolve()), total, args.music, args.music_vol,
               srt, style, enc, work, args.lufs)
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
    ap.add_argument("--lufs", type=float, default=-16.0,
                    help="volume final em LUFS (padrão -16; YouTube costuma normalizar perto de -14)")
    ap.add_argument("--subs", action="store_true", help="legendas automáticas (Whisper)")
    ap.add_argument("--lang", default=None, help="idioma da fala, ex.: pt (padrão: auto)")
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--sub-mode", choices=["line", "group", "word"], default="line",
                    help="legenda: line = frase inteira (padrão), group = poucas palavras com a atual "
                         "destacada, word = uma palavra por vez (estilo Shorts)")
    ap.add_argument("--sub-words", type=int, default=3, help="palavras por bloco no --sub-mode group (padrão 3)")
    ap.add_argument("--sub-color", default="#FFDE1E", help="cor da palavra destacada (padrão amarelo #FFDE1E)")
    ap.add_argument("--extras", choices=["auto", "on", "off"], default="auto",
                    help="intro + miniatura: auto = só se o vídeo final for grande")
    ap.add_argument("--long-min", type=float, default=180, help="segundos p/ considerar 'grande'")
    ap.add_argument("--intro-video", help="sua própria intro (usa no lugar da gerada)")
    ap.add_argument("--shorts", action="store_true", help="gera também versão vertical (<=58 s)")
    ap.add_argument("--short-crop", choices=["none", "square", "face", "facecam"], default="none",
                    help="Short: 'square' recorta o centro 1:1 (gameplay maior, perde as bordas/HUD); 'face' recorta "
                         "9:16 seguindo o rosto; 'facecam' põe o rosto em cima e o gameplay embaixo")
    ap.add_argument("--min-motion", type=float, default=0.5,
                    help="descarta trechos com movimento < X * mediana (menus/inventário). 0 desliga")
    ap.add_argument("--shorts-only", action="store_true", help="gera só o Short vertical")
    ap.add_argument("--ocr", action="store_true",
                    help="lê o texto ESCRITO na tela (OCR; não vê abates só visuais) e dá nota extra a trechos "
                         "com palavras-chave, ex.: tela de resultado (pip install -r requirements-ocr.txt)")
    ap.add_argument("--ocr-keywords", default=DEFAULT_OCR_KEYWORDS,
                    help="palavras escritas na tela que marcam bons momentos, 'palavra=peso,outra=peso' "
                         "(veja o padrão no código; calibre com o <nome>_ocr.json)")
    ap.add_argument("--ocr-weight", type=float, default=0.5,
                    help="quanto da nota vem do OCR, 0-1 (padrão 0,5: trecho com palavra-chave passa à frente)")
    ap.add_argument("--ocr-every", type=float, default=1.5, help="lê 1 quadro a cada X s do trecho (padrão 1,5)")
    ap.add_argument("--ocr-region", default="0,0,1,1",
                    help="área da tela lida pelo OCR, frações 'x0,y0,x1,y1' (padrão tela toda; "
                         "ex.: 0,0.6,1,1 = faixa de baixo)")
    ap.add_argument("--cut-silences", action="store_true",
                    help="gravação falada: corta os silêncios (mantém tudo que tem som) e salva a EDL. "
                         "Ignora --target e a pontuação por cenas")
    ap.add_argument("--silence-db", type=float, default=-35.0,
                    help="abaixo de X dB conta como silêncio (padrão -35; ruído de fundo alto: use -30)")
    ap.add_argument("--min-silence", type=float, default=0.6, help="só corta silêncios >= X s (padrão 0,6)")
    ap.add_argument("--pad", type=float, default=0.15, help="folga mantida em volta da fala, em s (padrão 0,15)")
    ap.add_argument("--broll", help='vídeos de apoio do Pexels, ex.: "city night,explosion" (precisa da chave)')
    ap.add_argument("--pexels-key", help="chave da API do Pexels (ou variável PEXELS_API_KEY). Nunca vai para o repositório")
    ap.add_argument("--broll-every", type=float, default=25, help="1 b-roll a cada X s de vídeo (padrão 25)")
    ap.add_argument("--broll-secs", type=float, default=4, help="duração de cada b-roll (padrão 4 s)")
    ap.add_argument("--broll-color", choices=["on", "off"], default="on",
                    help="ajusta a cor do b-roll para a do vídeo (padrão on)")
    ap.add_argument("--photo-secs", type=float, default=3.5)
    ap.add_argument("--photo-transition", choices=["none", "mix"] + XFADES, default="none",
                    help="slideshow: transição entre fotos (none = corte seco; mix = alterna)")
    ap.add_argument("--transition-secs", type=float, default=0.6, help="duração da transição (padrão 0,6 s)")
    ap.add_argument("--gpu", action="store_true", help="usar NVENC (placa NVIDIA)")
    ap.add_argument("--font", help="arquivo .ttf para títulos")
    ap.add_argument("--plan-only", action="store_true", help="só mostra/salva os trechos")
    args = ap.parse_args()
    args.broll_color = args.broll_color == "on"

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
            if args.cut_silences:
                items, total_dur = speech_items(videos, args)
            else:
                for order, v in enumerate(videos):
                    dur, has_audio, chunks, a_sc, m_sc, ocr_res = score_video(v, args)
                    total_dur += dur
                    ocr_res = ocr_res or [{"score": 0.0, "matched": [], "texts": []}] * len(chunks)
                    items += [{"src": str(v), "order": order, "s": s, "e": e, "a": a, "m": m,
                               "has_audio": has_audio, "o": r["score"], "words": r["matched"],
                               "texts": r["texts"]}
                              for (s, e), a, m, r in zip(chunks, a_sc, m_sc, ocr_res)]
            if not items:
                sys.exit("Nenhum trecho encontrado (vídeo muito curto, ou só silêncio?).")
            if args.cut_silences:
                clips = items
                got = sum(c["e"] - c["s"] for c in clips)
                print(f"→ {len(clips)} trechos, {got:.0f}s de {total_dur:.0f}s "
                      f"(cortou {total_dur - got:.0f}s de silêncio)")
                write_edl(clips, out_dir / f"{stem}.edl", title)
            else:
                target = args.target or min(max(total_dur * 0.25, 30), 600)
                ow = args.ocr_weight if args.ocr else 0.0
                clips, got = select_clips(items, target, args.audio_weight, args.min_motion, ow)
                print(f"→ {len(clips)} trechos escolhidos, {got:.0f}s (alvo {target:.0f}s)")
                if args.ocr:
                    hits = [i for i in items if i["words"]]
                    print(f"  OCR: {len(hits)} trechos com palavra-chave, {sum(1 for c in clips if c['words'])} "
                          f"entraram no corte")
                    (out_dir / f"{stem}_ocr.json").write_text(json.dumps(
                        [{"src": Path(i["src"]).name, "start": round(i["s"], 2), "end": round(i["e"], 2),
                          "matched": i["words"], "texts": i["texts"]} for i in items if i["texts"]],
                        indent=1, ensure_ascii=False), encoding="utf-8")
            plan = [{"src": Path(c["src"]).name, "start": round(c["s"], 2),
                     "end": round(c["e"], 2), "score": round(c["score"], 3),
                     **({"ocr": c["words"]} if c.get("words") else {})} for c in clips]
            (out_dir / f"{stem}_trechos.json").write_text(json.dumps(plan, indent=2))
            if args.plan_only:
                print(json.dumps(plan, indent=2))
                return

        W, H = 1920, 1080
        out_main = out_dir / f"{stem}_final.mp4"
        if not args.shorts_only:
            print("• montando vídeo principal...")
            thumb, total, is_long = produce(clips, out_main, tmp, args, W, H, title=title)
            if thumb is not None:
                make_thumbnail(thumb, title, out_dir / f"{stem}_miniatura.jpg", args.font)
                print("  miniatura + intro adicionadas (vídeo grande)")
            elif not args.photos_mode and args.extras == "auto" and not is_long:
                print(f"  vídeo curto ({total:.0f}s < {args.long_min:.0f}s): sem intro/miniatura")

        if (args.shorts or args.shorts_only) and not args.photos_mode:
            print("• montando Shorts vertical...")
            if args.cut_silences:  # primeiros 55 s de fala
                sh, acc = [], 0.0
                for c in clips:
                    d = c["e"] - c["s"]
                    sh.append(c if acc + d <= 55 else {**c, "e": c["s"] + (55 - acc)})
                    acc += d
                    if acc >= 55:
                        break
            else:
                sh, _ = select_clips(items, 55, args.audio_weight, args.min_motion,
                                     args.ocr_weight if args.ocr else 0.0)
            produce(sh, out_dir / f"{stem}_shorts.mp4", tmp, args, 1080, 1920,
                    vertical=True, allow_extras=False, title=title)
        print(f"\n✔ pronto! Arquivos em: {out_dir.resolve()}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
