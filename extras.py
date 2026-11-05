# -*- coding: utf-8 -*-
"""Hora/data, clima (Open-Meteo, grátis e sem chave), briefing do dia e ações da área de trabalho."""
import datetime as dt
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request

import perfil


def cidade_padrao():
    return perfil.cidade()

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]
SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
TEMPO_COD = {0: "céu limpo", 1: "quase limpo", 2: "parcialmente nublado", 3: "nublado", 45: "neblina", 48: "neblina",
             51: "garoa fraca", 53: "garoa", 55: "garoa forte", 61: "chuva fraca", 63: "chuva", 65: "chuva forte",
             71: "neve fraca", 73: "neve", 75: "neve forte", 80: "pancadas de chuva fracas", 81: "pancadas de chuva",
             82: "pancadas de chuva fortes", 95: "trovoadas", 96: "trovoadas com granizo", 99: "trovoadas com granizo"}


def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Jon-assistente/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------- hora / data ----------------------

def hora_texto():
    a = dt.datetime.now()
    return f"São {a.hour} horas e {a.minute} minutos." if a.minute else f"São {a.hour} horas em ponto."


def data_texto():
    a = dt.date.today()
    return f"Hoje é {SEMANA[a.weekday()]}, {a.day} de {MESES[a.month - 1]} de {a.year}."


def saudacao():
    h = dt.datetime.now().hour
    return "Bom dia" if 5 <= h < 12 else "Boa tarde" if 12 <= h < 18 else "Boa noite"


# ---------------------- clima ----------------------

def _geocodificar(cidade):
    r = _get("https://geocoding-api.open-meteo.com/v1/search?count=1&language=pt&name=" + urllib.parse.quote(cidade))
    res = (r.get("results") or [None])[0]
    if not res:
        return None
    return res["name"], res["latitude"], res["longitude"]


def clima(cidade: str = "", amanha: bool = False) -> str:
    local = cidade_padrao()
    if cidade:
        g = _geocodificar(cidade)
        if not g:
            return f"Não encontrei a cidade {cidade}."
        local = g
    nome, lat, lon = local
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&current=temperature_2m,apparent_temperature,weather_code,relative_humidity_2m"
           "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
           "&timezone=America%2FSao_Paulo&forecast_days=2")
    d = _get(url)
    i = 1 if amanha else 0
    mx, mn = round(d["daily"]["temperature_2m_max"][i]), round(d["daily"]["temperature_2m_min"][i])
    chuva = d["daily"]["precipitation_probability_max"][i]
    cond = TEMPO_COD.get(d["daily"]["weather_code"][i], "tempo variável")
    if amanha:
        return f"Amanhã em {nome}: {cond}, mínima de {mn} e máxima de {mx} graus, {chuva}% de chance de chuva."
    c = d["current"]
    agora = TEMPO_COD.get(c["weather_code"], "tempo variável")
    return (f"Agora em {nome}: {round(c['temperature_2m'])} graus, {agora}. "
            f"Hoje mínima de {mn} e máxima de {mx}, {chuva}% de chance de chuva.")


# ---------------------- área de trabalho ----------------------

def _pasta_conhecida(nome):
    guid = {"downloads": "{374DE290-123F-4565-9164-39C4925E467B}"}
    if nome in guid:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                return os.path.expandvars(winreg.QueryValueEx(k, guid[nome])[0])
        except Exception:
            pass
    r = subprocess.run(["powershell", "-NoProfile", "-Command", f"[Environment]::GetFolderPath('{nome}')"],
                       capture_output=True, text=True, creationflags=0x08000000)
    return r.stdout.strip()


PASTAS = {
    "downloads": "downloads", "download": "downloads", "baixados": "downloads",
    "documentos": "MyDocuments", "documento": "MyDocuments",
    "imagens": "MyPictures", "fotos": "MyPictures", "musicas": "MyMusic", "videos": "MyVideos",
    "area de trabalho": "Desktop", "desktop": "Desktop",
}


