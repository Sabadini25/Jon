# -*- coding: utf-8 -*-
"""
Jon — assistente de voz  -  "segura a tecla e fala"

Como usar:
  - Segure a tecla de atalho (padrão: F9), fale o comando no headset e solte.
  - Um bipe agudo = começou a ouvir; bipe grave = entendeu e vai executar.

Comandos de exemplo:
  "abre o spotify" / "abrir discord" / "abre o steam"
  "toca Coldplay no spotify" / "spotify Yellow"
  "toca lofi no youtube" / "youtube como fazer café"   (abre o 1º vídeo)
  "pesquisa previsão do tempo em Curitiba"            (Google)
  "claude, resume esse arquivo..."                    (manda o texto pro app do Claude)
  "volume" / "pausa" / "próxima" / "anterior"          (teclas de mídia)
  "fechar assistente"                                  (encerra o programa)
"""

import os
import re
import sys
import time
import queue
import threading
import subprocess
import unicodedata
import urllib.parse
import urllib.request
import webbrowser
import winsound

import numpy as np
import sounddevice as sd
import keyboard
import pyperclip
import speech_recognition as sr

import spotify_api
import ia_local
import rotinas
import extras
import sistema
import pesquisa
import video

# ===================== CONFIGURAÇÃO =====================
TECLA_FALAR = "f9"          # tecla para segurar enquanto fala (ex.: "f9", "ctrl+alt+v", "scroll lock")
IDIOMA = "pt-BR"
TAXA_AMOSTRAGEM = 16000
SEMPRE_TOCAR = True         # "pesquisa X no Spotify" já toca a música (False = só pesquisa)
FALAR_RESPOSTAS = True      # a IA fala as respostas em voz alta
CAUDA_SEGUNDOS = 0.45       # continua gravando esse tempo depois de soltar a tecla (evita cortar o fim)
MICROFONE = None           # None = microfone padrão do Windows. Rode com --listar-mics para ver os números.

# Apps que o "abre X" conhece. Chave = como você fala; valor = comando/atalho/URI.
# Se o app não estiver aqui, o assistente procura pelo Menu Iniciar.
APPS = {
    "spotify": "spotify:",
    "discord": "discord:",
    "steam": "steam:",
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "navegador": "msedge",
    "explorador": "explorer",
    "explorador de arquivos": "explorer",
    "arquivos": "explorer",
    "bloco de notas": "notepad",
    "calculadora": "calc",
    "obsidian": "obsidian:",
    "configuracoes": "ms-settings:",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "vs code": "code",
    "vscode": "code",
    "claude": "claude:",
    "whatsapp": "whatsapp:",
    "zap": "whatsapp:",
    "netflix": "netflix:",
    "telegram": "tg:",
}
# Apps que o celular (iPhone) sabe abrir por link. Pedido feito pelo celular abre no celular.
APPS_CELULAR = {
    "spotify": "spotify:", "whatsapp": "whatsapp://", "zap": "whatsapp://", "instagram": "instagram://",
    "insta": "instagram://", "youtube": "youtube://", "netflix": "nflx://", "telegram": "tg://",
    "discord": "discord://", "waze": "waze://", "google maps": "comgooglemaps://", "maps": "maps://",
    "mapa": "maps://", "mapas": "maps://", "tiktok": "snssdk1233://", "twitter": "twitter://", "x": "twitter://",
    "gmail": "googlegmail://", "chrome": "googlechrome://", "google chrome": "googlechrome://",
    "uber": "uber://", "ifood": "ifood://", "nubank": "nubank://", "mensagens": "sms:", "email": "mailto:",
    "safari": "https://www.google.com", "navegador": "https://www.google.com", "google": "https://www.google.com",
    "claude": "claude://",
}
# ========================================================


def _tocar_bip(freq, dur):
    try:
        winsound.Beep(freq, dur)
    except Exception:
        pass


def bip(freq=1000, dur=120):
    threading.Thread(target=_tocar_bip, args=(freq, dur), daemon=True).start()


def normalizar(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt.lower())
    return "".join(c for c in txt if not unicodedata.combining(c)).strip()


# ---------------------- AÇÕES ----------------------

_atalhos_cache = (0.0, [])


def _pastas_de_atalhos():
    pastas = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            for nome in ("Desktop", "Programs"):
                try:
                    pastas.append(os.path.expandvars(winreg.QueryValueEx(k, nome)[0]))
                except OSError:
                    pass
    except Exception:
        pass
    casa = os.path.expanduser("~")
    pastas += [os.path.join(casa, "Desktop"), os.path.join(casa, "OneDrive", "Desktop"),
               os.path.join(casa, "OneDrive", "Área de Trabalho"),
               os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop"),
               os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
               os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs")]
    vistas, saida = set(), []
    for p in pastas:
        if p and os.path.isdir(p) and os.path.normcase(p) not in vistas:
            vistas.add(os.path.normcase(p))
            saida.append(p)
    return saida


def _listar_atalhos():
    global _atalhos_cache
    if time.time() - _atalhos_cache[0] < 120:
        return _atalhos_cache[1]
    lista = []
    for pasta in _pastas_de_atalhos():
        for raiz, _, arquivos in os.walk(pasta):
            for a in arquivos:
                base, ext = os.path.splitext(a)
                if ext.lower() in (".lnk", ".url", ".appref-ms") and not re.search(
                        r"(?i)\b(uninstall|desinstalar|readme|leia-me|help|ajuda|manual|website|site)\b", base):
                    lista.append((normalizar(base), os.path.join(raiz, a)))
    _atalhos_cache = (time.time(), lista)
    return lista


def _esqueleto(p: str) -> str:
    """'Som' da palavra, pra perdoar o reconhecimento de voz: 'streamer'/'streaming' ~ 'stremio'."""
    p = re.sub(r"(ings?|ers?|s)$", "", p) if len(p) > 5 else p
    p = p.replace("ph", "f").replace("ck", "c").replace("k", "c").replace("q", "c").replace("y", "i")
    p = p.replace("w", "v").replace("z", "s").replace("x", "s").replace("h", "")
    p = p[:1] + re.sub(r"[aeiou]", "", p[1:])
    return re.sub(r"(.)\1+", r"\1", p)


def _parecido(a: str, b: str) -> float:
    import difflib
    nota = difflib.SequenceMatcher(None, a, b).ratio()
    if len(a) >= 4 and len(b) >= 4 and nota >= 0.55:     # o som só ajuda se a escrita já for parecida
        ea, eb = _esqueleto(a), _esqueleto(b)
        if len(ea) >= 3 and len(eb) >= 3:
            som = difflib.SequenceMatcher(None, ea, eb).ratio()
            if som >= 0.9:                               # só quando o "som" é praticamente o mesmo
                nota = max(nota, som * 0.97)
    return nota


def achar_atalho(chave: str):
    """Acha o atalho cujo nome mais parece com o que foi falado.
    Tolera erros de digitação e de reconhecimento de voz: 'mirrage' -> 'Mirage', 'streamer' -> 'Stremio'."""
    import difflib
    alvo = re.sub(r"[^\w\s]", " ", normalizar(chave))
    alvo = re.sub(r"\s+", " ", alvo).strip()
    if not alvo:
        return None
    melhor, nota_melhor = None, 0.0
    for nome, caminho in _listar_atalhos():
        n = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", nome)).strip()
        if not n:
            continue
        if alvo == n:
            return caminho
        nota = difflib.SequenceMatcher(None, alvo, n).ratio()
        # cada palavra falada parecida (na escrita ou no som) com alguma palavra do atalho
        pal_a, pal_n = alvo.split(), n.split()
        sims = [max(_parecido(p, q) for q in pal_n) for p in pal_a]
        if min(sims) >= 0.8:
            nota = max(nota, 0.78 + 0.12 * (sum(sims) / len(sims)) + 0.07 * min(1.0, len(pal_a) / len(pal_n)))
        if nota > nota_melhor:
            melhor, nota_melhor = caminho, nota
    return melhor if nota_melhor >= 0.78 else None


ENCHIMENTO_APP = (r"\b(pra mim|para mim|por favor|porfavor|ai|agora|rapidinho|pfv|"
                  r"(o|a|os|as|um|uma|meu|minha|esse|essa|aquele)?\s*(aplicativo|app|programa|atalho|jogo|game|icone|"
                  r"launcher|pasta do|software)( do| da| de)?|"
                  r"(que (esta|ta|fica)\s+)?(na|da|no|do|pela|pelo)\s+(minha\s+)?(area de trabalho|desktop|tela inicial|"
                  r"menu iniciar|barra de tarefas|tela)|no pc|no computador)\b")


def limpar_nome_app(nome: str) -> str:
    """'o aplicativo Hydra na área de trabalho' -> 'Hydra'."""
    n = unicodedata.normalize("NFKD", nome)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = re.sub(r"^\s*((abre|abrir|abra|inicia|iniciar|executa|executar|liga|ligar|entra|entrar)\s+)+", " ", n,
               flags=re.I)                       # "abrir abrir abrir o app X" (o reconhecimento repete)
    n = re.sub(ENCHIMENTO_APP, " ", n, flags=re.I)
    n = re.sub(r"^\s*(o|a|os|as|meu|minha)\s+", " ", n, flags=re.I)
    n = re.sub(r"\s+(na|no|da|do|de)$", "", re.sub(r"\s+", " ", n).strip(" ,.")).strip()
    return n or nome.strip()


def abrir_app(nome: str):
    nome = limpar_nome_app(nome)
    chave = normalizar(nome)
    chave = re.sub(r"^(o|a|os|as|meu|minha)\s+", "", chave)
    if no_celular():
        if chave in APPS_CELULAR:
            abrir_no_celular(APPS_CELULAR[chave], "Abrir " + nome)
            print(f"  -> abrindo {chave} no celular")
        else:
            achado = achar_atalho(chave)      # só existe no PC (ex.: um jogo) -> abre no PC mesmo
            if achado:
                print(f"  -> abrindo {os.path.splitext(os.path.basename(achado))[0]} no computador")
                try:
                    os.startfile(achado)
                except OSError as e:
                    print("  (não consegui abrir o atalho):", e)
            else:
                print(f"  -> não achei {nome} no celular nem no computador")
        return
    if chave in video.FALADO or chave.split(" ")[0] in video.FALADO:
        video.ultimo = (video.FALADO.get(chave) or video.FALADO[chave.split(" ")[0]], time.time())
    alvo = APPS.get(chave)
    if alvo:
        print(f"  -> abrindo {chave}")
        try:
            os.startfile(alvo)
            return
        except OSError:
            subprocess.Popen(f'start "" "{alvo}"', shell=True)
            return
    # Procura um atalho com nome parecido (área de trabalho e Menu Iniciar: .lnk, .url de jogos Steam/Ubisoft...)
    achado = achar_atalho(chave)
    if achado:
        print(f"  -> abrindo {os.path.splitext(os.path.basename(achado))[0]}")
        try:
            os.startfile(achado)
            return
        except OSError as e:
            print("  (não consegui abrir o atalho):", e)
    # Não conhecido: procura pelo Menu Iniciar
    print(f"  -> procurando '{nome}' no Menu Iniciar")
    keyboard.send("windows")
    time.sleep(0.6)
    keyboard.write(nome, delay=0.02)
    time.sleep(1.0)
    keyboard.send("enter")


def abrir_site(url: str, navegador: str = None):
    """Abre um site; se você falou o navegador (chrome, edge...), abre nele."""
    exe = {"chrome": "chrome", "edge": "msedge", "firefox": "firefox", "opera": "opera"}.get(navegador or "")
    if exe:
        try:
            subprocess.Popen(f'start "" {exe} "{url}"', shell=True)
            return
        except Exception:
            pass
    webbrowser.open(url)


def youtube(busca: str):
    print(f"  -> YouTube: {busca}")
    url_busca = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(busca)
    try:
        req = urllib.request.Request(url_busca, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "pt-BR"})
        html = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "ignore")
        m = re.search(r'"videoId":"([\w-]{11})"', html)
        if m:
            url = f"https://www.youtube.com/watch?v={m.group(1)}"
            if no_celular():
                abrir_no_celular(url, "Ver no YouTube")
                print("  -> YouTube no celular")
            else:
                webbrowser.open(url)
            return
    except Exception as e:
        print("  (não achei o 1º vídeo, abrindo a busca)", e)
    if no_celular():
        abrir_no_celular(url_busca, "Ver no YouTube")
        return
    webbrowser.open(url_busca)


