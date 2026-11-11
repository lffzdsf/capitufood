#!/usr/bin/env python3
"""Cliente mínimo da Tuya Cloud API (só biblioteca padrão) para o comedouro Amicura.

Uso:
  python3 tuya.py info                 dados do dispositivo (nome, categoria, online, local_key)
  python3 tuya.py funcoes              comandos que o dispositivo aceita (com tipos e faixas)
  python3 tuya.py status               estado atual de todos os data points
  python3 tuya.py modelo               modelo completo (propriedades, ações, eventos)
  python3 tuya.py propriedades         estado de todos os data points, inclusive alimentação
  python3 tuya.py definir CODE VALOR   escreve um data point, ex.: definir manual_feed 1
  python3 tuya.py comando CODE VALOR   envia um comando padrão (só funções de câmera)
  python3 tuya.py stream [rtsp|hls]    pede um link temporário do vídeo da câmera

Credenciais em Comedouro/.env (veja .env.example).
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

AQUI = os.path.dirname(os.path.abspath(__file__))


def carregar_env():
    caminho = os.path.join(AQUI, ".env")
    if not os.path.exists(caminho):
        sys.exit("Falta o arquivo Comedouro/.env. Copie .env.example para .env e preencha.")
    cfg = {}
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("TUYA_ACCESS_ID", "TUYA_ACCESS_SECRET", "TUYA_DEVICE_ID"):
        if not cfg.get(k):
            sys.exit(f"Falta {k} em Comedouro/.env")
    cfg.setdefault("TUYA_ENDPOINT", "https://openapi.tuyaus.com")
    return cfg


class TuyaErro(Exception):
    pass


class Tuya:
    def __init__(self, cfg):
        self.id = cfg["TUYA_ACCESS_ID"]
        self.secret = cfg["TUYA_ACCESS_SECRET"].encode()
        self.base = cfg["TUYA_ENDPOINT"].rstrip("/")
        self.device = cfg["TUYA_DEVICE_ID"]
        self.token = None
        self.expira = 0

    def _req(self, metodo, caminho, corpo=None, com_token=True):
        # A URL assinada precisa ter os parâmetros de query em ordem alfabética.
        partes = urllib.parse.urlsplit(caminho)
        if partes.query:
            q = sorted(urllib.parse.parse_qsl(partes.query, keep_blank_values=True))
            caminho = partes.path + "?" + "&".join(f"{k}={v}" for k, v in q)
        dados = json.dumps(corpo, separators=(",", ":")).encode() if corpo is not None else b""
        t = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        a_assinar = "\n".join([metodo, hashlib.sha256(dados).hexdigest(), "", caminho])
        token = self._token() if com_token else ""
        msg = self.id + token + t + nonce + a_assinar
        sign = hmac.new(self.secret, msg.encode(), hashlib.sha256).hexdigest().upper()
        cab = {
            "client_id": self.id,
            "sign": sign,
            "t": t,
            "nonce": nonce,
            "sign_method": "HMAC-SHA256",
            "Content-Type": "application/json",
        }
        if token:
            cab["access_token"] = token
        req = urllib.request.Request(self.base + caminho, data=dados or None, headers=cab, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.load(r)
        except urllib.error.HTTPError as e:
            raise TuyaErro(f"HTTP {e.code} em {caminho}: {e.read().decode(errors='replace')[:300]}")
        except urllib.error.URLError as e:
            raise TuyaErro(f"Sem conexão com {self.base}: {e.reason}")
        if not resp.get("success"):
            raise TuyaErro(f"Tuya recusou {caminho}: código {resp.get('code')} - {resp.get('msg')}")
        return resp["result"]

    def _token(self):
        if not self.token or time.time() > self.expira - 60:
            r = self._req("GET", "/v1.0/token?grant_type=1", com_token=False)
            self.token = r["access_token"]
            self.expira = time.time() + r["expire_time"]
        return self.token

    def info(self):
        return self._req("GET", f"/v1.0/devices/{self.device}")

    def funcoes(self):
        return self._req("GET", f"/v1.0/devices/{self.device}/specifications")

    def status(self):
        return self._req("GET", f"/v1.0/devices/{self.device}/status")

    def modelo(self):
        r = self._req("GET", f"/v2.0/cloud/thing/{self.device}/model")
        try:
            return json.loads(r["model"])
        except (KeyError, TypeError, ValueError):
            return r

    def propriedades(self):
        """Estado de TODOS os data points, inclusive os fora do padrão (alimentação)."""
        return self._req("GET", f"/v2.0/cloud/thing/{self.device}/shadow/properties")["properties"]

    def definir(self, code, valor):
        """Escreve um data point pelo modelo completo (funciona para os de alimentação)."""
        return self._req(
            "POST",
            f"/v2.0/cloud/thing/{self.device}/shadow/properties/issue",
            {"properties": json.dumps({code: valor}, separators=(",", ":"))},
        )

    def historico(self, code="feed_record", dias=7, tamanho=50):
        """Últimos valores reportados de um data point (padrão: refeições dos últimos 7 dias)."""
        fim = int(time.time() * 1000)
        ini = fim - dias * 86400 * 1000
        r = self._req(
            "GET",
            f"/v2.1/cloud/thing/{self.device}/report-logs"
            f"?codes={code}&start_time={ini}&end_time={fim}&size={tamanho}",
        )
        return r.get("logs") or []

    def comando(self, code, valor):
        return self._req(
            "POST",
            f"/v1.0/devices/{self.device}/commands",
            {"commands": [{"code": code, "value": valor}]},
        )

    def stream(self, tipo="rtsp"):
        return self._req(
            "POST",
            f"/v1.0/devices/{self.device}/stream/actions/allocate",
            {"type": tipo},
        )


def interpretar(valor):
    try:
        return json.loads(valor)
    except ValueError:
        return valor


def main():
    try:
        _main()
    except TuyaErro as e:
        sys.exit(str(e))


def _main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    t = Tuya(carregar_env())
    acao = args[0]
    if acao == "info":
        r = t.info()
    elif acao == "funcoes":
        r = t.funcoes()
    elif acao == "status":
        r = t.status()
    elif acao == "modelo":
        r = t.modelo()
    elif acao == "propriedades":
        r = t.propriedades()
    elif acao == "definir" and len(args) == 3:
        r = t.definir(args[1], interpretar(args[2]))
    elif acao == "comando" and len(args) == 3:
        r = t.comando(args[1], interpretar(args[2]))
    elif acao == "stream":
        r = t.stream(args[1] if len(args) > 1 else "rtsp")
    else:
        sys.exit(__doc__)
    print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
