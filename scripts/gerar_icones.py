#!/usr/bin/env python3
"""Gera os ícones do site (favicon e ícone da tela inicial do iPhone) a partir do logo.

Usa só a carinha da Capitu e o pote de ração: o texto "Capitu Food" é removido. Como as letras
encostam na base do pote, essa base é refeita antes do recorte.

Uso:  python3 scripts/gerar_icones.py        (precisa do Pillow)
Saída: docs/favicon.ico, docs/icon-32.png, docs/apple-touch-icon.png, docs/icon-192.png,
       docs/icon-512.png, docs/icon-maskable-512.png
"""
import os
import sys

from PIL import Image, ImageDraw

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
LOGO = os.path.join(RAIZ, "assets", "logo.webp")
SAIDA = os.path.join(RAIZ, "docs")
CREME = (0xF7, 0xF1, 0xE5)

# Medidas do logo original (1448x1086), lidas na imagem.
POTE_X0, POTE_X1 = 440, 985          # largura do pote
CENTRO_POTE = 712
LETRAS_DESDE = 846                   # abaixo disso, fora do pote, só há texto
ZONAS_COBERTAS = [(512, 630), (792, 952)]                 # trechos da base do pote cobertos por letras
COLUNAS_MEDIDAS = [(450, 512), (570, 812), (950, 972)]    # trechos onde a base do pote está visível
ALFA_MINIMO = 24                     # tira o brilho amarelado/avermelhado que sobrou do recorte original


def no_pote(p):
    """Cor da massa do pote (laranja), para distinguir de letras e halos."""
    r, g, b, _ = p
    return 0xB8 <= r <= 0xE2 and 0x54 <= g <= 0x82 and 0x2E <= b <= 0x54


def limpar_texto(im):
    px = im.load()
    w, h = im.size

    # 1) Onde a base do pote está visível, mede a altura dela (primeira linha, descendo, com alfa baixo).
    base = {}
    for a, b in COLUNAS_MEDIDAS:
        for x in range(a, b + 1):
            for y in range(800, 900):
                if px[x, y][3] < 128:
                    base[x] = y
                    break
    # Descarta medidas que destoam das vizinhas (a letra encostou na borda e enganou a leitura).
    for x in sorted(base):
        viz = sorted(base[k] for k in range(x - 12, x + 13) if k != x and k in base)
        if viz and abs(base[x] - viz[len(viz) // 2]) > 3:
            del base[x]
    # O pote é simétrico: o que não dá para medir (coberto por letras) vem das medidas à mesma
    # distância do centro, no outro lado.
    amostras = sorted((abs(x - CENTRO_POTE), y) for x, y in base.items())

    def base_em(x):
        if x in base:
            return base[x]
        d = abs(x - CENTRO_POTE)
        ant = max((s for s in amostras if s[0] <= d), default=amostras[0])
        pos = min((s for s in amostras if s[0] > d), default=amostras[-1])
        if pos[0] == ant[0]:
            return ant[1]
        t = (d - ant[0]) / (pos[0] - ant[0])
        return round(ant[1] * (1 - t) + pos[1] * t)

    # Perfil da borda (marrom) copiado de uma coluna limpa.
    perfil = [px[712, base[712] - 7 + i] for i in range(7)]

    # 2) Refaz as colunas cobertas e apaga tudo abaixo da base do pote.
    saida = im.copy()
    so = saida.load()
    for x in range(w):
        if POTE_X0 <= x <= POTE_X1:
            y_base = base_em(x)
            if any(a <= x <= b for a, b in ZONAS_COBERTAS):
                y0 = next((y for y in range(830, y_base) if not no_pote(px[x, y])), y_base)
                for y in range(y0, y_base - 6):
                    ref = 2 * y0 - y - 1                      # espelha as linhas de cima: mantém a textura
                    so[x, y] = px[x, max(ref, 800)][:3] + (255,)
                for i, cor in enumerate(perfil):              # borda marrom
                    so[x, y_base - 7 + i] = cor[:3] + (255,)
            for y in range(y_base, h):
                so[x, y] = (0, 0, 0, 0)
        else:
            for y in range(LETRAS_DESDE, h):
                so[x, y] = (0, 0, 0, 0)

    # 3) Descarta pixels quase transparentes (franjas coloridas do recorte original).
    r, g, b, a = saida.split()
    saida.putalpha(a.point(lambda v: 0 if v < ALFA_MINIMO else v))
    return saida


def sobre_creme(arte, lado, margem):
    """Arte centralizada num quadrado opaco; `margem` é a fração do lado deixada livre."""
    tela = Image.new("RGBA", (lado, lado), CREME + (255,))
    area = round(lado * (1 - 2 * margem))
    escala = min(area / arte.width, area / arte.height)
    tam = (round(arte.width * escala), round(arte.height * escala))
    pequena = arte.resize(tam, Image.LANCZOS)
    tela.alpha_composite(pequena, ((lado - tam[0]) // 2, (lado - tam[1]) // 2))
    return tela


def arredondar(img, raio_frac):
    """Aplica cantos arredondados com bordas suaves (desenha em 4x e reduz)."""
    lado = img.width
    f = 4
    mascara = Image.new("L", (lado * f, lado * f), 0)
    ImageDraw.Draw(mascara).rounded_rectangle((0, 0, lado * f - 1, lado * f - 1), radius=int(lado * f * raio_frac), fill=255)
    mascara = mascara.resize((lado, lado), Image.LANCZOS)
    saida = img.copy()
    saida.putalpha(mascara)
    return saida


def main():
    if not os.path.exists(LOGO):
        sys.exit(f"Não achei {LOGO}")
    logo = Image.open(LOGO).convert("RGBA")
    arte = limpar_texto(logo)
    arte = arte.crop(arte.getbbox())

    mestre = sobre_creme(arte, 1024, 0.085)
    os.makedirs(SAIDA, exist_ok=True)

    # iPhone: quadrado opaco (o iOS aplica os cantos arredondados sozinho).
    mestre.resize((180, 180), Image.LANCZOS).convert("RGB").save(os.path.join(SAIDA, "apple-touch-icon.png"), optimize=True)
    # Android / instalação como app.
    mestre.resize((192, 192), Image.LANCZOS).convert("RGB").save(os.path.join(SAIDA, "icon-192.png"), optimize=True)
    mestre.resize((512, 512), Image.LANCZOS).convert("RGB").save(os.path.join(SAIDA, "icon-512.png"), optimize=True)
    # Versão "maskable": arte menor, para sobreviver ao recorte circular do Android.
    sobre_creme(arte, 512, 0.2).convert("RGB").save(os.path.join(SAIDA, "icon-maskable-512.png"), optimize=True)

    # Aba do navegador: cantos arredondados e arte um pouco maior para ler em tamanho pequeno.
    fav = arredondar(sobre_creme(arte, 1024, 0.04), 0.22)
    tamanhos = [16, 32, 48]
    fav.resize((32, 32), Image.LANCZOS).save(os.path.join(SAIDA, "icon-32.png"), optimize=True)
    fav.resize((48, 48), Image.LANCZOS).save(
        os.path.join(SAIDA, "favicon.ico"), format="ICO", sizes=[(s, s) for s in tamanhos],
        append_images=[fav.resize((s, s), Image.LANCZOS) for s in tamanhos if s != 48],
    )
    for nome in ("favicon.ico", "icon-32.png", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png"):
        print(f"{nome}: {os.path.getsize(os.path.join(SAIDA, nome))} bytes")


if __name__ == "__main__":
    main()
