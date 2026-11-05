# -*- coding: utf-8 -*-
"""
J O N — assistente pessoal com painel HUD (estilo J.A.R.V.I.S., em roxo).
Abra pelo atalho "Jon" na Área de Trabalho (ou dê dois cliques neste arquivo).
"""
import ctypes
import datetime as dt
import json
import math
import os
import queue
import re
import sys
import threading
import time
import traceback
from versao import VERSAO, VERSAO_NOME
import codigo_analisador
import chat_topicos_mgr
from tkinter import filedialog
import base64

PASTA = os.path.dirname(os.path.abspath(__file__))
os.chdir(PASTA)
sys.path.insert(0, PASTA)
ARQ_LOG = os.path.join(PASTA, "assistente.log")
ARQ_CONFIG = os.path.join(PASTA, "config.json")

# ---------- uma instância só ----------
_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "JonAssistente_Mutex")
if ctypes.windll.kernel32.GetLastError() == 183:
    ctypes.windll.user32.MessageBoxW(0, "O Jon já está aberto (veja a barra de tarefas).", "Jon", 0x40)
    sys.exit(0)
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Jon.Assistente")
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# ---------- tudo que o assistente "printa" vai pro registro e pro arquivo de log ----------
FILA = queue.Queue()


class Saida:
    def __init__(self):
        self.bufs = {}
        try:
            self.log = open(ARQ_LOG, "a", encoding="utf-8")
        except OSError:
            self.log = None

    def write(self, txt):
        if self.log:
            try:
                self.log.write(txt)
                self.log.flush()
            except Exception:
                pass
        # cada thread tem seu próprio "pedaço" de linha (pedidos do celular rodam em outra thread)
        import threading as _t
        chave = _t.get_ident()
        buf = self.bufs.get(chave, "") + txt
        while "\n" in buf:
            linha, buf = buf.split("\n", 1)
            if linha.strip():
                FILA.put(("linha", linha))
                av_mod = sys.modules.get("assistente_voz")
                if av_mod is not None:
                    try:
                        av_mod.coletar(linha)
                    except Exception:
                        pass
        self.bufs[chave] = buf

    def flush(self):
        pass


sys.stdout = sys.stderr = Saida()
print(f"\n===== {time.strftime('%d/%m/%Y %H:%M:%S')} — app iniciado =====")

import customtkinter as ctk  # noqa: E402

try:
    import assistente_voz as av  # noqa: E402
    import spotify_api  # noqa: E402
    import atalhos  # noqa: E402
    import ia_local  # noqa: E402
    import rotinas  # noqa: E402
    import sistema  # noqa: E402
    import holo  # noqa: E402
    import web_jon  # noqa: E402
    import painel_extra as px  # noqa: E402
    try:
        import atualizador  # noqa: E402
    except Exception:
        atualizador = None
    try:
        import numpy  # noqa: F401
        from PIL import Image, ImageTk  # noqa: E402
        import holo_render  # noqa: E402
        ORGANICO = True
    except Exception:
        ORGANICO = False      # sem Pillow: usa a esfera antiga (linhas)
except Exception:
    traceback.print_exc()
    ctypes.windll.user32.MessageBoxW(0, "Erro ao carregar o Jon. Veja o arquivo assistente.log.", "Jon", 0x10)
    raise

av.ao_status = lambda estado: FILA.put(("status", estado))
av.mostrar_interface = lambda: FILA.put(("janela", "mostrar")) or True
av.esconder_interface = lambda: FILA.put(("janela", "esconder")) or True
av.modo_tela = lambda abrir: FILA.put(("bigpicture", abrir)) or True
av.checar_atualizacao = lambda: FILA.put(("checar_atualizacao", True)) or True

# ---------- configurações ----------
CONFIG_PADRAO = {"tecla": "f9", "maos_livres": False, "falar": True}


def carregar_config():
    try:
        with open(ARQ_CONFIG, encoding="utf-8") as f:
            return {**CONFIG_PADRAO, **json.load(f)}
    except Exception:
        return dict(CONFIG_PADRAO)


def salvar_config(cfg):
    try:
        with open(ARQ_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Não salvei a configuração:", e)


# ---------- paleta HUD roxa ----------
BG = "#07050d"
PAINEL = "#0d0a18"
PAINEL2 = "#140f24"
BORDA = "#2b1f4f"
ROXO = "#a855f7"
ROXO_CLARO = "#c4a1ff"
ROXO_ESCURO = "#3b1d6e"
LILAS = "#ede4ff"
MUDO = "#7d6fa3"
APAGADO = "#4a3f6b"
ROSA = "#f472d0"
VERDE = "#5ef0a0"
AMBAR = "#fbbf24"
VERMELHO = "#f87171"
MONO = "Consolas"
SANS = "Segoe UI"

ESTADOS = {
    "pronto": ("AGUARDANDO COMANDO", "ONLINE", ROXO),
    "ouvindo": ("OUVINDO… PODE FALAR", "OUVINDO", ROSA),
    "processando": ("PROCESSANDO", "PENSANDO", ROXO_CLARO),
    "erro": ("NÃO ENTENDI — TENTE DE NOVO", "ERRO", VERMELHO),
}

ICO = "Segoe MDL2 Assets"          # ícones do Windows (play, pausa, pastas...)
SPOTIFY_VERDE = "#1ed760"

TECLAS = ["f8", "f9", "f10", "f11", "f12", "scroll lock", "pause", "insert", "ctrl+space", "ctrl+alt+v"]

EXEMPLOS = [
    ("Spotify", ["toca Yellow do Coldplay", "toca a banda Legião Urbana", "coloca a playlist de rock",
                 "toca minhas músicas curtidas", "pesquisa Tempo Perdido no Spotify"]),
    ("Spotify — controles", ["coloca a música em looping", "repete a playlist", "tira o loop", "liga o aleatório",
                             "volume 40", "curte essa música", "adiciona Yellow na fila",
                             "volta a música do começo", "que música é essa?"]),
    ("Lembretes e rotinas", ["me lembra em 10 minutos de tirar o bolo", "me lembra às 18h de ligar pra mãe",
                             "timer de 5 minutos", "todo dia às 8 horas toca minhas músicas curtidas",
                             "dias úteis às 7:30 me lembra de tomar café", "quais são meus lembretes",
                             "cancela os timers"]),
    ("Dia a dia", ["bom dia (resumo do dia)", "que horas são", "que dia é hoje", "como está o tempo",
                   "vai chover amanhã", "como está o clima em São Paulo", "status do sistema"]),
    ("Computador e Agente IA", ["cria uma pasta chamada Projetos na área de trabalho",
                                "cria um arquivo notas.txt com minha lista de tarefas",
                                "otimiza o PC (limpa temp, libera RAM e lixeira)",
                                "organiza a pasta Downloads por tipo", "esvazia a lixeira",
                                "quais programas estão pesados?", "instala o VLC",
                                "abre o Discord", "fecha o Discord", "tira um print", "bloqueia o PC"]),
    ("YouTube e web", ["toca lofi no YouTube", "pesquisa receita de bolo"]),
    ("IA (frases livres)", ["bota aquela do Coldplay que fala de amarelo", "quanto é 15% de 230?",
                            "quando eu falar meu som, toca minhas músicas curtidas",
                            "lembra que o jogo é o Assassin's Creed Shadows", "esquece o meu som"]),
    ("Outros", ["Jon, … (no modo mãos-livres)", "Claude, <qualquer pedido>", "fechar assistente"]),
]


def mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))


# =====================================================================
#   COMPONENTES
# =====================================================================

class Painel(ctk.CTkFrame):
    """Cartão HUD: título + etiqueta à direita; o marcador ◢ "respira"."""
    marcas = []

    def __init__(self, master, titulo, etiqueta="", icone=None, **kw):
        super().__init__(master, fg_color=PAINEL, border_color=BORDA, border_width=1, corner_radius=4, **kw)
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=12, pady=(8, 0))
        if icone is not None:
            self.lbl_icone = ctk.CTkLabel(topo, text="", image=icone, width=20, height=20)
        else:
            self.lbl_icone = ctk.CTkLabel(topo, text="◢", font=(MONO, 10), text_color=ROXO, width=14, height=18)
            Painel.marcas.append(self.lbl_icone)
        self.lbl_icone.pack(side="left", padx=(0, 6))
        self.lbl_titulo = ctk.CTkLabel(topo, text=titulo.upper(), font=(MONO, 12, "bold"), text_color=ROXO_CLARO,
                                       height=18)
        self.lbl_titulo.pack(side="left")
        self.direita = ctk.CTkFrame(topo, fg_color="transparent")
        self.direita.pack(side="right")
        self.etiqueta = ctk.CTkLabel(self.direita, text=etiqueta.upper(), font=(MONO, 9), text_color=APAGADO,
                                     height=18)
        self.etiqueta.pack(side="right")
        ctk.CTkFrame(self, fg_color=BORDA, height=1).pack(fill="x", padx=12, pady=(6, 6))
        self.corpo = ctk.CTkFrame(self, fg_color="transparent")
        self.corpo.pack(fill="both", expand=True, padx=12, pady=(0, 9))


class Barra(ctk.CTkFrame):
    """Linha 'rótulo ......... valor' + barra fina."""

    def __init__(self, master, rotulo):
        super().__init__(master, fg_color="transparent")
        l = ctk.CTkFrame(self, fg_color="transparent")
        l.pack(fill="x")
        ctk.CTkLabel(l, text=rotulo, font=(MONO, 11), text_color=MUDO, height=16).pack(side="left")
        self.valor = ctk.CTkLabel(l, text="--", font=(MONO, 11, "bold"), text_color=LILAS, height=16)
        self.valor.pack(side="right")
        self.barra = ctk.CTkProgressBar(self, height=4, corner_radius=2, fg_color=ROXO_ESCURO, progress_color=ROXO)
        self.barra.set(0)
        self.barra.pack(fill="x", pady=(2, 8))

    def definir(self, frac, texto, alerta=False):
        frac = round(max(0.0, min(1.0, frac)), 2)
        if (frac, texto, alerta) == getattr(self, "_ultimo", None):
            return                                   # nada mudou: não redesenha
        antigo = getattr(self, "_ultimo", (None, None, None))
        self._ultimo = (frac, texto, alerta)
        if frac != antigo[0]:
            self.barra.set(frac)
        if alerta != antigo[2]:
            self.barra.configure(progress_color=VERMELHO if alerta else ROXO)
        self.valor.configure(text=texto, text_color=VERMELHO if alerta else LILAS)


