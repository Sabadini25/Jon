# -*- coding: utf-8 -*-
"""
Apoio para os painéis do Jon:
- ícone de verdade de um programa (.exe) para mostrar na tela
- últimos apps usados (vigia a janela em foco, bem leve)
- e-mails não lidos (Gmail/Outlook por IMAP, com senha de app)
- clima resumido para a faixa do centro
"""
import ctypes
import datetime as dt
import email
import email.header
import email.utils
import imaplib
import json
import os
import re
import threading
import time
from ctypes import wintypes

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_RECENTES = os.path.join(PASTA, "recentes.json")
ARQ_EMAIL = os.path.join(PASTA, "email_config.json")

# =====================================================================
#   ÍCONE DE UM .EXE  ->  imagem PIL (RGBA)
# =====================================================================
_cache_icones = {}


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class _ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]


class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int), ("dwAttributes", wintypes.DWORD),
                ("szDisplayName", wintypes.WCHAR * 260), ("szTypeName", wintypes.WCHAR * 80)]


_api_pronta = False


def _preparar_api():
    """Assinaturas certas (em Windows 64 bits os 'handles' não cabem no int padrão do ctypes)."""
    global _api_pronta
    if _api_pronta:
        return
    u32, g32, sh = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.shell32
    u32.PrivateExtractIconsW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                         ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
                                         wintypes.UINT, wintypes.UINT]
    u32.PrivateExtractIconsW.restype = wintypes.UINT
    u32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(_ICONINFO)]
    u32.GetIconInfo.restype = wintypes.BOOL
    u32.GetDC.argtypes = [wintypes.HWND]
    u32.GetDC.restype = wintypes.HDC
    u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    u32.DestroyIcon.argtypes = [wintypes.HICON]
    g32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                              ctypes.c_void_p, wintypes.UINT]
    g32.GetDIBits.restype = ctypes.c_int
    g32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    g32.GetObjectW.argtypes = [wintypes.HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
    sh.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_SHFILEINFOW), wintypes.UINT,
                                  wintypes.UINT]
    sh.SHGetFileInfoW.restype = ctypes.c_void_p
    _api_pronta = True


class _BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG), ("bmHeight", wintypes.LONG),
                ("bmWidthBytes", wintypes.LONG), ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


def _hicon_para_pil(hicon):
    from PIL import Image
    u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
    info = _ICONINFO()
    if not u32.GetIconInfo(hicon, ctypes.byref(info)) or not info.hbmColor:
        return None
    try:
        bm = _BITMAP()
        g32.GetObjectW(info.hbmColor, ctypes.sizeof(_BITMAP), ctypes.byref(bm))
        w, h = bm.bmWidth, bm.bmHeight
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight, bmi.biPlanes, bmi.biBitCount = w, -h, 1, 32
        buf = ctypes.create_string_buffer(w * h * 4)
        hdc = u32.GetDC(None)
        g32.GetDIBits(hdc, info.hbmColor, 0, h, buf, ctypes.byref(bmi), 0)
        bgra = bytearray(buf.raw)
        if not any(bgra[3::4]):                          # ícone antigo sem alfa: usa a máscara
            mbuf = ctypes.create_string_buffer(w * h * 4)
            g32.GetDIBits(hdc, info.hbmMask, 0, h, mbuf, ctypes.byref(bmi), 0)
            m = mbuf.raw
            for i in range(0, len(bgra), 4):
                bgra[i + 3] = 0 if m[i] else 255
        u32.ReleaseDC(None, hdc)
        return Image.frombuffer("RGBA", (w, h), bytes(bgra), "raw", "BGRA", 0, 1).copy()
    finally:
        g32.DeleteObject(info.hbmColor)
        if info.hbmMask:
            g32.DeleteObject(info.hbmMask)