def abrir_pasta(nome: str) -> str:
    n = nome.strip().lower()
    m = re.match(r"^(disco|drive|unidade)\s+([a-z])$", n) or re.match(r"^([a-z])$", n)
    if m:
        letra = m.groups()[-1].upper()
        os.startfile(f"{letra}:\\")
        return f"Abrindo o disco {letra}."
    if n in ("jon", "do jon", "assistente"):
        os.startfile(os.path.dirname(os.path.abspath(__file__)))
        return "Abrindo a pasta do Jon."
    for chave, especial in PASTAS.items():
        if n == chave or n.endswith(" " + chave):
            os.startfile(_pasta_conhecida(especial))
            return f"Abrindo {chave}."
    return ""


def print_tela() -> str:
    import keyboard
    keyboard.send("windows+print screen")
    return "Print salvo na pasta Imagens, em Capturas de Tela."


PROCESSOS = {"spotify": "Spotify.exe", "discord": "Discord.exe", "steam": "steam.exe", "chrome": "chrome.exe",
             "google chrome": "chrome.exe", "edge": "msedge.exe", "bloco de notas": "notepad.exe",
             "calculadora": "CalculatorApp.exe", "obs": "obs64.exe", "word": "WINWORD.EXE", "excel": "EXCEL.EXE",
             "powerpoint": "POWERPNT.EXE", "vs code": "Code.exe", "vscode": "Code.exe", "hydra": "Hydra.exe",
             "obsidian": "Obsidian.exe", "stremio": "stremio.exe", "utorrent": "uTorrent.exe"}


def _fechar_por_janela(n: str):
    """Acha a janela aberta com título parecido (ex.: 'assassins creed mirrage') e pede pra ela fechar."""
    import difflib
    import unicodedata
    try:
        import pygetwindow as gw
    except Exception:
        return None
    def norm(t):
        t = unicodedata.normalize("NFKD", t.lower())
        t = "".join(c for c in t if not unicodedata.combining(c))
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()
    alvo = norm(n)
    melhor, nota_m = None, 0.0
    for w in gw.getAllWindows():
        t = norm(w.title or "")
        if not t or t in ("jon", "program manager"):
            continue
        nota = difflib.SequenceMatcher(None, alvo, t).ratio()
        pals = alvo.split()
        if pals and all(any(difflib.SequenceMatcher(None, p, q).ratio() >= 0.8 for q in t.split()) for p in pals):
            nota = max(nota, 0.9)
        if nota > nota_m:
            melhor, nota_m = w, nota
    if melhor is None or nota_m < 0.78:
        return None
    try:
        melhor.close()
        return f"Fechando {melhor.title}."
    except Exception:
        return None


def fechar_app(nome: str) -> str:
    n = re.sub(r"^(o|a)\s+", "", nome.strip().lower())
    n = re.sub(r"^(aplicativo|app|programa|jogo|game)\s+(do\s+|da\s+)?", "", n).strip()
    exe = PROCESSOS.get(n)
    if not exe:
        return _fechar_por_janela(n) or f"Não achei {n} aberto."
    # sem /F: pede pro programa fechar normalmente (ele pode perguntar se quer salvar)
    r = subprocess.run(["taskkill", "/IM", exe], capture_output=True, text=True, creationflags=0x08000000)
    return f"Fechando {n}." if r.returncode == 0 else f"{n.capitalize()} não estava aberto."


def minimizar_tudo() -> str:
    import keyboard
    keyboard.send("windows+d")
    return "Área de trabalho."


def bloquear_pc() -> str:
    import ctypes
    ctypes.windll.user32.LockWorkStation()
    return "Bloqueando o computador."


# ---------------------- agente do PC: pastas, arquivos e otimização ----------------------