def limpar_busca_musica(busca: str) -> str:
    """Tira palavras de enchimento: 'a música', 'o álbum', 'por favor'..."""
    b = " " + busca.strip() + " "
    for lixo in [" por favor ", " pra mim ", " para mim ", " ai ", " la "]:
        b = b.replace(lixo, " ")
    b = re.sub(r"^\s*(a|o|as|os|uma|um)?\s*(musica|musicas|cancao|som|album|playlist|artista|banda|faixa)\s+(do|da|de|dos|das)?\s*", " ", b)
    b = re.sub(r"^\s*(por|pelo|pela|a|o)\s+", " ", b)
    return re.sub(r"\s+", " ", b).strip()



def trazer_janela_pra_frente(hwnd, maximizar=False):
    """Traz uma janela pra frente sem simular teclas (a tecla Alt travava o Jon no 'modo menu')."""
    import ctypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    if maximizar:
        u.ShowWindow(hwnd, 3)                     # SW_MAXIMIZE
    elif u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)                     # SW_RESTORE
    frente = u.GetForegroundWindow()
    t_frente = u.GetWindowThreadProcessId(frente, None)
    t_eu = k.GetCurrentThreadId()
    juntou = t_frente and t_frente != t_eu and u.AttachThreadInput(t_frente, t_eu, True)
    try:
        u.BringWindowToTop(hwnd)
        ok = u.SetForegroundWindow(hwnd)
        if not ok:
            u.SwitchToThisWindow(hwnd, True)
    finally:
        if juntou:
            u.AttachThreadInput(t_frente, t_eu, False)
    return True


def _janela_do_processo(exe: str):
    """Acha a janela principal visível de um programa pelo nome do .exe (ex.: 'spotify.exe')."""
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    achada = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        if user32.GetWindow(hwnd, 4):  # tem dono (popup) -> ignora
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)
        if h:
            buf = ctypes.create_unicode_buffer(520)
            n = wintypes.DWORD(520)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                if buf.value.lower().endswith("\\" + exe.lower()):
                    achada.append(hwnd)
            kernel32.CloseHandle(h)
        return True

    user32.EnumWindows(cb, 0)
    return achada[0] if achada else None


def trazer_pra_frente(hwnd) -> bool:
    return trazer_janela_pra_frente(hwnd)


def focar_janela(titulo: str) -> bool:
    exe = {"spotify": "spotify.exe", "discord": "discord.exe", "claude": "claude.exe"}.get(titulo.lower())
    if exe:
        try:
            hwnd = _janela_do_processo(exe)
            if hwnd:
                return trazer_pra_frente(hwnd)
        except Exception:
            pass
    try:
        import pygetwindow as gw
        for w in gw.getWindowsWithTitle(titulo):
            if w.title.strip():
                if w.isMinimized:
                    w.restore()
                w.activate()
                return True
    except Exception:
        pass
    return False


def detectar_tipo(busca: str) -> str:
    b = " " + busca + " "
    if re.search(r"\b(playlist|playlists)\b", b):
        return "playlist"
    if re.search(r"\b(album|disco)\b", b):
        return "album"
    if re.search(r"\b(artista|banda|cantor|cantora|grupo|musicas do|musicas da|musicas de)\b", b):
        return "artista"
    return "auto"


CURTIDAS = (r"\b(em |nas |dentro das |das |nas minhas |em minhas |das minhas |minhas )*"
            r"(minhas )?(musicas )?(curtidas|favoritas|que eu curti)\b(\s+do spotify)?")


def spotify(busca: str = "", tocar: bool = False, abrir: bool = False):
    global ultimo_app, ultimo_app_hora
    curtidas = bool(re.search(CURTIDAS, busca))
    busca = re.sub(CURTIDAS, " ", busca)
    busca = re.sub(r"\s+", " ", busca).strip()
    tipo = detectar_tipo(busca) if busca else "auto"
    busca = limpar_busca_musica(busca) if busca else ""
    busca = re.sub(r"^\s*(a |o )?(playlist|album|disco)\s+(de |do |da )?", "", busca).strip()

    if SEMPRE_TOCAR:
        tocar = True   # pesquisou música no Spotify -> já dá play
    if tocar and spotify_api.disponivel() and (busca or curtidas):
        try:
            if busca:
                oque = spotify_api.tocar(busca, tipo, curtidas=curtidas)
            else:
                oque = spotify_api.tocar_curtidas()
            print(f"  -> Spotify tocando{' no celular' if no_celular() else ''}: {oque}")
            if abrir and not no_celular():
                if not focar_janela("Spotify"):
                    os.startfile("spotify:")
            ultimo_app, ultimo_app_hora = "spotify", time.time()
            return
        except spotify_api.AbrirNoCelular as e:
            abrir_no_celular(e.uri, "Abrir no Spotify")
            _ctx.pendente = {"depois": []}
            _tocar_quando_celular_abrir(e, _ctx.pendente)
            print(f"  -> Abrindo o Spotify no celular: {e.nome}")
            ultimo_app, ultimo_app_hora = "spotify", time.time()
            return
        except Exception as e:
            print("  (API do Spotify falhou, só vou pesquisar):", e)

    if no_celular():
        abrir_no_celular("spotify:search:" + urllib.parse.quote(busca) if busca else "spotify:", "Abrir no Spotify")
        print("  -> Spotify no celular" + (f": pesquisando '{busca}'" if busca else ""))
        ultimo_app, ultimo_app_hora = "spotify", time.time()
        return

    if busca:
        print(f"  -> Spotify: pesquisando '{busca}'")
        # Pesquisa DENTRO do app do Spotify (funciona com ele já aberto ou fechado)
        os.startfile("spotify:search:" + urllib.parse.quote(busca))
    else:
        print("  -> abrindo Spotify")
        os.startfile("spotify:")
    time.sleep(1.2)
    focar_janela("Spotify")
    ultimo_app, ultimo_app_hora = "spotify", time.time()


# Lembra qual app você abriu por último: se acabou de abrir o Spotify,
# "pesquisa X" / "toca X" / "procura X" vão pro Spotify em vez do Google.
ultimo_app = None
ultimo_app_hora = 0.0
CONTEXTO_SEGUNDOS = 180


def contexto_spotify() -> bool:
    return ultimo_app == "spotify" and (time.time() - ultimo_app_hora) < CONTEXTO_SEGUNDOS


def pesquisar(busca: str):
    print(f"  -> Google: {busca}")
    if no_celular():
        abrir_no_celular("https://www.google.com/search?q=" + urllib.parse.quote(busca), "Ver no Google")
        return
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(busca))


def mandar_pro_claude(texto: str):
    """Abre o app do Claude, cola o texto e envia."""
    print(f"  -> Claude: {texto}")
    try:
        import pygetwindow as gw
        janelas = [w for w in gw.getWindowsWithTitle("Claude") if w.title.strip()]
        if janelas:
            j = janelas[0]
            if j.isMinimized:
                j.restore()
            j.activate()
        else:
            os.startfile("claude:")
            time.sleep(4)
    except Exception:
        os.startfile("claude:")
        time.sleep(4)
    time.sleep(0.8)
    pyperclip.copy(texto)
    keyboard.send("ctrl+v")
    time.sleep(0.3)
    keyboard.send("enter")


