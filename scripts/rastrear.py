#!/usr/bin/env python3
"""
rastrear.py - segue um objeto no vídeo (OpenCV VitTrack, modelo de 0,7 MB baixado uma vez) e usa o caminho dele:
  - desenha um anel/caixa + texto que acompanha o objeto (--forma, --texto);
  - com --seguir, gera um recorte vertical 9:16 que acompanha o objeto;
  - grava <saida>.json com a posição por quadro (para usar em outro editor).

Você diz onde o objeto está no PRIMEIRO quadro (--caixa x,y,largura,altura em pixels, ou em frações 0-1).
Para descobrir as coordenadas: `python scripts/rastrear.py video.mp4 --ver` salva `<video>_quadro.jpg` com uma grade.

Exemplos:
  python scripts/rastrear.py clipe.mp4 --caixa 100,200,300,300 --texto "OLHA ISSO" --forma anel
  python scripts/rastrear.py clipe.mp4 --caixa 0.1,0.3,0.2,0.2 --seguir -o vertical.mp4
Limites: o rastreador perde o objeto se ele sai da tela, é coberto ou muda muito; nesse caso a marca fica parada
no último ponto conhecido (o JSON marca `perdido: true`).
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _comum import abrir_saida, fechar_saida, modelo  # noqa: E402


def criar_rastreador():
    try:
        p = cv2.TrackerVit_Params()
        p.net = str(modelo("vittrack.onnx"))
        return cv2.TrackerVit_create(p), "VitTrack"
    except Exception as exc:  # noqa: BLE001
        print(f"  VitTrack indisponível ({exc}); usando TrackerMIL (menos preciso)", file=sys.stderr)
        return cv2.TrackerMIL_create(), "MIL"


def parse_caixa(s, w, h):
    x, y, bw, bh = (float(v) for v in s.split(","))
    if max(x, y, bw, bh) <= 1.0:
        x, y, bw, bh = x * w, y * h, bw * w, bh * h
    return int(x), int(y), int(bw), int(bh)


def ver(video):
    cap = cv2.VideoCapture(video)
    ok, f = cap.read()
    if not ok:
        sys.exit("Não consegui ler o vídeo.")
    h, w = f.shape[:2]
    for k in range(1, 10):
        cv2.line(f, (w * k // 10, 0), (w * k // 10, h), (255, 255, 255), 1)
        cv2.line(f, (0, h * k // 10), (w, h * k // 10), (255, 255, 255), 1)
        cv2.putText(f, f"{k * 10}%", (w * k // 10 + 3, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.putText(f, f"{k * 10}%", (3, h * k // 10 - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    dest = Path(video).with_name(Path(video).stem + "_quadro.jpg")
    cv2.imwrite(str(dest), f)
    print(f"Quadro {w}x{h} salvo em {dest} (grade a cada 10%). Use --caixa x,y,largura,altura.")


def marca(img, cx, cy, bw, bh, forma, texto):
    cor = (30, 222, 255)  # amarelo (BGR)
    if forma == "caixa":
        cv2.rectangle(img, (int(cx - bw / 2), int(cy - bh / 2)), (int(cx + bw / 2), int(cy + bh / 2)), cor, 4)
    else:
        cv2.ellipse(img, (int(cx), int(cy)), (int(bw * .62), int(bh * .62)), 0, 0, 360, cor, 5, cv2.LINE_AA)
    if texto:
        (tw, th), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_DUPLEX, 1.0, 2)
        x, y = int(cx - tw / 2), int(cy - bh * .62 - 14)
        y = max(y, th + 6)
        cv2.rectangle(img, (x - 8, y - th - 8), (x + tw + 8, y + 8), (0, 0, 0), -1)
        cv2.putText(img, texto, (x, y), cv2.FONT_HERSHEY_DUPLEX, 1.0, cor, 2, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser(description="Rastreia um objeto e desenha/recorta seguindo ele")
    ap.add_argument("video")
    ap.add_argument("--ver", action="store_true", help="só salva o 1º quadro com grade para achar a --caixa")
    ap.add_argument("--caixa", help="x,y,largura,altura do objeto no 1º quadro (pixels ou frações 0-1)")
    ap.add_argument("--texto", default="", help="texto ao lado da marca")
    ap.add_argument("--forma", choices=["anel", "caixa"], default="anel")
    ap.add_argument("--seguir", action="store_true", help="saída vertical 1080x1920 recortada em volta do objeto")
    ap.add_argument("-o", "--saida", help="arquivo de saída (padrão: <nome>_rastreio.mp4)")
    a = ap.parse_args()
    if a.ver:
        return ver(a.video)
    if not a.caixa:
        sys.exit("Passe --caixa x,y,largura,altura (use --ver para achar as coordenadas).")

    cap = cv2.VideoCapture(a.video)
    ok, f = cap.read()
    if not ok:
        sys.exit(f"Não consegui ler {a.video}")
    h, w = f.shape[:2]
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    box = parse_caixa(a.caixa, w, h)
    trk, nome = criar_rastreador()
    trk.init(f, box)
    ow, oh = (1080, 1920) if a.seguir else (w, h)
    saida = a.saida or str(Path(a.video).with_name(Path(a.video).stem + "_rastreio.mp4"))
    proc = abrir_saida(a.video, saida, ow, oh, fps)
    track, ult, sx, n = [], box, None, 0
    while True:
        if n:
            ok, f = cap.read()
            if not ok:
                break
            ok_t, b = trk.update(f)
            perdido = not ok_t
            if ok_t:
                ult = tuple(int(v) for v in b)
        else:
            perdido = False
        x, y, bw, bh = ult
        cx, cy = x + bw / 2, y + bh / 2
        track.append({"t": round(n / fps, 3), "x": x, "y": y, "w": bw, "h": bh, "perdido": perdido})
        out = f.copy()
        if a.seguir:
            cw = min(w, int(h * 9 / 16))
            sx = cx if sx is None else 0.8 * sx + 0.2 * cx  # câmera suave
            x0 = int(min(max(sx - cw / 2, 0), w - cw))
            out = cv2.resize(out[:, x0:x0 + cw], (1080, 1920), interpolation=cv2.INTER_CUBIC)
            marca(out, (cx - x0) * 1080 / cw, cy * 1920 / h, bw * 1080 / cw, bh * 1920 / h, a.forma, a.texto)
        else:
            marca(out, cx, cy, bw, bh, a.forma, a.texto)
        proc.stdin.write(out.tobytes())
        n += 1
    cap.release()
    fechar_saida(proc)
    Path(saida).with_suffix(".json").write_text(json.dumps(
        {"rastreador": nome, "fps": fps, "quadros": track}, indent=1), encoding="utf-8")
    perdidos = sum(t["perdido"] for t in track)
    print(f"✔ {saida} ({nome}; {perdidos} de {len(track)} quadros sem achar o objeto)")


if __name__ == "__main__":
    main()