class Nucleo(ctk.CTkCanvas):
    """Esfera holográfica do Jon: fragmentos de luz em 3D, órbitas e um olho no centro. Clique = falar."""

    N_CORES = 14

    def __init__(self, master, ao_clicar):
        super().__init__(master, bg=BG, highlightthickness=0, cursor="hand2")
        self.estado = "pronto"
        self.nivel = 0.0
        self.fase = 0.0
        self.ang = 0.0
        self.frags = holo.gerar_fragmentos(210)
        self._montado_para = None
        self.bind("<Button-1>", lambda e: ao_clicar())

    def _paleta(self, cor):
        # do roxo escuro (fundo da esfera) até quase branco (frente)
        return [mix(mix(ROXO_ESCURO, cor, k / (self.N_CORES - 1) * 1.1), LILAS,
                    max(0.0, k / (self.N_CORES - 1) - 0.62) * 1.7) for k in range(self.N_CORES)]

    def _montar(self, w, h):
        self.delete("all")
        self._montado_para = (w, h)
        self._n_halo = -1.0
        self._txt = None
        self._orb_cache = {}
        cx, cy = w / 2, h / 2
        R = min(w, h) * 0.34
        self.R = R
        # brilho de fundo (halo)
        self.halo = []
        for i in range(10):
            r = R * 1.3 * (1 - i / 10)
            self.halo.append(self.create_oval(cx - r, cy - r, cx + r, cy + r, outline="",
                                              fill=mix(BG, ROXO_ESCURO, 0.12 + i * 0.07)))
        self.orb = [self.create_line(0, 0, 0, 0, width=1) for _ in range(6)]
        self.arco = self.create_arc(0, 0, 1, 1, style="arc", width=3, start=0, extent=200)
        self.itens = [self.create_line(0, 0, 0, 0, capstyle="round") for _ in self.frags]
        self.cor_item = [None] * len(self.frags)
        self.olho_anel = self.create_oval(0, 0, 1, 1, width=3)
        self.olho = self.create_oval(0, 0, 1, 1, outline="")
        self.olho_arco = self.create_arc(0, 0, 1, 1, style="arc", width=3, start=0, extent=120)
        self.txt_nome = self.create_text(cx, cy - R * 1.42, text="J  O  N", fill=LILAS,
                                         font=(MONO, max(12, int(R / 11)), "bold"))
        self.txt_estado = self.create_text(cx, cy + R * 1.42, text="", font=(MONO, max(10, int(R / 16)), "bold"))

    def desenhar(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 50 or h < 50:
            return
        if self._montado_para != (w, h):
            self._montar(w, h)
        cx, cy, R = w / 2, h / 2, self.R
        cor = ESTADOS[self.estado][2]
        pal = self._paleta(cor)
        f, n = self.fase, self.nivel
        self.ang += 0.045 if self.estado == "processando" else 0.012 + n * 0.02
        varr = math.sin(f * 1.5) if self.estado == "processando" else None

        # halo pulsa com a voz (só recalcula quando o volume muda)
        if abs(n - self._n_halo) > 0.02:
            self._n_halo = n
            for i, it in enumerate(self.halo):
                r = R * (1.3 + n * 0.25) * (1 - i / 10)
                self.coords(it, cx - r, cy - r, cx + r, cy + r)

        # órbitas (cada uma em 2 metades: trás mais escura, frente mais clara)
        for k, (gi, rr) in enumerate(((0.5, 1.18), (-0.9, 1.1), (1.4, 0.8))):
            cs, pf = holo.orbita(cx, cy, R * rr * (1 + n * 0.15), self.ang * (1 + k * 0.3), 0.32, gi, 30)
            meio = len(pf) // 2
            frente_primeiro = sum(pf[:meio]) > sum(pf[meio:])
            for parte, (a, b) in enumerate(((0, meio), (meio, len(pf) - 1))):
                item = self.orb[k * 2 + parte]
                self.coords(item, *cs[a * 2:(b + 1) * 2])
                frente = (parte == 0) == frente_primeiro
                chave = (pal[10] if frente else pal[3], 2 if frente else 1)
                if self._orb_cache.get(item) != chave:
                    self._orb_cache[item] = chave
                    self.itemconfig(item, fill=chave[0], width=chave[1])

        # arco amplo girando
        ra = R * 0.62
        self.coords(self.arco, cx - ra, cy - ra * 0.92, cx + ra, cy + ra * 0.92)
        self.itemconfig(self.arco, start=-f * 40, outline=pal[11])

        # fragmentos
        segs = holo.projetar(self.frags, cx, cy, R, self.ang, nivel=n, fase=f, varredura=varr)
        for i, (x1, y1, x2, y2, prof, bloco, extra) in enumerate(segs):
            it = self.itens[i]
            self.coords(it, x1, y1, x2, y2)
            k = min(self.N_CORES - 1, int((prof + extra) * (self.N_CORES - 1)))
            larg = (3 if bloco else 1) + (1 if prof > 0.6 else 0)
            chave = (k, larg)
            if self.cor_item[i] != chave:
                self.itemconfig(it, fill=pal[k], width=larg)
                self.cor_item[i] = chave

        # olho central
        rc = R * 0.17 + n * 12 + 1.5 * math.sin(f * 2)
        self.coords(self.olho_anel, cx - rc, cy - rc, cx + rc, cy + rc)
        self.itemconfig(self.olho_anel, outline=LILAS)
        ri = rc * 0.55
        self.coords(self.olho, cx - ri, cy - ri, cx + ri, cy + ri)
        self.itemconfig(self.olho, fill=mix(cor, LILAS, 0.5))
        ro = rc * 1.5
        self.coords(self.olho_arco, cx - ro, cy - ro, cx + ro, cy + ro)
        self.itemconfig(self.olho_arco, start=f * 80, outline=cor)
        self.tag_raise(self.olho_anel)
        self.tag_raise(self.olho)
        if getattr(self, "_txt", None) != self.estado:
            self._txt = self.estado
            self.itemconfig(self.txt_estado, text=ESTADOS[self.estado][1], fill=mix(cor, "#ffffff", 0.4))

        # cor dos fragmentos muda quando o estado muda
        if getattr(self, "_ultima_cor", None) != cor:
            self._ultima_cor = cor
            self.cor_item = [None] * len(self.frags)
            self._orb_cache = {}


class NucleoOrganico(ctk.CTkCanvas):
    """Esfera orgânica: partículas de luz suaves com rastros (desenhada com numpy + Pillow, sem serrilhado)."""

    def __init__(self, master, ao_clicar):
        super().__init__(master, bg=BG, highlightthickness=0, cursor="hand2")
        self.estado = "pronto"
        self.nivel = 0.0
        self.fase = 0.0
        self.ang = 0.0
        self.rend = None
        self.foto = None
        self._tam = None
        self._estado_cor = None
        self.item_img = self.create_image(0, 0, anchor="center")
        self.txt_nome = self.create_text(0, 0, text="J  O  N", fill=LILAS, font=(MONO, 16, "bold"))
        self.txt_estado = self.create_text(0, 0, text="", font=(MONO, 12, "bold"))
        self.bind("<Button-1>", lambda e: ao_clicar())
        self.teto = 660

    def _preparar(self, w, h):
        tam = int(min(w * 0.9, h * 0.86, self.teto))
        tam -= tam % 2
        if tam < 80:
            return False
        if tam != self._tam:
            self._tam = tam
            self.rend = holo_render.Renderizador(tam)
            self.foto = ImageTk.PhotoImage(Image.new("RGB", (tam, tam), BG))
            self.itemconfig(self.item_img, image=self.foto)
            self._estado_cor = None
        self.coords(self.item_img, w / 2, h / 2)
        self.coords(self.txt_nome, w / 2, h / 2 - tam / 2 - 6)
        self.coords(self.txt_estado, w / 2, h / 2 + tam / 2 + 4)
        return True

    def desenhar(self):
        w, h = self.winfo_width(), self.winfo_height()
        if not self._preparar(w, h):
            return
        cor = ESTADOS[self.estado][2]
        if self._estado_cor != self.estado:
            self._estado_cor = self.estado
            self.rend.definir_paleta(holo_render.paleta(BG, ROXO_ESCURO if self.estado != "erro" else "#5b1414",
                                                        cor, LILAS))
            self.itemconfig(self.txt_estado, text=ESTADOS[self.estado][1], fill=mix(cor, "#ffffff", 0.4))
        n = self.nivel
        self.ang += 0.045 if self.estado == "processando" else 0.012 + n * 0.02
        varr = math.sin(self.fase * 1.5) if self.estado == "processando" else None
        arr = self.rend.quadro(self.ang, self.fase, n, varr, self.estado)
        self.foto.paste(Image.fromarray(arr))


class Onda(ctk.CTkCanvas):
    """Ondinha de áudio embaixo do núcleo."""

    def __init__(self, master):
        super().__init__(master, width=260, height=44, bg=BG, highlightthickness=0)
        self.alturas = [0.1] * 21

    def desenhar(self, nivel, fase, cor):
        w, h = self.winfo_width(), self.winfo_height()
        n = len(self.alturas)
        if not getattr(self, "barras", None):
            self.barras = [self.create_rectangle(0, 0, 1, 1, outline="") for _ in range(n)]
            self._cor = None
        if cor != self._cor:
            self._cor = cor
            for i, b in enumerate(self.barras):
                self.itemconfig(b, fill=mix(cor, BG, 0.15 + (i % 3) * 0.12))
        for i in range(n):
            alvo = 0.12 + nivel * (0.5 + 0.5 * math.sin(fase * 3 + i * 0.9)) * (1 - abs(i - n / 2) / (n / 1.6))
            self.alturas[i] += (alvo - self.alturas[i]) * 0.4
            bh = max(3, self.alturas[i] * h)
            x = w / 2 + (i - n / 2) * 9
            self.coords(self.barras[i], x, h / 2 - bh / 2, x + 5, h / 2 + bh / 2)


class Recursos(ctk.CTkCanvas):
    """Barras de recursos desenhadas à mão: deslizam suavemente até o valor novo (sem pulos)."""
    ALT_LINHA = 29

    def __init__(self, master, nomes):
        super().__init__(master, height=self.ALT_LINHA * len(nomes) + 2, bg=PAINEL, highlightthickness=0)
        self.nomes = nomes
        self.atual = {n: 0.0 for n in nomes}
        self.alvo = {n: 0.0 for n in nomes}
        self.alerta = {n: False for n in nomes}
        self.itens = {}
        self._larg = None
        self.bind("<Configure>", lambda e: self._montar())

    def _montar(self):
        w = self.winfo_width()
        if w < 20 or w == self._larg:
            return
        self._larg = w
        self.delete("all")
        for k, n in enumerate(self.nomes):
            y = k * self.ALT_LINHA
            rot = self.create_text(0, y + 7, text=n, anchor="w", fill=MUDO, font=(MONO, 10))
            val = self.create_text(w, y + 7, text="--", anchor="e", fill=LILAS, font=(MONO, 10, "bold"))
            self.create_rectangle(0, y + 17, w, y + 20, fill=ROXO_ESCURO, outline="")
            barra = self.create_rectangle(0, y + 17, 0, y + 20, fill=ROXO, outline="")
            ponta = self.create_rectangle(0, y + 15, 3, y + 22, fill=ROXO_CLARO, outline="")
            self.itens[n] = (rot, val, barra, ponta, y)
            self.atual[n] = -1  # força redesenho

    def definir(self, nome, frac, texto, alerta=False):
        self.alvo[nome] = max(0.0, min(1.0, frac))
        it = self.itens.get(nome)
        if not it:
            return
        if self.itemcget(it[1], "text") != texto:
            self.itemconfig(it[1], text=texto)
        if self.alerta[nome] != alerta:
            self.alerta[nome] = alerta
            self.itemconfig(it[1], fill=VERMELHO if alerta else LILAS)
            self.itemconfig(it[2], fill=VERMELHO if alerta else ROXO)

    def animar(self):
        w = self._larg or 0
        for n, it in self.itens.items():
            a, b = self.atual[n], self.alvo[n]
            if abs(a - b) < 0.0015:
                continue
            a = b if a < 0 else a + (b - a) * 0.22         # desliza 22% do caminho por quadro
            self.atual[n] = a
            x = a * w
            y = it[4]
            self.coords(it[2], 0, y + 17, x, y + 20)
            self.coords(it[3], max(0, x - 3), y + 15, x, y + 22)


class Grafico(ctk.CTkCanvas):
    """Linha + área do uso de CPU que rola continuamente (estilo monitor cardíaco)."""
    PONTOS = 60          # 60 amostras x 0,25 s = 15 s na tela

    def __init__(self, master):
        super().__init__(master, height=54, bg=PAINEL2, highlightthickness=1, highlightbackground=BORDA)
        self.valores = [0.0] * (self.PONTOS + 2)
        self.t_ultimo = time.perf_counter()
        self.intervalo = 0.25
        self.area = self.create_polygon(0, 0, 0, 0, 0, 0, fill=mix(PAINEL2, ROXO, 0.28), outline="")
        self.linhas_grade = [self.create_line(0, 0, 0, 0, fill=mix(PAINEL2, BORDA, 0.6)) for _ in range(3)]
        self.linha = self.create_line(0, 0, 0, 0, fill=ROXO_CLARO, width=2)
        self.ponto = self.create_oval(0, 0, 0, 0, fill=LILAS, outline="")
        self.txt = self.create_text(6, 6, text="", anchor="nw", fill=LILAS, font=(MONO, 10, "bold"))
        self._txt_val = None

    def adicionar(self, v):
        agora = time.perf_counter()
        self.intervalo = min(1.0, max(0.1, agora - self.t_ultimo))
        self.t_ultimo = agora
        self.valores = self.valores[1:] + [v]
        txt = f"CPU {v:.0f}%"
        if txt != self._txt_val:
            self._txt_val = txt
            self.itemconfig(self.txt, text=txt)

    def desenhar(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20:
            return
        passo = w / self.PONTOS
        # quanto já "andou" desde a última amostra -> rolagem contínua
        frac = min(1.0, (time.perf_counter() - self.t_ultimo) / self.intervalo)
        desloc = frac * passo
        pts = []
        n = len(self.valores)
        for i, v in enumerate(self.valores):
            x = (i - (n - 1 - self.PONTOS)) * passo - desloc
            y = h - 4 - v / 100 * (h - 10)
            pts += [x, y]
        # interpola o último ponto pra ele "crescer" suave até o valor novo
        self.coords(self.linha, *pts)
        self.coords(self.area, pts[0], h, *pts, pts[-2], h)
        self.coords(self.ponto, pts[-2] - 3, pts[-1] - 3, pts[-2] + 3, pts[-1] + 3)
        if getattr(self, "_grade_w", None) != (w, h):
            self._grade_w = (w, h)
            for k, ln in enumerate(self.linhas_grade):
                y = h * (k + 1) / 4
                self.coords(ln, 0, y, w, y)


class Progresso(ctk.CTkCanvas):
    """Barra fina da música (clique = pular pra aquele ponto)."""

    def __init__(self, master, ao_clicar):
        super().__init__(master, height=12, bg=PAINEL, highlightthickness=0, cursor="hand2")
        self.frac = 0.0
        self.fundo = self.create_rectangle(0, 5, 0, 8, fill=ROXO_ESCURO, outline="")
        self.barra = self.create_rectangle(0, 5, 0, 8, fill=SPOTIFY_VERDE, outline="")
        self.bola = self.create_oval(0, 2, 0, 11, fill=LILAS, outline="")
        self.bind("<Configure>", lambda e: self.definir(self.frac, True))
        self.bind("<Button-1>", lambda e: ao_clicar(max(0.0, min(1.0, e.x / max(1, self.winfo_width())))))

    def definir(self, frac, forcar=False):
        frac = max(0.0, min(1.0, frac))
        if abs(frac - self.frac) < 0.0005 and not forcar:
            return
        self.frac = frac
        w = self.winfo_width()
        x = 5 + frac * (w - 10)
        self.coords(self.fundo, 5, 5, w - 5, 8)
        self.coords(self.barra, 5, 5, x, 8)
        self.coords(self.bola, x - 4.5, 2, x + 4.5, 11)


def _mmss(ms):
    s_ = max(0, int(ms // 1000))
    return f"{s_ // 60}:{s_ % 60:02d}"


def capa_arredondada(img, tam, raio=8):
    from PIL import ImageDraw
    img = img.convert("RGBA").resize((tam * 2, tam * 2))
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, img.size[0] - 1, img.size[1] - 1), raio * 2, fill=255)
    img.putalpha(m)
    return img.resize((tam, tam), Image.LANCZOS)


# =====================================================================
#   CONTROLE DE XBOX (XInput) — sem instalar nada
# =====================================================================
class _XGamepad(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_ushort), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class _XState(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", _XGamepad)]


class Controle:
    """Lê o controle (Xbox ou compatível). Devolve um conjunto de botões apertados."""
    BOTOES = {"cima": 0x1, "baixo": 0x2, "esq": 0x4, "dir": 0x8, "start": 0x10, "back": 0x20, "lb": 0x100,
              "rb": 0x200, "a": 0x1000, "b": 0x2000, "x": 0x4000, "y": 0x8000}

    def __init__(self):
        self.dll = None
        for nome in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                self.dll = getattr(ctypes.windll, nome)
                break
            except OSError:
                continue
        self.idx = None
        self._procurado = 0.0

    def ler(self):
        if not self.dll:
            return set()
        if self.idx is None:
            if time.time() - self._procurado < 2.0:       # procurar controle desligado é lento: só a cada 2 s
                return set()
            self._procurado = time.time()
            for i in range(4):
                st = _XState()
                if self.dll.XInputGetState(i, ctypes.byref(st)) == 0:
                    self.idx = i
                    break
            if self.idx is None:
                return set()
        st = _XState()
        if self.dll.XInputGetState(self.idx, ctypes.byref(st)) != 0:
            self.idx = None
            return set()
        g = st.Gamepad
        ap = {n for n, m in self.BOTOES.items() if g.wButtons & m}
        if g.sThumbLX > 16000:
            ap.add("dir")
        elif g.sThumbLX < -16000:
            ap.add("esq")
        if g.sThumbLY > 16000:
            ap.add("cima")
        elif g.sThumbLY < -16000:
            ap.add("baixo")
        return ap


# =====================================================================
#   MODO BIG PICTURE (tela cheia, estilo Steam)
# =====================================================================
class BigPicture(ctk.CTkToplevel):
    """Tela cheia no estilo Steam Big Picture: o mesmo layout do Jon, maior e navegável pelo controle."""
    ATALHOS = [("", "Downloads", "abre a pasta downloads"), ("", "Print", "tira um print"),
               ("", "Bom dia", "bom dia"), ("", "Clima", "como está o tempo"),
               ("", "Timer 5 min", "timer de 5 minutos"), ("", "Status", "status do sistema"),
               ("", "Curtidas", "toca minhas músicas curtidas"), ("", "Bloquear", "bloqueia o pc")]

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("J O N — Big Picture")
        self.configure(fg_color=BG)
        try:
            self.iconbitmap(os.path.join(PASTA, "assistente.ico"))
        except Exception:
            pass
        self.attributes("-fullscreen", True)
        self.protocol("WM_DELETE_WINDOW", self.fechar)
        self.bind("<Escape>", lambda e: self.fechar())
        self.bind("<F11>", lambda e: self.fechar())
        for tecla, d in (("<Left>", (0, -1)), ("<Right>", (0, 1)), ("<Up>", (-1, 0)), ("<Down>", (1, 0))):
            self.bind(tecla, lambda e, d=d: self.mover(*d))
        self.bind("<Return>", lambda e: self.ativar())
        self.bind("<space>", lambda e: self.app.controle_spotify("pausa_play"))
        self.controle = Controle()
        self._antes = set()
        self._repete = 0.0
        self._falando = False
        self.sel = [0, 0]
        self.linhas = []
        self._imgs = []
        self._imgs_notif = []
        n0 = len(Painel.marcas)
        self._montar()
        self._minhas_marcas = Painel.marcas[n0:]
        self.after(60, self._focar)

    def _focar(self):
        try:
            self.lift()
            self.focus_force()
            av.trazer_janela_pra_frente(int(self.wm_frame(), 16))
        except Exception:
            pass

    def _painel(self, master, titulo, etiqueta=""):
        p = Painel(master, titulo, etiqueta)
        p.lbl_titulo.configure(font=(MONO, 14, "bold"))
        p.etiqueta.configure(font=(MONO, 11))
        return p

    # ---------------- layout (igual ao modo normal, em tamanho de TV) ----------------
    def _montar(self):
        # topo
        cab = ctk.CTkFrame(self, fg_color=PAINEL, border_color=BORDA, border_width=1, corner_radius=0, height=86)
        cab.pack(fill="x")
        cab.pack_propagate(False)
        esq = ctk.CTkFrame(cab, fg_color="transparent")
        esq.pack(side="left", padx=28)
        self.logo = ctk.CTkLabel(esq, text="◆", font=(SANS, 30), text_color=ROXO)
        self.logo.pack(side="left", padx=(0, 14))
        tt = ctk.CTkFrame(esq, fg_color="transparent")
        tt.pack(side="left")
        ctk.CTkLabel(tt, text="J  O  N", font=(MONO, 26, "bold"), text_color=LILAS, height=30).pack(anchor="w")
        ctk.CTkLabel(tt, text="BIG PICTURE", font=(MONO, 11, "bold"), text_color=ROXO_CLARO,
                     height=14).pack(anchor="w")
        meio = ctk.CTkFrame(cab, fg_color="transparent")
        meio.place(relx=0.5, rely=0.5, anchor="center")
        self.lbl_hora = ctk.CTkLabel(meio, text="--:--", font=(MONO, 38, "bold"), text_color=LILAS, height=42)
        self.lbl_hora.pack()
        self.lbl_data = ctk.CTkLabel(meio, text="", font=(SANS, 13), text_color=ROXO_CLARO, height=16)
        self.lbl_data.pack()
        dir_ = ctk.CTkFrame(cab, fg_color="transparent")
        dir_.pack(side="right", padx=28)
        self.lbl_ia = ctk.CTkLabel(dir_, text="", font=(MONO, 13, "bold"), text_color=LILAS)
        self.lbl_ia.pack(anchor="e")
        self.lbl_clima = ctk.CTkLabel(dir_, text="", font=(SANS, 13), text_color=MUDO)
        self.lbl_clima.pack(anchor="e")
        self.varredura = ctk.CTkCanvas(self, height=2, bg=BG, highlightthickness=0)
        self.varredura.pack(fill="x")
        self._var_itens = [self.varredura.create_line(0, 1, 0, 1, fill=mix(BG, ROXO, k / 6), width=2)
                           for k in range(7)]

        # rodapé com as dicas dos botões (igual Steam)
        rod = ctk.CTkFrame(self, fg_color=PAINEL, corner_radius=0, height=44)
        rod.pack(side="bottom", fill="x")
        rod.pack_propagate(False)
        dicas = ctk.CTkFrame(rod, fg_color="transparent")
        dicas.pack(side="right", padx=28)
        for letra, cor, txt in (("A", "#5ec26a", "SELECIONAR  (Enter)"), ("B", "#e05a5a", "SAIR  (Esc)"),
                                ("Y", "#e8c547", "FALAR  (F9)"), ("X", "#4a8fe0", "PLAY/PAUSE  (Espaço)"),
                                ("LB/RB", MUDO, "MÚSICA")):
            ctk.CTkLabel(dicas, text=letra, width=26 if len(letra) == 1 else 50, height=26, corner_radius=13,
                         fg_color=cor if len(letra) == 1 else PAINEL2, text_color="#0b0716" if len(letra) == 1
                         else LILAS, font=(MONO, 11, "bold")).pack(side="left", padx=(16, 6))
            ctk.CTkLabel(dicas, text=txt, font=(MONO, 11), text_color=LILAS).pack(side="left")
        self.lbl_controle = ctk.CTkLabel(rod, text="", font=(MONO, 11), text_color=MUDO)
        self.lbl_controle.pack(side="left", padx=28)

        # corpo em 3 colunas
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=18, pady=14)
        corpo.grid_columnconfigure(0, weight=3, uniform="b")
        corpo.grid_columnconfigure(1, weight=5, uniform="b")
        corpo.grid_columnconfigure(2, weight=3, uniform="b")
        corpo.grid_rowconfigure(0, weight=1)
        col_e = ctk.CTkFrame(corpo, fg_color="transparent")
        col_e.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        col_c = ctk.CTkFrame(corpo, fg_color="transparent")
        col_c.grid(row=0, column=1, sticky="nsew")
        col_d = ctk.CTkFrame(corpo, fg_color="transparent")
        col_d.grid(row=0, column=2, sticky="nsew", padx=(14, 0))

        # ----- esquerda: sistema, ações, apps -----
        p = self._painel(col_e, "Sistema", "ao vivo")
        p.pack(fill="x")
        self.grafico = Grafico(p.corpo)
        self.grafico.configure(height=80)
        self.grafico.pack(fill="x")
        self.recursos = Recursos(p.corpo, ["CPU", "Memória RAM", "Placa de vídeo", "Disco C:"])
        self.recursos.pack(fill="x", pady=(8, 0))
        linha = ctk.CTkFrame(p.corpo, fg_color="transparent")
        linha.pack(fill="x")
        self.lbl_temp = self.app._mini(linha, "Temp. GPU", "--")
        self.lbl_rede = self.app._mini(linha, "Rede ↓ / ↑", "--")

        p = self._painel(col_e, "Ações", "A = abrir")
        p.pack(fill="x", pady=(12, 0))
        self.grade_acoes = ctk.CTkFrame(p.corpo, fg_color="transparent")
        self.grade_acoes.pack(fill="x")
        p = self._painel(col_e, "Apps recentes", "")
        p.pack(fill="both", expand=True, pady=(12, 0))
        self.grade_apps = ctk.CTkFrame(p.corpo, fg_color="transparent")
        self.grade_apps.pack(fill="x")
        for g in (self.grade_acoes, self.grade_apps):
            for k in range(4):
                g.grid_columnconfigure(k, weight=1, uniform="t")

        # ----- centro: o cérebro do Jon -----
        moldura = ctk.CTkFrame(col_c, fg_color="transparent", border_color=BORDA, border_width=1, corner_radius=0)
        moldura.pack(fill="both", expand=True)
        self.nucleo = (NucleoOrganico if ORGANICO else Nucleo)(moldura, self.app.clicou_mic)
        if ORGANICO:
            self.nucleo.teto = 640
        self.nucleo.estado = self.app.estado
        self.nucleo.pack(fill="both", expand=True, padx=20, pady=(14, 0))
        self.pilula = ctk.CTkLabel(moldura, text="", height=38, corner_radius=19, fg_color=PAINEL,
                                   font=(MONO, 14, "bold"), text_color=ROXO_CLARO)
        self.pilula.pack(pady=(4, 2), ipadx=20)
        ctk.CTkLabel(moldura, text="Diga “Jon, …”  •  segure F9  •  segure Y no controle", font=(MONO, 11),
                     text_color=MUDO, height=16).pack()
        faixa = ctk.CTkFrame(moldura, fg_color="transparent")
        faixa.pack(fill="x", padx=20, pady=(12, 16))
        for k in range(3):
            faixa.grid_columnconfigure(k, weight=1, uniform="f")
        self.card_clima = self.app._card(faixa, 0, "", "CLIMA", "", "", lambda: None)
        self.card_prox = self.app._card(faixa, 1, "", "PRÓXIMO", "", "", lambda: None)
        self.card_mail = self.app._card(faixa, 2, "", "E-MAIL", "", "", lambda: None)
        for v, s_ in (self.card_clima, self.card_prox, self.card_mail):
            v.configure(font=(SANS, 15, "bold"), height=24)
            s_.configure(font=(SANS, 11), height=16)

        # ----- direita: música, notificações, downloads -----
        p = self._painel(col_d, "Tocando agora", "")
        p.pack(fill="x")
        self.painel_mus = p
        l = ctk.CTkFrame(p.corpo, fg_color="transparent")
        l.pack(fill="x")
        self.capa = ctk.CTkLabel(l, text="", font=(ICO, 34), text_color=APAGADO, width=120, height=120,
                                 fg_color=PAINEL2, corner_radius=10)
        self.capa.pack(side="left")
        info = ctk.CTkFrame(l, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(14, 0))
        self.lbl_mus = ctk.CTkLabel(info, text="Nada tocando", font=(SANS, 18, "bold"), text_color=LILAS,
                                    anchor="w", justify="left", wraplength=240)
        self.lbl_mus.pack(fill="x", pady=(8, 0))
        self.lbl_art = ctk.CTkLabel(info, text="", font=(SANS, 14), text_color=ROXO_CLARO, anchor="w")
        self.lbl_art.pack(fill="x")
        self.lbl_onde = ctk.CTkLabel(info, text="", font=(MONO, 10), text_color=MUDO, anchor="w")
        self.lbl_onde.pack(fill="x", pady=(4, 0))
        pr = ctk.CTkFrame(p.corpo, fg_color="transparent")
        pr.pack(fill="x", pady=(10, 0))
        self.t0 = ctk.CTkLabel(pr, text="0:00", font=(MONO, 11), text_color=MUDO, width=40)
        self.t0.pack(side="left")
        self.t1 = ctk.CTkLabel(pr, text="0:00", font=(MONO, 11), text_color=MUDO, width=40)
        self.t1.pack(side="right")
        self.prog = ctk.CTkProgressBar(pr, height=6, corner_radius=3, fg_color=ROXO_ESCURO,
                                       progress_color=self.app.acento)
        self.prog.set(0)
        self.prog.pack(side="left", fill="x", expand=True, padx=4)
        bts = ctk.CTkFrame(p.corpo, fg_color="transparent")
        bts.pack(pady=(8, 2))
        for glifo, acao, grande in (("", "anterior", False), ("", "pausa_play", True),
                                    ("", "proxima", False)):
            tam = 58 if grande else 46
            b = ctk.CTkButton(bts, text=glifo, width=tam, height=tam, corner_radius=tam // 2,
                              fg_color=self.app.acento if grande else PAINEL2,
                              hover_color=ROXO_ESCURO, text_color="#0b0716" if grande else LILAS,
                              font=(ICO, 20 if grande else 16), command=lambda a=acao: self.app.controle_spotify(a))
            b.pack(side="left", padx=10)
            if grande:
                self.bt_play = b

        p = self._painel(col_d, "Notificações", "")
        p.pack(fill="both", expand=True, pady=(12, 0))
        self.painel_notif = p
        self.notifs = ctk.CTkFrame(p.corpo, fg_color="transparent")
        self.notifs.pack(fill="both", expand=True)

        p = self._painel(col_d, "Downloads", "")
        p.pack(fill="x", pady=(12, 0))
        self.painel_dl = p
        self.lista_dl = ctk.CTkFrame(p.corpo, fg_color="transparent")
        self.lista_dl.pack(fill="x")

        self.desenhar_blocos()
        self.desenhar_notifs()
        self.desenhar_dl()
        self.atualizar()

    def _bloco(self, master, glifo, nome, acao, imagem=None):
        f = ctk.CTkFrame(master, fg_color=PAINEL2, border_color=BORDA, border_width=2, corner_radius=10,
                         height=86, cursor="hand2")
        f.pack_propagate(False)
        if imagem is not None:
            ic = ctk.CTkLabel(f, text="", image=imagem, height=40)
        else:
            ic = ctk.CTkLabel(f, text=glifo, font=(ICO, 24), text_color=ROXO_CLARO, height=40)
        ic.pack(pady=(10, 2))
        tx = ctk.CTkLabel(f, text=nome if len(nome) <= 13 else nome[:12] + "…", font=(SANS, 12),
                          text_color=LILAS, height=18)
        tx.pack()
        for w in (f, ic, tx):
            w.bind("<Button-1>", lambda e: acao())
        f.acao = acao
        return f

    def desenhar_blocos(self):
        for g in (self.grade_acoes, self.grade_apps):
            for w in g.winfo_children():
                w.destroy()
        self._imgs = []
        acoes = []
        for glifo, nome, cmd in self.ATALHOS:
            acoes.append(self._bloco(self.grade_acoes, glifo, nome, lambda c=cmd: self.app.rodar_comando(c)))
        apps = []
        for it in self.app.recentes.lista[:8]:
            img = px.icone_exe(it["exe"], 48)
            ci = ctk.CTkImage(img, size=(36, 36)) if img is not None else None
            self._imgs.append(ci)
            apps.append(self._bloco(self.grade_apps, "", it["nome"],
                                    lambda e=it["exe"]: px.abrir_ou_focar(e), ci))
        if not apps:
            ctk.CTkLabel(self.grade_apps, text="Os programas que você usar aparecem aqui.", font=(SANS, 12),
                         text_color=MUDO).grid(row=0, column=0, columnspan=4, sticky="w")
        self.linhas = []
        for lista in (acoes, apps):
            for k, b in enumerate(lista):
                b.grid(row=k // 4, column=k % 4, sticky="ew", padx=3, pady=3)
            for i in range(0, len(lista), 4):
                self.linhas.append(lista[i:i + 4])
        self.sel[0] = min(self.sel[0], max(0, len(self.linhas) - 1))
        self._marcar()

    def desenhar_notifs(self):
        for w in self.notifs.winfo_children():
            w.destroy()
        self._imgs_notif = []
        n = self.app.notif
        self.painel_notif.etiqueta.configure(text=str(len(n.itens)) if n.itens else "", text_color=ROSA)
        if n.estado != "ok" or not n.itens:
            ctk.CTkLabel(self.notifs, text="Nenhuma notificação. Tudo em dia ✓" if n.estado == "ok" else
                         "Notificações indisponíveis.", font=(SANS, 13), text_color=MUDO,
                         anchor="w").pack(fill="x")
            return
        for it in n.itens[:4]:
            f = ctk.CTkFrame(self.notifs, fg_color=PAINEL2, corner_radius=8)
            f.pack(fill="x", pady=3)
            ic = self.app._icone_ctk(px.exe_por_nome_app(it["app"]), 28)
            self._imgs_notif.append(ic)
            if ic is not None:
                ctk.CTkLabel(f, text="", image=ic, width=34).pack(side="left", padx=(10, 4), pady=10, anchor="n")
            c = ctk.CTkFrame(f, fg_color="transparent")
            c.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=6)
            ctk.CTkLabel(c, text=it["app"].upper()[:24], font=(MONO, 10), text_color=ROXO_CLARO, anchor="w",
                         height=14).pack(fill="x")
            ctk.CTkLabel(c, text=it["titulo"][:38], font=(SANS, 13, "bold"), text_color=LILAS, anchor="w",
                         height=18).pack(fill="x")
            if it["texto"]:
                ctk.CTkLabel(c, text=it["texto"][:70], font=(SANS, 11), text_color=MUDO, anchor="w",
                             height=16).pack(fill="x")

    def desenhar_dl(self):
        for w in self.lista_dl.winfo_children():
            w.destroy()
        d = self.app.downloads
        self.painel_dl.etiqueta.configure(text=f"↓ {len(d.ativos)} BAIXANDO" if d.ativos else "",
                                          text_color=self.app.acento)
        for it in d.ativos[:2]:
            ctk.CTkLabel(self.lista_dl, text=it["nome"][:34], font=(SANS, 13, "bold"), text_color=LILAS,
                         anchor="w", height=18).pack(fill="x")
            vel = f"{px.humano(it['vel'])}/s" if it["vel"] > 0 else "aguardando…"
            pct = f" • {it['frac'] * 100:.0f}%" if it["frac"] is not None else ""
            ctk.CTkLabel(self.lista_dl, text=f"{it['origem']} • {px.humano(it['feito'])}{pct} • {vel}",
                         font=(MONO, 10), text_color=MUDO, anchor="w", height=14).pack(fill="x")
            b = ctk.CTkProgressBar(self.lista_dl, height=5, corner_radius=2, fg_color=ROXO_ESCURO,
                                   progress_color=self.app.acento,
                                   mode="determinate" if it["frac"] is not None else "indeterminate")
            b.pack(fill="x", pady=(3, 8))
            if it["frac"] is not None:
                b.set(it["frac"])
            else:
                b.start()
        for it in d.recentes[: (3 if not d.ativos else 1)]:
            ctk.CTkLabel(self.lista_dl, text="✓  " + it["nome"][:36], font=(SANS, 12), text_color=MUDO,
                         anchor="w", height=18).pack(fill="x")
        if not d.ativos and not d.recentes:
            ctk.CTkLabel(self.lista_dl, text="Nada baixando.", font=(SANS, 12), text_color=MUDO,
                         anchor="w").pack(fill="x")

    def stats(self, d):
        r = self.recursos
        r.definir("CPU", d["cpu"] / 100, f"{d['cpu']:.0f}%", d["cpu"] > 90)
        r.definir("Memória RAM", d["ram_pct"] / 100, f"{d['ram_usada']:.1f} / {d['ram_total']:.0f} GB",
                  d["ram_pct"] > 90)
        g = d.get("gpu")
        if g:
            r.definir("Placa de vídeo", g["uso"] / 100, f"{g['uso']}%  •  {g['mem_usada']:.1f}/{g['mem_total']:.0f} GB")
            self.app._set(self.lbl_temp, text=f"{g['temp']} °C")
        for disco in d["discos"]:
            if disco["letra"] == "C":
                r.definir("Disco C:", disco["pct"] / 100, f"{disco['livre']:.0f} GB livres", disco["livre"] < 10)
        self.grafico.adicionar(d["cpu"])
        self.app._set(self.lbl_rede, text=f"{d['down']:.1f} / {d['up']:.1f} MB/s")

    # ---------------- navegação ----------------
    def _marcar(self):
        for r, linha in enumerate(self.linhas):
            for c, b in enumerate(linha):
                ativo = [r, c] == self.sel
                b.configure(border_color=self.app.acento if ativo else BORDA,
                            fg_color=mix(PAINEL2, self.app.acento, 0.2) if ativo else PAINEL2)

    def mover(self, dr, dc):
        if not self.linhas:
            return
        r, c = self.sel
        if dr:
            r = max(0, min(len(self.linhas) - 1, r + dr))
            c = min(c, len(self.linhas[r]) - 1)
        if dc:
            c = max(0, min(len(self.linhas[r]) - 1, c + dc))
        self.sel = [r, c]
        self._marcar()

    def ativar(self):
        r, c = self.sel
        if r < len(self.linhas) and c < len(self.linhas[r]):
            b = self.linhas[r][c]
            self.app._piscar(b, ROXO_CLARO, mix(PAINEL2, self.app.acento, 0.2), 8)
            b.acao()

    def fechar(self):
        if self._falando:
            self.app.motor.soltar()
        self.app.bp = None
        Painel.marcas[:] = [m for m in Painel.marcas if m not in self._minhas_marcas]
        self.destroy()
        try:
            self.app.mostrar_janela()
        except Exception:
            pass

    # ---------------- a cada quadro ----------------
    def animar(self, t):
        self.recursos.animar()
        self.grafico.desenhar()
        w = self.varredura.winfo_width()
        if w > 10:
            x = (t * 0.25 % 1.0) * (w + 300) - 150
            for k, it in enumerate(self._var_itens):
                larg = 150 - k * 20
                self.varredura.coords(it, x - larg, 1, x + larg, 1)
        if int(t * 30) % 3 == 0:
            self.logo.configure(text_color=mix(ROXO, ROSA, 0.5 + 0.5 * math.sin(t * 1.6)))
            for k, m in enumerate(Painel.marcas):
                try:
                    m.configure(text_color=mix(ROXO_ESCURO, ROXO_CLARO, 0.5 + 0.5 * math.sin(t * 2.2 - k * 0.7)))
                except Exception:
                    pass
        ap = self.controle.ler()
        novos = ap - self._antes
        agora = time.time()
        for d, (dr, dc) in {"cima": (-1, 0), "baixo": (1, 0), "esq": (0, -1), "dir": (0, 1)}.items():
            if d in novos:
                self.mover(dr, dc)
                self._repete = agora + 0.35
            elif d in ap and agora >= self._repete:
                self.mover(dr, dc)
                self._repete = agora + 0.12
        if "a" in novos:
            self.ativar()
        if "b" in novos:
            self.fechar()
            return
        if "x" in novos:
            self.app.controle_spotify("pausa_play")
        if "lb" in novos:
            self.app.controle_spotify("anterior")
        if "rb" in novos:
            self.app.controle_spotify("proxima")
        if "y" in novos and not self._falando:           # segura Y = falar (igual ao F9)
            self._falando = True
            self.app.motor.comecar()
        elif "y" not in ap and self._falando:
            self._falando = False
            self.app.motor.soltar()
        self._antes = ap
        txt = f"🎮 CONTROLE {self.controle.idx + 1} CONECTADO" if self.controle.idx is not None else \
            "TECLADO / MOUSE  •  conecte um controle de Xbox para navegar"
        if self.lbl_controle.cget("text") != txt:
            self.lbl_controle.configure(text=txt)

    def atualizar(self):
        a = self.app
        agora = dt.datetime.now()
        self.lbl_hora.configure(text=agora.strftime("%H:%M:%S"))
        import extras
        self.lbl_data.configure(text=f"{extras.SEMANA[agora.weekday()]}, {agora.day} de "
                                     f"{extras.MESES[agora.month - 1]}")
        self.lbl_ia.configure(text=a.lbl_ia.cget("text"), text_color=a.ponto_ia.cget("text_color"))
        c = getattr(a, "clima_atual", None)
        if c:
            self.lbl_clima.configure(text=f"{c['cidade']} • chuva {c['chuva']}%")
        txt, _, cor = ESTADOS[a.estado]
        self.pilula.configure(text=f"🎙   {txt}", text_color=cor)
        for meu, dele in ((self.card_clima, a.card_clima), (self.card_prox, a.card_prox), (self.card_mail, a.card_mail)):
            for k in range(2):
                t_ = dele[k].cget("text")
                if meu[k].cget("text") != t_:
                    meu[k].configure(text=t_)
        d = a.player
        if d:
            self.lbl_mus.configure(text=d["nome"][:50])
            self.lbl_art.configure(text=d["artista"][:40])
            self.lbl_onde.configure(text=("▶ TOCANDO EM " if d["tocando"] else "⏸ PAUSADO EM ") + d["device"].upper()[:20])
            self.painel_mus.etiqueta.configure(text="▶ TOCANDO" if d["tocando"] else "⏸ PAUSADO",
                                               text_color=a.acento if d["tocando"] else APAGADO)
            if d.get("duracao"):
                pos = min(d["duracao"], d["progresso"] + ((time.time() - a._player_t) * 1000 if d["tocando"] else 0))
                self.prog.set(pos / d["duracao"])
                self.t0.configure(text=_mmss(pos))
                self.t1.configure(text=_mmss(d["duracao"]))
            self.bt_play.configure(text="" if d["tocando"] else "", fg_color=a.acento)
            self.prog.configure(progress_color=a.acento)
            capa = getattr(a, "_capa_pil", None)
            if capa is not None and getattr(self, "_capa_feita", None) is not capa:
                self._capa_feita = capa
                self._capa_img = ctk.CTkImage(capa_arredondada(capa, 120, 12), size=(120, 120))
                self.capa.configure(image=self._capa_img, text="")
        else:
            self.lbl_mus.configure(text="Nada tocando")
            self.lbl_art.configure(text="Diga “Jon, toca …”")
            self.lbl_onde.configure(text="")
            self.painel_mus.etiqueta.configure(text="")


# =====================================================================
#   APP
# =====================================================================

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.cfg = carregar_config()
        av.TECLA_FALAR = self.cfg["tecla"]
        av.FALAR_RESPOSTAS = self.cfg["falar"]
        self.motor = av.Motor(self.cfg["tecla"])

        self.title(f"J O N — v{VERSAO}")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(1360, sw - 40)}x{min(820, sh - 70)}+10+5")
        self.minsize(1040, 640)
        self.after(50, lambda: self.state("zoomed"))
        self.configure(fg_color=BG)
        try:
            self.iconbitmap(os.path.join(PASTA, "assistente.ico"))
        except Exception:
            pass
        self.protocol("WM_DELETE_WINDOW", self.sair)
        self.bind("<F11>", lambda e: self.big_picture(True))
        self.bind("<F2>", self.mostrar_chat)
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        self._cache_lbl = {}
        self.spotify_ok = False
        self.sp_estado = {"repeat": "off", "shuffle": False}
        self.player = {}                    # última leitura do Spotify
        self._player_t = time.time()
        self._vol_mexido = 0.0
        self._capa_url = None
        self._curtida_id = None
        self.recentes = px.Recentes(8)
        self.notif = px.Notificacoes()
        self.downloads = px.Downloads()
        self.acento = SPOTIFY_VERDE         # muda com a cor da capa do álbum
        self.bp = None                      # janela do modo Big Picture (quando aberta)
        self.clima_atual = None
        self._capa_pil = None
        self._marcas = []                   # marcadores dos painéis que "respiram"
        self._fase_ui = 0.0
        self.email_cfg = px.carregar_email()
        self.email_uids = None
        self._checar_email_agora = threading.Event()
        self.alertas_avisados = {}
        self.estado = "pronto"
        self._montar()

        self.motor.ligar_tecla(self.cfg["tecla"])
        if self.cfg["maos_livres"]:
            self.motor.ligar_maos_livres(True)
        rotinas.iniciar_relogio()
        av.preparar_voz()
        web_jon.av = av
        web_jon.ao_pedido = lambda estado: FILA.put(("status", estado))
        web_jon.iniciar()
        for alvo in (atalhos.migrar_nome, self._conectar_spotify, self._checar_ia, self._ler_sistema,
                     self.recentes.vigiar, self._vigiar_email, self._vigiar_clima,
                     lambda: self.notif.rodar(lambda: getattr(self, "visivel", True)),
                     lambda: self.downloads.rodar(lambda: getattr(self, "visivel", True)),
                     self._vigiar_controle, self._vigiar_atualizacao, self._instalar_faltando):
            threading.Thread(target=alvo, daemon=True).start()
        self.after(33, self._loop)
        self.after(1000, self._relogio)
        if not self.cfg.get("nome"):
            self.after(1200, self.boas_vindas)
        self.after(2000, self._agenda_tick)

    # ---------------- layout ----------------
    def _montar(self):
        # ===== cabeçalho =====
        cab = ctk.CTkFrame(self, fg_color=PAINEL, border_color=BORDA, border_width=1, corner_radius=0, height=64)
        cab.pack(fill="x")
        cab.pack_propagate(False)
        logo = ctk.CTkFrame(cab, fg_color="transparent")
        logo.pack(side="left", padx=18)
        self.lbl_logo = ctk.CTkLabel(logo, text="◆", font=(SANS, 22), text_color=ROXO)
        self.lbl_logo.pack(side="left", padx=(0, 12))
        tt = ctk.CTkFrame(logo, fg_color="transparent")
        tt.pack(side="left")
        ctk.CTkLabel(tt, text=f"J  O  N   v{VERSAO}", font=(MONO, 18, "bold"), text_color=LILAS, height=22).pack(anchor="w")
        ctk.CTkLabel(tt, text="SEU ASSISTENTE PESSOAL — UM SISTEMA BEM INTELIGENTE", font=(MONO, 9),
                     text_color=MUDO, height=12).pack(anchor="w")

        meio = ctk.CTkFrame(cab, fg_color="transparent")
        meio.place(relx=0.5, rely=0.5, anchor="center")
        b1 = ctk.CTkFrame(meio, fg_color="transparent")
        b1.pack(side="left", padx=18)
        ctk.CTkLabel(b1, text="STATUS DO SISTEMA", font=(MONO, 9), text_color=MUDO, height=12).pack()
        self.lbl_sys = ctk.CTkLabel(b1, text="●  ÓTIMO", font=(MONO, 12, "bold"), text_color=ROXO_CLARO, height=18)
        self.lbl_sys.pack()
        b2 = ctk.CTkFrame(meio, fg_color="transparent")
        b2.pack(side="left", padx=18)
        ctk.CTkLabel(b2, text="HORA LOCAL", font=(MONO, 9), text_color=MUDO, height=12).pack()
        self.lbl_hora = ctk.CTkLabel(b2, text="--:--:--", font=(MONO, 12, "bold"), text_color=LILAS, height=18)
        self.lbl_hora.pack()
        b3 = ctk.CTkFrame(meio, fg_color="transparent")
        b3.pack(side="left", padx=18)
        ctk.CTkLabel(b3, text="NÚCLEO DE IA", font=(MONO, 9), text_color=MUDO, height=12).pack()
        l = ctk.CTkFrame(b3, fg_color="transparent")
        l.pack()
        self.ponto_ia = ctk.CTkLabel(l, text="●", text_color=APAGADO, font=(SANS, 11), width=10, height=18)
        self.ponto_ia.pack(side="left")
        self.lbl_ia = ctk.CTkLabel(l, text="VERIFICANDO…", font=(MONO, 12, "bold"), text_color=LILAS, height=18)
        self.lbl_ia.pack(side="left", padx=(4, 0))
        b4 = ctk.CTkFrame(meio, fg_color="transparent")
        b4.pack(side="left", padx=18)
        ctk.CTkLabel(b4, text="MÃOS-LIVRES", font=(MONO, 9), text_color=MUDO, height=12).pack()
        self.sw_ml = ctk.CTkSwitch(b4, text="“Jon, …”", font=(MONO, 10), text_color=LILAS, progress_color=ROXO,
                                   button_color=ROXO_CLARO, fg_color=ROXO_ESCURO, command=self.trocar_maos_livres,
                                   height=18, switch_width=32, switch_height=16)
        self.sw_ml.pack()
        if self.cfg["maos_livres"]:
            self.sw_ml.select()

        dir_ = ctk.CTkFrame(cab, fg_color="transparent")
        dir_.pack(side="right", padx=14)
        # aparece só quando o GitHub tem uma versão nova
        self.bt_atualizar = ctk.CTkButton(dir_, text="⬇  ATUALIZAÇÃO", width=130, height=30, corner_radius=15,
                                          fg_color=ROSA, hover_color=ROXO_CLARO, text_color="#0b0716",
                                          font=(MONO, 10, "bold"), command=self.mostrar_atualizacao)
        self._info_atualizacao = None
        self._primeiro_botao_topo = ctk.CTkButton(dir_, text="\uE8BD", width=34, height=34, corner_radius=17,
                                                  fg_color="transparent", border_width=1, border_color=BORDA,
                                                  hover_color=PAINEL2, text_color=ROXO_CLARO, font=(ICO, 13),
                                                  command=self.mostrar_chat)
        self._primeiro_botao_topo.pack(side="left", padx=4)
        ctk.CTkButton(dir_, text="?", width=34, height=34, corner_radius=17, fg_color="transparent",
                      border_width=1, border_color=BORDA, hover_color=PAINEL2, text_color=ROXO_CLARO,
                      font=(MONO, 14, "bold"), command=self.mostrar_exemplos).pack(side="left", padx=4)
        ctk.CTkButton(dir_, text="\uE740", width=34, height=34, corner_radius=17, fg_color="transparent",
                      border_width=1, border_color=BORDA, hover_color=PAINEL2, text_color=ROXO_CLARO,
                      font=(ICO, 13), command=lambda: self.big_picture(True)).pack(side="left", padx=4)
        ctk.CTkButton(dir_, text="\uE8BC", width=34, height=34, corner_radius=17, fg_color="transparent",
                      border_width=1, border_color=BORDA, hover_color=PAINEL2, text_color=ROXO_CLARO,
                      font=(ICO, 13), command=self.mostrar_memoria).pack(side="left", padx=4)
        ctk.CTkButton(dir_, text="⚙", width=34, height=34, corner_radius=17, fg_color="transparent",
                      border_width=1, border_color=BORDA, hover_color=PAINEL2, text_color=ROXO_CLARO,
                      font=(SANS, 15), command=self.mostrar_config).pack(side="left", padx=4)
        chip = ctk.CTkFrame(dir_, fg_color=PAINEL2, border_color=BORDA, border_width=1, corner_radius=20)
        chip.pack(side="left", padx=(10, 0))
        self.lbl_dono = ctk.CTkLabel(chip, text=(self.cfg.get("nome") or "JON").upper()[:18], font=(MONO, 12, "bold"),
                                     text_color=LILAS)
        self.lbl_dono.pack(side="left",
                                                                                              padx=(14, 8), pady=6)
        ctk.CTkLabel(chip, text="●", font=(SANS, 20), text_color=ROXO).pack(side="left", padx=(0, 10))

        # linha de varredura (dá vida ao topo, custa quase nada)
        self.varredura = ctk.CTkCanvas(self, height=2, bg=BG, highlightthickness=0)
        self.varredura.pack(fill="x")
        self._var_itens = [self.varredura.create_line(0, 1, 0, 1, fill=mix(BG, ROXO, k / 6), width=2)
                           for k in range(7)]
        self._var_x = 0.0

        # ===== corpo em 3 colunas =====
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=12, pady=10)
        corpo.grid_columnconfigure(0, weight=3, uniform="c")
        corpo.grid_columnconfigure(1, weight=5, uniform="c")
        corpo.grid_columnconfigure(2, weight=3, uniform="c")
        corpo.grid_rowconfigure(0, weight=1)
        esq = ctk.CTkFrame(corpo, fg_color="transparent")
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        cen = ctk.CTkFrame(corpo, fg_color="transparent")
        cen.grid(row=0, column=1, sticky="nsew")
        dir_c = ctk.CTkFrame(corpo, fg_color="transparent")
        dir_c.grid(row=0, column=2, sticky="nsew", padx=(10, 0))

        # ----- esquerda: sistema (gráfico + barras) -----
        p = Painel(esq, "Sistema", "ao vivo")
        p.pack(fill="x")
        self.grafico = Grafico(p.corpo)
        self.grafico.pack(fill="x")
        linha = ctk.CTkFrame(p.corpo, fg_color="transparent")
        linha.pack(fill="x", pady=(6, 6))
        self.lbl_gpu_temp = self._mini(linha, "Temp. GPU", "--")
        self.lbl_rede = self._mini(linha, "Rede ↓ / ↑", "--")
        self.recursos = Recursos(p.corpo, ["CPU", "Memória RAM", "Placa de vídeo", "Disco C:", "Disco E:", "Disco F:"])
        self.recursos.pack(fill="x")

        # ----- esquerda: atalhos rápidos -----
        p = Painel(esq, "Atalhos rápidos", "1 clique")
        p.pack(fill="x", pady=(10, 0))
        grade = ctk.CTkFrame(p.corpo, fg_color="transparent")
        grade.pack(fill="x")
        ATALHOS = [("", "Downloads", "abre a pasta downloads"), ("", "Otimizar PC", "otimiza o pc"),
                   ("", "Arrumar DL", "organiza a pasta downloads"), ("", "Limpar Lixo", "esvazia a lixeira"),
                   ("", "Bom dia", "bom dia"), ("", "Clima", "como está o tempo"),
                   ("", "Print", "tira um print"), ("", "Bloquear", "bloqueia o pc")]
        for k, (ic, rot, cmd) in enumerate(ATALHOS):
            grade.grid_columnconfigure(k % 4, weight=1, uniform="a")
            t = self._tile(grade, ic, rot, lambda c=cmd: self.rodar_comando(c))
            t.grid(row=k // 4, column=k % 4, sticky="ew", padx=2, pady=2)

        # ----- esquerda: apps recentes -----
        p = Painel(esq, "Apps recentes", "clique p/ abrir")
        p.pack(fill="x", pady=(10, 0))
        self.grade_apps = ctk.CTkFrame(p.corpo, fg_color="transparent")
        self.grade_apps.pack(fill="x")
        for k in range(4):
            self.grade_apps.grid_columnconfigure(k, weight=1, uniform="r")
        self._img_apps = []

        # ----- esquerda: downloads -----
        p = Painel(esq, "Downloads", "")
        p.pack(fill="both", expand=True, pady=(10, 0))
        self.painel_dl = p
        ctk.CTkButton(p.direita, text="\uE8B7", width=22, height=18, fg_color="transparent", hover_color=PAINEL2,
                      text_color=ROXO_CLARO, font=(ICO, 10),
                      command=lambda: os.startfile(self.downloads.pasta)).pack(side="right", padx=(6, 0))
        self.lista_dl = ctk.CTkFrame(p.corpo, fg_color="transparent")
        self.lista_dl.pack(fill="both", expand=True)
        self.agenda = ctk.CTkFrame(p.corpo, fg_color="transparent")     # (a agenda agora fica no cartão "Próximo")

        # ----- centro: núcleo -----
        moldura = ctk.CTkFrame(cen, fg_color="transparent", border_color=BORDA, border_width=1, corner_radius=0)
        moldura.pack(fill="both", expand=True)
        self.nucleo = (NucleoOrganico if ORGANICO else Nucleo)(moldura, self.clicou_mic)
        self.nucleo.pack(fill="both", expand=True, padx=20, pady=(12, 0))
        self.onda = Onda(moldura)
        self.onda.pack(pady=(2, 2))
        self.pilula = ctk.CTkButton(moldura, text="🎙   AGUARDANDO COMANDO…", height=34, corner_radius=17,
                                    fg_color=PAINEL, border_width=1, border_color=ROXO_ESCURO, hover_color=PAINEL2,
                                    text_color=ROXO_CLARO, font=(MONO, 12, "bold"), command=self.clicou_mic)
        self.pilula.pack(pady=(2, 4))
        self.lbl_dica = ctk.CTkLabel(moldura, text="", font=(MONO, 10), text_color=MUDO, height=14)
        self.lbl_dica.pack()
        self._atualizar_dica()
        # faixa de informações: clima • próximo lembrete • e-mails
        faixa = ctk.CTkFrame(moldura, fg_color="transparent")
        faixa.pack(fill="x", padx=20, pady=(10, 0))
        for k in range(3):
            faixa.grid_columnconfigure(k, weight=1, uniform="f")
        self.card_clima = self._card(faixa, 0, "", "CLIMA", "carregando…", "",
                                     lambda: self.rodar_comando("como está o tempo"))
        self.card_prox = self._card(faixa, 1, "", "PRÓXIMO", "nada agendado", "", self.mostrar_rotinas)
        self.card_mail = self._card(faixa, 2, "", "E-MAIL", "não conectado", "clique para conectar",
                                    self.clicou_card_email)
        # terminal (digitar comandos)
        term = ctk.CTkFrame(moldura, fg_color=PAINEL, border_color=BORDA, border_width=1, corner_radius=4)
        term.pack(fill="x", padx=20, pady=(10, 14))
        ctk.CTkLabel(term, text=">_", font=(MONO, 14, "bold"), text_color=ROXO).pack(side="left", padx=(12, 6))
        ctk.CTkButton(term, text="💬  CONVERSAR COM A IA", height=28, corner_radius=4, fg_color=ROXO_ESCURO,
                      hover_color=ROXO, text_color=LILAS, font=(MONO, 10, "bold"),
                      command=self.mostrar_chat).pack(side="right", padx=(0, 8))
        self.entrada = ctk.CTkEntry(term, placeholder_text="digite um comando pro Jon e aperte Enter…",
                                    fg_color=PAINEL, border_width=0, text_color=LILAS, font=(MONO, 12),
                                    placeholder_text_color=APAGADO, height=36)
        self.entrada.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.entrada.bind("<Return>", self.enviou_texto)

        # ----- direita: player do Spotify -----
        icone_sp = None
        try:
            exe = px.exe_spotify()
            img = px.icone_exe(exe, 32) if exe else None
            if img is not None:
                icone_sp = ctk.CTkImage(img, size=(18, 18))
        except Exception:
            pass
        p = Painel(dir_c, "Spotify", "conectando…", icone=icone_sp)
        p.pack(fill="x")
        if icone_sp is None:
            p.lbl_icone.configure(text="●", text_color=SPOTIFY_VERDE, font=(SANS, 14))
        self.painel_sp = p
        self.eq = ctk.CTkCanvas(p.direita, width=20, height=14, bg=PAINEL, highlightthickness=0)
        self.eq.pack(side="right", padx=(0, 8))
        self._eq_barras = [self.eq.create_rectangle(k * 5, 14, k * 5 + 3, 14, fill=SPOTIFY_VERDE, outline="")
                           for k in range(4)]
        topo = ctk.CTkFrame(p.corpo, fg_color="transparent")
        topo.pack(fill="x")
        self.capa_vazia = ctk.CTkImage(Image.new("RGBA", (84, 84), (20, 15, 36, 255)), size=(84, 84)) \
            if ORGANICO else None
        self.lbl_capa = ctk.CTkLabel(topo, text="" if not ORGANICO else "", image=self.capa_vazia,
                                     width=84, height=84, fg_color=PAINEL2, corner_radius=8, font=(ICO, 26),
                                     text_color=APAGADO)
        self.lbl_capa.pack(side="left")
        info = ctk.CTkFrame(topo, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.lbl_musica = ctk.CTkLabel(info, text="Nada tocando", font=(SANS, 14, "bold"), text_color=LILAS,
                                       anchor="w", justify="left", height=20)
        self.lbl_musica.pack(fill="x", pady=(4, 0))
        self.lbl_artista = ctk.CTkLabel(info, text="Peça uma música pro Jon", font=(SANS, 12),
                                        text_color=ROXO_CLARO, anchor="w", height=18)
        self.lbl_artista.pack(fill="x")
        self.lbl_album = ctk.CTkLabel(info, text="", font=(SANS, 10), text_color=MUDO, anchor="w", height=16)
        self.lbl_album.pack(fill="x")
        self.lbl_device = ctk.CTkLabel(info, text="", font=(MONO, 9), text_color=SPOTIFY_VERDE, anchor="w",
                                       height=14)
        self.lbl_device.pack(fill="x", pady=(2, 0))
        # progresso
        prog = ctk.CTkFrame(p.corpo, fg_color="transparent")
        prog.pack(fill="x", pady=(8, 0))
        self.lbl_t0 = ctk.CTkLabel(prog, text="0:00", font=(MONO, 9), text_color=MUDO, width=34, height=12)
        self.lbl_t0.pack(side="left")
        self.lbl_t1 = ctk.CTkLabel(prog, text="0:00", font=(MONO, 9), text_color=MUDO, width=34, height=12)
        self.lbl_t1.pack(side="right")
        self.progresso = Progresso(prog, self.pular_para)
        self.progresso.pack(side="left", fill="x", expand=True)
        # botões
        ctrl = ctk.CTkFrame(p.corpo, fg_color="transparent")
        ctrl.pack(pady=(4, 0))
        self.bt_sp = {}

        def bt(chave, glifo, acao, tam=34, grande=False):
            b = ctk.CTkButton(ctrl, text=glifo, width=tam, height=tam, corner_radius=tam // 2,
                              fg_color=ROXO if grande else "transparent", hover_color=ROXO_ESCURO if not grande
                              else ROXO_CLARO, text_color="#0b0716" if grande else LILAS,
                              font=(ICO, 15 if grande else 13), command=lambda: self.controle_spotify(acao))
            b.pack(side="left", padx=4)
            self.bt_sp[chave] = b
        bt("curtir", "", "curtir")
        bt("aleatorio", "", "aleatorio")
        bt("anterior", "", "anterior")
        bt("pausa_play", "", "pausa_play", 44, True)
        bt("proxima", "", "proxima")
        bt("repetir", "", "repetir")
        bt("abrir", "", "abrir")
        # volume
        vol = ctk.CTkFrame(p.corpo, fg_color="transparent")
        vol.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(vol, text="", font=(ICO, 12), text_color=MUDO, width=22).pack(side="left")
        self.vol = ctk.CTkSlider(vol, from_=0, to=100, number_of_steps=50, height=14, button_length=0,
                                 button_color=LILAS, button_hover_color="#ffffff", progress_color=SPOTIFY_VERDE,
                                 fg_color=ROXO_ESCURO, command=self.mexeu_volume)
        self.vol.set(50)
        self.vol.pack(side="left", fill="x", expand=True, padx=(2, 6))
        self.lbl_vol = ctk.CTkLabel(vol, text="--", font=(MONO, 9), text_color=MUDO, width=30)
        self.lbl_vol.pack(side="left")

        # ----- direita: e-mail -----
        p = Painel(dir_c, "E-mail", "")
        p.pack(fill="x", pady=(10, 0))
        self.painel_mail = p
        ctk.CTkButton(p.direita, text="", width=22, height=18, fg_color="transparent", hover_color=PAINEL2,
                      text_color=ROXO_CLARO, font=(ICO, 10), command=self.mostrar_config_email).pack(side="right",
                                                                                                     padx=(6, 0))
        self.lista_mail = ctk.CTkFrame(p.corpo, fg_color="transparent")
        self.lista_mail.pack(fill="x")

        # ----- direita: notificações do Windows | registro (abas) -----
        p = Painel(dir_c, "Central", "")
        p.pack(fill="both", expand=True, pady=(10, 0))
        self.painel_central = p
        self.abas = ctk.CTkSegmentedButton(p.direita, values=["NOTIFICAÇÕES", "REGISTRO"], height=22,
                                           font=(MONO, 9, "bold"), fg_color=PAINEL2, selected_color=ROXO_ESCURO,
                                           selected_hover_color=ROXO_ESCURO, unselected_color=PAINEL2,
                                           unselected_hover_color=BORDA, text_color=LILAS,
                                           command=self.trocar_aba)
        self.abas.pack(side="right")
        self.abas.set("NOTIFICAÇÕES")
        self.aba_notif = ctk.CTkScrollableFrame(p.corpo, fg_color="transparent", scrollbar_button_color=BORDA,
                                                scrollbar_button_hover_color=ROXO_ESCURO)
        self.aba_notif.pack(fill="both", expand=True)
        self.aba_reg = ctk.CTkFrame(p.corpo, fg_color="transparent")
        topo_r = ctk.CTkFrame(self.aba_reg, fg_color="transparent", height=0)
        topo_r.pack(fill="x")
        ctk.CTkButton(topo_r, text="LIMPAR", width=50, height=18, fg_color="transparent", hover_color=PAINEL2,
                      text_color=APAGADO, font=(MONO, 9), command=self.limpar_hist).pack(side="right")
        self.hist = ctk.CTkTextbox(self.aba_reg, fg_color=PAINEL, font=(MONO, 11), text_color=LILAS, wrap="word",
                                   border_width=0)
        self.hist.pack(fill="both", expand=True)
        tb = self.hist._textbox
        tb.tag_config("hora", foreground=APAGADO)
        tb.tag_config("voce", foreground="#ffffff", font=(MONO, 11, "bold"))
        tb.tag_config("acao", foreground=ROXO_CLARO)
        tb.tag_config("resp", foreground=ROSA)
        tb.tag_config("erro", foreground=VERMELHO)
        tb.tag_config("alerta", foreground=AMBAR, font=(MONO, 11, "bold"))
        tb.tag_config("info", foreground=MUDO)
        self.hist.configure(state="disabled")
        self.add_hist("acao", "INICIALIZAÇÃO COMPLETA")
        self.add_hist("info", "Segure a tecla, clique no núcleo ou digite um comando. Clique em ? para exemplos.")
        self._desenhar_apps()
        self._desenhar_email()
        self._desenhar_notif()
        self._desenhar_dl()

    def _mini(self, master, rot, val):
        f = ctk.CTkFrame(master, fg_color=PAINEL2, border_color=BORDA, border_width=1, corner_radius=4)
        f.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkLabel(f, text=rot, font=(MONO, 9), text_color=MUDO, height=12).pack(anchor="w", padx=8, pady=(6, 0))
        lbl = ctk.CTkLabel(f, text=val, font=(MONO, 12, "bold"), text_color=ROXO_CLARO, height=18)
        lbl.pack(anchor="w", padx=8, pady=(0, 6))
        return lbl

    def _tile(self, master, glifo, rotulo, acao, imagem=None):
        """Quadradinho clicável: ícone em cima, nome embaixo."""
        f = ctk.CTkFrame(master, fg_color=PAINEL2, border_color=BORDA, border_width=1, corner_radius=4, height=52,
                         cursor="hand2")
        f.pack_propagate(False)
        if imagem is not None:
            ic = ctk.CTkLabel(f, text="", image=imagem, height=26, cursor="hand2")
        else:
            ic = ctk.CTkLabel(f, text=glifo, font=(ICO, 15), text_color=ROXO_CLARO, height=24, cursor="hand2")
        ic.pack(pady=(5, 0))
        tx = ctk.CTkLabel(f, text=rotulo, font=(MONO, 9), text_color=LILAS, height=14, cursor="hand2")
        tx.pack()

        def entrar(_):
            f.configure(fg_color=ROXO_ESCURO, border_color=ROXO)

        def sair(_):
            f.configure(fg_color=PAINEL2, border_color=BORDA)
        for w in (f, ic, tx):
            w.bind("<Button-1>", lambda e: acao())
            w.bind("<Enter>", entrar)
            w.bind("<Leave>", sair)
        return f

    def _card(self, master, col, glifo, titulo, valor, sub, acao):
        f = ctk.CTkFrame(master, fg_color=PAINEL, border_color=BORDA, border_width=1, corner_radius=6,
                         cursor="hand2")
        f.grid(row=0, column=col, sticky="nsew", padx=4)
        topo = ctk.CTkFrame(f, fg_color="transparent")
        topo.pack(fill="x", padx=10, pady=(7, 0))
        ctk.CTkLabel(topo, text=glifo, font=(ICO, 11), text_color=ROXO, width=16, height=14).pack(side="left")
        ctk.CTkLabel(topo, text=titulo, font=(MONO, 9), text_color=MUDO, height=14).pack(side="left", padx=(4, 0))
        v = ctk.CTkLabel(f, text=valor, font=(SANS, 13, "bold"), text_color=LILAS, anchor="w", height=20)
        v.pack(fill="x", padx=10)
        s_ = ctk.CTkLabel(f, text=sub, font=(SANS, 10), text_color=MUDO, anchor="w", height=14)
        s_.pack(fill="x", padx=10, pady=(0, 7))
        for w in (f, topo, v, s_):
            w.bind("<Button-1>", lambda e: acao())
        return v, s_

    def _atualizar_dica(self):
        self.lbl_dica.configure(text=f"SEGURE [{self.cfg['tecla'].upper()}] • CLIQUE NO NÚCLEO • FUNCIONA MINIMIZADO")

    # ---------------- ações ----------------
    def clicou_mic(self):
        if self.motor.gravando():
            self.motor.soltar()
        else:
            self.motor.comecar()

    def enviou_texto(self, _=None):
        txt = self.entrada.get().strip()
        if not txt:
            return
        self.entrada.delete(0, "end")
        self.rodar_comando(txt)

    def rodar_comando(self, txt):
        def rodar():
            print(f'Você disse: "{txt}"')
            FILA.put(("status", "processando"))
            try:
                av.executar(txt)
                FILA.put(("status", "pronto"))
            except Exception as e:
                print("  Erro ao executar:", e)
                FILA.put(("status", "erro"))
        threading.Thread(target=rodar, daemon=True).start()

    def trocar_maos_livres(self):
        ligar = bool(self.sw_ml.get())
        self.cfg["maos_livres"] = ligar
        salvar_config(self.cfg)
        self.motor.ligar_maos_livres(ligar)

    def controle_spotify(self, acao):
        if acao == "abrir":
            if not av.focar_janela("Spotify"):
                try:
                    os.startfile("spotify:")
                except OSError:
                    pass
            return

        def run():
            try:
                if acao == "curtir":
                    print("  -> Spotify: " + spotify_api.curtir_atual(not self.player.get("curtida")))
                    self._curtida_id = None
                elif acao == "aleatorio":
                    print("  -> Spotify: " + spotify_api.aleatorio(not self.sp_estado["shuffle"]))
                elif acao == "repetir":
                    prox = {"off": "context", "context": "track", "track": "off"}[self.sp_estado["repeat"]]
                    print("  -> Spotify: " + spotify_api.repetir(prox))
                elif acao == "pausa_play":
                    c = spotify_api.conectar().current_playback()
                    spotify_api.controle("pausa" if c and c.get("is_playing") else "continua")
                else:
                    spotify_api.controle(acao)
                time.sleep(0.6)
                self._atualizar_tocando()
            except Exception:
                import keyboard
                keyboard.send({"anterior": "previous track", "proxima": "next track"}.get(acao, "play/pause media"))
        threading.Thread(target=run, daemon=True).start()

    def pular_para(self, frac):
        dur = self.player.get("duracao") or 0
        if not dur:
            return
        ms = int(frac * dur)
        self.player["progresso"] = ms
        self._player_t = time.time()
        self.progresso.definir(frac)

        def run():
            try:
                sp = spotify_api.conectar()
                sp.seek_track(ms)
            except Exception as e:
                print("  Erro no Spotify:", e)
        threading.Thread(target=run, daemon=True).start()

    def mexeu_volume(self, v):
        v = int(v)
        self.lbl_vol.configure(text=f"{v}%")
        self._vol_mexido = time.time()
        if getattr(self, "_vol_job", None):
            self.after_cancel(self._vol_job)

        def aplicar():
            self._vol_job = None
            threading.Thread(target=lambda: self._tentar(spotify_api.mudar_volume, v), daemon=True).start()
        self._vol_job = self.after(350, aplicar)

    @staticmethod
    def _tentar(fn, *a):
        try:
            fn(*a)
        except Exception as e:
            print("  Erro no Spotify:", e)

    # ---------------- apps recentes ----------------
    def _desenhar_apps(self):
        for w in self.grade_apps.winfo_children():
            w.destroy()
        self._img_apps = []
        lista = self.recentes.lista[:8]
        if not lista:
            ctk.CTkLabel(self.grade_apps, text="Os programas que você usar aparecem aqui.", font=(MONO, 10),
                         text_color=APAGADO).grid(row=0, column=0, columnspan=4, sticky="w")
            return
        for k, it in enumerate(lista):
            img = px.icone_exe(it["exe"], 32)
            ci = ctk.CTkImage(img, size=(24, 24)) if img is not None else None
            self._img_apps.append(ci)
            nome = it["nome"] if len(it["nome"]) <= 11 else it["nome"][:10] + "…"
            t = self._tile(self.grade_apps, "\uE71D", nome, lambda e=it["exe"]: px.abrir_ou_focar(e), ci)
            t.grid(row=k // 4, column=k % 4, sticky="ew", padx=2, pady=2)

    # ---------------- central: notificações | registro ----------------
    def trocar_aba(self, aba):
        # o quadro com rolagem fica dentro de outro quadro: é esse de fora que precisa sumir/aparecer
        notif = getattr(self.aba_notif, "_parent_frame", None) or self.aba_notif
        if aba == "REGISTRO":
            notif.pack_forget()
            self.aba_reg.pack(fill="both", expand=True)
        else:
            self.aba_reg.pack_forget()
            notif.pack(fill="both", expand=True)

    def _piscar(self, frame, de=None, para=PAINEL2, passos=14, k=0):
        """Item novo acende e vai apagando (deixa a tela viva sem gastar quase nada)."""
        de = de or ROXO_ESCURO
        try:
            frame.configure(fg_color=mix(de, para, k / passos))
        except Exception:
            return
        if k < passos:
            self.after(70, lambda: self._piscar(frame, de, para, passos, k + 1))

    def _icone_ctk(self, caminho, tam=22):
        if not caminho:
            return None
        img = px.icone_exe(caminho, 32)
        return ctk.CTkImage(img, size=(tam, tam)) if img is not None else None

    def _desenhar_notif(self):
        for w in self.aba_notif.winfo_children():
            w.destroy()
        n = self.notif
        self._img_notif = []
        if n.estado != "ok":
            msgs = {"iniciando": "Conectando às notificações do Windows…",
                    "instalando": "Preparando o leitor de notificações (só na primeira vez, leva ~1 min)…",
                    "sem_permissao": "O Windows não deixou o Jon ler as notificações.\nLigue em Configurações → "
                                     "Privacidade → Notificações → “Permitir que os aplicativos acessem suas "
                                     "notificações”.",
                    "erro": "Não consegui ler as notificações: " + n.detalhe}
            ctk.CTkLabel(self.aba_notif, text=msgs.get(n.estado, ""), font=(SANS, 11), text_color=MUDO,
                         justify="left", anchor="w", wraplength=300).pack(fill="x", pady=(4, 6))
            if n.estado == "sem_permissao":
                ctk.CTkButton(self.aba_notif, text="ABRIR CONFIGURAÇÕES", height=26, fg_color=PAINEL2, border_width=1,
                              border_color=BORDA, hover_color=ROXO_ESCURO, text_color=ROXO_CLARO,
                              font=(MONO, 10, "bold"),
                              command=lambda: os.startfile("ms-settings:privacy-notifications")).pack(fill="x")
            self.painel_central.etiqueta.configure(text="")
            return
        novas = {x["id"] for x in n.novas}
        self.painel_central.etiqueta.configure(text=f"{len(n.itens)}" if n.itens else "", text_color=ROSA)
        if not n.itens:
            ctk.CTkLabel(self.aba_notif, text="Nenhuma notificação. Tudo em dia ✓", font=(SANS, 11),
                         text_color=MUDO, anchor="w").pack(fill="x", pady=4)
            return
        for it in n.itens[:12]:
            f = ctk.CTkFrame(self.aba_notif, fg_color=PAINEL2, corner_radius=6)
            f.pack(fill="x", pady=2, padx=(0, 4))
            ic = self._icone_ctk(px.exe_por_nome_app(it["app"]))
            self._img_notif.append(ic)
            if ic is not None:
                ctk.CTkLabel(f, text="", image=ic, width=26).pack(side="left", padx=(8, 4), anchor="n", pady=8)
            else:
                ctk.CTkLabel(f, text=(it["app"][:1] or "?").upper(), width=24, height=24, corner_radius=12,
                             fg_color=ROXO_ESCURO, text_color=LILAS, font=(MONO, 11, "bold")).pack(
                    side="left", padx=(8, 4), anchor="n", pady=8)
            corpo = ctk.CTkFrame(f, fg_color="transparent")
            corpo.pack(side="left", fill="both", expand=True, padx=(2, 8), pady=4)
            l1 = ctk.CTkFrame(corpo, fg_color="transparent")
            l1.pack(fill="x")
            ctk.CTkLabel(l1, text=it["app"].upper()[:20], font=(MONO, 9), text_color=ROXO_CLARO, height=14,
                         anchor="w").pack(side="left")
            mins = int((time.time() - it["ts"]) // 60)
            quando = "agora" if mins < 1 else f"{mins} min" if mins < 60 else \
                time.strftime("%H:%M", time.localtime(it["ts"]))
            ctk.CTkLabel(l1, text=quando, font=(MONO, 9), text_color=APAGADO, height=14).pack(side="right")
            ctk.CTkLabel(corpo, text=it["titulo"][:40], font=(SANS, 11, "bold"), text_color=LILAS, anchor="w",
                         height=16).pack(fill="x")
            if it["texto"]:
                ctk.CTkLabel(corpo, text=it["texto"][:110], font=(SANS, 10), text_color=MUDO, anchor="w",
                             justify="left", wraplength=250).pack(fill="x")
            if it["id"] in novas:
                self._piscar(f)
        if n.novas:
            n.novas = []

    def _desenhar_dl(self):
        for w in self.lista_dl.winfo_children():
            w.destroy()
        d = self.downloads
        self._img_dl = []
        self.painel_dl.etiqueta.configure(text=f"↓ {len(d.ativos)} BAIXANDO" if d.ativos else "",
                                          text_color=self.acento)
        for it in d.ativos[:3]:
            f = ctk.CTkFrame(self.lista_dl, fg_color=PAINEL2, corner_radius=6)
            f.pack(fill="x", pady=2)
            l1 = ctk.CTkFrame(f, fg_color="transparent")
            l1.pack(fill="x", padx=8, pady=(5, 0))
            ctk.CTkLabel(l1, text="\uE896", font=(ICO, 11), text_color=self.acento, width=16,
                         height=16).pack(side="left")
            ctk.CTkLabel(l1, text=it["nome"][:30], font=(SANS, 11, "bold"), text_color=LILAS, anchor="w",
                         height=16).pack(side="left", padx=(4, 0))
            vel = f"{px.humano(it['vel'])}/s" if it["vel"] > 0 else "aguardando…"
            info = f"{it['origem']} • {px.humano(it['feito'])}"
            if it["frac"] is not None:
                info += f" de {px.humano(it['total'])} • {it['frac'] * 100:.0f}%"
            ctk.CTkLabel(f, text=f"{info}  •  {vel}", font=(MONO, 9), text_color=MUDO, anchor="w",
                         height=14).pack(fill="x", padx=8)
            barra = ctk.CTkProgressBar(f, height=4, corner_radius=2, fg_color=ROXO_ESCURO,
                                       progress_color=self.acento,
                                       mode="determinate" if it["frac"] is not None else "indeterminate")
            barra.pack(fill="x", padx=8, pady=(3, 7))
            if it["frac"] is not None:
                barra.set(it["frac"])
            else:
                barra.configure(indeterminate_speed=0.6)
                barra.start()
        if d.recentes:
            ctk.CTkLabel(self.lista_dl, text="ÚLTIMOS BAIXADOS", font=(MONO, 9), text_color=APAGADO, anchor="w",
                         height=14).pack(fill="x", pady=(4 if d.ativos else 0, 2))
        for it in d.recentes[: (4 if not d.ativos else 2)]:
            f = ctk.CTkFrame(self.lista_dl, fg_color="transparent", cursor="hand2")
            f.pack(fill="x", pady=1)
            ic = self._icone_ctk(it["caminho"], 18)
            self._img_dl.append(ic)
            a = ctk.CTkLabel(f, text="" if ic else "\uE8A5", image=ic, font=(ICO, 11), text_color=MUDO, width=22,
                             height=20)
            a.pack(side="left")
            b = ctk.CTkLabel(f, text=it["nome"][:30], font=(SANS, 11), text_color=LILAS, anchor="w", height=20)
            b.pack(side="left", padx=(4, 0))
            mins = int((time.time() - it["ts"]) // 60)
            c = ctk.CTkLabel(f, text=f"{mins} min" if mins < 60 else (f"{mins // 60} h" if mins < 1440 else
                                                                      f"{mins // 1440} d"),
                             font=(MONO, 9), text_color=APAGADO, height=20)
            c.pack(side="right")
            for w in (f, a, b, c):
                w.bind("<Button-1>", lambda e, cam=it["caminho"]: __import__("subprocess").Popen(
                    ["explorer", "/select,", cam]))
        if not d.ativos and not d.recentes:
            ctk.CTkLabel(self.lista_dl, text="Nada baixando. Downloads do navegador, uTorrent, Hydra\ne Steam "
                                             "aparecem aqui com a velocidade.", font=(MONO, 10), text_color=APAGADO,
                         justify="left", anchor="w").pack(fill="x")

    def _animar_vida(self):
        """Pequenas animações: marcadores respirando, logo pulsando, varredura no topo, equalizador."""
        self._fase_ui += 0.033
        t = self._fase_ui
        # varredura no topo (atravessa a tela a cada ~4 s)
        w = self.varredura.winfo_width()
        if w > 10:
            x = (t * 0.25 % 1.0) * (w + 300) - 150
            for k, it in enumerate(self._var_itens):
                larg = 150 - k * 20
                self.varredura.coords(it, x - larg, 1, x + larg, 1)
        # a cada 3 quadros: cores que respiram
        self._quadro_ui = getattr(self, "_quadro_ui", 0) + 1
        if self._quadro_ui % 3 == 0:
            for k, m in enumerate(Painel.marcas):
                try:
                    m.configure(text_color=mix(ROXO_ESCURO, ROXO_CLARO, 0.5 + 0.5 * math.sin(t * 2.2 - k * 0.7)))
                except Exception:
                    pass
            self.lbl_logo.configure(text_color=mix(ROXO, ROSA, 0.5 + 0.5 * math.sin(t * 1.6)))
        # equalizador do Spotify
        tocando = self.player.get("tocando")
        for k, b in enumerate(self._eq_barras):
            if tocando:
                h = 3 + 10 * abs(math.sin(t * (5.1 + k * 1.7) + k * 1.3)) * (0.6 + 0.4 * math.sin(t * 2.3 + k))
            else:
                h = 2
            self.eq.coords(b, k * 5, 14 - h, k * 5 + 3, 14)

    def _aplicar_acento(self, cor):
        self.acento = cor
        self.progresso.itemconfig(self.progresso.barra, fill=cor)
        self.vol.configure(progress_color=cor)
        self.lbl_device.configure(text_color=cor)
        for b in self._eq_barras:
            self.eq.itemconfig(b, fill=cor)
        self.bt_sp["pausa_play"].configure(fg_color=cor, hover_color=mix(cor, "#ffffff", 0.3))

    # ---------------- e-mail ----------------
    def clicou_card_email(self):
        if self.email_cfg:
            import webbrowser
            webbrowser.open(px.link_caixa(self.email_cfg))
        else:
            self.mostrar_config_email()

    def _desenhar_email(self):
        for w in self.lista_mail.winfo_children():
            w.destroy()
        d = px.ultimo_email
        if not self.email_cfg:
            self.painel_mail.etiqueta.configure(text="DESCONECTADO")
            ctk.CTkLabel(self.lista_mail, text="Veja aqui os e-mails novos (Gmail, Outlook…).", font=(SANS, 11),
                         text_color=MUDO, anchor="w").pack(fill="x")
            ctk.CTkButton(self.lista_mail, text="CONECTAR E-MAIL", height=26, corner_radius=4, fg_color=PAINEL2,
                          border_width=1, border_color=BORDA, hover_color=ROXO_ESCURO, text_color=ROXO_CLARO,
                          font=(MONO, 10, "bold"), command=self.mostrar_config_email).pack(fill="x", pady=(6, 0))
            self.card_mail[0].configure(text="não conectado")
            self.card_mail[1].configure(text="clique para conectar")
            return
        if d["erro"] and d["total"] is None:
            self.painel_mail.etiqueta.configure(text="ERRO")
            ctk.CTkLabel(self.lista_mail, text=d["erro"], font=(SANS, 11), text_color=VERMELHO, anchor="w",
                         justify="left", wraplength=280).pack(fill="x")
            self.card_mail[0].configure(text="erro no e-mail")
            self.card_mail[1].configure(text="confira a senha de app")
            return
        if d["total"] is None:
            self.painel_mail.etiqueta.configure(text="LENDO…")
            return
        n = d["total"]
        self.painel_mail.etiqueta.configure(text=f"{n} NÃO LIDO{'S' if n != 1 else ''}",
                                            text_color=ROSA if n else APAGADO)
        self.card_mail[0].configure(text=f"{n} não lido{'s' if n != 1 else ''}" if n else "caixa em dia")
        self.card_mail[1].configure(text=(d["itens"][0]["de"][:26] if d["itens"] else self.email_cfg["email"][:26]))
        if not d["itens"]:
            ctk.CTkLabel(self.lista_mail, text="Nenhum e-mail novo. ✓", font=(SANS, 11), text_color=MUDO,
                         anchor="w").pack(fill="x")
        link = px.link_caixa(self.email_cfg)
        for it in d["itens"][:3]:
            f = ctk.CTkFrame(self.lista_mail, fg_color=PAINEL2, corner_radius=4, cursor="hand2")
            f.pack(fill="x", pady=2)
            l1 = ctk.CTkFrame(f, fg_color="transparent")
            l1.pack(fill="x", padx=8, pady=(4, 0))
            a = ctk.CTkLabel(l1, text=it["de"][:26], font=(SANS, 11, "bold"), text_color=LILAS, anchor="w", height=16)
            a.pack(side="left")
            b = ctk.CTkLabel(l1, text=it["quando"], font=(MONO, 9), text_color=APAGADO, height=16)
            b.pack(side="right")
            c = ctk.CTkLabel(f, text=it["assunto"][:44], font=(SANS, 10), text_color=MUDO, anchor="w", height=15)
            c.pack(fill="x", padx=8, pady=(0, 4))
            import webbrowser
            for w in (f, l1, a, b, c):
                w.bind("<Button-1>", lambda e: webbrowser.open(link))

    def mostrar_config_email(self):
        j = ctk.CTkToplevel(self)
        j.title("Conectar e-mail")
        j.geometry("460x470")
        j.configure(fg_color=BG)
        j.transient(self)
        j.after(100, j.lift)
        ctk.CTkLabel(j, text="CONECTAR E-MAIL", font=(MONO, 14, "bold"), text_color=ROXO_CLARO).pack(pady=(16, 6))
        ctk.CTkLabel(j, text=("O Jon só LÊ quem mandou e o assunto dos e-mails não lidos (não marca como lido, "
                              "não apaga e não envia nada). A senha fica só neste PC, no arquivo email_config.json.\n\n"
                              "Gmail: use uma SENHA DE APP (não a sua senha normal):\n"
                              "1. Ative a verificação em duas etapas na conta Google.\n"
                              "2. Clique no botão abaixo, crie uma senha de app chamada \"Jon\".\n"
                              "3. Cole aqui os 16 caracteres que o Google mostrar."),
                     font=(SANS, 11), text_color=MUDO, wraplength=410, justify="left").pack(padx=20)
        import webbrowser
        ctk.CTkButton(j, text="ABRIR PÁGINA DE SENHAS DE APP DO GOOGLE", height=28, fg_color=PAINEL2, border_width=1,
                      border_color=BORDA, hover_color=ROXO_ESCURO, text_color=ROXO_CLARO, font=(MONO, 10, "bold"),
                      command=lambda: webbrowser.open("https://myaccount.google.com/apppasswords")).pack(pady=10)
        e1 = ctk.CTkEntry(j, placeholder_text="seu e-mail (ex.: voce@gmail.com)", width=400, height=34,
                          fg_color=PAINEL, border_color=BORDA, text_color=LILAS)
        e1.pack(pady=4)
        e2 = ctk.CTkEntry(j, placeholder_text="senha de app (16 letras)", show="•", width=400, height=34,
                          fg_color=PAINEL, border_color=BORDA, text_color=LILAS)
        e2.pack(pady=4)
        if self.email_cfg:
            e1.insert(0, self.email_cfg["email"])
        msg = ctk.CTkLabel(j, text="", font=(SANS, 11), text_color=MUDO, wraplength=410)
        msg.pack(pady=6)

        def salvar():
            end, senha = e1.get().strip(), e2.get().strip()
            if "@" not in end or len(senha.replace(" ", "")) < 8:
                msg.configure(text="Preencha o e-mail e a senha de app.", text_color=VERMELHO)
                return
            msg.configure(text="Testando…", text_color=MUDO)

            def testar():
                cfg = {"email": end, "senha_app": senha.replace(" ", ""),
                       "servidor": px.SERVIDORES.get(end.split("@")[-1].lower(), "imap." + end.split("@")[-1])}
                try:
                    px.ler_nao_lidos(cfg, 1)
                    px.salvar_email(end, senha)
                    self.email_cfg = px.carregar_email()
                    self.email_uids = None
                    j.after(0, lambda: (msg.configure(text="Conectado! ✓", text_color=VERDE),
                                        j.after(900, j.destroy)))
                    self._checar_email_agora.set()
                except Exception as ex:
                    t = str(ex)
                    if "AUTHENTICATIONFAILED" in t.upper() or "invalid credentials" in t.lower():
                        t = "E-mail ou senha de app incorretos."
                    j.after(0, lambda: msg.configure(text="Não conectou: " + t[:120], text_color=VERMELHO))
            threading.Thread(target=testar, daemon=True).start()
        ctk.CTkButton(j, text="SALVAR E TESTAR", height=32, fg_color=ROXO, hover_color=ROXO_CLARO,
                      text_color="#0b0716", font=(MONO, 11, "bold"), command=salvar).pack(pady=(4, 6))
        if self.email_cfg:
            def desconectar():
                try:
                    os.remove(px.ARQ_EMAIL)
                except OSError:
                    pass
                self.email_cfg = None
                px.ultimo_email.update({"total": None, "itens": [], "erro": ""})
                self._desenhar_email()
                j.destroy()
            ctk.CTkButton(j, text="desconectar", height=22, fg_color="transparent", hover_color=PAINEL2,
                          text_color=APAGADO, font=(MONO, 9), command=desconectar).pack()

    def _vigiar_email(self):
        while True:
            cfg = self.email_cfg
            if cfg:
                try:
                    r = px.ler_nao_lidos(cfg, 4)
                    novos = []
                    uids = {i["uid"] for i in r["itens"]}
                    if self.email_uids is not None:
                        novos = [i for i in r["itens"] if i["uid"] not in self.email_uids]
                    self.email_uids = (self.email_uids or set()) | uids
                    px.ultimo_email.update({"total": r["total"], "itens": r["itens"], "erro": ""})
                    for i in reversed(novos):
                        print(f"✉ Novo e-mail de {i['de']}: {i['assunto']}")
                except Exception as e:
                    t = str(e)
                    if "AUTHENTICATIONFAILED" in t.upper() or "invalid credentials" in t.lower():
                        t = "E-mail ou senha de app incorretos — clique na engrenagem."
                    px.ultimo_email.update({"erro": "Não consegui ler: " + t[:100]})
                FILA.put(("email", None))
            self._checar_email_agora.wait(90 if getattr(self, "visivel", True) else 180)
            self._checar_email_agora.clear()

    def _vigiar_clima(self):
        while True:
            try:
                FILA.put(("clima", px.clima_curto()))
                time.sleep(1200)
            except Exception:
                time.sleep(120)

    def mostrar_janela(self):
        """Traz o Jon pra frente, maximizado, mesmo se outro programa estiver em foco."""
        try:
            self.deiconify()
            self.state("zoomed")
            hwnd = int(self.wm_frame(), 16)
            av.trazer_janela_pra_frente(hwnd, maximizar=True)
            self.attributes("-topmost", True)
            self.after(400, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except Exception as e:
            print("  (não consegui trazer a janela pra frente):", e)

    def _instalar_faltando(self):
        """Bibliotecas novas que vieram numa atualização (ex.: voz JARVIS = edge-tts): instala sozinho, uma vez."""
        if atualizador is not None:
            try:
                tirados = atualizador.limpar_ignorados()
                if tirados:
                    print("  -> Removi do Jon o que você não usa: " + ", ".join(tirados) + " (cópia em backups/removidos).")
            except Exception as e:
                print("  (não consegui limpar os arquivos ignorados:", e, ")")
        faltando = []
        for modulo, pacote in (("edge_tts", "edge-tts"),):
            try:
                __import__(modulo)
            except ImportError:
                faltando.append(pacote)
        if not faltando:
            return
        import subprocess
        py = sys.executable
        if py.lower().endswith("pythonw.exe"):
            py = py[:-len("pythonw.exe")] + "python.exe"
        print("  (instalando o que faltou na atualização: " + ", ".join(faltando) + "…)")
        r = subprocess.run([py, "-m", "pip", "install", "--quiet", *faltando], capture_output=True, text=True,
                           creationflags=0x08000000, timeout=600)
        print("  -> Voz JARVIS pronta." if r.returncode == 0 else
              "  (não consegui instalar: " + (r.stderr or r.stdout)[-200:] + ")")

    # ---------------- atualização pelo GitHub ----------------
    def _vigiar_atualizacao(self):
        """Confere o GitHub 20 s depois de abrir e depois a cada 3 horas."""
        if atualizador is None:
            return
        self._checar_agora = threading.Event()
        time.sleep(20)
        while True:
            try:
                r = atualizador.checar()
                print(f"  (atualização: GitHub {r['sha'][:7]} • instalado {atualizador.estado().get('sha', '')[:7]} • "
                      f"{'NOVA VERSÃO' if r['disponivel'] else 'em dia'})")
                FILA.put(("atualizacao", r))
            except Exception as e:
                print("  (atualização: não consegui olhar o GitHub:", e, ")")
                FILA.put(("atualizacao", {"erro": str(e)[:120]}))
            self._checar_agora.wait(3 * 3600)
            self._checar_agora.clear()

    def _mostrar_info_atualizacao(self, r, pedido=False):
        try:
            self._mostrar_info_atualizacao2(r, pedido)
        except Exception as e:
            print("  (atualização: erro ao mostrar:", e, ")")

    def _mostrar_info_atualizacao2(self, r, pedido=False):
        self._info_atualizacao = r
        if r.get("erro"):
            if pedido:
                self.add_hist("erro", "Não consegui olhar o GitHub agora: " + r["erro"])
            return
        if r["disponivel"]:
            self.bt_atualizar.pack(side="left", padx=(0, 8), before=self._primeiro_botao_topo)
            if getattr(self, "_avisado_sha", None) != r["sha"]:
                self._avisado_sha = r["sha"]
                self.add_hist("alerta", f"⬇ Atualização do Jon disponível: {r['mensagem']}  (clique em ATUALIZAÇÃO no topo)")
        else:
            self.bt_atualizar.pack_forget()
            if pedido:
                self.add_hist("acao", f"O Jon está atualizado (versão de {r['data']}).")
        if r.get("original_novo") and getattr(self, "_avisado_orig", None) != r.get("original_msg"):
            self._avisado_orig = r.get("original_msg")
            self.add_hist("info", f"Novidade no projeto original ({r['original']}): {r['original_msg']} — "
                                  f"abra github.com/{r['repo']} e clique em 'Sync fork' pra trazer pra você.")

    def mostrar_atualizacao(self):
        r = self._info_atualizacao or {}
        j = ctk.CTkToplevel(self)
        j.title("Atualizar o Jon")
        # sempre no meio da janela do Jon (senão pode abrir fora da tela / em outro monitor)
        x = self.winfo_rootx() + max(0, (self.winfo_width() - 460) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - 300) // 3)
        j.geometry(f"460x300+{x}+{y}")
        j.after(150, lambda: (j.lift(), j.focus_force(), j.attributes("-topmost", True),
                              j.after(600, lambda: j.attributes("-topmost", False))))
        j.configure(fg_color=BG)
        j.transient(self)
        j.after(120, j.lift)
        ctk.CTkLabel(j, text="⬇  NOVA VERSÃO DO JON", font=(MONO, 14, "bold"), text_color=ROXO_CLARO).pack(pady=(18, 6))
        ctk.CTkLabel(j, text=f"“{r.get('mensagem', '')}”\n{r.get('repo', '')} • {r.get('data', '')}", font=(SANS, 12),
                     text_color=LILAS, wraplength=410).pack(padx=20)
        ctk.CTkLabel(j, text="O Jon guarda uma cópia da versão atual (pasta backups), troca só o código e reinicia "
                             "sozinho. Sua memória, configurações, e-mail e Spotify não são mexidos.",
                     font=(SANS, 11), text_color=MUDO, wraplength=410, justify="left").pack(padx=20, pady=12)
        msg = ctk.CTkLabel(j, text="", font=(SANS, 11), text_color=MUDO, wraplength=410)
        msg.pack()

        def instalar():
            msg.configure(text="Baixando e instalando…", text_color=MUDO)

            def rodar():
                try:
                    trocados = atualizador.aplicar(r.get("sha"))
                    print(f"  -> Jon atualizado ({len(trocados)} arquivos). Reiniciando…")
                    j.after(0, lambda: msg.configure(text="Pronto! Reiniciando o Jon…", text_color=VERDE))
                    atualizador.reiniciar_jon()
                    self.after(1200, self.sair)
                except Exception as e:
                    j.after(0, lambda: msg.configure(text="Não consegui atualizar: " + str(e)[:120],
                                                     text_color=VERMELHO))
            threading.Thread(target=rodar, daemon=True).start()
        ctk.CTkButton(j, text="ATUALIZAR AGORA", height=34, width=200, fg_color=ROXO, hover_color=ROXO_CLARO,
                      text_color="#0b0716", font=(MONO, 12, "bold"), command=instalar).pack(pady=(10, 4))
        ctk.CTkButton(j, text="depois", height=22, fg_color="transparent", hover_color=PAINEL2, text_color=APAGADO,
                      font=(MONO, 9), command=j.destroy).pack()

    def _vigiar_controle(self):
        """Start + Back (ou Menu + Visualizar) no controle abre o Big Picture de qualquer lugar."""
        c = Controle()
        while True:
            try:
                if self.bp is None and {"start", "back"} <= c.ler():
                    FILA.put(("bigpicture", True))
                    time.sleep(1.5)
            except Exception:
                pass
            time.sleep(0.25)

    def big_picture(self, abrir=True):
        if abrir and self.bp is None:
            try:
                self.deiconify()
            except Exception:
                pass
            self.bp = BigPicture(self)
            print("  -> modo Big Picture")
        elif not abrir and self.bp is not None:
            self.bp.fechar()

    def alternar_tela_cheia(self, _=None):
        cheia = not self.attributes("-fullscreen")
        self.attributes("-fullscreen", cheia)

    def limpar_hist(self):
        self.hist.configure(state="normal")
        self.hist.delete("1.0", "end")
        self.hist.configure(state="disabled")

    def sair(self):
        try:
            self.motor.desligar_tecla()
            self.motor.ligar_maos_livres(False)
        except Exception:
            pass
        self.destroy()
        os._exit(0)

    # ---------------- janelas extras ----------------
    def _janela(self, titulo, tam="440x560"):
        j = ctk.CTkToplevel(self)
        j.title(titulo)
        j.geometry(tam)
        j.configure(fg_color=BG)
        j.transient(self)
        try:
            j.after(250, lambda: j.iconbitmap(os.path.join(PASTA, "assistente.ico")))
        except Exception:
            pass
        sf = ctk.CTkScrollableFrame(j, fg_color=BG)
        sf.pack(fill="both", expand=True, padx=10, pady=10)
        return j, sf

    def _secao(self, sf, titulo, dica=""):
        ctk.CTkLabel(sf, text=titulo.upper(), font=(MONO, 13, "bold"), text_color=ROXO_CLARO).pack(anchor="w",
                                                                                                pady=(12, 0))
        if dica:
            ctk.CTkLabel(sf, text=dica, font=(SANS, 11), text_color=MUDO, wraplength=380, justify="left").pack(
                anchor="w", pady=(0, 4))

    def _item(self, sf, texto, ao_apagar=None):
        fr = ctk.CTkFrame(sf, fg_color=PAINEL, border_color=BORDA, border_width=1, corner_radius=4)
        fr.pack(fill="x", pady=2)
        ctk.CTkLabel(fr, text=texto, font=(SANS, 12), text_color=LILAS, wraplength=320, justify="left",
                     anchor="w").pack(side="left", padx=10, pady=6, fill="x", expand=True)
        if ao_apagar:
            ctk.CTkButton(fr, text="✕", width=28, height=24, fg_color="transparent", hover_color="#3a1d2a",
                          text_color=VERMELHO, command=ao_apagar).pack(side="right", padx=6)

    # ---------------- chat por texto com a IA ----------------
    def mostrar_chat(self, _=None):
        """Janela de conversa com barra lateral de Projetos e T?picos (estilo Antigravity / IDE)."""
        j = getattr(self, "_chat_janela", None)
        if j is not None and j.winfo_exists():
            j.lift()
            j.focus_force()
            self._chat_entrada.focus_set()
            return

        self._chat_topicos_dados = chat_topicos_mgr.carregar_dados()
        proj_ativo, top_ativo = chat_topicos_mgr.obter_topico_ativo(self._chat_topicos_dados)
        self._chat_hist = top_ativo.get("mensagens", [])
        self._chat_topico_id = top_ativo["id"]
        self._chat_fila = queue.Queue()
        self._chat_ocupado = False
        self._chat_imagens_pendentes = []

        j = ctk.CTkToplevel(self)
        self._chat_janela = j
        j.title("J O N ? Conversar com a IA")
        j.geometry("1020x820")
        j.minsize(780, 560)
        j.configure(fg_color=BG)
        j.after(150, j.lift)
        try:
            j.after(250, lambda: j.iconbitmap(os.path.join(PASTA, "assistente.ico")))
        except Exception:
            pass

        # ===== CORPO DIVIDIDO EM 2 COLUNAS =====
        # Lateral esquerda: Projetos / T?picos (estilo Antigravity)
        lat = ctk.CTkFrame(j, fg_color="#0e081c", width=260, corner_radius=0, border_color=BORDA, border_width=1)
        lat.pack(side="left", fill="y")
        lat.pack_propagate(False)

        lat_topo = ctk.CTkFrame(lat, fg_color="transparent", height=48)
        lat_topo.pack(fill="x", padx=10, pady=(10, 6))
        ctk.CTkLabel(lat_topo, text="Projects", font=(SANS, 14, "bold"), text_color="#ffffff").pack(side="left", padx=4)
        
        btn_novo = ctk.CTkButton(lat_topo, text="+ Novo", width=62, height=26, fg_color=ROXO, hover_color=ROXO_CLARO,
                                 text_color="#0b0716", font=(MONO, 10, "bold"), command=self._chat_novo_topico)
        btn_novo.pack(side="right")

        # Scrollable frame para lista de projetos e chats
        self._chat_lista_frame = ctk.CTkScrollableFrame(lat, fg_color="transparent", scrollbar_button_color=BORDA)
        self._chat_lista_frame.pack(fill="both", expand=True, padx=4, pady=4)

        # Lateral direita: ?rea da Conversa
        dir_frame = ctk.CTkFrame(j, fg_color=BG, corner_radius=0)
        dir_frame.pack(side="right", fill="both", expand=True)

        topo = ctk.CTkFrame(dir_frame, fg_color=PAINEL, border_color=BORDA, border_width=1, corner_radius=0, height=50)
        topo.pack(fill="x")
        topo.pack_propagate(False)
        ctk.CTkLabel(topo, text="?", font=(SANS, 18), text_color=ROXO).pack(side="left", padx=(14, 8))
        self._chat_titulo_label = ctk.CTkLabel(topo, text=top_ativo["titulo"].upper(), font=(MONO, 12, "bold"), text_color=LILAS)
        self._chat_titulo_label.pack(side="left")
        self._chat_status = ctk.CTkLabel(topo, text="", font=(MONO, 9), text_color=MUDO)
        self._chat_status.pack(side="left", padx=10)

        ctk.CTkButton(topo, text="LIMPAR", width=64, height=24, fg_color="transparent", border_width=1,
                      border_color=BORDA, hover_color=PAINEL2, text_color=ROXO_CLARO, font=(MONO, 9, "bold"),
                      command=self._chat_limpar).pack(side="right", padx=(4, 12))
        ctk.CTkButton(topo, text="?? ANALISAR PASTA", width=120, height=24, fg_color="transparent", border_width=1,
                      border_color=BORDA, hover_color=PAINEL2, text_color=LILAS, font=(MONO, 9, "bold"),
                      command=self._chat_selecionar_pasta).pack(side="right", padx=4)
        ctk.CTkButton(topo, text="?? ANEXAR FOTO", width=105, height=24, fg_color="transparent", border_width=1,
                      border_color=BORDA, hover_color=PAINEL2, text_color=LILAS, font=(MONO, 9, "bold"),
                      command=self._chat_anexar_foto).pack(side="right", padx=4)

        self._chat_txt = ctk.CTkTextbox(dir_frame, fg_color=BG, font=(SANS, 13), text_color=LILAS, wrap="word",
                                        border_width=0, scrollbar_button_color=BORDA,
                                        scrollbar_button_hover_color=ROXO_ESCURO)
        self._chat_txt.pack(fill="both", expand=True, padx=12, pady=(8, 4))
        tb = self._chat_txt._textbox
        tb.tag_config("quem_voce", foreground=ROSA, font=(MONO, 10, "bold"), spacing1=16)
        tb.tag_config("quem_jon", foreground=ROXO, font=(MONO, 10, "bold"), spacing1=16)
        tb.tag_config("voce", foreground="#ffffff", font=(SANS, 13), lmargin1=16, lmargin2=16, spacing1=4, spacing3=10)
        tb.tag_config("jon", foreground="#e2ddf7", font=(SANS, 13), lmargin1=16, lmargin2=16, spacing1=4, spacing3=10)
        tb.tag_config("codigo", foreground="#a6e22e", background="#120c24", font=(MONO, 11), lmargin1=24, lmargin2=24, spacing1=4, spacing3=6)
        tb.tag_config("info", foreground=MUDO, font=(SANS, 11, "italic"), lmargin1=16, lmargin2=16, spacing1=6)
        tb.tag_config("erro", foreground=VERMELHO, font=(SANS, 12), lmargin1=16, lmargin2=16)

        base = ctk.CTkFrame(dir_frame, fg_color=PAINEL, border_color=BORDA, border_width=1, corner_radius=6)
        base.pack(fill="x", padx=12, pady=(4, 10))
        self._chat_entrada = ctk.CTkTextbox(base, height=60, fg_color=PAINEL, border_width=0, text_color=LILAS,
                                            font=(SANS, 13), wrap="word")
        self._chat_entrada.pack(side="left", fill="both", expand=True, padx=(8, 4), pady=6)
        self._chat_bt = ctk.CTkButton(base, text="ENVIAR", width=84, height=40, fg_color=ROXO,
                                      hover_color=ROXO_CLARO, text_color="#0b0716", font=(MONO, 11, "bold"),
                                      command=self._chat_enviar)
        self._chat_bt.pack(side="right", padx=(4, 8), pady=6)
        ctk.CTkLabel(dir_frame, text="Enter = enviar  ?  Shift+Enter = nova linha", font=(MONO, 9),
                     text_color=APAGADO, height=12).pack(pady=(0, 6))

        def tecla_enter(e):
            if e.state & 0x1:
                return None
            self._chat_enviar()
            return "break"
        self._chat_entrada.bind("<Return>", tecla_enter)
        j.bind("<Escape>", lambda e: j.destroy())

        self._chat_renderizar_lateral()
        self._chat_carregar_historico_na_tela()
        if not ia_local.disponivel():
            self._chat_add("info", "A IA local est? desligada. Abra o Ollama (ou rode 3_baixar_ia.bat) e tente de novo.")
        self._chat_entrada.focus_set()
        self._chat_loop()

    def _chat_renderizar_lateral(self):
        """Desenha a lista de pastas e t?picos na barra lateral estilo Antigravity."""
        for w in self._chat_lista_frame.winfo_children():
            w.destroy()

        for proj in self._chat_topicos_dados.get("projetos", []):
            p_box = ctk.CTkFrame(self._chat_lista_frame, fg_color="transparent")
            p_box.pack(fill="x", pady=(8, 2), padx=2)
            ctk.CTkLabel(p_box, text=f"??  {proj['nome']}", font=(SANS, 12, "bold"),
                         text_color="#a09cb0", anchor="w").pack(side="left", padx=4)

            for top in proj.get("topicos", []):
                ativo = (top["id"] == self._chat_topico_id)
                cor_bg = "#22193b" if ativo else "transparent"
                cor_txt = "#ffffff" if ativo else "#62a0ea"
                btn_top = ctk.CTkButton(
                    self._chat_lista_frame,
                    text=f"    {top['titulo'][:26]}",
                    anchor="w",
                    fg_color=cor_bg,
                    hover_color="#1d1433",
                    text_color=cor_txt,
                    font=(SANS, 12, "bold" if ativo else "normal"),
                    height=28,
                    corner_radius=6,
                    command=lambda tid=top["id"]: self._chat_abrir_topico(tid)
                )
                btn_top.pack(fill="x", padx=6, pady=1)

    def _chat_abrir_topico(self, topico_id):
        if self._chat_ocupado:
            return
        self._chat_topicos_dados["ativo_id"] = topico_id
        chat_topicos_mgr.salvar_dados(self._chat_topicos_dados)
        _, top = chat_topicos_mgr.obter_topico_ativo(self._chat_topicos_dados)
        self._chat_topico_id = top["id"]
        self._chat_hist = top.get("mensagens", [])
        self._chat_titulo_label.configure(text=top["titulo"].upper())
        self._chat_renderizar_lateral()
        self._chat_carregar_historico_na_tela()

    def _chat_novo_topico(self):
        if self._chat_ocupado:
            return
        proj, top = chat_topicos_mgr.criar_topico(self._chat_topicos_dados, "Jon", "Nova Conversa")
        self._chat_topico_id = top["id"]
        self._chat_hist = []
        self._chat_titulo_label.configure(text=top["titulo"].upper())
        self._chat_renderizar_lateral()
        self._chat_carregar_historico_na_tela()

    def _chat_carregar_historico_na_tela(self):
        self._chat_txt.configure(state="normal")
        self._chat_txt.delete("1.0", "end")
        self._chat_txt.configure(state="disabled")
        if self._chat_hist:
            for msg in self._chat_hist:
                self._chat_add("voce" if msg.get("role") == "user" else "jon", msg.get("content", ""))
        else:
            nome = self.cfg.get("nome") or ""
            self._chat_add("jon", f"Oi{', ' + nome if nome else ''}! T?pico pronto. Pode me perguntar ou pedir o que quiser ? c?digo, tarefas, fotos, projetos?")

    def _chat_salvar_historico(self):
        chat_topicos_mgr.salvar_mensagens_topico(self._chat_topicos_dados, self._chat_topico_id, self._chat_hist)
        self._chat_renderizar_lateral()

    def _chat_anexar_foto(self):
        if self._chat_ocupado:
            return
        caminho = filedialog.askopenfilename(
            title="Selecione uma imagem ou foto",
            filetypes=[("Imagens", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"), ("Todos os arquivos", "*.*")]
        )
        if not caminho or not os.path.exists(caminho):
            return
        try:
            with open(caminho, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            if not hasattr(self, "_chat_imagens_pendentes"):
                self._chat_imagens_pendentes = []
            self._chat_imagens_pendentes.append(b64)
            nome_arq = os.path.basename(caminho)
            self._chat_add("info", f"?? Foto anexada: {nome_arq} (ser? enviada na sua pr?xima mensagem)")
        except Exception as e:
            self._chat_add("erro", f"Erro ao anexar foto: {e}")

    def _chat_selecionar_pasta(self):
        if self._chat_ocupado:
            return
        pasta = filedialog.askdirectory(title="Selecione a pasta do c?digo para o Jon analisar")
        if not pasta or not os.path.exists(pasta):
            return
        self._chat_add("info", f"?? Lendo e indexando pasta: {pasta} ...")
        self._chat_ocupado = True
        self._chat_status.configure(text="INDEXANDO C?DIGO?", text_color=ROXO_CLARO)

        def _ler():
            try:
                resumo_codigo = codigo_analisador.ler_codigo_completo(pasta)
                msg_sistema = {
                    "role": "user",
                    "content": f"[ARQUIVOS DO PROJETO CARREGADOS: {pasta}]\n\n" + resumo_codigo + "\n\nPor favor, analise a arquitetura e os arquivos acima."
                }
                self._chat_hist.append(msg_sistema)
                self._chat_salvar_historico()
                self._chat_fila.put(("fim", f"Analisei todos os arquivos de `{os.path.basename(pasta)}` com sucesso, senhor. J? memorizei a estrutura e o c?digo do projeto. O que gostaria que eu fizesse ou criasse nele?"))
            except Exception as e:
                self._chat_fila.put(("erro", f"Erro ao analisar pasta: {e}"))
        threading.Thread(target=_ler, daemon=True).start()

    def _chat_limpar(self):
        if self._chat_ocupado:
            return
        self._chat_hist = []
        self._chat_imagens_pendentes = []
        self._chat_salvar_historico()
        self._chat_txt.configure(state="normal")
        self._chat_txt.delete("1.0", "end")
        self._chat_txt.configure(state="disabled")
        self._chat_add("info", "Conversa nova limpa.")

    def _chat_enviar(self):
        if self._chat_ocupado:
            return
        texto = self._chat_entrada.get("1.0", "end").strip()
        if not texto and not getattr(self, "_chat_imagens_pendentes", None):
            return
        self._chat_entrada.delete("1.0", "end")
        self._chat_add("voce", texto or "(imagem anexada)")
        
        msg_usuario = {"role": "user", "content": texto}
        if getattr(self, "_chat_imagens_pendentes", None):
            msg_usuario["images"] = list(self._chat_imagens_pendentes)
            self._chat_imagens_pendentes = []
            
        self._chat_hist.append(msg_usuario)
        self._chat_salvar_historico()
        # começa a resposta do Jon (vai sendo preenchida enquanto chega)
        tb = self._chat_txt._textbox
        self._chat_txt.configure(state="normal")
        tb.insert("end", "JON\n", "quem_jon")
        tb.mark_set("chat_resp", "end-1c")
        tb.mark_gravity("chat_resp", "left")
        tb.insert("end", "…\n", "jon")
        tb.see("end")
        self._chat_txt.configure(state="disabled")
        self._chat_ocupado = True
        self._chat_bt.configure(state="disabled", text="…")
        self._chat_status.configure(text="PENSANDO…", text_color=ROXO_CLARO)
        FILA.put(("status", "processando"))
        hist = list(self._chat_hist)
        fila = self._chat_fila

        def rodar():
            try:
                # Se for uma ordem direta pro PC (criar pasta/arquivo, otimizar, abrir, vscode, tocar, etc.), executa de verdade!
                f_norm = av.normalizar(texto)
                eh_acao = re.match(r"^(cria\w*|otimiza\w*|limpa\w*|libera\w*|esvazia\w*|organiza\w*|arruma\w*|abre\w*|abrir|vscode|vs code|fecha\w*|fechar|toca\w*|tocar|instala\w*|bloqueia\w*|minimiza\w*|tira\w* um print|processos pesados)", f_norm)
                if eh_acao:
                    r_exec = av.executar_remoto(texto, "pc")
                    resp_acao = r_exec.get("resposta") or "Pronto, senhor."
                    av.falar(resp_acao)
                    fila.put(("fim", "⚡ " + resp_acao))
                    return
                resp = ia_local.conversar(hist, lambda parcial: fila.put(("parcial", parcial)))
                fila.put(("fim", resp or "(sem resposta)"))
            except Exception as e:
                fila.put(("erro", f"Não consegui falar com a IA: {e}"))
        threading.Thread(target=rodar, daemon=True).start()

    def _chat_trocar_resposta(self, texto, tag="jon"):
        tb = self._chat_txt._textbox
        self._chat_txt.configure(state="normal")
        tb.delete("chat_resp", "end")
        tb.insert("end", (texto.strip() or "…") + "\n", tag)
        tb.see("end")
        self._chat_txt.configure(state="disabled")

    def _chat_loop(self):
        j = getattr(self, "_chat_janela", None)
        if j is None or not j.winfo_exists():
            return
        ultimo = None
        try:
            while True:
                tipo, val = self._chat_fila.get_nowait()
                if tipo == "parcial":
                    ultimo = val
                    continue
                ultimo = None
                if tipo == "fim":
                    self._chat_trocar_resposta(val)
                    self._chat_hist.append({"role": "assistant", "content": val})
                    self._chat_salvar_historico()
                else:
                    self._chat_trocar_resposta(val, "erro")
                    if self._chat_hist and self._chat_hist[-1]["role"] == "user":
                        self._chat_hist.pop()
                    self._chat_salvar_historico()
                self._chat_ocupado = False
                self._chat_bt.configure(state="normal", text="ENVIAR")
                self._chat_status.configure(text="")
                FILA.put(("status", "pronto"))
        except queue.Empty:
            pass
        if ultimo is not None:
            self._chat_trocar_resposta(ultimo)
            self._chat_status.configure(text="DIGITANDO…")
        j.after(50, self._chat_loop)

    def mostrar_exemplos(self):
        _, sf = self._janela("Comandos do Jon", "420x620")
        for grupo, frases in EXEMPLOS:
            self._secao(sf, grupo)
            for fr in frases:
                ctk.CTkLabel(sf, text=f"“{fr}”", font=(SANS, 13), text_color=LILAS, anchor="w").pack(anchor="w",
                                                                                                    padx=8)
        ctk.CTkLabel(sf, text="Também dá pra digitar qualquer um desses no terminal embaixo do núcleo.",
                     font=(SANS, 11), text_color=MUDO, wraplength=360, justify="left").pack(anchor="w", pady=14)

    def mostrar_config(self):
        j = ctk.CTkToplevel(self)
        j.title("Configurações do Jon")
        j.geometry("380x300")
        j.configure(fg_color=BG)
        j.transient(self)
        ctk.CTkLabel(j, text="CONFIGURAÇÕES", font=(MONO, 14, "bold"), text_color=ROXO_CLARO).pack(pady=(16, 10))
        l = ctk.CTkFrame(j, fg_color="transparent")
        l.pack(fill="x", padx=24, pady=6)
        ctk.CTkLabel(l, text="Tecla para falar", font=(SANS, 12), text_color=LILAS).pack(side="left")
        op = ctk.CTkOptionMenu(l, values=[t.upper() for t in TECLAS], width=130, fg_color=PAINEL2,
                               button_color=ROXO_ESCURO, button_hover_color=ROXO, dropdown_fg_color=PAINEL,
                               command=self.trocar_tecla)
        op.set(self.cfg["tecla"].upper())
        op.pack(side="right")
        chk_win = ctk.CTkSwitch(j, text="Abrir o Jon junto com o Windows", font=(SANS, 12), text_color=LILAS,
                                progress_color=ROXO, fg_color=ROXO_ESCURO)
        chk_win.pack(anchor="w", padx=24, pady=8)
        if atalhos.inicia_com_windows():
            chk_win.select()
        chk_win.configure(command=lambda: self.trocar_inicio(bool(chk_win.get())))
        chk_fala = ctk.CTkSwitch(j, text="Falar as respostas em voz alta", font=(SANS, 12), text_color=LILAS,
                                 progress_color=ROXO, fg_color=ROXO_ESCURO)
        chk_fala.pack(anchor="w", padx=24, pady=8)
        if self.cfg["falar"]:
            chk_fala.select()
        chk_fala.configure(command=lambda: self.trocar_fala(bool(chk_fala.get())))
        ctk.CTkButton(j, text="ABRIR PASTA DO JON", fg_color=PAINEL2, border_width=1, border_color=BORDA,
                      hover_color=ROXO_ESCURO, text_color=ROXO_CLARO, font=(MONO, 11, "bold"),
                      command=lambda: os.startfile(PASTA)).pack(pady=(16, 6))
        ctk.CTkButton(j, text="MEU PERFIL (NOME, CIDADE, SPOTIFY)", fg_color=PAINEL2, border_width=1,
                      border_color=BORDA, hover_color=ROXO_ESCURO, text_color=ROXO_CLARO, font=(MONO, 11, "bold"),
                      command=lambda: (j.destroy(), self.boas_vindas(False))).pack(pady=(0, 10))

    def boas_vindas(self, primeira=True):
        """Primeira vez (ou ⚙ > Meu perfil): nome, cidade e Spotify do dono deste Jon."""
        j = ctk.CTkToplevel(self)
        j.title("Bem-vindo ao Jon" if primeira else "Meu perfil")
        j.geometry("470x520")
        j.configure(fg_color=BG)
        j.transient(self)
        j.after(150, j.lift)
        ctk.CTkLabel(j, text="◆  BEM-VINDO AO JON" if primeira else "MEU PERFIL", font=(MONO, 15, "bold"),
                     text_color=ROXO_CLARO).pack(pady=(18, 4))
        ctk.CTkLabel(j, text="Só pra eu te conhecer. Dá pra mudar depois em ⚙ → Meu perfil.", font=(SANS, 11),
                     text_color=MUDO).pack()

        def campo(rotulo, dica, valor=""):
            ctk.CTkLabel(j, text=rotulo, font=(MONO, 10, "bold"), text_color=LILAS, anchor="w").pack(
                fill="x", padx=30, pady=(14, 2))
            e = ctk.CTkEntry(j, placeholder_text=dica, width=410, height=34, fg_color=PAINEL, border_color=BORDA,
                             text_color=LILAS)
            e.pack(padx=30)
            if valor:
                e.insert(0, valor)
            return e
        e_nome = campo("COMO EU TE CHAMO?", "seu nome", self.cfg.get("nome", ""))
        cid = (self.cfg.get("cidade") or {}).get("nome", "")
        e_cid = campo("SUA CIDADE (PRO CLIMA)", "ex.: Curitiba", cid)
        try:
            with open(os.path.join(PASTA, "spotify_client_id.txt"), encoding="utf-8") as f:
                sp_atual = f.read().strip()
        except OSError:
            sp_atual = ""
        e_sp = campo("SPOTIFY CLIENT ID (OPCIONAL — PRA TOCAR MÚSICA DIRETO)", "32 letras/números", sp_atual)
        import webbrowser
        ctk.CTkButton(j, text="COMO PEGAR O CLIENT ID DO SPOTIFY? (abre o site)", height=24, fg_color="transparent",
                      hover_color=PAINEL2, text_color=ROXO_CLARO, font=(MONO, 9, "bold"),
                      command=lambda: webbrowser.open("https://developer.spotify.com/dashboard")).pack(pady=(4, 0))
        ctk.CTkLabel(j, text="No site: Create app → Redirect URI: http://127.0.0.1:8888/callback → marque Web API "
                             "→ copie o Client ID. Precisa de Spotify Premium para tocar.",
                     font=(SANS, 10), text_color=APAGADO, wraplength=410, justify="left").pack(padx=30)
        msg = ctk.CTkLabel(j, text="", font=(SANS, 11), text_color=MUDO, wraplength=410)
        msg.pack(pady=6)

        def salvar():
            nome_, cidade_, sp = e_nome.get().strip(), e_cid.get().strip(), e_sp.get().strip()
            if not nome_:
                msg.configure(text="Me diz pelo menos o seu nome 🙂", text_color=VERMELHO)
                return
            if sp and not re.fullmatch(r"[0-9a-fA-F]{32}", sp):
                msg.configure(text="O Client ID do Spotify tem 32 letras e números.", text_color=VERMELHO)
                return
            msg.configure(text="Salvando…", text_color=MUDO)

            def rodar():
                import extras
                import perfil
                local = None
                if cidade_:
                    try:
                        local = extras._geocodificar(cidade_)
                    except Exception:
                        local = None
                    if not local:
                        j.after(0, lambda: msg.configure(text=f"Não achei a cidade “{cidade_}”. Confira o nome.",
                                                         text_color=VERMELHO))
                        return
                perfil.salvar(nome_, local)
                self.cfg["nome"] = nome_
                if local:
                    self.cfg["cidade"] = {"nome": local[0], "lat": local[1], "lon": local[2]}
                mudou_sp = sp != sp_atual
                if mudou_sp:
                    caminho = os.path.join(PASTA, "spotify_client_id.txt")
                    if sp:
                        with open(caminho, "w", encoding="utf-8") as f:
                            f.write(sp)
                    elif os.path.exists(caminho):
                        os.remove(caminho)
                    try:
                        os.remove(os.path.join(PASTA, ".spotify_token_cache"))
                    except OSError:
                        pass

                def pronto():
                    self.lbl_dono.configure(text=nome_.upper()[:18])
                    msg.configure(text=f"Prontinho, {nome_}! ✓" + ("  Feche e abra o Jon pra ligar o Spotify."
                                                                    if mudou_sp and sp else ""), text_color=VERDE)
                    j.after(2500 if mudou_sp else 1200, j.destroy)
                    threading.Thread(target=lambda: FILA.put(("clima", px.clima_curto())), daemon=True).start()
                j.after(0, pronto)
            threading.Thread(target=rodar, daemon=True).start()
        ctk.CTkButton(j, text="SALVAR", height=34, width=200, fg_color=ROXO, hover_color=ROXO_CLARO,
                      text_color="#0b0716", font=(MONO, 12, "bold"), command=salvar).pack(pady=(4, 10))

    def trocar_tecla(self, valor):
        tecla = valor.lower()
        try:
            self.motor.ligar_tecla(tecla)
        except Exception as e:
            self.add_hist("erro", f"Não consegui usar a tecla {valor}: {e}")
            return
        av.TECLA_FALAR = tecla
        self.cfg["tecla"] = tecla
        salvar_config(self.cfg)
        self._atualizar_dica()
        self.add_hist("acao", f"Tecla de falar agora é {valor}.")

    def trocar_inicio(self, ligar):
        try:
            atalhos.iniciar_com_windows(ligar)
            self.add_hist("acao", "Vai abrir junto com o Windows." if ligar else "Não abre mais com o Windows.")
        except Exception as e:
            self.add_hist("erro", f"Não consegui mudar: {e}")

    def trocar_fala(self, ligar):
        self.cfg["falar"] = ligar
        av.FALAR_RESPOSTAS = ligar
        salvar_config(self.cfg)

    def mostrar_memoria(self):
        j, sf = self._janela("Memória do Jon")

        def recarregar():
            for w in sf.winfo_children():
                w.destroy()
            m = ia_local.carregar_memoria()

            def salvar(fn):
                mm = ia_local.carregar_memoria()
                fn(mm)
                ia_local.salvar_memoria(mm)
                recarregar()

            self._secao(sf, "Apelidos", 'Ensine falando: "quando eu falar meu som, toca minhas músicas curtidas"')
            for k, v in m["apelidos"].items():
                self._item(sf, f"“{k}”  →  {v}", lambda k=k: salvar(lambda mm: mm["apelidos"].pop(k, None)))
            self._secao(sf, "Fatos sobre você", 'Ensine falando: "lembra que o jogo é o Assassin\'s Creed Shadows"')
            for fato in m["fatos"]:
                self._item(sf, fato, lambda fato=fato: salvar(
                    lambda mm: mm["fatos"].remove(fato) if fato in mm["fatos"] else None))
            self._secao(sf, "Atalhos aprendidos sozinho", "Frases que a IA resolveu 2x do mesmo jeito.")
            for k, v in m["aprendidos"].items():
                desc = v.get("acao", "") + (": " + v["texto"] if v.get("texto") else "")
                self._item(sf, f"“{k}”  →  {desc}", lambda k=k: salvar(lambda mm: mm["aprendidos"].pop(k, None)))
        recarregar()

    def mostrar_rotinas(self):
        j, sf = self._janela("Rotinas e lembretes do Jon")

        def recarregar():
            for w in sf.winfo_children():
                w.destroy()
            d = rotinas.carregar()

            def apagar(id_):
                rotinas.remover(id_)
                recarregar()
                self._atualizar_agenda()

            self._secao(sf, "Rotinas", 'Crie falando: "todo dia às 8 horas toca minhas músicas curtidas"')
            for r in d["rotinas"]:
                oque = r["comando"] or ("lembrar: " + r.get("lembrete", ""))
                self._item(sf, f"{rotinas.descrever_dias(r['dias'])} às {r['hora']}  →  {oque}",
                           lambda i=r["id"]: apagar(i))
            self._secao(sf, "Lembretes e timers", 'Crie falando: "me lembra em 10 minutos de tirar o bolo"')
            for x in sorted(d["lembretes"], key=lambda x: x["quando"]):
                self._item(sf, f"{rotinas._fmt_quando(x['quando'])}  →  {x['texto']}", lambda i=x["id"]: apagar(i))
            if not d["rotinas"] and not d["lembretes"]:
                ctk.CTkLabel(sf, text="Nada agendado ainda.", text_color=MUDO).pack(pady=20)
        recarregar()

    # ---------------- tarefas em segundo plano ----------------
    def _conectar_spotify(self):
        ok = av.conectar_spotify()
        FILA.put(("spotify", ok))
        while ok:
            self._atualizar_tocando()
            time.sleep(3 if getattr(self, "visivel", True) else 20)

    def _atualizar_tocando(self):
        try:
            sp = spotify_api.conectar()
            c = sp.current_playback()
            if c and c.get("item"):
                it = c["item"]
                imgs = it.get("album", {}).get("images") or []
                capa = (sorted(imgs, key=lambda i: abs((i.get("width") or 300) - 160))[0]["url"] if imgs else None)
                dev = c.get("device") or {}
                d = {"id": it.get("id"), "nome": it["name"], "artista": ", ".join(a["name"] for a in it["artists"][:2]),
                     "album": it.get("album", {}).get("name", ""), "capa": capa, "tocando": bool(c.get("is_playing")),
                     "progresso": c.get("progress_ms") or 0, "duracao": it.get("duration_ms") or 0,
                     "repeat": c.get("repeat_state", "off"), "shuffle": bool(c.get("shuffle_state")),
                     "volume": dev.get("volume_percent"), "device": dev.get("name", ""),
                     "device_tipo": dev.get("type", "")}
                if d["id"] and d["id"] != self._curtida_id:
                    try:
                        d["curtida"] = bool(sp.current_user_saved_tracks_contains([d["id"]])[0])
                        self._curtida_id = d["id"]
                    except Exception:
                        d["curtida"] = False
                else:
                    d["curtida"] = self.player.get("curtida", False)
                if capa and capa != self._capa_url:
                    self._capa_url = capa
                    threading.Thread(target=self._baixar_capa, args=(capa,), daemon=True).start()
            else:
                d = {}
            FILA.put(("player", d))
            if c:
                FILA.put(("sp_estado", {"repeat": c.get("repeat_state", "off"),
                                        "shuffle": bool(c.get("shuffle_state"))}))
        except Exception:
            pass

    def _baixar_capa(self, url):
        try:
            import io
            import urllib.request
            dados = urllib.request.urlopen(url, timeout=8).read()
            img = capa_arredondada(Image.open(io.BytesIO(dados)), 84)
            FILA.put(("capa", (url, img)))
        except Exception:
            pass

    def _checar_ia(self):
        ultimo = None
        while True:
            ok = ia_local.disponivel()
            estado_ia = (ok, ia_local.MODELO)
            if estado_ia != ultimo:
                FILA.put(("ia", ok))
                if ok:
                    ia_local.aquecer()
                ultimo = estado_ia
            time.sleep(10)

    def _ler_sistema(self):
        n = 0
        g = None
        while True:
            try:
                d = sistema.leitura()
                d["gpu"] = sistema.gpu()
                FILA.put(("stats", d))
                if n % 120 == 0:
                    for a in sistema.alertas(d):
                        FILA.put(("alerta", a))
            except Exception as e:
                print("  Erro lendo o sistema:", e)
            n += 1
            time.sleep(0.25 if getattr(self, "visivel", True) else 2.0)

    # ---------------- registro ----------------
    def add_hist(self, tipo, texto):
        self.hist.configure(state="normal")
        tb = self.hist._textbox
        tb.insert("end", "[" + time.strftime("%H:%M:%S") + "] ", "hora")
        tb.insert("end", texto + "\n", tipo)
        tb.see("end")
        self.hist.configure(state="disabled")

    def _tratar_linha(self, linha):
        l = linha.strip()
        if not l or l.startswith("=") or "Ouvindo..." in l or l.startswith("🧠") or l.startswith("(IA:") \
                or l.startswith("Conectando ao Spotify") or l.startswith("Spotify conectado") \
                or l.startswith("Jon ligado") or l.startswith('Diga "fechar'):
            return
        if l.startswith("Você disse (celular):"):
            self.add_hist("voce", "📱 " + l.split(":", 1)[1].strip().strip('"').upper())
            return
        if l.startswith("🔎") or l.startswith("(fonte:"):
            self.add_hist("info", l.strip("() "))
            return
        if l.startswith("Página do celular"):
            return
        if l.startswith("Você disse:"):
            self.add_hist("voce", "› " + l.split(":", 1)[1].strip().strip('"').upper())
        elif l.startswith("✉"):
            self.add_hist("alerta", l)
        elif l.startswith("🔔"):
            self.add_hist("alerta", l)
            self.after(10, self._atualizar_agenda)
            try:
                self.deiconify()
                self.lift()
            except Exception:
                pass
        elif l.startswith("💬"):
            self.add_hist("resp", l[1:].strip())
        elif l.startswith("->"):
            self.add_hist("acao", l[2:].strip())
            if "Spotify" in l and self.spotify_ok:
                threading.Thread(target=lambda: (time.sleep(0.8), self._atualizar_tocando()), daemon=True).start()
            if any(p in l for p in ("lembro", "Rotina", "Timer", "Cancelei")):
                self.after(300, self._atualizar_agenda)
        elif l.startswith(("Traceback", "File ", "HTTP Error")):
            return
        elif any(p in l for p in ("Erro", "erro", "Não entendi", "falhou", "Não consegui", "Exception")):
            self.add_hist("erro", l)
        else:
            self.add_hist("info", l.strip("() "))

    # ---------------- relógio, agenda e loop ----------------
    def _relogio(self):
        self.lbl_hora.configure(text=time.strftime("%H:%M:%S"))
        if self.bp is not None:
            try:
                self.bp.atualizar()
            except Exception as e:
                print("  (big picture):", e)
        if getattr(self, "visivel", True):
            self._tick_player()
            if self.recentes.mudou.is_set():
                self.recentes.mudou.clear()
                self._desenhar_apps()
                if self.bp is not None:
                    self.bp.desenhar_blocos()
            if self.notif.mudou.is_set():
                self.notif.mudou.clear()
                self._desenhar_notif()
                if self.bp is not None:
                    self.bp.desenhar_notifs()
            if self.downloads.mudou.is_set():
                self.downloads.mudou.clear()
                self._desenhar_dl()
                if self.bp is not None:
                    self.bp.desenhar_dl()
        self.after(500, self._relogio)

    def _tick_player(self):
        d = self.player
        if not d or not d.get("duracao"):
            return
        pos = d["progresso"] + ((time.time() - self._player_t) * 1000 if d.get("tocando") else 0)
        pos = min(pos, d["duracao"])
        self.progresso.definir(pos / d["duracao"])
        self._set(self.lbl_t0, text=_mmss(pos))
        self._set(self.lbl_t1, text=_mmss(d["duracao"]))

    def _mostrar_player(self, d):
        self.player = d
        self._player_t = time.time()
        if not d:
            self._set(self.lbl_musica, text="Nada tocando")
            self._set(self.lbl_artista, text="Peça uma música pro Jon")
            self._set(self.lbl_album, text="")
            self._set(self.lbl_device, text="")
            self.progresso.definir(0)
            self._set(self.lbl_t0, text="0:00")
            self._set(self.lbl_t1, text="0:00")
            self.bt_sp["pausa_play"].configure(text="\uE768")
            if self.capa_vazia is not None:
                self.lbl_capa.configure(image=self.capa_vazia)
                self._capa_url = None
            return
        nome = d["nome"] if len(d["nome"]) <= 30 else d["nome"][:29] + "…"
        self._set(self.lbl_musica, text=nome)
        self._set(self.lbl_artista, text=d["artista"][:36])
        self._set(self.lbl_album, text=d["album"][:40])
        tipo = {"Smartphone": "\uE8EA  ", "Computer": "\uE7F4  ", "Speaker": "\uE7F5  "}.get(d["device_tipo"], "")
        self._set(self.lbl_device, text=("TOCANDO EM " if d["tocando"] else "PAUSADO EM ") + d["device"].upper()[:22])
        self.painel_sp.etiqueta.configure(text="▶ TOCANDO" if d["tocando"] else "⏸ PAUSADO",
                                          text_color=SPOTIFY_VERDE if d["tocando"] else APAGADO)
        self.bt_sp["pausa_play"].configure(text="\uE769" if d["tocando"] else "\uE768")
        self.bt_sp["curtir"].configure(text="\uEB52" if d.get("curtida") else "\uEB51",
                                       text_color=self.acento if d.get("curtida") else LILAS)
        if d.get("volume") is not None and time.time() - self._vol_mexido > 3:
            self.vol.set(d["volume"])
            self._set(self.lbl_vol, text=f"{d['volume']}%")
        self._tick_player()

    def _agenda_tick(self):
        self._atualizar_agenda()
        self.after(30000, self._agenda_tick)

    def _atualizar_agenda(self):
        for w in self.agenda.winfo_children():
            w.destroy()
        itens = rotinas.proximos(4)
        if not itens:
            ctk.CTkLabel(self.agenda, text="Nada agendado. Diga “me lembra em 10 min de…”", font=(MONO, 10),
                         text_color=APAGADO, justify="left", anchor="w").pack(fill="x")
            self.card_prox[0].configure(text="nada agendado")
            self.card_prox[1].configure(text="peça um lembrete ao Jon")
            return
        for k, (ts, texto, _) in enumerate(itens):
            quando = dt.datetime.fromtimestamp(ts)
            hoje = quando.date() == dt.date.today()
            l = ctk.CTkFrame(self.agenda, fg_color="transparent")
            l.pack(fill="x")
            ctk.CTkLabel(l, text=quando.strftime("%H:%M") if hoje else quando.strftime("%d/%m %H:%M"),
                         font=(MONO, 10, "bold"), text_color=ROXO, width=78, anchor="w", height=18).pack(side="left")
            ctk.CTkLabel(l, text=texto[:34], font=(MONO, 10), text_color=LILAS, anchor="w", height=18).pack(side="left")
            if k == 0:
                falta = max(0, int((ts - time.time()) // 60))
                self.card_prox[0].configure(text=(texto.lstrip("⏰⏱ ")[:24] or "lembrete"))
                self.card_prox[1].configure(text=(f"em {falta} min" if falta < 60 else
                                                  quando.strftime("hoje às %H:%M") if hoje else
                                                  quando.strftime("%d/%m às %H:%M")))

    def _set(self, lbl, **kw):
        chave = id(lbl)
        if self._cache_lbl.get(chave) != kw:
            self._cache_lbl[chave] = kw
            lbl.configure(**kw)

    def _mostrar_stats(self, d):
        r = self.recursos
        r.definir("CPU", d["cpu"] / 100, f"{d['cpu']:.0f}%", d["cpu"] > 90)
        r.definir("Memória RAM", d["ram_pct"] / 100, f"{d['ram_usada']:.1f} / {d['ram_total']:.0f} GB", d["ram_pct"] > 90)
        g = d.get("gpu")
        if g:
            r.definir("Placa de vídeo", g["uso"] / 100, f"{g['uso']}%  •  {g['mem_usada']:.1f}/{g['mem_total']:.0f} GB")
            self._set(self.lbl_gpu_temp, text=f"{g['temp']} °C", text_color=VERMELHO if g["temp"] >= 83 else ROXO_CLARO)
        for disco in d["discos"]:
            r.definir(f"Disco {disco['letra']}:", disco["pct"] / 100, f"{disco['livre']:.0f} GB livres",
                      disco["letra"] == "C" and disco["livre"] < 10)
        self.grafico.adicionar(d["cpu"])
        self._set(self.lbl_rede, text=f"{d['down']:.1f} / {d['up']:.1f} MB/s")
        if self.bp is not None:
            self.bp.stats(d)
        al = sistema.alertas(d)
        self._set(self.lbl_sys, text="●  ATENÇÃO" if al else "●  ÓTIMO", text_color=AMBAR if al else ROXO_CLARO)

    def _loop(self):
        try:
            while True:
                tipo, val = FILA.get_nowait()
                if tipo == "linha":
                    self._tratar_linha(val)
                elif tipo == "status":
                    self.estado = val
                    self.nucleo.estado = val
                    if self.bp is not None:
                        self.bp.nucleo.estado = val
                    txt, _, cor = ESTADOS[val]
                    self.pilula.configure(text=f"🎙   {txt}…", text_color=cor,
                                          border_color=cor if val != "pronto" else ROXO_ESCURO)
                    if val == "erro":
                        self.after(2500, lambda: FILA.put(("status", "pronto")) if self.estado == "erro" else None)
                elif tipo == "spotify":
                    self.spotify_ok = val
                    self.painel_sp.etiqueta.configure(text="CONECTADO" if val else "SÓ PESQUISA (API DESLIGADA)",
                                                      text_color=SPOTIFY_VERDE if val else VERMELHO)
                elif tipo == "sp_estado":
                    self.sp_estado = val
                    r = val["repeat"]
                    self.bt_sp["repetir"].configure(text="\uE8ED" if r == "track" else "\uE8EE",
                                                    text_color=self.acento if r != "off" else LILAS)
                    self.bt_sp["aleatorio"].configure(text_color=self.acento if val["shuffle"] else LILAS)
                elif tipo == "player":
                    self._mostrar_player(val)
                elif tipo == "capa":
                    url, img = val
                    if url == self._capa_url:
                        self._img_capa = ctk.CTkImage(img, size=(84, 84))
                        self.lbl_capa.configure(image=self._img_capa, text="")
                        self._aplicar_acento(px.cor_dominante(img) or SPOTIFY_VERDE)
                        self._capa_pil = img
                elif tipo == "email":
                    self._desenhar_email()
                elif tipo == "atualizacao":
                    self._mostrar_info_atualizacao(val, getattr(self, "_pediu_checar", False))
                    self._pediu_checar = False
                elif tipo == "checar_atualizacao":
                    self._pediu_checar = True
                    if getattr(self, "_checar_agora", None):
                        self._checar_agora.set()
                elif tipo == "bigpicture":
                    self.big_picture(val)
                elif tipo == "clima":
                    self.clima_atual = val
                    self.card_clima[0].configure(text=f"{val['icone']}  {val['temp']}°  {val['cond']}"[:28])
                    self.card_clima[1].configure(text=f"mín {val['min']}° • máx {val['max']}° • chuva {val['chuva']}%")
                elif tipo == "ia":
                    self.ponto_ia.configure(text_color=VERDE if val else VERMELHO)
                    self.lbl_ia.configure(text=f"ATIVA • {ia_local.MODELO}" if val else "DESLIGADA — ABRA O OLLAMA")
                elif tipo == "janela":
                    self.mostrar_janela() if val == "mostrar" else self.iconify()
                elif tipo == "stats":
                    if getattr(self, "visivel", True):      # minimizado: não redesenha números
                        self._mostrar_stats(val)
                elif tipo == "alerta":
                    if time.time() - self.alertas_avisados.get(val, 0) > 1800:
                        self.alertas_avisados[val] = time.time()
                        self.add_hist("alerta", "⚠ " + val)
        except queue.Empty:
            pass
        # minimizado/escondido: não anima nada, só confere a fila 5x por segundo
        self.visivel = bool(self.winfo_viewable()) and self.state() != "iconic"
        if not self.visivel:
            self.after(200, self._loop)
            return
        # animação
        t0 = time.perf_counter()
        ativo = self.estado in ("ouvindo", "processando")
        nuc = self.bp.nucleo if self.bp is not None else self.nucleo
        nuc.fase += 0.06 if ativo else 0.075
        alvo = self.motor.gravador.nivel if self.motor.gravando() else 0.0
        nuc.nivel += (alvo - nuc.nivel) * 0.35
        if self.bp is not None:                     # Big Picture aberto: só ele anima (a tela de trás fica parada)
            try:
                nuc.desenhar()
                self._fase_ui += 0.033
                self.bp.animar(self._fase_ui)
            except Exception as e:
                print("  (big picture):", e)
                self.bp = None
        else:
            self.recursos.animar()
            self._animar_vida()
            self.grafico.desenhar()
            self.nucleo.desenhar()
            self.onda.desenhar(max(self.nucleo.nivel, 0.15 if self.estado == "processando" else 0.0),
                               self.nucleo.fase, ESTADOS[self.estado][2])
        gasto = (time.perf_counter() - t0) * 1000
        alvo_ms = 33                                                      # 30 fps: gráfico e barras sempre suaves
        self.after(max(5, int(alvo_ms - gasto)), self._loop)


if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception:
        traceback.print_exc()
        ctypes.windll.user32.MessageBoxW(0, "O Jon fechou por um erro. Veja assistente.log.", "Jon", 0x10)