def icone_exe(caminho: str, tam: int = 32):
    """Ícone de verdade do programa (o mesmo da barra de tarefas) como imagem PIL RGBA, ou None."""
    chave = (os.path.normcase(caminho or ""), tam)
    if chave in _cache_icones:
        return _cache_icones[chave]
    img = None
    try:
        _preparar_api()
        u32 = ctypes.windll.user32
        hicon = wintypes.HICON()
        idx = wintypes.UINT()
        n = u32.PrivateExtractIconsW(caminho, 0, tam, tam, ctypes.byref(hicon), ctypes.byref(idx), 1, 0)
        if n and n != 0xFFFFFFFF and hicon.value:
            img = _hicon_para_pil(hicon)
            u32.DestroyIcon(hicon)
        if img is None:                                  # plano B: o ícone que o Explorer mostra
            sfi = _SHFILEINFOW()
            if ctypes.windll.shell32.SHGetFileInfoW(caminho, 0, ctypes.byref(sfi), ctypes.sizeof(sfi), 0x100) \
                    and sfi.hIcon:
                img = _hicon_para_pil(sfi.hIcon)
                u32.DestroyIcon(sfi.hIcon)
        if img is not None and img.size != (tam, tam):
            from PIL import Image
            img = img.resize((tam, tam), Image.LANCZOS)
    except Exception as e:
        print("  (ícone não carregou:", os.path.basename(caminho or "?"), e, ")")
        img = None
    _cache_icones[chave] = img
    return img


def cor_dominante(img):
    """Cor de destaque de uma imagem (capa do álbum) — viva, nem escura nem cinza."""
    try:
        import colorsys
        p = img.convert("RGB").resize((24, 24)).getdata()
        melhor, nota_m = None, -1
        for r, g, b in p:
            h, l, s_ = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            nota = s_ * (1 - abs(l - 0.55) * 1.6)
            if nota > nota_m:
                melhor, nota_m = (h, s_), nota
        if not melhor or nota_m < 0.15:
            return None
        r, g, b = colorsys.hls_to_rgb(melhor[0], 0.62, max(0.55, min(0.9, melhor[1])))
        return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
    except Exception:
        return None


def exe_do_processo(nome_exe: str):
    """Caminho do .exe de um programa que está aberto (ex.: 'Spotify.exe')."""
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            if (p.info.get("name") or "").lower() == nome_exe.lower() and p.info.get("exe"):
                return p.info["exe"]
    except Exception:
        pass
    return None


def exe_spotify():
    caminho = exe_do_processo("Spotify.exe")
    if caminho:
        return caminho
    padrao = os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe")
    return padrao if os.path.exists(padrao) else None


# =====================================================================
#   ÚLTIMOS APPS USADOS
# =====================================================================
IGNORAR = {"explorer.exe", "pythonw.exe", "python.exe", "applicationframehost.exe", "shellexperiencehost.exe",
           "searchhost.exe", "startmenuexperiencehost.exe", "lockapp.exe", "textinputhost.exe", "claude.exe",
           "taskmgr.exe", "systemsettings.exe", "nvidia overlay.exe", "searchapp.exe", "rundll32.exe",
           "consent.exe", "openwith.exe", "pickerhost.exe", "msedgewebview2.exe", "snippingtool.exe",
           "screenclippinghost.exe", "gamebar.exe", "xboxgamebarwidgets.exe", "conhost.exe", "cmd.exe",
           "powershell.exe", "windowsterminal.exe", "upc.exe"}
NOMES = {"chrome.exe": "Chrome", "msedge.exe": "Edge", "spotify.exe": "Spotify", "discord.exe": "Discord",
         "steam.exe": "Steam", "steamwebhelper.exe": "Steam", "code.exe": "VS Code", "winword.exe": "Word",
         "excel.exe": "Excel", "powerpnt.exe": "PowerPoint", "obsidian.exe": "Obsidian", "obs64.exe": "OBS",
         "hydra.exe": "Hydra", "whatsapp.exe": "WhatsApp", "notepad.exe": "Bloco de notas",
         "firefox.exe": "Firefox", "telegram.exe": "Telegram", "pbidesktop.exe": "Power BI",
         "acmirage_plus.exe": "AC Mirage", "acshadows.exe": "AC Shadows", "riotclientservices.exe": "Riot",
         "vlc.exe": "VLC", "acrobat.exe": "Acrobat", "acrord32.exe": "Acrobat"}