def _resolver_pasta_base(local: str) -> str:
    l = (local or "").strip().lower()
    if any(p in l for p in ("download", "baixado")):
        return _pasta_conhecida("downloads")
    if any(p in l for p in ("documento", "documentos", "docs")):
        return _pasta_conhecida("MyDocuments")
    if any(p in l for p in ("imagem", "imagens", "foto", "fotos")):
        return _pasta_conhecida("MyPictures")
    if any(p in l for p in ("musica", "musicas", "música", "músicas")):
        return _pasta_conhecida("MyMusic")
    if any(p in l for p in ("video", "videos", "vídeo", "vídeos")):
        return _pasta_conhecida("MyVideos")
    if re.match(r"^(disco|drive|unidade)\s+([a-z])$", l) or re.match(r"^([a-z]):?$", l):
        letra = re.sub(r"[^a-z]", "", l)[-1].upper()
        return f"{letra}:\\"
    return _pasta_conhecida("Desktop")


def criar_pasta(nome: str, onde: str = "", abrir: bool = True) -> str:
    """Cria uma pasta na Área de Trabalho, Documentos, Downloads ou caminho informado."""
    nome = (nome or "").strip().strip('"\'\\/')
    nome = re.sub(r'[<>:"|?*]', "", nome).strip()
    if not nome:
        return "Me diga o nome da pasta que quer criar."
    if os.path.isabs(nome):
        caminho = nome
    else:
        base = _resolver_pasta_base(onde)
        caminho = os.path.join(base, nome)
    try:
        ja_existia = os.path.exists(caminho)
        os.makedirs(caminho, exist_ok=True)
        if abrir:
            try:
                os.startfile(caminho)
            except OSError:
                pass
        lugar = os.path.basename(os.path.dirname(caminho)) or os.path.dirname(caminho)
        if ja_existia:
            return f"A pasta {os.path.basename(caminho)} já existia em {lugar}. Abri ela para o senhor."
        return f"Pasta {os.path.basename(caminho)} criada em {lugar}, senhor."
    except Exception as e:
        return f"Não consegui criar a pasta: {e}"


def criar_arquivo(nome: str, conteudo: str = "", onde: str = "", abrir: bool = True) -> str:
    """Cria um arquivo de texto/nota/script com o conteúdo pedido."""
    nome = (nome or "nota.txt").strip().strip('"\'\\/')
    nome = re.sub(r'[<>:"|?*]', "", nome).strip() or "nota.txt"
    if "." not in os.path.basename(nome):
        nome += ".txt"
    base = _resolver_pasta_base(onde)
    caminho = nome if os.path.isabs(nome) else os.path.join(base, nome)
    try:
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(conteudo or "")
        if abrir:
            try:
                os.startfile(caminho)
            except OSError:
                pass
        return f"Arquivo {os.path.basename(caminho)} criado com sucesso, senhor."
    except Exception as e:
        return f"Não consegui criar o arquivo: {e}"


def organizar_pasta(qual: str = "downloads") -> str:
    """Organiza os arquivos soltos de uma pasta (padrão: Downloads) em subpastas por tipo."""
    import shutil
    pasta = _resolver_pasta_base(qual or "downloads")
    if not os.path.isdir(pasta):
        return f"Não encontrei a pasta {qual}."
    categorias = {
        "Instaladores e Programas": (".exe", ".msi", ".bat", ".cmd", ".apk", ".iso"),
        "Compactados": (".zip", ".rar", ".7z", ".tar", ".gz"),
        "Documentos e PDFs": (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".epub"),
        "Imagens": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"),
        "Vídeos": (".mp4", ".mkv", ".avi", ".mov", ".webm"),
        "Músicas e Áudio": (".mp3", ".wav", ".flac", ".ogg", ".m4a"),
        "Código e Dados": (".py", ".js", ".ts", ".html", ".css", ".json", ".sql", ".xml", ".yaml", ".yml"),
    }
    ignorados = (".crdownload", ".part", ".partial", ".!ut", ".!qb", ".tmp", ".lnk", ".ini")
    movidos = 0
    try:
        for item in os.scandir(pasta):
            if not item.is_file():
                continue
            ext = os.path.splitext(item.name)[1].lower()
            if not ext or ext in ignorados:
                continue
            destino_cat = next((cat for cat, exts in categorias.items() if ext in exts), None)
            if not destino_cat:
                continue
            subpasta = os.path.join(pasta, destino_cat)
            os.makedirs(subpasta, exist_ok=True)
            alvo = os.path.join(subpasta, item.name)
            if os.path.exists(alvo):
                base_n, ext_n = os.path.splitext(item.name)
                alvo = os.path.join(subpasta, f"{base_n}_{int(dt.datetime.now().timestamp())}{ext_n}")
            try:
                shutil.move(item.path, alvo)
                movidos += 1
            except OSError:
                pass
        if movidos == 0:
            return f"A pasta {os.path.basename(pasta)} já está organizada, senhor."
        return f"Organizei {movidos} arquivo{'s' if movidos != 1 else ''} por categoria na pasta {os.path.basename(pasta)}, senhor."
    except Exception as e:
        return f"Erro ao organizar a pasta: {e}"