def tecla_midia(cmd: str):
    mapa = {
        "pausa": "play/pause media", "pausar": "play/pause media", "play": "play/pause media",
        "continua": "play/pause media", "continuar": "play/pause media",
        "proxima": "next track", "proxima musica": "next track", "pula": "next track", "pular": "next track",
        "anterior": "previous track", "musica anterior": "previous track", "volta": "previous track",
        "aumenta o volume": "volume up", "aumentar volume": "volume up", "sobe o volume": "volume up",
        "abaixa o volume": "volume down", "diminui o volume": "volume down", "baixa o volume": "volume down",
        "muta": "volume mute", "mudo": "volume mute", "silencio": "volume mute",
    }
    cmd = re.sub(r"^(da |de |faz |fazer )", "", cmd)
    cmd = re.sub(r"\s+(a |o |essa |esse )?(musica|som|spotify|video|faixa)$", "", cmd).strip()
    cmd = {"pausar": "pausa", "pause": "pausa", "para": "pausa", "parar": "pausa", "despausa": "continua",
           "despausar": "continua", "volta a tocar": "continua", "proximo": "proxima",
           "pula": "proxima", "pular": "proxima", "passa": "proxima", "passar": "proxima"}.get(cmd, cmd)
    tecla = mapa.get(cmd)
    if tecla and no_celular() and spotify_api.disponivel():
        # pelo celular: controla o Spotify que estiver tocando (no celular ou no PC)
        try:
            if "volume" in tecla:
                txt = spotify_api.mudar_volume(0 if "mute" in tecla else None,
                                               delta=10 if "up" in tecla else -10)
            else:
                acao = {"play/pause media": "pausa" if cmd == "pausa" else "continua",
                        "next track": "proxima", "previous track": "anterior"}[tecla]
                spotify_api.controle(acao)
                txt = {"pausa": "Pausado", "continua": "Tocando", "proxima": "Próxima",
                       "anterior": "Anterior"}[acao]
            print(f"  -> Spotify: {txt}")
        except Exception as e:
            print("  Erro no Spotify:", e)
        return True
    if tecla:
        vezes = 5 if "volume" in tecla and "mute" not in tecla else 1
        for _ in range(vezes):
            keyboard.send(tecla)
        print(f"  -> mídia: {tecla}")
        return True
    return False


# ---------------------- INTERPRETADOR ----------------------

def controles_spotify(f: str) -> bool:
    """Repetir, aleatório, volume %, curtir, fila, recomeçar, 'que música é essa'.
    f = frase normalizada. Retorna True se tratou. Uma frase pode ter vários comandos."""
    if not spotify_api.disponivel():
        return False
    feito = []

    def rodar(fn, *args):
        try:
            feito.append(fn(*args))
        except Exception as e:
            print("  Erro no Spotify:", e)

    # adicionar na fila: "adiciona Yellow na fila"
    m = re.match(r"^(adiciona|adicionar|coloca|colocar|bota|poe|add|joga)\s+(.+?)\s+(na|pra|para a|para) fila$", f)
    if m:
        rodar(spotify_api.adicionar_fila, limpar_busca_musica(m.group(2)))
    else:
        desligar = re.search(r"\b(tira|tirar|desliga|desligar|desativa|desativar|para de|parar de|sai do|sem|cancela|chega de)\b", f)
        # repetir / loop
        if re.search(r"\b(loop|looping|repet\w*|repeat|de novo e de novo)\b", f):
            if desligar:
                rodar(spotify_api.repetir, "off")
            elif re.search(r"\b(playlist|album|lista|disco|tudo|todas)\b", f):
                rodar(spotify_api.repetir, "context")
            else:
                rodar(spotify_api.repetir, "track")
        # aleatório
        if re.search(r"\b(aleatori\w*|shuffle|embaralha\w*|misturad\w*)\b", f):
            rodar(spotify_api.aleatorio, not desligar)
        # volume com número: "volume 40", "volume no 70 por cento", "volume no máximo"
        mv = re.search(r"\bvolume\b\D{0,15}(\d{1,3})", f)
        if mv:
            rodar(spotify_api.mudar_volume, int(mv.group(1)))
        elif re.search(r"\bvolume\b.*\b(maximo|todo|tudo)\b", f):
            rodar(spotify_api.mudar_volume, 100)
        elif re.search(r"\bvolume\b.*\b(metade|meio)\b", f):
            rodar(spotify_api.mudar_volume, 50)
        # curtir / descurtir a música atual
        if not re.match(r"^(toca|tocar|toque|coloca|bota|poe|pesquisa|procura|abre)\b", f):
            if re.search(r"\b(descurt\w*|tira\w* (dos|das|de) (curtid|favorit)\w*)", f):
                rodar(spotify_api.curtir_atual, False)
            elif re.search(r"\b(curt\w*|salva\w*|favorita\w*|da (um )?like|deixa (um )?like|gostei)\b", f) and \
                    not re.search(r"\bmusicas curtidas\b", f):
                rodar(spotify_api.curtir_atual, True)
        # recomeçar
        if re.search(r"\b(volta|voltar|recomeca|recomecar|reinicia|reiniciar|comeca de novo)\b.*\b(comeco|inicio|musica|faixa)\b", f) \
                or re.search(r"\bdo (comeco|inicio)\b", f):
            if not re.search(r"\b(anterior|passada)\b", f):
                rodar(spotify_api.reiniciar_musica)
        # que música é essa?
        if re.search(r"\b(que|qual)\b.*\b(musica|som|faixa)\b.*\b(essa|esse|tocando|toca)\b", f) or \
                re.search(r"\bo que (ta|esta) tocando\b", f):
            try:
                feito.append("Está tocando " + spotify_api.tocando_agora())
            except Exception as e:
                print("  Erro no Spotify:", e)

    if not feito:
        return False
    for txt in feito:
        print(f"  -> Spotify: {txt}")
    falar(". ".join(feito))
    return True


# "pausa a música no Spotify", "parar o som", "próxima música", "dá play" -> controle, nunca pesquisa
ENCHIMENTO_MIDIA = (r"\b(a|o|essa|esse|da|do|na|no|pro|pra|pra mim|para mim|por favor|ai|agora|ja|ae|aqui|"
                    r"musica|musicas|som|faixa|spotify|video|player|reproducao|que (ta|esta) tocando)\b")
ACOES_MIDIA = {
    "pausa": r"(pausa|pausar|pause|pausei|para|parar|pare|stop|para de tocar|parar de tocar|desliga|desligar|"
             r"congela|segura)",
    "continua": r"(continua|continuar|continue|despausa|despausar|despause|volta a tocar|retoma|retomar|play|"
                r"da play|dar play|de play|da o play|solta|soltar)",
    "proxima": r"(proxima|proximo|pula|pular|pule|passa|passar|avanca|avancar|skip|troca|trocar|muda|mudar)",
    "anterior": r"(anterior|musica anterior|volta uma|voltar uma|retrocede|a de antes)",
}


def comando_midia(f: str) -> bool:
    resto = re.sub(r"\s+", " ", re.sub(ENCHIMENTO_MIDIA, " ", f)).strip()
    acao = next((a for a, rx in ACOES_MIDIA.items() if re.fullmatch(rx, resto)), None)
    if not acao:
        return False
    txt = {"pausa": "Pausado", "continua": "Tocando", "proxima": "Próxima música", "anterior": "Música anterior"}[acao]
    if spotify_api.disponivel():
        try:
            spotify_api.controle(acao)
            print(f"  -> Spotify: {txt}")
            return True
        except Exception as e:
            print("  (API do Spotify falhou, usando as teclas de mídia):", e)
    if remoto():
        print("  -> Não consegui controlar o Spotify agora.")
        return True
    keyboard.send({"pausa": "play/pause media", "continua": "play/pause media", "proxima": "next track",
                   "anterior": "previous track"}[acao])
    print(f"  -> mídia: {txt}")
    return True


def controle_video(f: str) -> bool:
    """Filmes/vídeos: 'coloca o Stremio em tela cheia', 'pausa o filme', 'avança 30 segundos', 'próximo episódio'.
    Sem dizer o player, só vale se um vídeo estiver na frente (ex.: você segurou F9 vendo Netflix)."""
    if re.search(r"\b(musica|musicas|spotify|playlist|curtidas)\b", f):
        return False
    try:
        pedido_ = video.entender(f)
    except Exception:
        return False
    if not pedido_:
        return False
    acao, vezes, player = pedido_
    tem_alvo = bool(re.search(video.ALVO, f))
    try:
        foco = video.em_foco()
    except Exception:
        foco = None
    recente = video.ultimo if video.ultimo and time.time() - video.ultimo[1] < 25 else None
    if not tem_alvo and not foco:
        if not recente:
            return False                  # ex.: "tela cheia" com o Jon na frente = modo Big Picture
        player = recente[0]               # "abre o Stremio" + "coloca em tela cheia": vale pro Stremio
        for _ in range(20):               # espera a janela dele aparecer
            if video.achar(player)[0]:
                break
            time.sleep(0.5)
        if time.time() - recente[1] < 6:
            time.sleep(2.5)               # acabou de abrir: ainda está carregando
    # "abre o Stremio e coloca em tela cheia": abre primeiro, espera e depois faz
    if player and re.match(r"^(abre|abrir|abra|inicia|iniciar)\b", f):
        h, _ = video.achar(player)
        if not h:
            abrir_app(player)
            for _ in range(20):
                time.sleep(0.5)
                h, _ = video.achar(player)
                if h:
                    break
            time.sleep(2.5)               # o player ainda está carregando
    resp = video.controlar(acao, vezes, player)
    print(f"  -> {resp}")
    return True


def avisar(texto: str):
    """Lembrete/rotina disparou: bipa, mostra e fala."""
    for f_, d in ((880, 150), (1100, 150), (880, 150)):
        _tocar_bip(f_, d)
    print(f"  🔔 {texto}")
    falar(texto)


rotinas.avisar = avisar
rotinas.executar_comando = lambda texto: executar(texto)


# ---------------------- pedidos vindos do celular ----------------------
_ctx = threading.local()


def remoto() -> bool:
    return getattr(_ctx, "remoto", False)


