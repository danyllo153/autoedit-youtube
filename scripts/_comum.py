"""Auxiliares dos scripts de visão (pessoa_fundo.py, rastrear.py): download de modelos e saída para o ffmpeg."""
import subprocess
import sys
import urllib.request
from pathlib import Path

CACHE = Path.home() / ".cache" / "autoedit"
MODELOS = {
    # U²-Net pequeno (4,6 MB, Apache-2.0): recorte do objeto/pessoa em primeiro plano
    "u2netp.onnx": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
    # U²-Net treinado para pessoas (176 MB, Apache-2.0): recorte melhor, mais lento
    "u2net_human_seg.onnx": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx",
    # VitTrack (0,7 MB): rastreador de objetos do OpenCV
    "vittrack.onnx": "https://huggingface.co/opencv/object_tracking_vittrack/resolve/main/"
                     "object_tracking_vittrack_2023sep.onnx",
}


def modelo(nome):
    """Caminho do modelo; baixa uma vez para ~/.cache/autoedit."""
    dest = CACHE / nome
    if not dest.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"baixando {nome}...", file=sys.stderr)
        parcial = dest.with_suffix(".part")
        urllib.request.urlretrieve(MODELOS[nome], parcial)
        parcial.replace(dest)
    return dest


def abrir_saida(entrada, saida, w, h, fps, vertical_audio=True):
    """Processo do ffmpeg que recebe quadros BGR crus no stdin e junta o áudio do arquivo de entrada."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
           "-r", f"{fps:.4f}", "-i", "-", "-i", str(entrada), "-map", "0:v", "-map", "1:a?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", str(saida)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def fechar_saida(proc):
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg falhou ao gravar o vídeo.")