def _nome_bonito(exe_path, titulo):
    base = os.path.basename(exe_path).lower()
    if base in NOMES:
        return NOMES[base]
    try:                                               # descrição do arquivo (ex.: "Hydra Launcher")
        tam = ctypes.windll.version.GetFileVersionInfoSizeW(exe_path, None)
        if tam:
            buf = ctypes.create_string_buffer(tam)
            ctypes.windll.version.GetFileVersionInfoW(exe_path, 0, tam, buf)
            p, n = ctypes.c_void_p(), wintypes.UINT()
            if ctypes.windll.version.VerQueryValueW(buf, r"\VarFileInfo\Translation", ctypes.byref(p),
                                                    ctypes.byref(n)) and n.value >= 4:
                lang = ctypes.cast(p, ctypes.POINTER(wintypes.WORD * 2)).contents
                sub = rf"\StringFileInfo\{lang[0]:04x}{lang[1]:04x}\FileDescription"
                if ctypes.windll.version.VerQueryValueW(buf, sub, ctypes.byref(p), ctypes.byref(n)) and n.value:
                    desc = ctypes.wstring_at(p, n.value - 1).strip()
                    if desc and len(desc) <= 28:
                        return desc
    except Exception:
        pass
    if titulo and " - " in titulo:
        return titulo.rsplit(" - ", 1)[-1][:22]
    return os.path.splitext(os.path.basename(exe_path))[0][:22]


class Recentes:
    """Guarda os últimos programas que ficaram em foco por alguns segundos."""

    def __init__(self, maximo=8):
        self.maximo = maximo
        self.lista = []                                 # [{"exe", "nome", "ts"}]
        self.mudou = threading.Event()
        try:
            with open(ARQ_RECENTES, encoding="utf-8") as f:
                self.lista = [x for x in json.load(f) if os.path.exists(x.get("exe", ""))][:maximo]
        except Exception:
            pass
        self._candidato = (None, 0)

    def _salvar(self):
        try:
            with open(ARQ_RECENTES, "w", encoding="utf-8") as f:
                json.dump(self.lista, f, ensure_ascii=False)
        except Exception:
            pass

    def _janela_em_foco(self):
        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return None, ""
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        n = u32.GetWindowTextLengthW(hwnd)
        b = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, b, n + 1)
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid.value)
        exe = None
        if h:
            buf = ctypes.create_unicode_buffer(520)
            sz = wintypes.DWORD(520)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(sz)):
                exe = buf.value
            k32.CloseHandle(h)
        return exe, b.value

    def registrar(self, exe, nome=None):
        if not exe or os.path.basename(exe).lower() in IGNORAR or "\\windows\\system32\\" in exe.lower():
            return
        chave = os.path.normcase(exe)
        antigo = next((x for x in self.lista if os.path.normcase(x["exe"]) == chave), None)
        if antigo and self.lista and self.lista[0] is antigo:
            antigo["ts"] = time.time()
            return
        if antigo:
            self.lista.remove(antigo)
        self.lista.insert(0, {"exe": exe, "nome": nome or (antigo or {}).get("nome") or _nome_bonito(exe, ""),
                              "ts": time.time()})
        del self.lista[self.maximo:]
        self._salvar()
        self.mudou.set()

    def vigiar(self, visivel=lambda: True):
        """Roda numa thread: a cada 2 s olha a janela em foco (precisa ficar 4 s pra contar)."""
        while True:
            try:
                exe, titulo = self._janela_em_foco()
                if exe and os.path.basename(exe).lower() not in IGNORAR:
                    if self._candidato[0] == exe:
                        if time.time() - self._candidato[1] >= 4:
                            self.registrar(exe, _nome_bonito(exe, titulo))
                    else:
                        self._candidato = (exe, time.time())
            except Exception:
                pass
            time.sleep(2.0)