def _ctx_set(chave, valor):
    if remoto():
        setattr(_ctx, chave, valor)


def coletar(linha: str):
    """Chamado pela saída do app: guarda as linhas do pedido do celular que está rodando nesta thread."""
    if remoto():
        _ctx.linhas.append(linha)


def no_celular() -> bool:
    """Pedido feito pelo celular (e sem dizer 'no PC'): música, vídeo e apps abrem no celular."""
    return remoto() and getattr(_ctx, "celular", False)


def abrir_no_celular(url: str, rotulo: str):
    _ctx.abrir.append({"url": url, "rotulo": rotulo})


def _tocar_quando_celular_abrir(e, pendente):
    """Depois que o celular abre o Spotify, ele aparece pro Jon: aí dá o play e aplica repeat/aleatório."""
    def rodar():
        _ctx.remoto, _ctx.celular, _ctx.falas, _ctx.linhas, _ctx.fontes, _ctx.abrir = True, True, [], [], [], []
        spotify_api.usar_celular(True)
        if spotify_api.tocar_quando_celular_abrir(e.contexto, e.faixa):
            print(f"  (celular: tocando {e.nome})")
            time.sleep(1.0)
            for ctl in pendente["depois"]:
                controles_spotify(ctl)
    threading.Thread(target=rodar, daemon=True).start()


def executar_remoto(texto: str, destino: str = "celular") -> dict:
    """Executa um comando vindo do celular e devolve a resposta (o PC não fala; quem fala é o celular).
    destino = botão da página (telefone/computador). Falar "no computador" / "no telefone" no comando
    manda só aquele comando pra lá."""
    _ctx.remoto, _ctx.falas, _ctx.linhas, _ctx.fontes, _ctx.abrir = True, [], [], [], []
    _ctx.pendente = None
    LUGAR = r"\s*,?\s*\b(no|na|pelo|pela|pro|pra|para o|para a|em|no meu|pelo meu|em meu)\s+(meu\s+)?"
    if re.search(LUGAR + r"(pc|computador|desktop)\b", texto, flags=re.I):
        destino = "pc"
    elif re.search(LUGAR + r"(telefone|celular|iphone)\b", texto, flags=re.I):
        destino = "celular"
    _ctx.celular = destino != "pc"
    texto = re.sub(LUGAR + r"(pc|computador|desktop|telefone|celular|iphone)\b", " ", texto, flags=re.I).strip() or texto
    spotify_api.usar_celular(_ctx.celular)
    try:
        print(f'Você disse (celular): "{texto}"' + ("" if _ctx.celular else "  [no PC]"))
        executar(texto)
    except Exception as e:
        _ctx.linhas.append(f"Erro: {e}")
    finally:
        _ctx.remoto = False
        spotify_api.usar_celular(False)
    acoes = [l.strip()[2:].strip() for l in _ctx.linhas if l.strip().startswith("->")]
    resposta = " ".join(_ctx.falas) or (acoes[-1] if acoes else "Feito.")
    return {"resposta": resposta, "acoes": acoes, "fontes": _ctx.fontes, "abrir": _ctx.abrir[:1]}


# o app troca estas funções pra mostrar/esconder a própria janela
def mostrar_interface():
    return False


def modo_tela(abrir: bool):
    return False


def checar_atualizacao():
    return False


def esconder_interface():
    return False


# frases que, vindas do celular, viram pesquisa na internet direto (sem passar pela IA antes)
PERGUNTA = (r"^(pesquisa|pesquise|pesquisar|procura|procure|busca|busque|google|veja|ve|descobre|descubra|"
            r"me diz|me fala|me fale|sabe|voce sabe|qual|quais|quanto|quantos|quantas|quando|onde|como|"
            r"por que|porque|o que|quem|existe|tem como|vale a pena|e verdade)\b")

INTERFACE = r"\b(interfa\w*|interfe\w*|painel|hud|sua tela|sua janela|seu app|seu aplicativo|o jon|voce)\b"


def comandos_jarvis(f: str, original: str) -> bool:
    """Hora, data, clima, briefing, status do sistema, lembretes/timers/rotinas, pastas, print, fechar apps."""
    resp = None
    # procurar atualização do Jon no GitHub
    if re.search(r"\b(atualiza|atualizar|atualize|atualizacao|atualizacoes|update)\b", f) and \
            re.search(r"\b(jon|voce|se|sistema|assistente|versao|tem|procura|procurar|checa|checar|verifica)\b", f) \
            and not re.search(r"\b(windows|driver|steam|spotify|chrome|jogo)\b", f):
        if checar_atualizacao():
            resp = "Vou olhar no GitHub se tem versão nova."
            print(f"  -> {resp}")
            falar(resp)
            return True
    # modo Big Picture (tela cheia estilo Steam)
    if re.search(r"\b(big picture|bigpicture|big pic\w*|modo (tela cheia|imersivo|tv|televisao|cinema|sofa))\b", f) \
            or re.match(r"^(tela cheia|abre (a )?tela cheia|modo grande)$", f):
        sair = re.search(r"\b(sai|sair|saia|fecha|fechar|feche|desliga|desligar|tira|volta|voltar)\b", f)
        if modo_tela(not sair):
            resp = "Saindo do modo Big Picture." if sair else "Modo Big Picture."
            print(f"  -> {resp}")
            falar(resp)
            return True
    # abrir / esconder a interface do Jon
    if re.match(r"^(aparece|aparecer|aparece ai|mostra a cara|cade voce|apareca|volta|volta pra tela|"
                r"tela cheia|abre tudo)$", f) or (
            re.search(r"\b(abre|abrir|abra|mostra|mostrar|exibe|exibir|traz|trazer|aparece|maximiza|maximizar|"
                      r"volta|voltar|chama)\b", f) and re.search(INTERFACE, f) and "pasta" not in f):
        if mostrar_interface():
            resp = "Aqui estou."
    elif re.search(r"\b(esconde|esconder|minimiza|minimizar|fecha|fechar|some)\b", f) and \
            re.search(INTERFACE, f) and "pasta" not in f:
        if esconder_interface():
            resp = "Fico aqui em segundo plano. É só me chamar."
    if resp:
        print(f"  -> {resp}")
        falar(resp)
        return True
    # lembretes / timers / rotinas
    pedido = rotinas.interpretar(f, original)
    if pedido:
        resp = rotinas.aplicar(pedido)
    # e-mails não lidos: "tenho e-mail novo?", "lê meus e-mails"
    elif re.search(r"\b(e-?mails?|e mails?|caixa de entrada)\b", f) and \
            re.search(r"\b(tenho|tem|chegou|chegaram|novo|novos|nova|le|ler|leia|ver|veja|meus|meu|algum|quantos)\b", f) \
            and not re.search(r"\b(manda|mandar|envia|enviar|escreve|escrever|responde|responder)\b", f):
        import painel_extra
        resp = painel_extra.resumo_email_falado()
    # hora e data
    elif re.search(r"\b(que horas|que hora|horas sao|hora agora)\b", f):
        resp = extras.hora_texto()
    elif re.search(r"\b(que dia|qual (a|e a) data|data de hoje|dia e hoje|dia da semana)\b", f):
        resp = extras.data_texto()
    # clima
    elif re.search(r"\b(tempo|clima|previsao|temperatura|vai chover|chovendo|calor|frio)\b", f) and \
            not re.search(r"\b(timer|toca|musica|quanto tempo)\b", f):
        m = re.search(r"\b(?:em|no|na|de)\s+([a-z][a-z ]+?)(?:\s+(?:hoje|amanha|agora))?$", f)
        cidade = m.group(1) if m and m.group(1) not in ("hoje", "amanha", "agora", "casa") else ""
        cidade = rotinas._com_acentos(cidade, original) if cidade else ""
        try:
            resp = extras.clima(cidade, amanha="amanha" in f)
        except Exception as e:
            resp = "Não consegui ver o clima agora."
            print("  Erro no clima:", e)
    # briefing
    elif re.search(r"^(bom dia|boa tarde|boa noite)$|\b(resumo do dia|briefing|como (esta|ta) meu dia|meu dia)\b", f):
        import perfil
        quem = perfil.nome()
        partes = [f"{extras.saudacao()}{', ' + quem if quem else ''}! {extras.hora_texto()}"]
        try:
            partes.append(extras.clima())
        except Exception:
            pass
        partes.append(rotinas.listar_texto())
        try:
            alerta = sistema.alertas({**sistema.leitura(), "gpu": sistema.gpu()})
            if alerta:
                partes.append("Atenção: " + "; ".join(alerta) + ".")
        except Exception:
            pass
        resp = " ".join(partes)
    # status do sistema
    elif re.search(r"\b(status|diagnostico|como (esta|ta)) (do|o) (sistema|pc|computador)\b|\bstatus do sistema\b", f):
        resp = sistema.resumo_falado()
    # pastas e discos
    elif re.match(r"^(abre|abrir|abra|mostra)\s+(a\s+|o\s+)?(pasta|disco|drive|unidade)\s+(de\s+|do\s+|da\s+)?(.+)$", f):
        m = re.match(r"^(abre|abrir|abra|mostra)\s+(a\s+|o\s+)?(pasta|disco|drive|unidade)\s+(de\s+|do\s+|da\s+)?(.+)$", f)
        alvo = m.group(5) if m.group(3) == "pasta" else m.group(3) + " " + m.group(5)
        resp = extras.abrir_pasta(alvo) or None
    elif re.match(r"^(abre|abrir|abra)\s+(a\s+|os\s+|meus\s+|minhas\s+)?(downloads|documentos|imagens|fotos|videos|area de trabalho)$", f):
        resp = extras.abrir_pasta(f.split()[-1] if "area" not in f else "area de trabalho")
    # print, fechar, minimizar, bloquear
    elif re.search(r"\b(tira|tirar|faz|fazer)\s+(um\s+)?(print|captura|screenshot)\b", f):
        resp = extras.print_tela()
    elif re.match(r"^(fecha|fechar|feche|encerra|encerrar|mata)\s+(o\s+|a\s+)?(.+)$", f) and "assistente" not in f:
        resp = extras.fechar_app(re.match(r"^(fecha|fechar|feche|encerra|encerrar|mata)\s+(o\s+|a\s+)?(.+)$", f).group(3))
    elif re.search(r"\b(minimiza tudo|mostra a area de trabalho|esconde tudo)\b", f):
        resp = extras.minimizar_tudo()
    elif re.search(r"\b(bloqueia|trava|tranca)\s+(o\s+)?(pc|computador|tela)\b", f):
        resp = extras.bloquear_pc()
    # otimizar PC / limpar memória / limpar arquivos temporários / esvaziar lixeira
    elif re.search(r"\b(otimiza\w*|limpa\w*|libera\w*|acelera\w*|desfragmenta\w*|turbo)\b.*\b(pc|computador|sistema|memoria|ram|arquivos temporarios|cache|disco)\b", f) \
            or re.match(r"^(otimizar|otimiza|limpar pc|limpar computador|liberar memoria|liberar ram|limpar memoria)$", f):
        resp = extras.otimizar_pc()
    elif re.search(r"\b(esvazia\w*|limpa\w*)\s+(a\s+)?lixeira\b", f):
        resp = extras.esvaziar_lixeira()
    elif re.search(r"\b(organiza\w*|arruma\w*)\s+(a\s+|os\s+|meus\s+)?(pasta\s+(de\s+)?)?(downloads?|area de trabalho|desktop|documentos)\b", f):
        qual = "desktop" if ("area" in f or "desktop" in f) else "documentos" if "documento" in f else "downloads"
        resp = extras.organizar_pasta(qual)
    elif re.search(r"\b(quais|que)\s+(programas?|processos?|apps?)\s+(estao\s+|ta\s+)?(pesados?|gastando|consumindo|usando)\b|\bprocessos pesados\b|\bo que (ta|esta) deixando o pc lento\b", f):
        resp = extras.processos_pesados()
    elif re.match(r"^(cria|criar|crie|nova)\s+(uma\s+|a\s+)?pasta\s+(?:chamada\s+|com\s+o\s+nome\s+|de\s+nome\s+)?(.+)$", f):
        resto_p = re.match(r"^(?:cria|criar|crie|nova)\s+(?:uma\s+|a\s+)?pasta\s+(?:chamada\s+|com\s+o\s+nome\s+|de\s+nome\s+)?(.+)$", original, flags=re.I).group(1).strip()
        onde_p = "desktop"
        m_onde = re.search(r"\s+(?:na|no|em|dentro\s+de|dentro\s+da|nos|nas)\s+(area de trabalho|desktop|documentos|downloads|imagens|fotos|videos|musicas|disco\s+[a-z])$", normalizar(resto_p))
        if m_onde:
            onde_p = m_onde.group(1)
            resto_p = resto_p[:m_onde.start()].strip()
        resto_p = re.sub(r"^(chamada|com nome|de nome)\s+", "", resto_p, flags=re.I).strip(" \"'")
        resp = extras.criar_pasta(resto_p, onde_p)
    # pesquisa de verdade (busca + resumo falado)
    elif "spotify" not in f and "youtube" not in f and (
            re.match(r"^(me fala sobre|me fale sobre|me explica|me explique|pesquisa pra mim|pesquisa para mim|"
                     r"pesquisa sobre|pesquise sobre|o que e|o que sao|quem e|quem foi|quem sao|quanto custa|"
                     r"como funciona|qual o preco|qual e o preco|quando e|quando foi|onde fica)\b", f)
            or (remoto() and re.match(r"^(pesquisa|pesquise|pesquisar|procura|procure|busca|busque|google|"
                                      r"veja|ve|descobre|descubra)\b", f))):
        resp = fazer_pesquisa(original)
    if not resp:
        return False
    print(f"  -> {resp}")
    falar(resp)
    return True


