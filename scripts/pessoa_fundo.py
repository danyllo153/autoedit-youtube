#!/usr/bin/env python3
"""
pessoa_fundo.py - recorta a PESSOA (ou o objeto em primeiro plano) de cada quadro, sem tela verde.

Dois usos (combináveis):
  --titulo "TEXTO"    título grande ATRÁS da pessoa (entra com fade/zoom; --de/--ate escolhem o intervalo)
  --fundo MODO        troca o fundo: blur | escuro | cor:#RRGGBB | caminho de imagem

O recorte usa o U²-Net pequeno (4,6 MB, baixado uma vez para ~/.cache/autoedit) via onnxruntime, na CPU.
Ele recorta "o que está em destaque": funciona melhor com uma pessoa sozinha, bem separada do fundo.

Exemplos:
  python scripts/pessoa_fundo.py eu.mp4 --titulo "CLUTCH INSANO" --de 0 --ate 4
  python scripts/pessoa_fundo.py eu.mp4 --fundo blur
  python scripts/pessoa_fundo.py eu.mp4 --fundo cor:#00AA55 --titulo "OI" -o saida.mp4
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _comum import abrir_saida, fechar_saida, modelo  # noqa: E402

MEDIA, DESVIO = np.array([0.485, 0.456, 0.406], np.float32), np.array([0.229, 0.224, 0.225], np.float32)


class Recortador:
    def __init__(self, humano=False):
        import onnxruntime as ort
        arq = "u2net_human_seg.onnx" if humano else "u2netp.onnx"
        self.sess = ort.InferenceSession(str(modelo(arq)), providers=["CPUExecutionProvider"])
        self.nome = self.sess.get_inputs()[0].name

    def mascara(self, bgr):
        """Mapa 0-1 (mesma altura/largura do quadro): 1 = pessoa/primeiro plano."""
        h, w = bgr.shape[:2]
        x = cv2.cvtColor(cv2.resize(bgr, (320, 320), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        x = ((x.astype(np.float32) / 255.0 - MEDIA) / DESVIO).transpose(2, 0, 1)[None]
        m = self.sess.run(None, {self.nome: x})[0][0, 0]
        m = (m - m.min()) / (m.max() - m.min() + 1e-6)
        m = np.clip((m - 0.3) / 0.4, 0, 1)  # endurece a borda: dentro = 1, fora = 0
        return cv2.GaussianBlur(cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR), (0, 0), 1.5)


def camada_titulo(texto, w, h, cor, pos, fonte):
    """Imagem BGR + alfa (0-1) do título, do tamanho do quadro."""
    from PIL import Image
    import autoedit
    rgb = tuple(int(cor.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cy = int(h * pos)
    autoedit.draw_title(img, texto, (int(w * .04), cy - int(h * .28), int(w * .96), cy + int(h * .28)),
                        rgb + (255,), fonte, start=int(h * .30), anchor="center")
    a = np.asarray(img)
    return a[..., [2, 1, 0]].copy(), a[..., 3].astype(np.float32) / 255.0


def novo_fundo(modo, frame):
    h, w = frame.shape[:2]
    if modo == "blur":
        return cv2.GaussianBlur(frame, (0, 0), max(w, h) / 60)
    if modo == "escuro":
        return (cv2.GaussianBlur(frame, (0, 0), max(w, h) / 60) * 0.35).astype(np.uint8)
    if modo.startswith("cor:"):
        r, g, b = (int(modo[4:].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        return np.full_like(frame, (b, g, r))
    img = cv2.imread(modo)
    if img is None:
        sys.exit(f"Não consegui abrir a imagem de fundo: {modo}")
    return cv2.resize(img, (w, h))


def main():
    ap = argparse.ArgumentParser(description="Recorte de pessoa: título atrás dela e/ou troca de fundo")
    ap.add_argument("video")
    ap.add_argument("-o", "--saida", help="arquivo de saída (padrão: <nome>_recorte.mp4)")
    ap.add_argument("--titulo", help="texto grande atrás da pessoa")
    ap.add_argument("--cor", default="#FFDE1E", help="cor do título (padrão amarelo)")
    ap.add_argument("--pos", type=float, default=0.42, help="altura do centro do título, 0-1 (padrão 0,42)")
    ap.add_argument("--de", type=float, default=0.0, help="o título entra neste segundo (padrão 0)")
    ap.add_argument("--ate", type=float, default=None, help="o título sai neste segundo (padrão: até o fim)")
    ap.add_argument("--fundo", help="blur | escuro | cor:#RRGGBB | imagem.jpg")
    ap.add_argument("--fonte", help="arquivo .ttf do título")
    ap.add_argument("--modelo", choices=["leve", "humano"], default="leve",
                    help="leve = U²-Net pequeno (4,6 MB, rápido, borda grosseira); humano = U²-Net de pessoas "
                         "(176 MB baixados uma vez, recorte melhor, mais lento)")
    ap.add_argument("--cada", type=int, default=1,
                    help="calcula o recorte a cada N quadros (padrão 1; 2-3 acelera, com leve atraso na borda)")
    a = ap.parse_args()
    if not a.titulo and not a.fundo:
        sys.exit("Use --titulo e/ou --fundo.")

    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened():
        sys.exit(f"Não consegui abrir {a.video}")
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    saida = a.saida or str(Path(a.video).with_name(Path(a.video).stem + "_recorte.mp4"))
    rec = Recortador(a.modelo == "humano")
    tit_bgr = tit_a = None
    if a.titulo:
        tit_bgr, tit_a = camada_titulo(a.titulo, w, h, a.cor, a.pos, a.fonte)
    proc = abrir_saida(a.video, saida, w, h, fps)
    m, n = None, 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        t = n / fps
        if m is None or n % a.cada == 0:
            novo = rec.mascara(f)
            m = novo if m is None else 0.35 * m + 0.65 * novo  # suaviza no tempo: menos tremida na borda
        out = novo_fundo(a.fundo, f) if a.fundo else f.copy()
        if a.titulo and t >= a.de and (a.ate is None or t <= a.ate):
            k = min((t - a.de) / 0.4, 1.0)  # fade/zoom de entrada
            k = k * k * (3 - 2 * k)
            if a.ate is not None:
                k *= min((a.ate - t) / 0.3, 1.0)
            esc = 1.12 - 0.12 * k
            M = cv2.getRotationMatrix2D((w / 2, h * a.pos), 0, esc)
            tb = cv2.warpAffine(tit_bgr, M, (w, h))
            ta = cv2.warpAffine(tit_a, M, (w, h)) * k
            out = (out * (1 - ta[..., None]) + tb * ta[..., None]).astype(np.uint8)
        mm = m[..., None]
        out = (out * (1 - mm) + f * mm).astype(np.uint8)  # a pessoa sempre por cima
        proc.stdin.write(out.tobytes())
        n += 1
        if n % 60 == 0:
            print(f"\r  {n}/{total} quadros", end="", file=sys.stderr)
    cap.release()
    fechar_saida(proc)
    print(f"\n✔ {saida}")


if __name__ == "__main__":
    main()