def abrir_ou_focar(exe):
    """Se o programa já está aberto, traz pra frente; senão abre."""
    try:
        import assistente_voz as av
        hwnd = av._janela_do_processo(os.path.basename(exe))
        if hwnd:
            av.trazer_janela_pra_frente(hwnd)
            return
    except Exception:
        pass
    try:
        os.startfile(exe)
    except OSError:
        pass


# =====================================================================
#   E-MAIL (IMAP)
# =====================================================================
SERVIDORES = {"gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com",
              "outlook.com": "outlook.office365.com", "hotmail.com": "outlook.office365.com",
              "live.com": "outlook.office365.com", "yahoo.com": "imap.mail.yahoo.com",
              "yahoo.com.br": "imap.mail.yahoo.com", "icloud.com": "imap.mail.me.com"}


def carregar_email():
    try:
        with open(ARQ_EMAIL, encoding="utf-8") as f:
            c = json.load(f)
        if c.get("email") and c.get("senha_app"):
            return c
    except Exception:
        pass
    return None


def salvar_email(endereco, senha_app):
    dominio = endereco.split("@")[-1].lower().strip()
    cfg = {"email": endereco.strip(), "senha_app": senha_app.replace(" ", "").strip(),
           "servidor": SERVIDORES.get(dominio, "imap." + dominio)}
    with open(ARQ_EMAIL, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


def _dec(v):
    try:
        partes = email.header.decode_header(v or "")
        return "".join(t.decode(c or "utf-8", "ignore") if isinstance(t, bytes) else t for t, c in partes).strip()
    except Exception:
        return (v or "").strip()


def ler_nao_lidos(cfg, maximo=4):
    """{'total': n, 'itens': [{'uid','de','assunto','quando'}]} — não marca nada como lido."""
    m = imaplib.IMAP4_SSL(cfg.get("servidor") or "imap.gmail.com", 993, timeout=20)
    try:
        m.login(cfg["email"], cfg["senha_app"])
        m.select("INBOX", readonly=True)
        typ, d = m.uid("search", None, "UNSEEN")
        uids = d[0].split() if typ == "OK" and d and d[0] else []
        itens = []
        for uid in reversed(uids[-maximo:]):
            typ, dados = m.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK" or not dados or not isinstance(dados[0], tuple):
                continue
            msg = email.message_from_bytes(dados[0][1])
            nome, end = email.utils.parseaddr(_dec(msg.get("From")))
            try:
                quando = email.utils.parsedate_to_datetime(msg.get("Date")).astimezone()
            except Exception:
                quando = None
            itens.append({"uid": uid.decode(), "de": nome or end, "assunto": _dec(msg.get("Subject")) or "(sem assunto)",
                          "quando": quando.strftime("%d/%m %H:%M") if quando and quando.date() != dt.date.today()
                          else (quando.strftime("%H:%M") if quando else "")})
        return {"total": len(uids), "itens": itens}
    finally:
        try:
            m.logout()
        except Exception:
            pass


def link_caixa(cfg):
    s = (cfg or {}).get("servidor", "")
    if "gmail" in s:
        return "https://mail.google.com/mail/u/0/#inbox"
    if "office365" in s:
        return "https://outlook.live.com/mail/0/"
    if "yahoo" in s:
        return "https://mail.yahoo.com/"
    return "https://mail.google.com/"


ultimo_email = {"total": None, "itens": [], "erro": ""}


def resumo_email_falado() -> str:
    cfg = carregar_email()
    if not cfg:
        return "Seu e-mail ainda não está conectado. Clique em conectar no painel de e-mails do Jon."
    try:
        r = ler_nao_lidos(cfg, 3)
    except Exception:
        return "Não consegui olhar seus e-mails agora."
    if not r["total"]:
        return "Nenhum e-mail novo."
    txt = f"Você tem {r['total']} e-mail{'s' if r['total'] > 1 else ''} não lido{'s' if r['total'] > 1 else ''}."
    for it in r["itens"]:
        txt += f" De {it['de']}: {it['assunto']}."
    return txt


# =====================================================================
#   CLIMA RESUMIDO
# =====================================================================
def clima_curto():
    import extras
    nome, lat, lon = extras.cidade_padrao()
    d = extras._get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                    "&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max&timezone=America%2FSao_Paulo&forecast_days=1")
    c = d["current"]
    cod = c["weather_code"]
    icone = "☀" if cod == 0 else "🌤" if cod in (1, 2) else "☁" if cod in (3, 45, 48) else \
        "⛈" if cod >= 95 else "🌧"
    return {"cidade": nome, "temp": round(c["temperature_2m"]), "cond": extras.TEMPO_COD.get(cod, ""),
            "icone": icone, "max": round(d["daily"]["temperature_2m_max"][0]),
            "min": round(d["daily"]["temperature_2m_min"][0]), "chuva": d["daily"]["precipitation_probability_max"][0]}