def fazer_pesquisa(original: str) -> str:
    """Busca na internet e devolve um resumo curto pra falar."""
    consulta = re.sub(r"^(me fala sobre|me fale sobre|me explica|me explique|pesquisa|pesquise|pesquisar|"
                      r"procura|procure|busca|busque|google|veja|ve|vê|descobre|descubra|me diz|me fala|"
                      r"me fale|sabe)\s+(pra mim|para mim)?\s*(sobre|na internet|se|que)?\s*",
                      "", original, flags=re.I)
    consulta = re.sub(r"\b(pra mim|para mim|por favor)\b", "", consulta, flags=re.I)
    consulta = re.sub(r"\s+", " ", consulta).strip(" ,.?") or original
    resp = ""
    print(f"  🔎 pesquisando: {consulta}")
    ao_status("processando")
    try:
        r = pesquisa.pesquisar(consulta, ia_local)
        resp = r["resposta"]
        _ctx_set("fontes", r["fontes"])
        for fonte in r["fontes"][:3]:
            print(f"  (fonte: {fonte['titulo']})")
    except Exception as e:
        resp = "Não consegui pesquisar agora."
        print("  Erro na pesquisa:", e)
    return resp


HISTORICO = []
# pedido + modo no fim: "toca Yellow e deixa em loop", "abre o spotify ... e tocar no repeat"
CTL_NO_FIM = (r"^(?P<pedido>.+?)[\s,]+(?:e\s+)?(?P<ctl>(?:(?:deixa|deixar|deixe|coloca|colocar|coloque|bota|botar|"
              r"poe|toca|tocar|toque|ja|fica|ficar)\s+)*(?:ela\s+|a musica\s+|isso\s+)?(?:no|em|com|de|na)?\s*"
              r"(?:modo\s+)?(?:repeat|repet\w*|loop\w*|aleatori\w*|shuffle)\b.*)$")


VERBOS_COMANDO = (r"(abre|abrir|abra|fecha|fechar|feche|toca|tocar|toque|coloca|colocar|coloque|bota|botar|poe|por|"
                  r"pausa|pausar|pause|para|parar|pare|continua|continuar|continue|despausa|despausar|da play|"
                  r"dar play|de play|play|volta|voltar|volte|avanca|avancar|avance|adianta|adiantar|pula|pular|"
                  r"pule|passa|passar|aumenta|aumentar|abaixa|abaixar|diminui|diminuir|muta|mutar|deixa|deixar|"
                  r"liga|ligar|desliga|desligar|tira|tirar|pesquisa|pesquisar|procura|procurar|busca|buscar|"
                  r"me lembra|lembra|mostra|mostrar|minimiza|minimizar|maximiza|maximizar|bloqueia|curte|curtir|"
                  r"repete|repetir|sai|sair|entra|entrar|recomeca|recomecar|reinicia|reiniciar|comeca|sobe|baixa|"
                  r"ativa|ativar|desativa|desativar|seleciona|escolhe|inicia|iniciar|executa|joga|manda|mande)")
SEPARADOR = (r"\s*[,;]\s*(?:e\s+)?(?:depois\s+|em seguida\s+|entao\s+)?|"
             r"\s+(?:e\s+(?:depois\s+|em seguida\s+|tambem\s+|ja\s+|logo\s+)?|depois\s+|em seguida\s+|entao\s+)")


def dividir_comandos(texto: str):
    """'bota tela cheia e dá play' -> ['bota tela cheia', 'dá play'].
    Só corta quando o pedaço seguinte começa com um verbo de comando (não corta 'toca Simon e Garfunkel')."""
    pedacos, inicio = [], 0
    for m in re.finditer(SEPARADOR, texto, flags=re.I):
        resto = normalizar(texto[m.end():])
        resto = re.sub(r"^(jon|john|ai|tambem|ja)\s+", "", resto)
        if re.match(VERBOS_COMANDO + r"\b", resto) and \
                not re.match(r"(deixa|deixar|coloca|colocar|bota|botar|poe)\s+(ela\s+|a musica\s+)?(no|em|com|de|na)?\s*"
                             r"(modo\s+)?(repeat|repet|loop|aleatori|shuffle)", resto):   # 'toca X e deixa no repeat' tem caminho próprio
            pedacos.append(texto[inicio:m.start()].strip(" ,"))
            inicio = m.end()
    pedacos.append(texto[inicio:].strip(" ,"))
    return [p for p in pedacos if p]


def executar(frase: str):
    original = re.sub(r"^\s*(ei|oi|hey|ok|e ai|fala)?[\s,]*(jon|john|jhon|jonh|jonny|djon)\b[\s,.!:]*", "",
                      frase.strip(), flags=re.I).strip() or frase.strip()
    partes = dividir_comandos(original)
    if len(partes) > 1:
        print(f"  ({len(partes)} comandos: " + " → ".join(f'“{p}”' for p in partes) + ")")
        for k, parte in enumerate(partes):
            if k:
                time.sleep(0.9)            # dá tempo do comando anterior acontecer (abrir app, tela cheia...)
            executar_um(parte)
        return
    executar_um(original)


