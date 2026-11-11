#!/usr/bin/env python3
"""Robô de fotos: pergunta ao Apps Script se há foto pendente, captura um quadro e entrega.

Roda no GitHub Actions (veja .github/workflows/fotos.yml). Só usa a biblioteca padrão e o ffmpeg.
Variáveis de ambiente: APPS_SCRIPT_URL (termina em /exec) e TOKEN_ROBO.
Nenhum segredo da Tuya passa por aqui: o link do vídeo vem pronto e nunca é impresso.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request


def chamar(url, dados):
    req = urllib.request.Request(
        url,
        data=json.dumps(dados).encode(),
        headers={"Content-Type": "text/plain;charset=utf-8"},
        method="POST",
    )
    # O Apps Script responde com um redirecionamento; o urllib segue sozinho.
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    url = os.environ.get("APPS_SCRIPT_URL", "").strip()
    token = os.environ.get("TOKEN_ROBO", "").strip()
    if not url or not token:
        # Ainda não configurado: avisa sem marcar a tarefa como falha (evita e-mails a cada 5 minutos).
        print("::notice::Fotos desativadas: crie os segredos APPS_SCRIPT_URL e TOKEN_ROBO no repositório.")
        return

    try:
        p = chamar(url, {"acao": "fotoPendente", "robo": token})
    except (urllib.error.URLError, ValueError) as e:
        sys.exit(f"O Apps Script não respondeu: {type(e).__name__}")
    if not p.get("ok"):
        sys.exit(f"O Apps Script recusou: {p.get('erro')}")
    if not p.get("tirar"):
        print(f"Nada a fazer: {p.get('motivo')}")
        return

    with tempfile.TemporaryDirectory() as pasta:
        arquivo = os.path.join(pasta, "quadro.jpg")
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", p["url"],
             "-frames:v", "1", "-q:v", "3", arquivo],
            capture_output=True, text=True, timeout=90,
        )
        if r.returncode != 0 or not os.path.exists(arquivo):
            # A mensagem do ffmpeg pode conter o link do vídeo; não vai para o log.
            sys.exit("O ffmpeg não conseguiu capturar a imagem da câmera.")
        with open(arquivo, "rb") as f:
            jpeg = base64.b64encode(f.read()).decode()

    g = chamar(url, {"acao": "fotoSalvar", "robo": token, "motivo": p["motivo"],
                     "refeicao": p.get("refeicao", 0), "jpeg": jpeg})
    if not g.get("ok"):
        sys.exit(f"O Apps Script não salvou a foto: {g.get('erro')}")
    print(f"Foto salva no Drive: {g.get('nome')} ({p['motivo']})")


if __name__ == "__main__":
    main()
