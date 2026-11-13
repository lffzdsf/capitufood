#!/usr/bin/env python3
"""Robô de fotos: pergunta ao Apps Script se há foto pendente, captura um quadro e entrega.

Roda no GitHub Actions (veja .github/workflows/fotos.yml). Só usa a biblioteca padrão e o ffmpeg.
Variáveis de ambiente: APPS_SCRIPT_URL (termina em /exec) e TOKEN_ROBO.
Nenhum segredo da Tuya passa por aqui: o link do vídeo vem pronto e nunca é impresso.

O resultado de cada execução aparece como anotação na página da execução no GitHub
(visível sem abrir o log).
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request


def anotar(nivel, msg):
    """Anotação na página da execução (notice, warning ou error)."""
    print(f"::{nivel}::{msg}", flush=True)


def falhar(msg):
    anotar("error", msg)
    sys.exit(1)


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
    faltam = [nome for nome, valor in (("APPS_SCRIPT_URL", url), ("TOKEN_ROBO", token)) if not valor]
    if faltam:
        msg = ("Faltam os segredos do repositório: " + ", ".join(faltam) + ". Crie em Settings > Secrets and variables > "
               "Actions, na aba Secrets (não em Variables), com o nome exatamente assim.")
        if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
            falhar(msg)                        # teste manual ou alteração no robô: a falha tem que aparecer
        # Execução agendada sem configuração: avisa sem marcar falha (evita e-mail a cada execução).
        anotar("notice", "Fotos desativadas. " + msg)
        return
    if not (url.startswith("https://script.google.com/macros/s/") and url.endswith("/exec")):
        falhar("APPS_SCRIPT_URL não parece o endereço do app da web: deve começar com "
               "https://script.google.com/macros/s/ e terminar em /exec (não é o 'código de implantação').")

    try:
        p = chamar(url, {"acao": "fotoPendente", "robo": token})
    except (urllib.error.URLError, ValueError) as e:
        falhar(f"O Apps Script não respondeu ({type(e).__name__}). Confira o endereço e se a implantação está aberta a 'Qualquer pessoa'.")
    if not p.get("ok"):
        falhar(f"O Apps Script recusou: {p.get('erro')}")
    if not p.get("tirar"):
        anotar("notice", f"Nada a fazer: {p.get('motivo')}")
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
            falhar("O ffmpeg não conseguiu capturar a imagem da câmera.")
        with open(arquivo, "rb") as f:
            jpeg = base64.b64encode(f.read()).decode()

    g = chamar(url, {"acao": "fotoSalvar", "robo": token, "motivo": p["motivo"],
                     "refeicao": p.get("refeicao", 0), "jpeg": jpeg})
    if not g.get("ok"):
        falhar(f"O Apps Script não salvou a foto: {g.get('erro')}")
    anotar("notice", f"Foto salva no Drive: {g.get('nome')} ({p['motivo']})")


if __name__ == "__main__":
    main()