def executar_um(frase: str):
    original = frase.strip()
    # "Jon, toca X" / "ei Jon abre o Discord" -> tira o nome
    original = re.sub(r"^\s*(ei|oi|hey|ok|e ai|fala)?[\s,]*(jon|john|jhon|jonh|jonny|djon)\b[\s,.!:]*", "",
                      original, flags=re.I).strip() or original
    HISTORICO.append(original)
    del HISTORICO[:-10]
    # Apelidos que você ensinou ("quando eu falar X, faça Y")
    try:
        trocado = ia_local.aplicar_apelido(original)
        if trocado and ia_local.norm(trocado) != ia_local.norm(original):
            print(f"  (apelido → \"{trocado}\")")
            original = trocado
    except Exception as e:
        print("  (erro lendo a memória):", e)
    f = normalizar(original)
    f = re.sub(r"[.!?,]+$", "", f)

    if f in ("fechar assistente", "encerrar assistente", "desligar assistente"):
        print("Encerrando. Até mais!")
        bip(600, 300)
        time.sleep(0.4)
        os._exit(0)

    if controle_video(f):
        return

    if comandos_jarvis(f, original):
        return

    # "abre o Spotify, procura X e toca no repeat" -> primeiro toca X, depois liga o repeat/aleatório
    m = re.match(CTL_NO_FIM, f)
    if m and spotify_api.disponivel():
        pedido = m.group("pedido")
        conteudo = re.sub(r"\b(abre|abrir|abra|toca|tocar|toque|coloca|coloque|colocar|bota|botar|poe|deixa|o|a|e|"
                          r"no|na|essa|esse|ela|musica|isso|tira|tirar|do|da)\b", " ", pedido).strip()
        if "spotify" in pedido or (re.match(r"^(toca|tocar|toque|coloca|coloque|bota|poe|quero ouvir|ouvir|escutar|"
                                            r"pesquisa|procura|busca)\b", pedido) and len(conteudo) >= 3):
            executar(pedido)
            pend = getattr(_ctx, "pendente", None) if remoto() else None
            if pend is not None:       # celular ainda vai abrir o Spotify: aplica o modo quando a música começar
                pend["depois"].append(m.group("ctl"))
                return
            time.sleep(1.5)            # espera a música começar antes de mudar o modo
            controles_spotify(m.group("ctl"))
            return

    if comando_midia(f):
        return

    if controles_spotify(f):
        return

    if tecla_midia(f):
        return

    # "claude, ..." -> manda pro app do Claude (mantém acentos do original)
    m = re.match(r"^(ei |oi |hey )?claude[,:]?\s+(.+)$", f)
    if m:
        resto = re.sub(r"^(ei |oi |hey )?claude[,:]?\s+", "", original, flags=re.I)
        mandar_pro_claude(resto)
        return

    TOCAR = r"\b(toca|tocar|toque|coloca|coloque|colocar|bota|botar|poe|ouvir|escutar|play)\b"
    ABRIR = r"\b(abre|abrir|abra|inicia|iniciar|mostra|mostrar)\b"
    # "... e tocar", "... pra tocar", "... e dar play" no fim da frase
    FIM_TOCAR = (r"(\s+(e|pra|para|e depois|e ja))?(\s+|^)(toca|tocar|toque|da play|dar play|de play|reproduz|reproduzir|"
                 r"coloca|colocar|bota|botar)(\s+(ela|essa|isso|a musica|pra mim|o primeiro|a primeira))*\s*$")
    VERBOS = (r"(toca|tocar|toque|coloca|coloque|colocar|bota|botar|poe|ouvir|escutar|"
              r"procura|procurar|procure|pesquisa|pesquisar|pesquise|busca|buscar|busque|acha|achar|ache|"
              r"abre|abrir|abra|ver|assistir|mostra|mostrar)")

    # Pedido vago/descritivo ("aquela que fala de...", "alguma música pra treinar") -> IA resolve
    VAGO = (r"\b(aquela|aquele|aquilo|que fala|que diz|que tem|que toca|alguma|algum|algo|qualquer|"
            r"pra (treinar|estudar|dormir|relaxar|focar|malhar)|tipo|parecid|igual|lembra|sabe qual)\b")
    if re.search(VAGO, f) and ia_local.disponivel():
        f = "__ia__"

    # ---------- YOUTUBE: qualquer frase que mencione youtube ----------
    if "youtube" in f:
        nav = next((n for n in ("chrome", "edge", "firefox", "opera") if n in f), None)
        busca = re.sub(r"\b(no|na|do|pelo|pro|para o|pra|com o|com a|em|o|a)?\s*youtube\b", " ", f)
        # tira o navegador e as ligações: "abre o google chrome com o youtube", "entra no youtube pelo chrome"
        busca = re.sub(r"\b(no|na|pelo|pela|com|em|o|a)?\s*(google chrome|chrome|navegador|microsoft edge|edge|"
                       r"firefox|opera)\b", " ", busca)
        busca = re.sub(r"\b(por favor|pra mim|para mim|(o|a) site( do| da)?|(o |a )?(app|aplicativo|pagina inicial|"
                       r"pagina|inicio|tela inicial))\b", " ", busca)
        busca = re.sub(r"\b" + VERBOS + r"\b", " ", busca)
        busca = re.sub(r"\b(e|entra|entrar|entre|vai|ir|com|no|na|em|o|a|os|as|um|uma|ai|agora|la|pra|pro)\b", " ", busca)
        busca = re.sub(r"\s+", " ", busca).strip()
        # só pesquisa se você disse O QUE ver ("youtube lofi", "toca lofi no youtube"); senão abre a página inicial
        if busca:
            youtube(busca)
        elif no_celular():
            abrir_no_celular("youtube://", "Abrir o YouTube")
            print("  -> YouTube no celular")
        else:
            print("  -> abrindo o YouTube (página inicial)" + (f" no {nav}" if nav else ""))
            abrir_site("https://www.youtube.com", nav)
        return

    # ---------- SPOTIFY: qualquer frase que mencione spotify ----------
    # Ex.: "pesquisa Coldplay no Spotify", "no Spotify procura Yellow",
    #      "spotify Legião Urbana", "abre o Spotify e toca Matuê", "procura no spotify a música Tempo Perdido"
    if "spotify" in f:
        partes = re.split(r"\bspotify\b", f, maxsplit=1)
        antes, depois = partes[0], partes[1] if len(partes) > 1 else ""
        # tira "abre o", "no", "dentro do" etc.
        antes = re.sub(r"^\s*" + VERBOS + r"\b", " ", antes)
        antes = re.sub(r"\b(dentro|no|na|do|da|o|a|pelo|pro|para|pra|e|aplicativo|app|programa)\b", " ", antes)
        depois = re.sub(r"^\s*(e\s+)?(depois\s+)?" + VERBOS + r"?\b", " ", depois.strip())
        depois = re.sub(r"^\s*(e|,)\s*" + VERBOS + r"?\b", " ", depois.strip())
        busca = (antes.strip() + " " + depois.strip()).strip()
        busca = re.sub(r"^\s*" + VERBOS + r"\b", " ", busca).strip()
        busca = re.sub(FIM_TOCAR, "", busca).strip()
        spotify(busca, tocar=bool(re.search(TOCAR, f)), abrir=bool(re.search(ABRIR, f)))
        return

    # ---------- "toca X" sem dizer onde -> toca no Spotify ----------
    m = re.match(r"^(toca|tocar|toque|coloca|coloque|bota|poe|quero ouvir|ouvir|escutar)\s+(.+)$", f)
    if m:
        spotify(re.sub(FIM_TOCAR, "", m.group(2)).strip(), tocar=True)
        return

    # ---------- "pesquisa X": se o Spotify acabou de ser usado (ou falou "curtidas"), vai pro Spotify ----------
    m = re.match(r"^(pesquisa|pesquisar|pesquise|procura|procurar|procure|busca|buscar|busque|acha|ache)\s+(.+)$", f)
    if m and (contexto_spotify() or re.search(CURTIDAS, f)):
        spotify(re.sub(FIM_TOCAR, "", m.group(2)).strip(), tocar=bool(re.search(TOCAR, f)))
        return

    # abrir X
    m = re.match(r"^(abre|abrir|abra|inicia|iniciar|executa|executar|liga|ligar)\s+(.+)$", f)
    if m:
        abrir_app(m.group(2))
        return

    # pesquisar X (Google)
    m = re.match(r"^(pesquisa|pesquisar|pesquise|procura|procurar|procure|busca|buscar|busque|google)\s+(.+)$", f)
    if m:
        pesquisar(m.group(2))
        return

    # Celular: pergunta que nenhum comando reconheceu -> pesquisa direto (mais rápido que perguntar à IA o que fazer)
    if remoto() and (re.match(PERGUNTA, f) or original.strip().endswith("?")):
        resp = fazer_pesquisa(original)
        print(f"  -> {resp}")
        falar(resp)
        return

    # Já aprendi essa frase antes? -> instantâneo
    aprendida = ia_local.acao_aprendida(original)
    if aprendida:
        print("  (atalho aprendido)")
        executar_acao(aprendida, original)
        return

    # IA local entende frases livres
    if ia_local.disponivel():
        print("  🧠 pensando...")
        try:
            acao = ia_local.interpretar(original, HISTORICO[:-1])
            print(f"  (IA: {acao.get('acao')} em {acao.get('_segundos')}s)")
            acao.pop("_segundos", None)
            executar_acao(acao, original)
            try:
                ia_local.registrar_uso(original, acao)
            except Exception:
                pass
            return
        except Exception as e:
            print("  Erro na IA local:", e)

    if remoto():
        falar("Não entendi esse comando. Tenta falar de outro jeito.")
        return
    # Sem IA: manda pro app do Claude resolver
    print("  (comando não reconhecido — enviando pro Claude)")
    mandar_pro_claude(original)


# Motor de voz neural estilo J.A.R.V.I.S. (edge-tts: pt-BR-AntonioNeural grave) + fallback Windows Speech.
VOZ_JARVIS = "pt-BR-AntonioNeural"
VOZ_VELOCIDADE = "+6%"
VOZ_TOM = "-4Hz"

_VOZ_SCRIPT = (
    "[Console]::InputEncoding=[Text.Encoding]::UTF8;"
    "Add-Type -AssemblyName System.Speech;"
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "try{$s.SelectVoiceByHints('NotSet','NotSet',0,[Globalization.CultureInfo]'pt-BR')}catch{};"
    "try{$s.Rate=2;$s.SetOutputToDefaultAudioDevice()}catch{};"
    "while(($l=[Console]::In.ReadLine()) -ne $null){ try{$s.SpeakAsyncCancelAll(); if($l){ $s.SpeakAsync($l) | Out-Null }}catch{} }"
)
_voz = None
_voz_trava = threading.Lock()
_fala_id = 0
_tts_cache_pc = {}


def _motor_voz():
    global _voz
    if _voz is None or _voz.poll() is not None:
        _voz = subprocess.Popen(["powershell", "-NoProfile", "-NoLogo", "-Command", _VOZ_SCRIPT],
                                stdin=subprocess.PIPE, creationflags=0x08000000)
    return _voz