# =====================================================================
#   NOTIFICAÇÕES DO WINDOWS (WhatsApp, Discord, Teams, e-mail...)
# =====================================================================
PACOTES_WINRT = ["winrt-runtime", "winrt-Windows.UI.Notifications", "winrt-Windows.UI.Notifications.Management",
                 "winrt-Windows.Foundation", "winrt-Windows.Foundation.Collections", "winrt-Windows.ApplicationModel"]


def _instalar_winrt():
    """Instala os pacotes que leem as notificações (uma vez só, em segundo plano)."""
    import subprocess
    import sys
    py = sys.executable
    if py.lower().endswith("pythonw.exe"):
        py = py[:-len("pythonw.exe")] + "python.exe"
    print("  (instalando o leitor de notificações do Windows — só na primeira vez…)")
    r = subprocess.run([py, "-m", "pip", "install", "--quiet", *PACOTES_WINRT], capture_output=True, text=True,
                       creationflags=0x08000000, timeout=600)
    if r.returncode != 0:
        print("  Erro ao instalar o leitor de notificações:", (r.stderr or r.stdout)[-300:])
        return False
    return True


class Notificacoes:
    """Lê a central de notificações do Windows a cada poucos segundos (só lê; não fecha nem responde nada)."""

    def __init__(self):
        self.itens = []          # [{"id","app","titulo","texto","quando","ts"}] mais novas primeiro
        self.estado = "iniciando"   # iniciando | instalando | sem_permissao | ok | erro
        self.detalhe = ""
        self.mudou = threading.Event()
        self.novas = []          # chegaram agora (pra avisar)
        self._vistos = None

    def _importar(self):
        from winrt.windows.ui.notifications.management import (UserNotificationListener,  # noqa: F401
                                                                UserNotificationListenerAccessStatus)
        from winrt.windows.ui.notifications import NotificationKinds, KnownNotificationBindings  # noqa: F401
        return UserNotificationListener, UserNotificationListenerAccessStatus, NotificationKinds, \
            KnownNotificationBindings

    def rodar(self, visivel=lambda: True):
        import asyncio
        try:
            mods = self._importar()
        except (ImportError, AttributeError, Exception) as e:
            self.estado = "instalando"
            self.mudou.set()
            if not _instalar_winrt():
                self.estado, self.detalhe = "erro", "não consegui instalar o leitor (veja o registro)"
                self.mudou.set()
                return
            try:
                mods = self._importar()
            except Exception as e:
                self.estado, self.detalhe = "erro", str(e)[:120]
                self.mudou.set()
                return
        UNL, Status, Kinds, Bindings = mods
        laco = asyncio.new_event_loop()
        try:
            ouvinte = UNL.current
            st = ouvinte.get_access_status()
            if st != Status.ALLOWED:
                try:
                    st = laco.run_until_complete(ouvinte.request_access_async())
                except Exception:
                    pass
            if st != Status.ALLOWED:
                self.estado = "sem_permissao"
                self.mudou.set()
                # continua conferindo: se você liberar nas Configurações, começa sozinho
                while ouvinte.get_access_status() != Status.ALLOWED:
                    time.sleep(10)
            self.estado = "ok"
            self.mudou.set()
            while True:
                try:
                    lista = laco.run_until_complete(ouvinte.get_notifications_async(Kinds.TOAST))
                    itens = []
                    for n in lista:
                        try:
                            app = n.app_info.display_info.display_name
                        except Exception:
                            app = "Windows"
                        try:
                            b = n.notification.visual.get_binding(Bindings.toast_generic)
                            textos = [t.text for t in b.get_text_elements()] if b else []
                        except Exception:
                            textos = []
                        try:
                            ts = n.creation_time.timestamp()
                        except Exception:
                            ts = time.time()
                        itens.append({"id": n.id, "app": app or "Windows", "titulo": (textos[0] if textos else app),
                                      "texto": " ".join(textos[1:])[:160], "ts": ts})
                    itens.sort(key=lambda x: -x["ts"])
                    ids = {x["id"] for x in itens}
                    if self._vistos is not None:
                        self.novas = [x for x in itens if x["id"] not in self._vistos]
                    self._vistos = ids if self._vistos is None else (self._vistos | ids)
                    if [x["id"] for x in itens] != [x["id"] for x in self.itens] or self.novas:
                        self.itens = itens[:30]
                        self.mudou.set()
                except Exception as e:
                    self.detalhe = str(e)[:120]
                time.sleep(3 if visivel() else 8)
        except Exception as e:
            self.estado, self.detalhe = "erro", str(e)[:160]
            self.mudou.set()


