#!/usr/bin/env python3
"""
animar_html.py - renderiza uma animação feita em HTML/CSS/JS (GSAP, Three.js, canvas...) quadro a quadro
e grava um vídeo, com fundo transparente se quiser. Navegador sem janela (Playwright/Chromium) + FFmpeg,
a mesma ideia de Remotion/HyperFrames, mas sem Node nem licença de empresa.

Contrato da página HTML (veja scripts/animacoes/*.html):
  - lê os textos em  window.DADOS  (o JSON de --dados);
  - define  window.seek(t)  que coloca a animação no instante t (em segundos). Com GSAP: `tl.pause(); window.seek = t => tl.time(t)`;
  - (opcional) window.DURACAO = duração sugerida, usada se --duracao não for passado.
O renderizador chama seek(t) para cada quadro e tira uma captura: o resultado é exato e não depende do relógio.

Exemplos:
  python scripts/animar_html.py titulo --dados '{"titulo":"CLUTCH INSANO","subtitulo":"@meucanal"}' -o titulo.mov
  python scripts/animar_html.py titulo --dados '{"titulo":"RANKED"}' --fundo "#0b1020" -o intro.mp4      # p/ --intro-video
  python scripts/animar_html.py terco_inferior --dados '{"nome":"Danyllo","cargo":"Gameplay"}' --sobre video.mp4 --em 3 -o com_nome.mp4
Saídas: .mov (transparente, qtrle), .webm (transparente, VP9) ou .mp4 (opaco; precisa de --fundo).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

PASTA = Path(__file__).resolve().parent / "animacoes"
GSAP_URL = "https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js"
CACHE = Path.home() / ".cache" / "autoedit"


def gsap_local():
    """GSAP (gratuito) é baixado uma vez e servido do disco, para renderizar também sem internet."""
    dest = CACHE / "gsap-3.12.5.min.js"
    if not dest.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print("baixando GSAP (uma vez)...", file=sys.stderr)
        urllib.request.urlretrieve(GSAP_URL, dest)
    return dest


def achar_html(nome):
    p = Path(nome)
    if p.exists():
        return p.resolve()
    q = PASTA / (nome if nome.endswith(".html") else nome + ".html")
    if q.exists():
        return q
    sys.exit(f"Não achei o HTML '{nome}'. Modelos prontos: " + ", ".join(sorted(x.stem for x in PASTA.glob("*.html"))))


def lancar(pw):
    try:
        return pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001
        for cand in (os.environ.get("AUTOEDIT_CHROMIUM"), "/opt/pw-browsers/chromium"):
            if cand and Path(cand).exists():  # navegador já instalado fora do Playwright (ex.: nuvem)
                return pw.chromium.launch(executable_path=cand, args=["--no-sandbox"])
        sys.exit(f"Não consegui abrir o Chromium ({exc}).\nRode uma vez:  python -m playwright install chromium")


def codec_saida(saida, transparente):
    ext = Path(saida).suffix.lower()
    if ext == ".webm":
        return ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "28", "-auto-alt-ref", "0"]
    if ext == ".mov":
        return ["-c:v", "qtrle", "-pix_fmt", "argb"]
    if transparente:
        sys.exit("Fundo transparente só em .mov ou .webm. Para .mp4 passe --fundo '#RRGGBB'.")
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]


def renderizar(html, dados, dur, fps, w, h, fundo, destino):
    from playwright.sync_api import sync_playwright
    transp = not fundo
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "png", "-i", "-"]
    cmd += codec_saida(destino, transp) + [str(destino)]
    gsap = gsap_local()
    with sync_playwright() as pw:
        nav = lancar(pw)
        page = nav.new_page(viewport={"width": w, "height": h})
        page.route(GSAP_URL, lambda r: r.fulfill(path=str(gsap), content_type="application/javascript"))
        page.add_init_script(f"window.DADOS = {json.dumps(dados, ensure_ascii=False)};")
        page.goto(html.as_uri())
        page.wait_for_function("typeof window.seek === 'function'", timeout=15000)
        page.evaluate("document.fonts.ready")
        if fundo:
            page.evaluate("c => { document.documentElement.style.background = c; document.body.style.background = c; }",
                          fundo)
        dur = dur or page.evaluate("window.DURACAO") or 3.0
        n = max(1, int(round(dur * fps)))
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(n):
            page.evaluate("t => window.seek(t)", i / fps)
            proc.stdin.write(page.screenshot(type="png", omit_background=transp))
            if i % 30 == 29:
                print(f"\r  {i + 1}/{n} quadros", end="", file=sys.stderr)
        proc.stdin.close()
        if proc.wait() != 0:
            sys.exit("ffmpeg falhou ao gravar o vídeo.")
        nav.close()
    print(f"\n✔ {destino} ({n} quadros, {dur:g} s)", file=sys.stderr)
    return dur


def sobrepor(video, anim, em, saida):
    """Coloca a animação transparente por cima do vídeo, começando em 'em' s."""
    fc = (f"[1:v]format=rgba,setpts=PTS-STARTPTS+{em}/TB[a];"
          "[0:v][a]overlay=eof_action=pass:format=auto[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(anim), "-filter_complex", fc,
                    "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "copy", str(saida)], check=True)
    print(f"✔ {saida}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Renderiza uma animação HTML (GSAP/Three.js/canvas) em vídeo")
    ap.add_argument("html", help="modelo pronto (titulo, terco_inferior) ou caminho de um .html seu")
    ap.add_argument("--dados", default="{}", help="JSON com os textos (ou @arquivo.json)")
    ap.add_argument("--duracao", type=float, help="segundos (padrão: o que a página sugerir em window.DURACAO)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--res", default="1920x1080", help="LARGURAxALTURA (padrão 1920x1080; Shorts: 1080x1920)")
    ap.add_argument("--fundo", help="cor de fundo #RRGGBB (sem ela o fundo é transparente)")
    ap.add_argument("--sobre", help="vídeo onde colocar a animação por cima (ela é renderizada no tamanho do vídeo)")
    ap.add_argument("--em", type=float, default=0.0, help="com --sobre: segundo em que a animação entra")
    ap.add_argument("-o", "--saida", required=True, help=".mov/.webm (transparente) ou .mp4 (com --fundo, ou com --sobre)")
    a = ap.parse_args()
    dados = json.loads(Path(a.dados[1:]).read_text(encoding="utf-8") if a.dados.startswith("@") else a.dados)
    w, h = (int(v) for v in a.res.lower().split("x"))
    html = achar_html(a.html)
    if a.sobre:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", a.sobre], capture_output=True, text=True)
        try:
            w, h = (int(v) for v in r.stdout.strip().split(",")[:2])  # a animação nasce no tamanho do vídeo
        except ValueError:
            sys.exit(f"Não consegui ler o tamanho de {a.sobre}")
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "anim.mov"
            renderizar(html, dados, a.duracao, a.fps, w, h, None, tmp)
            sobrepor(a.sobre, tmp, a.em, a.saida)
    else:
        renderizar(html, dados, a.duracao, a.fps, w, h, a.fundo, a.saida)


if __name__ == "__main__":
    main()