def _sintetizar_jarvis(texto: str) -> bytes:
    if texto in _tts_cache_pc:
        return _tts_cache_pc[texto]
    import asyncio
    import edge_tts

    async def _gerar():
        com = edge_tts.Communicate(texto, voice=VOZ_JARVIS, rate=VOZ_VELOCIDADE, pitch=VOZ_TOM)
        partes = []
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                partes.append(chunk["data"])
        return b"".join(partes)

    dados = asyncio.run(_gerar())
    if dados:
        if len(_tts_cache_pc) > 80:
            _tts_cache_pc.clear()
        _tts_cache_pc[texto] = dados
    return dados


def _tocar_mp3_jarvis(dados: bytes, meu_id: int) -> bool:
    import ctypes
    import tempfile
    if not dados or meu_id != _fala_id:
        return False
    fd, caminho = tempfile.mkstemp(prefix="jon_voz_", suffix=".mp3")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
        winmm = ctypes.windll.winmm
        alias = f"jarvis_{meu_id}"
        winmm.mciSendStringW(f'open "{caminho}" type mpegvideo alias {alias}', None, 0, 0)
        try:
            winmm.mciSendStringW(f"play {alias}", None, 0, 0)
            buf = ctypes.create_unicode_buffer(64)
            while meu_id == _fala_id:
                winmm.mciSendStringW(f"status {alias} mode", buf, 64, 0)
                if buf.value.strip().lower() != "playing":
                    break
                time.sleep(0.05)
        finally:
            winmm.mciSendStringW(f"stop {alias}", None, 0, 0)
            winmm.mciSendStringW(f"close {alias}", None, 0, 0)
        return True
    finally:
        try:
            os.remove(caminho)
        except OSError:
            pass


def preparar_voz():
    """Pré-aquece o motor de voz neural J.A.R.V.I.S. em segundo plano."""
    def ligar():
        try:
            _sintetizar_jarvis("Sistemas online.")
        except Exception:
            with _voz_trava:
                _motor_voz()
    threading.Thread(target=ligar, daemon=True).start()


def falar(texto: str):
    """Fala em voz alta com a voz neural J.A.R.V.I.S. (uma fala nova interrompe a anterior)."""
    global _voz, _fala_id
    if remoto():
        _ctx.falas.append(texto)          # pedido do celular: a resposta volta pro celular
        return
    if not FALAR_RESPOSTAS or not texto:
        return
    limpo = re.sub(r"[\r\n]+", " ", texto).strip()[:500]
    if not limpo:
        return
    _fala_id += 1
    meu_id = _fala_id

    def rodar():
        global _voz
        try:
            dados = _sintetizar_jarvis(limpo)
            if _tocar_mp3_jarvis(dados, meu_id):
                return
        except Exception:
            pass
        # Fallback: voz nativa do Windows se estiver sem internet ou sem edge-tts
        linha = limpo + "\n"
        with _voz_trava:
            for _ in range(2):
                try:
                    p = _motor_voz()
                    p.stdin.write(linha.encode("utf-8"))
                    p.stdin.flush()
                    return
                except Exception:
                    _voz = None

    threading.Thread(target=rodar, daemon=True).start()


def executar_acao(a: dict, frase_original: str = ""):
    """Executa a ação que a IA (ou a memória) escolheu."""
    tipo_acao = a.get("acao")
    txt = (a.get("texto") or "").strip()
    resp = (a.get("resposta") or "").strip()
    if tipo_acao == "abrir_app":
        alvo = normalizar(txt)
        if "spotify" in alvo:
            spotify("")
        else:
            abrir_app(txt)
    elif tipo_acao in ("tocar_spotify", "pesquisar_spotify"):
        busca = normalizar(txt)
        if a.get("tipo") in ("artista", "album", "playlist") and busca:
            busca = {"artista": "a banda ", "album": "o album ", "playlist": "a playlist "}[a["tipo"]] + busca
        if a.get("curtidas"):
            busca = (busca + " nas minhas musicas curtidas").strip()
        spotify(busca, tocar=True)
    elif tipo_acao == "youtube":
        youtube(txt)
    elif tipo_acao == "pesquisar_google" and remoto():
        r = pesquisa.pesquisar(txt or frase_original, ia_local)
        _ctx_set("fontes", r["fontes"])
        resp = r["resposta"]
        print(f"  -> {resp}")
    elif tipo_acao == "pesquisar_google":
        pesquisar(txt)
    elif tipo_acao == "spotify_controle":
        mapa = {"repetir_faixa": (spotify_api.repetir, "track"), "repetir_playlist": (spotify_api.repetir, "context"),
                "repetir_off": (spotify_api.repetir, "off"), "aleatorio_on": (spotify_api.aleatorio, True),
                "aleatorio_off": (spotify_api.aleatorio, False), "curtir": (spotify_api.curtir_atual, True),
                "descurtir": (spotify_api.curtir_atual, False), "reiniciar": (spotify_api.reiniciar_musica,)}
        partes = [p.strip() for p in re.split(r"[,;+ ]+", normalizar(txt)) if p.strip()]
        for p in partes:
            p = p.replace(" ", "_")
            if p.startswith("volume_") and p[7:].isdigit():
                print("  -> Spotify:", spotify_api.mudar_volume(int(p[7:])))
            elif p in mapa:
                fn, *args = mapa[p]
                print("  -> Spotify:", fn(*args))
    elif tipo_acao == "midia":
        mapa = {"pausa": "pausa", "continua": "continua", "proxima": "proxima", "anterior": "anterior",
                "aumentar_volume": "aumenta o volume", "diminuir_volume": "abaixa o volume", "mudo": "mudo"}
        tecla_midia(mapa.get(normalizar(txt).replace(" ", "_"), "pausa"))
    elif tipo_acao == "digitar":
        print(f"  -> digitando: {txt}")
        pyperclip.copy(txt)
        keyboard.send("ctrl+v")
    elif tipo_acao == "ensinar_apelido":
        gat = (a.get("gatilho") or "").strip()
        if gat and txt:
            ia_local.ensinar_apelido(gat, txt)
            print(f"  -> aprendi: quando você falar \"{gat}\" = \"{txt}\"")
            resp = resp or "Aprendido!"
        else:
            print("  Não entendi o que era pra aprender.")
    elif tipo_acao == "lembrar_fato":
        ia_local.lembrar_fato(txt)
        print(f"  -> vou lembrar: {txt}")
    elif tipo_acao == "esquecer":
        n = ia_local.esquecer(txt)
        print(f"  -> esqueci {n} item(ns) sobre \"{txt}\"")
    elif tipo_acao == "mandar_pro_claude":
        mandar_pro_claude(txt or frase_original)
    elif tipo_acao == "lembrete_rotina":
        pedido = rotinas.interpretar(normalizar(txt), txt)
        print("  -> " + (rotinas.aplicar(pedido) if pedido else "Não entendi o horário do lembrete."))
    elif tipo_acao == "clima":
        print("  -> " + extras.clima(txt, amanha="amanha" in normalizar(frase_original)))
    elif tipo_acao == "status_sistema":
        resp = sistema.resumo_falado()
    elif tipo_acao == "criar_pasta":
        resp = extras.criar_pasta(txt, a.get("onde") or "desktop")
        print(f"  -> {resp}")
    elif tipo_acao == "criar_arquivo":
        resp = extras.criar_arquivo(txt, a.get("conteudo") or "", a.get("onde") or "desktop")
        print(f"  -> {resp}")
    elif tipo_acao == "organizar_pasta":
        resp = extras.organizar_pasta(txt or a.get("onde") or "downloads")
        print(f"  -> {resp}")
    elif tipo_acao == "otimizar_pc":
        resp = extras.otimizar_pc()
        print(f"  -> {resp}")
    elif tipo_acao == "esvaziar_lixeira":
        resp = extras.esvaziar_lixeira()
        print(f"  -> {resp}")
    elif tipo_acao == "processos_pesados":
        resp = extras.processos_pesados()
        print(f"  -> {resp}")
    elif tipo_acao == "instalar_programa":
        resp = extras.instalar_programa(txt)
        print(f"  -> {resp}")
    elif tipo_acao == "comando_powershell":
        resp = extras.comando_powershell(txt)
        print(f"  -> {resp}")
    elif tipo_acao == "abrir_vscode":
        resp = extras.abrir_no_vscode(txt)
        print(f"  -> {resp}")
    elif tipo_acao == "responder":
        pass
    else:
        print("  Não entendi a ação da IA:", tipo_acao)
        return
    if resp:
        print(f"  💬 {resp}")
        falar(resp)


# ---------------------- ÁUDIO ----------------------

class Gravador:
    def __init__(self):
        self.fila = queue.Queue()
        self.gravando = False
        self.stream = None
        self.nivel = 0.0   # volume atual do microfone (0 a 1), usado pela barra do app

    def _cb(self, indata, frames, t, status):
        if self.gravando:
            self.fila.put(indata.copy())
            rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2))) / 32768.0
            self.nivel = min(1.0, rms * 8)

    def iniciar(self):
        self.fila = queue.Queue()
        self.gravando = True
        self.stream = sd.InputStream(samplerate=TAXA_AMOSTRAGEM, channels=1, dtype="int16",
                                     device=MICROFONE, callback=self._cb)
        self.stream.start()

    def parar(self) -> bytes:
        self.gravando = False
        self.nivel = 0.0
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        blocos = []
        while not self.fila.empty():
            blocos.append(self.fila.get())
        if not blocos:
            return b""
        return np.concatenate(blocos).tobytes()


reconhecedor = sr.Recognizer()


def transcrever(pcm: bytes) -> str:
    audio = sr.AudioData(pcm, TAXA_AMOSTRAGEM, 2)
    return reconhecedor.recognize_google(audio, language=IDIOMA)


