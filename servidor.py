#!/usr/bin/env python3
"""Painel local do comedouro. Rode: python3 servidor.py  e abra http://127.0.0.1:8765

Só escuta em 127.0.0.1 (este computador). Usa tuya.py e o .env desta pasta.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from tuya import Tuya, TuyaErro, carregar_env  # noqa: E402

PORTA = int(os.environ.get("PORT", "8765"))
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

# Só estes data points podem ser escritos pelo painel, com validação de valor.
GRAVAVEIS = {
    "manual_feed": lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 10,
    "dev_volume_adjust": lambda v: isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100,
    "basic_private": lambda v: isinstance(v, bool),
    "basic_osd": lambda v: isinstance(v, bool),
    "motion_switch": lambda v: isinstance(v, bool),
    "motion_sensitivity": lambda v: v in ("0", "1", "2"),
    "basic_nightvision": lambda v: v in ("0", "1", "2"),
}

tuya = Tuya(carregar_env())
trava = threading.Lock()


def decodificar_agenda(hexa):
    """meal_plan2: blocos de 4 bytes. Interpretação inferida dos dados, ainda não confirmada:
    dias (bitmask) | hora | minuto | porções (nibble alto) + ligado (nibble baixo)."""
    itens = []
    try:
        for i in range(0, len(hexa) - 7, 8):
            dias, hora, minuto, ultimo = hexa[i:i + 2], hexa[i + 2:i + 4], hexa[i + 4:i + 6], hexa[i + 6:i + 8]
            itens.append({
                "dias": int(dias, 16),
                "hora": f"{hora}:{minuto}",
                "porcoes": int(ultimo[0], 16),
                "ligado": ultimo[1] != "0",
            })
    except ValueError:
        return []
    return itens


def codificar_agenda(itens):
    """Inverso de decodificar_agenda. Valida tudo e devolve a string hexadecimal ordenada por horário."""
    if not isinstance(itens, list) or len(itens) > 10:
        raise ValueError("a agenda aceita no máximo 10 horários")
    blocos = []
    for it in itens:
        try:
            dias, hora, porcoes, ligado = it["dias"], it["hora"], it["porcoes"], it["ligado"]
            hh, mm = hora.split(":")
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError("horário inválido")
        if not (isinstance(dias, int) and not isinstance(dias, bool) and 1 <= dias <= 127):
            raise ValueError("dias inválidos")
        if not (len(hh) == 2 and len(mm) == 2 and hh.isdigit() and mm.isdigit() and int(hh) < 24 and int(mm) < 60):
            raise ValueError(f"hora inválida: {hora}")
        if not (isinstance(porcoes, int) and not isinstance(porcoes, bool) and 1 <= porcoes <= 9):
            raise ValueError("porções devem ser de 1 a 9")
        if not isinstance(ligado, bool):
            raise ValueError("campo ligado inválido")
        blocos.append((hh + mm, f"{dias:02x}{hh}{mm}{porcoes:x}{1 if ligado else 0}"))
    horas = [h for h, _ in blocos]
    if len(set(horas)) != len(horas):
        raise ValueError("há dois horários iguais")
    return "".join(b for _, b in sorted(blocos))


def estado():
    info = tuya.info()
    props = {p["code"]: p.get("value") for p in tuya.propriedades()}
    ultima = None
    try:
        ultima = json.loads(props.get("feed_record") or "null")
    except ValueError:
        pass
    return {
        "nome": info.get("name"),
        "modelo": info.get("product_name"),
        "online": info.get("online"),
        "props": {k: props.get(k) for k in list(GRAVAVEIS) + ["feed_state", "battery_value", "weight_part"]},
        "ultima_refeicao": ultima,
        "agenda": decodificar_agenda(props.get("meal_plan2") or ""),
    }


class Painel(BaseHTTPRequestHandler):
    def _json(self, codigo, obj):
        corpo = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(AQUI, "painel.html"), "rb") as f:
                corpo = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
        elif self.path.startswith("/assets/"):
            self._estatico()
        elif self.path == "/api/estado":
            try:
                self._json(200, estado())
            except TuyaErro as e:
                self._json(502, {"erro": str(e)})
        elif self.path.startswith("/api/video.mjpeg"):
            self._mjpeg()
        elif self.path.startswith("/api/audio.mp3"):
            self._audio()
        elif self.path == "/api/video":
            try:
                self._json(200, {"url": tuya.stream("hls").get("url")})
            except TuyaErro as e:
                self._json(502, {"erro": str(e)})
        elif self.path == "/api/historico":
            try:
                itens = []
                for l in tuya.historico():
                    try:
                        v = json.loads(l.get("value") or "")
                        itens.append({"hora": v["time"], "porcoes": v["value"], "manual": v.get("type") == 1})
                    except (ValueError, KeyError, TypeError):
                        continue
                self._json(200, {"itens": itens})
            except TuyaErro as e:
                self._json(502, {"erro": str(e)})
        else:
            self._json(404, {"erro": "não encontrado"})

    def _estatico(self):
        """Entrega imagens da pasta assets (só o nome do arquivo, sem subpastas)."""
        tipos = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml"}
        nome = os.path.basename(self.path.split("?", 1)[0])
        caminho = os.path.join(AQUI, "assets", nome)
        ext = os.path.splitext(nome)[1].lower()
        if ext not in tipos or not os.path.isfile(caminho):
            return self._json(404, {"erro": "não encontrado"})
        with open(caminho, "rb") as f:
            corpo = f.read()
        self.send_response(200)
        self.send_header("Content-Type", tipos[ext])
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(corpo)

    def _mjpeg(self):
        """Vídeo da câmera (HEVC via RTSP) convertido em MJPEG, que toca em qualquer navegador."""
        self._ffmpeg("multipart/x-mixed-replace;boundary=ffmpeg",
                     ["-an", "-r", "10", "-q:v", "5", "-f", "mpjpeg"])

    def _audio(self):
        """Som do microfone da câmera convertido em MP3 contínuo, para um <audio> comum."""
        self._ffmpeg("audio/mpeg",
                     ["-vn", "-ac", "1", "-ar", "22050",
                      "-c:a", "libmp3lame", "-b:a", "48k", "-flush_packets", "1", "-f", "mp3"])

    def _ffmpeg(self, tipo, saida):
        """Abre uma sessão RTSP na Tuya e repassa a saída do ffmpeg ao navegador.
        Quando a Tuya encerra a sessão, pede outro link e continua na mesma resposta."""
        if not os.path.exists(FFMPEG):
            return self._json(501, {"erro": "ffmpeg não encontrado neste computador"})
        try:
            url = tuya.stream("rtsp")["url"]
        except TuyaErro as e:
            return self._json(502, {"erro": str(e)})
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        falhas = 0
        while falhas < 2:
            proc = subprocess.Popen(
                [FFMPEG, "-loglevel", "error", "-rtsp_transport", "tcp", "-i", url]
                + saida + ["pipe:1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            enviados = 0
            try:
                while True:
                    bloco = proc.stdout.read1(16384)
                    if not bloco:
                        break
                    self.wfile.write(bloco)
                    self.wfile.flush()
                    enviados += len(bloco)
            except (BrokenPipeError, ConnectionResetError):
                return
            finally:
                proc.kill()
                proc.wait()
            falhas = 0 if enviados else falhas + 1
            try:
                url = tuya.stream("rtsp")["url"]
            except TuyaErro:
                return

    def do_POST(self):
        if self.path not in ("/api/definir", "/api/agenda"):
            return self._json(404, {"erro": "não encontrado"})
        # Só aceita chamadas feitas pela própria página do painel.
        origem = self.headers.get("Origin")
        if origem and origem not in (f"http://127.0.0.1:{PORTA}", f"http://localhost:{PORTA}"):
            return self._json(403, {"erro": "origem não permitida"})
        try:
            dados = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        except (ValueError, TypeError):
            return self._json(400, {"erro": "corpo inválido"})
        if self.path == "/api/agenda":
            try:
                hexa = codificar_agenda(dados.get("itens") if isinstance(dados, dict) else None)
            except ValueError as e:
                return self._json(400, {"erro": str(e)})
            try:
                with trava:
                    tuya.definir("meal_plan2", hexa)
                return self._json(200, {"ok": True, "gravado": hexa})
            except TuyaErro as e:
                return self._json(502, {"erro": str(e)})
        try:
            code, valor = dados["code"], dados["value"]
        except (KeyError, TypeError):
            return self._json(400, {"erro": "corpo inválido"})
        if code not in GRAVAVEIS or not GRAVAVEIS[code](valor):
            return self._json(400, {"erro": f"valor não permitido para {code}"})
        try:
            with trava:
                tuya.definir(code, valor)
            self._json(200, {"ok": True})
        except TuyaErro as e:
            self._json(502, {"erro": str(e)})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    print(f"Painel do comedouro em http://127.0.0.1:{PORTA}")
    ThreadingHTTPServer(("127.0.0.1", PORTA), Painel).serve_forever()