_icone_app_cache = {}


def exe_por_nome_app(nome_app: str):
    """'WhatsApp' -> caminho do WhatsApp.exe aberto (pra pegar o ícone de verdade)."""
    chave = (nome_app or "").lower()
    if chave in _icone_app_cache:
        return _icone_app_cache[chave]
    achado = None
    palavras = [p for p in re.split(r"\W+", chave) if len(p) >= 3 and p not in ("google", "microsoft", "app")]
    especiais = {"google chrome": "chrome.exe", "microsoft edge": "msedge.exe", "microsoft teams": "ms-teams.exe",
                 "outlook": "olk.exe"}
    try:
        import psutil
        alvo = especiais.get(chave)
        for p in psutil.process_iter(["name", "exe"]):
            nome = (p.info.get("name") or "").lower()
            if not p.info.get("exe"):
                continue
            if (alvo and nome == alvo) or (not alvo and palavras and any(w in nome for w in palavras)):
                achado = p.info["exe"]
                break
    except Exception:
        pass
    _icone_app_cache[chave] = achado
    return achado


# =====================================================================
#   DOWNLOADS (navegador, uTorrent, Hydra, Steam)
# =====================================================================
PARCIAIS = (".crdownload", ".part", ".partial", ".!ut", ".!qb", ".aria2", ".download", ".opdownload", ".tmp")


def pasta_downloads():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            v = winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
            v = os.path.expandvars(v)
            if os.path.isdir(v):
                return v
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


def _bibliotecas_steam():
    libs = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            raiz = winreg.QueryValueEx(k, "SteamPath")[0].replace("/", "\\")
        libs.append(os.path.join(raiz, "steamapps"))
        vdf = os.path.join(raiz, "steamapps", "libraryfolders.vdf")
        with open(vdf, encoding="utf-8", errors="ignore") as f:
            for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                p = os.path.join(m.group(1).replace("\\\\", "\\"), "steamapps")
                if os.path.isdir(p) and p.lower() not in (x.lower() for x in libs):
                    libs.append(p)
    except Exception:
        pass
    return libs


def _tam_pasta(caminho, limite=4000):
    total, n = 0, 0
    for raiz, _, arqs in os.walk(caminho):
        for a in arqs:
            try:
                total += os.path.getsize(os.path.join(raiz, a))
            except OSError:
                pass
            n += 1
            if n > limite:
                return total
    return total


def humano(b):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or u == "TB":
            return f"{b:.0f} {u}" if u in ("B", "KB") else f"{b:.1f} {u}"
        b /= 1024