def esvaziar_lixeira() -> str:
    """Esvazia a Lixeira do Windows silenciosamente."""
    import ctypes
    # SHERB_NOCONFIRMATION (1) | SHERB_NOPROGRESSUI (2) | SHERB_NOSOUND (4) = 7
    ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 7)
    return "Lixeira esvaziada, senhor."


def otimizar_pc() -> str:
    """Limpa arquivos temporários, libera memória RAM dos processos em segundo plano, limpa cache DNS e Lixeira."""
    import ctypes
    import shutil
    # 1. Limpar arquivos temporários (%TEMP% e C:\Windows\Temp)
    bytes_livres = 0
    arqs_apagados = 0
    pastas_temp = [os.environ.get("TEMP"), os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp")]
    vistas = set()
    for pt in pastas_temp:
        if not pt or not os.path.isdir(pt) or os.path.normcase(pt) in vistas:
            continue
        vistas.add(os.path.normcase(pt))
        try:
            for item in os.scandir(pt):
                try:
                    if item.is_file(follow_symlinks=False):
                        tam = item.stat().st_size
                        os.remove(item.path)
                        bytes_livres += tam
                        arqs_apagados += 1
                    elif item.is_dir(follow_symlinks=False):
                        shutil.rmtree(item.path, ignore_errors=True)
                        arqs_apagados += 1
                except OSError:
                    pass
        except OSError:
            pass

    # 2. Liberar Working Set de memória RAM dos processos
    ram_antes, ram_depois = 0.0, 0.0
    try:
        import psutil
        ram_antes = psutil.virtual_memory().used / 1e9
        psapi = ctypes.windll.psapi
        k32 = ctypes.windll.kernel32
        for p in psutil.process_iter(["pid"]):
            h = k32.OpenProcess(0x0100 | 0x0400, False, p.info["pid"])   # PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION
            if h:
                try:
                    psapi.EmptyWorkingSet(h)
                except Exception:
                    pass
                k32.CloseHandle(h)
        ram_depois = psutil.virtual_memory().used / 1e9
    except Exception:
        pass

    # 3. Limpar cache DNS
    try:
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, creationflags=0x08000000, timeout=10)
    except Exception:
        pass

    # (a Lixeira NÃO é esvaziada aqui: apagar da Lixeira não tem volta. Só com "esvazia a lixeira".)

    mb_temp = bytes_livres / (1024 * 1024)
    ram_ganha = max(0.0, ram_antes - ram_depois)
    partes = ["Otimização concluída, senhor."]
    if arqs_apagados > 0:
        partes.append(f"Removi {arqs_apagados} itens temporários ({mb_temp:.0f} megas)" if mb_temp >= 1 else f"Removi {arqs_apagados} arquivos temporários")
    if ram_ganha >= 0.15:
        partes.append(f"liberei {ram_ganha * 1024:.0f} megas de memória RAM")
    partes.append("limpei o cache de rede. A lixeira continua intacta — se quiser, diga \"esvazia a lixeira\".")
    return " ".join(partes)