def processar(pcm: bytes):
    duracao = len(pcm) / (TAXA_AMOSTRAGEM * 2)
    if duracao < 0.4:
        print("  (muito curto, ignorado)")
        return True
    try:
        texto = transcrever(pcm)
    except sr.UnknownValueError:
        print("  Não entendi. Tenta de novo.")
        bip(300, 250)
        return False
    except sr.RequestError as e:
        print("  Erro no reconhecimento (internet?):", e)
        bip(300, 400)
        return False
    print(f'Você disse: "{texto}"')
    bip(700, 120)
    if desvio_fala is not None:                 # chat aberto: o que você falou vira mensagem do chat
        try:
            desvio_fala(texto)
            return True
        except Exception as e:
            print("  Erro no chat:", e)
    try:
        executar(texto)
        return True
    except Exception as e:
        print("  Erro ao executar:", e)
        bip(300, 400)
        return False


# ---------------------- MOTOR (usado pelo app e pelo modo console) ----------------------

desvio_fala = None   # (app) quando o chat está aberto, recebe o texto falado em vez de executar como comando


# O app com interface troca estas funções pra receber os avisos.
def ao_status(estado: str):   # estados: "pronto", "ouvindo", "processando", "erro"
    pass


def conectar_spotify():
    if spotify_api.disponivel():
        try:
            print("Conectando ao Spotify (na 1ª vez abre o navegador pra você autorizar)...")
            spotify_api.conectar()
            print("Spotify conectado ✔  — 'toca X' já toca a música direto.")
            return True
        except Exception as e:
            print("Não consegui conectar ao Spotify (vou só pesquisar no app):", e)
    else:
        print("Spotify API não configurada (falta spotify_client_id.txt) — 'toca X' só pesquisa.")
    return False


class Motor:
    """Liga a tecla de atalho ao gravador. Também pode ser acionado por botão (iniciar/soltar)."""

    def __init__(self, tecla=None):
        self.gravador = Gravador()
        self.pressionado = threading.Event()
        self.finalizando = threading.Event()
        self.tecla = tecla or TECLA_FALAR
        self._hooks = []

    # --- tecla ---
    # Lê o estado da tecla direto do Windows (GetAsyncKeyState) várias vezes por segundo.
    # Funciona com o Jon minimizado, em segundo plano ou com qualquer janela na frente,
    # e não depende de "gancho" de teclado (que o Windows às vezes desliga sozinho).
    VK = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "space": 0x20, "insert": 0x2D,
          "scroll lock": 0x91, "pause": 0x13, "home": 0x24, "end": 0x23, "caps lock": 0x14,
          "page up": 0x21, "page down": 0x22}

    @classmethod
    def _codigos(cls, tecla):
        cods = []
        for parte in tecla.lower().split("+"):
            parte = parte.strip()
            if parte in cls.VK:
                cods.append(cls.VK[parte])
            elif re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", parte):
                cods.append(0x70 + int(parte[1:]) - 1)       # F1 = 0x70
            elif len(parte) == 1 and parte.isalnum():
                cods.append(ord(parte.upper()))
            else:
                raise ValueError(f"tecla desconhecida: {parte}")
        return cods

    def ligar_tecla(self, tecla=None):
        cods = self._codigos(tecla or self.tecla)   # valida antes de trocar
        self.desligar_tecla()
        if tecla:
            self.tecla = tecla
        self._geracao = getattr(self, "_geracao", 0) + 1
        threading.Thread(target=self._vigiar, args=(cods, self._geracao), daemon=True).start()

    def _vigiar(self, cods, geracao):
        import ctypes
        estado = ctypes.windll.user32.GetAsyncKeyState
        apertado_antes = False
        while geracao == self._geracao:
            try:
                apertado = all(estado(c) & 0x8000 for c in cods)
                if apertado and not apertado_antes:
                    self.comecar()
                elif not apertado and apertado_antes:
                    self.soltar()
                apertado_antes = apertado
            except Exception as e:
                print("  (erro lendo a tecla):", e)
                time.sleep(1)
            time.sleep(0.02)

    def desligar_tecla(self):
        self._geracao = getattr(self, "_geracao", 0) + 1

    # --- gravação ---
    def comecar(self):
        if self.pressionado.is_set() or self.finalizando.is_set():
            return
        self.pressionado.set()
        ia_local.aquecer_async()          # vai carregando a IA enquanto você fala
        bip(1200, 80)
        print("\n🎙️  Ouvindo...")
        ao_status("ouvindo")
        try:
            self.gravador.iniciar()
        except Exception as e:
            self.pressionado.clear()
            print("  Erro no microfone:", e)
            ao_status("erro")

    def soltar(self):
        if not self.pressionado.is_set():
            return
        self.pressionado.clear()
        self.finalizando.set()
        threading.Thread(target=self._finalizar, daemon=True).start()

    def gravando(self):
        return self.pressionado.is_set()

    # --- modo mãos-livres (palavra de ativação "Jon") ---
    # o Google escreve "Jon" de vários jeitos; aceita nas 2 primeiras palavras ("ô Jon", "ei Jon", "Jon,")
    PALAVRA = (r"^\s*((ei|oi|hey|ok|o|fala|alo|ola|eai|e ai|opa|bom dia|boa tarde|boa noite)[\s,]+)?(jon|john|jhon|jonh|djon|jonn|jhonn|jom|jone|jonny|jhonny|joni|jhoni|jon's)"
               r"\b[\s,.!:?]*")

    def ligar_maos_livres(self, ligar: bool):
        self._ml_geracao = getattr(self, "_ml_geracao", 0) + 1
        self.maos_livres = ligar
        if ligar:
            threading.Thread(target=self._ouvir_sempre, args=(self._ml_geracao,), daemon=True).start()
            print("Modo mãos-livres LIGADO — diga \"Jon, ...\" e o comando.")
        else:
            print("Modo mãos-livres desligado.")

    def _ouvir_sempre(self, geracao):
        bloco = int(TAXA_AMOSTRAGEM * 0.1)          # blocos de 100 ms
        fila = queue.Queue()
        try:
            stream = sd.InputStream(samplerate=TAXA_AMOSTRAGEM, channels=1, dtype="int16", device=MICROFONE,
                                    blocksize=bloco, callback=lambda d, *_: fila.put(d.copy()))
            stream.start()
        except Exception as e:
            print("  Erro abrindo o microfone pro modo mãos-livres:", e)
            return
        def rms(d):
            return float(np.sqrt(np.mean(d.astype(np.float32) ** 2)))
        # calibra o ruído do ambiente (1 s)
        ruido = [rms(fila.get()) for _ in range(10)]
        base = float(np.median(ruido))
        limiar = max(base * 2.5, 220.0)
        print(f"  (mãos-livres: microfone ok — ruído {base:.0f}, sensibilidade {limiar:.0f})")
        pre = []          # 300 ms antes da fala
        falando, fala, silencio = False, [], 0
        acordado_ate = 0.0
        while geracao == self._ml_geracao:
            try:
                d = fila.get(timeout=1)
            except queue.Empty:
                continue
            if self.pressionado.is_set() or self.finalizando.is_set():   # F9 tem prioridade
                falando, fala, pre = False, [], []
                continue
            nivel = rms(d)
            if not falando:
                pre = (pre + [d])[-3:]
                if nivel > limiar:
                    falando, fala, silencio = True, list(pre), 0
                else:
                    limiar = 0.98 * limiar + 0.02 * max(nivel * 2.5, 220.0)   # acompanha o ruído
                continue
            fala.append(d)
            silencio = silencio + 1 if nivel < limiar * 0.8 else 0
            if silencio >= 6 or len(fala) > 120:      # 0,6 s de silêncio ou 12 s falando
                falando = False
                pcm = np.concatenate(fala).tobytes()
                if len(fala) < 6:
                    continue
                threading.Thread(target=self._tratar_fala_livre, args=(pcm, acordado_ate), daemon=True).start()
                fala = []
        stream.stop()
        stream.close()

    def _tratar_fala_livre(self, pcm, acordado_ate):
        try:
            texto = transcrever(pcm)
        except sr.UnknownValueError:
            return                                   # barulho, não era fala
        except Exception as e:
            print("  (mãos-livres: erro no reconhecimento — internet?)", e)
            return
        agora = time.time()
        m = re.match(self.PALAVRA, normalizar(texto))
        if not m and agora > getattr(self, "_acordado_ate", 0):
            print(f'  (ouvi "{texto}" — não chamou o Jon, ignorei)')
            return
        # normalizar() mantém o tamanho do texto, então dá pra cortar o original na mesma posição
        resto = texto[m.end():].strip(" ,.!?") if m else texto
        if not resto:
            # só falou "Jon": fica esperando o comando por 6 s
            self._acordado_ate = agora + 6
            bip(1200, 80)
            print("\n🎙️  Sim? (pode falar o comando)")
            ao_status("ouvindo")
            return
        self._acordado_ate = 0
        ia_local.aquecer_async()
        print(f'Você disse: "{texto}"')
        bip(700, 120)
        ao_status("processando")
        if desvio_fala is not None:
            desvio_fala(resto)
            ao_status("pronto")
            return
        try:
            executar(resto)
            ao_status("pronto")
        except Exception as e:
            print("  Erro ao executar:", e)
            ao_status("erro")

    def _finalizar(self):
        # Continua gravando um pouquinho depois de soltar, pra não cortar a última palavra.
        time.sleep(CAUDA_SEGUNDOS)
        pcm = self.gravador.parar()
        self.finalizando.clear()
        ao_status("processando")
        ok = processar(pcm)
        ao_status("pronto" if ok else "erro")


def main():
    if "--listar-mics" in sys.argv:
        print(sd.query_devices())
        return
    conectar_spotify()
    rotinas.iniciar_relogio()
    motor = Motor()
    motor.ligar_tecla()
    print("=" * 56)
    print(f"  Jon ligado. Segure [{TECLA_FALAR.upper()}] e fale.")
    print('  Diga "fechar assistente" ou feche esta janela para sair.')
    print("=" * 56)
    keyboard.wait()


if __name__ == "__main__":
    main()