class Downloads:
    """Mostra o que está baixando agora (e os últimos que terminaram)."""

    def __init__(self, pastas_extra=()):
        self.pasta = pasta_downloads()
        self.pastas = [self.pasta] + [p for p in pastas_extra if p and os.path.isdir(p)]
        self.ativos = []        # [{"nome","origem","feito","total","vel","frac","caminho"}]
        self.recentes = []      # [{"nome","quando","caminho","tam"}]
        self.mudou = threading.Event()
        self._antes = {}        # caminho -> (bytes, t)
        self._steam = _bibliotecas_steam()

    def _ler(self):
        agora = time.time()
        ativos, recentes = [], []
        for pasta in self.pastas:
            try:
                entradas = list(os.scandir(pasta))
            except OSError:
                continue
            for e in entradas:
                try:
                    st = e.stat()
                except OSError:
                    continue
                nome = e.name
                parcial = nome.lower().endswith(PARCIAIS)
                recente = agora - st.st_mtime < 90
                if parcial or (recente and e.is_dir()):
                    tam = _tam_pasta(e.path) if e.is_dir() else st.st_size
                    b0, t0 = self._antes.get(e.path, (tam, agora))
                    vel = (tam - b0) / max(0.5, agora - t0) if agora - t0 > 0.5 else 0
                    self._antes[e.path] = (tam, agora)
                    if not parcial and vel <= 0 and not recente:
                        continue
                    if nome.lower().endswith(".aria2"):          # o arquivo de controle; mostra o de verdade
                        continue
                    limpo = re.sub(r"(?i)\.(crdownload|part|partial|!ut|!qb|download|opdownload|tmp)$", "", nome)
                    origem = "uTorrent" if nome.endswith(".!ut") else "navegador" if parcial else "Hydra / pasta"
                    if e.is_dir() and vel <= 0 and agora - st.st_mtime > 30:
                        continue
                    ativos.append({"nome": limpo, "origem": origem, "feito": tam, "total": 0, "vel": max(0, vel),
                                   "frac": None, "caminho": e.path})
                elif e.is_file() and agora - st.st_mtime < 3 * 86400:
                    recentes.append({"nome": nome, "ts": st.st_mtime, "caminho": e.path, "tam": st.st_size})
        # Steam: jogos atualizando/baixando
        for lib in self._steam:
            try:
                for e in os.scandir(lib):
                    if not e.name.startswith("appmanifest_") or agora - e.stat().st_mtime > 600:
                        continue
                    with open(e.path, encoding="utf-8", errors="ignore") as f:
                        t = f.read()
                    def campo(k):
                        m = re.search(r'"%s"\s+"([^"]*)"' % k, t)
                        return m.group(1) if m else ""
                    total, feito = int(campo("BytesToDownload") or 0), int(campo("BytesDownloaded") or 0)
                    if total and feito < total:
                        b0, t0 = self._antes.get(e.path, (feito, agora))
                        vel = (feito - b0) / max(0.5, agora - t0) if agora - t0 > 0.5 else 0
                        self._antes[e.path] = (feito, agora)
                        ativos.append({"nome": campo("name") or "Jogo da Steam", "origem": "Steam", "feito": feito,
                                       "total": total, "vel": max(0, vel), "frac": feito / total, "caminho": None})
            except OSError:
                pass
        recentes.sort(key=lambda x: -x["ts"])
        return ativos, recentes[:4]

    def rodar(self, visivel=lambda: True):
        while True:
            try:
                ativos, recentes = self._ler()
                assin = lambda L: [(x["nome"], round(x.get("feito", 0) / 1e6), round(x.get("vel", 0) / 1e5))
                                   for x in L] if L and "vel" in L[0] else [x["nome"] for x in L]
                if assin(ativos) != assin(self.ativos) or [x["nome"] for x in recentes] != \
                        [x["nome"] for x in self.recentes]:
                    self.ativos, self.recentes = ativos, recentes
                    self.mudou.set()
            except Exception as e:
                print("  (downloads):", e)
            time.sleep(2 if visivel() else 10)