def processos_pesados() -> str:
    """Mostra os programas que mais estão gastando memória RAM e CPU agora."""
    try:
        import psutil
        grupos = {}
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                nome = (p.info.get("name") or "").replace(".exe", "")
                if not nome or nome.lower() in ("system idle process", "system", "registry", "memcompression"):
                    continue
                mem = (p.info.get("memory_info").rss if p.info.get("memory_info") else 0) / (1024 * 1024)
                grupos[nome] = grupos.get(nome, 0.0) + mem
            except Exception:
                pass
        top = sorted(grupos.items(), key=lambda x: -x[1])[:4]
        if not top:
            return "Não encontrei processos pesados no momento."
        lista = ", ".join(f"{nome} com {mb:.0f} megas" for nome, mb in top)
        return f"Os programas usando mais memória agora são: {lista}."
    except Exception as e:
        return f"Não consegui ler os processos: {e}"


def instalar_programa(nome: str) -> str:
    """Instala um programa oficial no Windows via winget em segundo plano."""
    nome = (nome or "").strip()
    if not nome:
        return "Qual programa o senhor quer instalar?"
    import threading

    def _rodar():
        print(f"  📦 instalando {nome} via winget...")
        r = subprocess.run(["winget", "install", "--name", nome, "--accept-package-agreements",
                            "--accept-source-agreements", "--silent"],
                           capture_output=True, text=True, creationflags=0x08000000)
        if r.returncode == 0:
            print(f"  -> {nome} instalado com sucesso!")
        else:
            print(f"  (winget: não consegui instalar {nome} automaticamente)")

    threading.Thread(target=_rodar, daemon=True).start()
    return f"Iniciei a instalação de {nome} em segundo plano, senhor."


def comando_powershell(cmd: str) -> str:
    """Executa um comando seguro do Windows/PowerShell pedido pela IA (bloqueia comandos destrutivos)."""
    cmd = (cmd or "").strip()
    if not cmd:
        return "Nenhum comando informado."
    # Desligado por padrão: a IA local pode entender errado e rodar algo que você não pediu.
    # Para ligar (por sua conta e risco): no config.json, "permitir_powershell": true
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"), encoding="utf-8") as f:
            liberado = bool(json.load(f).get("permitir_powershell"))
    except Exception:
        liberado = False
    if not liberado:
        print(f"  (a IA quis rodar no PowerShell: {cmd[:120]} — bloqueado, está desligado nas configurações)")
        return "Esse tipo de comando avançado está desligado por segurança, senhor."
    proibidos = r"\b(format-volume|clear-disk|remove-item\s+.*-recurse\s+.*[c-z]:\\|del\s+/s|rd\s+/s\s+[c-z]:\\|cipher\s+/w|reg\s+delete)\b"
    if re.search(proibidos, cmd, flags=re.I):
        return "Por segurança, bloqueei esse comando destrutivo, senhor."
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, creationflags=0x08000000, timeout=25)
        saida = (r.stdout or r.stderr or "").strip()
        if saida:
            primeira = saida.splitlines()[0][:180]
            return f"Comando executado: {primeira}"
        return "Comando executado com sucesso, senhor."
    except Exception as e:
        return f"Erro ao executar o comando: {e}"


def abrir_no_vscode(caminho_ou_pasta: str = "") -> str:
    """Abre um arquivo ou pasta no Visual Studio Code (comando code)."""
    caminho = (caminho_ou_pasta or "").strip()
    try:
        if not caminho:
            subprocess.Popen(["code", "."], shell=True)
            return "Abrindo o VS Code no diretório do projeto, senhor."
        alvo = caminho
        if caminho.lower() in ("desktop", "área de trabalho", "area de trabalho"):
            alvo = os.path.join(os.path.expanduser("~"), "Desktop")
        elif caminho.lower() in ("downloads", "download"):
            alvo = os.path.join(os.path.expanduser("~"), "Downloads")
        elif caminho.lower() in ("jon", "projeto"):
            alvo = os.path.dirname(os.path.abspath(__file__))
        subprocess.Popen(["code", alvo], shell=True)
        return f"Abrindo {os.path.basename(alvo) or alvo} no VS Code, senhor."
    except Exception as e:
        return f"Não consegui abrir o VS Code: {e}"
