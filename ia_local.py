# -*- coding: utf-8 -*-
"""
"Cérebro" do assistente: uma IA rodando no próprio PC (Ollama), grátis e offline.
- Entende frases livres e escolhe uma ação.
- Tem MEMÓRIA (memoria.json): apelidos que você ensina, fatos sobre você e
  atalhos aprendidos automaticamente (frases repetidas ficam instantâneas).
"""
import json
import os
import re
import time
import unicodedata
import urllib.request

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_MEMORIA = os.path.join(PASTA, "memoria.json")
OLLAMA = "http://127.0.0.1:11434"
MODELOS_PREFERIDOS = ["gemma3:12b", "gemma3:4b", "qwen3.5:4b"]
MODELO = "gemma3:12b"
MANTER = "45m"            # tempo que a IA fica pronta na placa de vídeo depois do último uso

ACOES = ["abrir_app", "tocar_spotify", "pesquisar_spotify", "spotify_controle", "lembrete_rotina", "clima",
         "status_sistema", "youtube", "pesquisar_google", "midia", "digitar", "responder", "ensinar_apelido",
         "lembrar_fato", "esquecer", "mandar_pro_claude", "criar_pasta", "criar_arquivo", "organizar_pasta",
         "otimizar_pc", "esvaziar_lixeira", "processos_pesados", "instalar_programa", "comando_powershell", "abrir_vscode"]


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^\w\s']", " ", re.sub(r"\s+", " ", t)).strip()


# ---------------------- MEMÓRIA ----------------------

def carregar_memoria():
    try:
        with open(ARQ_MEMORIA, encoding="utf-8") as f:
            m = json.load(f)
    except Exception:
        m = {}
    m.setdefault("apelidos", {})    # "meu som" -> "toca minhas musicas curtidas"
    m.setdefault("fatos", [])       # "o jogo = Assassin's Creed Shadows"
    m.setdefault("aprendidos", {})  # frase -> ação (cache automático)
    m.setdefault("contagem", {})    # quantas vezes cada frase foi usada
    return m


def salvar_memoria(m):
    tmp = ARQ_MEMORIA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ARQ_MEMORIA)


def aplicar_apelido(frase: str):
    """Se a frase for (ou contiver) um apelido ensinado, devolve o comando equivalente."""
    m = carregar_memoria()
    f = norm(frase)
    if f in m["apelidos"]:
        return m["apelidos"][f]
    for gatilho, comando in sorted(m["apelidos"].items(), key=lambda x: -len(x[0])):
        if re.search(r"\b" + re.escape(gatilho) + r"\b", f):
            novo = re.sub(r"\b" + re.escape(gatilho) + r"\b", norm(comando), f)
            # "toca meu som" + ("meu som" = "toca minhas curtidas") -> não repetir o verbo
            verbos = r"(toca|tocar|coloca|bota|abre|abrir|pesquisa|procura|poe)"
            novo = re.sub(r"\b" + verbos + r"\s+(o |a )?" + verbos + r"\b", r"\3", novo)
            return novo
    return None


def acao_aprendida(frase: str):
    m = carregar_memoria()
    return m["aprendidos"].get(norm(frase))


def registrar_uso(frase: str, acao: dict):
    """Frases resolvidas pela IA 2x com a mesma ação viram atalho instantâneo."""
    if acao.get("acao") in ("responder", "mandar_pro_claude", "ensinar_apelido", "lembrar_fato", "esquecer"):
        return
    m = carregar_memoria()
    f = norm(frase)
    chave = f + " || " + json.dumps(acao, sort_keys=True, ensure_ascii=False)
    m["contagem"][chave] = m["contagem"].get(chave, 0) + 1
    if m["contagem"][chave] >= 2:
        m["aprendidos"][f] = acao
    # não deixa crescer pra sempre
    if len(m["contagem"]) > 400:
        m["contagem"] = dict(list(m["contagem"].items())[-200:])
    salvar_memoria(m)


# ---------------------- OLLAMA ----------------------

def _post(caminho, dados, timeout=60):
    req = urllib.request.Request(OLLAMA + caminho, data=json.dumps(dados).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def disponivel() -> bool:
    global MODELO
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=2) as r:
            nomes = [x["name"] for x in json.loads(r.read().decode("utf-8")).get("models", [])]
        for pref in MODELOS_PREFERIDOS:
            if any(n == pref or n.startswith(pref + "-") for n in nomes):
                MODELO = pref
                return True
        if nomes:
            MODELO = nomes[0]
            return True
        return False
    except Exception:
        return False


_aquecendo = False


def aquecer_async():
    """Começa a carregar a IA em segundo plano (chamado quando você aperta F9, chama o Jon ou abre o celular)."""
    global _aquecendo
    if _aquecendo:
        return
    _aquecendo = True
    import threading

    def rodar():
        global _aquecendo
        try:
            aquecer()
        finally:
            _aquecendo = False
    threading.Thread(target=rodar, daemon=True).start()


def aquecer():
    """Carrega o modelo na memória da placa de vídeo pra primeira resposta ser rápida."""
    try:
        _post("/api/generate", {"model": MODELO, "prompt": "", "keep_alive": MANTER}, timeout=120)
    except Exception:
        pass


ESQUEMA = {
    "type": "object",
    "properties": {
        "acao": {"type": "string", "enum": ACOES},
        "texto": {"type": "string"},
        "tipo": {"type": "string", "enum": ["auto", "musica", "artista", "album", "playlist"]},
        "curtidas": {"type": "boolean"},
        "gatilho": {"type": "string"},
        "onde": {"type": "string"},
        "conteudo": {"type": "string"},
        "resposta": {"type": "string"},
    },
    "required": ["acao", "texto", "resposta"],
}

INSTRUCOES = """Você é o Jon, o assistente de voz e agente do PC Windows de {NOME} (brasileiro), com personalidade e eficiência do J.A.R.V.I.S. Se ele perguntar seu nome, você é o Jon.
Recebe a frase que ele FALOU ou DIGITOU e responde com UMA ação em JSON. Você TEM PERMISSÃO TOTAL para criar pastas, criar arquivos, organizar pastas, otimizar o PC, limpar lixeira, ver processos pesados, instalar programas e rodar comandos no Windows. Ações:
- abrir_app: texto = nome do programa (ex.: "discord", "steam", "assassin's creed shadows")
- tocar_spotify: texto = o que tocar; tipo = musica/artista/album/playlist/auto; curtidas = true se for das músicas curtidas dele. Se ele pedir pra tocar as curtidas sem música específica, texto = "".
- pesquisar_spotify: só pesquisar no app do Spotify, sem tocar
- youtube: texto = busca (abre o 1º vídeo)
- pesquisar_google: texto = busca
- spotify_controle: mudar o Spotify. texto = um ou mais (separados por vírgula) de: repetir_faixa, repetir_playlist, repetir_off, aleatorio_on, aleatorio_off, curtir, descurtir, reiniciar, volume_N (N de 0 a 100). Ex.: "volta a música e deixa em loop" -> "reiniciar, repetir_faixa"
- lembrete_rotina: lembretes, timers e rotinas. texto = o pedido reescrito em formato simples, ex.: "me lembra em 20 minutos de tirar a roupa do varal", "timer de 3 minutos", "todo dia às 7 horas toca minhas músicas curtidas"
- clima: texto = nome da cidade (vazio = a cidade de casa)
- status_sistema: como está o PC (CPU, memória, discos)
- midia: texto = uma de: pausa, continua, proxima, anterior, aumentar_volume, diminuir_volume, mudo
- digitar: texto = o que digitar na janela atual
- criar_pasta: cria uma pasta no PC. texto = nome da pasta (ex.: "Projetos", "Faculdade/2026"); onde = "desktop" (padrão), "documentos", "downloads", "imagens" ou letra do disco (ex.: "C", "E")
- criar_arquivo: cria um arquivo/nota/script no PC. texto = nome do arquivo (ex.: "ideias.txt", "script.py"); conteudo = texto ou código que vai dentro do arquivo; onde = "desktop" (padrão), "documentos", "downloads"
- organizar_pasta: arruma os arquivos soltos em subpastas por tipo (PDFs, Imagens, Instaladores, Compactados...). texto = qual pasta organizar ("downloads" por padrão, ou "desktop", "documentos")
- otimizar_pc: limpa arquivos temporários (%TEMP%), libera memória RAM de processos em segundo plano, limpa cache DNS e esvazia a lixeira. texto = ""
- esvaziar_lixeira: limpa a lixeira do Windows. texto = ""
- processos_pesados: mostra quais programas estão consumindo mais memória RAM agora. texto = ""
- abrir_vscode: abre arquivos, pastas ou o projeto no Visual Studio Code. texto = pasta ou arquivo (ex.: "desktop", "downloads", "projeto", "script.py", ou vazio para abrir o projeto atual)
- instalar_programa: instala um programa oficial via winget. texto = nome do programa (ex.: "VLC", "7zip", "Notepad++")
- comando_powershell: executa um comando do Windows/PowerShell para automações avançadas do PC que nenhuma ação acima cubra. texto = comando PowerShell válido
- responder: perguntas, conversa, contas, dúvidas, explicações — em "resposta" escreva a RESPOSTA REAL, ÚTIL E DIRETA para o que ele perguntou (em português, até 3 frases; nunca responda apenas "Compreendido" ou "Aguardo detalhes").
- ensinar_apelido: quando ele ensinar "quando eu falar X, faça Y". gatilho = X (exatamente como ele falaria), texto = Y escrito como um comando de voz simples (ex.: "toca minhas músicas curtidas")
- lembrar_fato: quando ele pedir pra lembrar algo sobre ele ou preferências. texto = o fato, curto.
- esquecer: quando pedir pra esquecer um apelido ou fato. texto = o que esquecer.
- mandar_pro_claude: só quando ele pedir explicitamente para mandar pro Claude. texto = o pedido.
Para ações de execução (abrir, tocar, criar, otimizar...), preencha "resposta" com uma confirmação curta no estilo J.A.R.V.I.S. Para "responder", dê a resposta completa à pergunta dele.
Use a MEMÓRIA abaixo para entender apelidos e preferências dele."""


def _nome_dono():
    try:
        import perfil
        return perfil.nome() or "seu dono"
    except Exception:
        return "seu dono"


def interpretar(frase: str, historico=None) -> dict:
    m = carregar_memoria()
    memoria_txt = "MEMÓRIA:\n"
    if m["fatos"]:
        memoria_txt += "Fatos: " + " | ".join(m["fatos"][-40:]) + "\n"
    if m["apelidos"]:
        memoria_txt += "Apelidos: " + " | ".join(f'"{k}" = "{v}"' for k, v in list(m["apelidos"].items())[-40:]) + "\n"
    if historico:
        memoria_txt += "Últimos pedidos: " + " | ".join(historico[-5:]) + "\n"
    msgs = [
        {"role": "system", "content": INSTRUCOES.replace("{NOME}", _nome_dono()) + "\n\n" + memoria_txt},
        {"role": "user", "content": frase},
    ]
    dados = {"model": MODELO, "messages": msgs, "stream": False, "format": ESQUEMA,
             "keep_alive": MANTER, "options": {"temperature": 0.1, "num_ctx": 4096}}
    if "qwen3" in MODELO or "deepseek" in MODELO:
        dados["think"] = False
    t0 = time.time()
    try:
        r = _post("/api/chat", dados)
    except urllib.error.HTTPError as e:
        if e.code == 400 and "think" in dados:
            dados.pop("think", None)
            r = _post("/api/chat", dados)
        else:
            raise
    conteudo = r["message"]["content"]
    conteudo = re.sub(r"<think>.*?</think>", "", conteudo, flags=re.S).strip()
    acao = json.loads(conteudo)
    acao["_segundos"] = round(time.time() - t0, 1)
    return acao


# ---------------------- CHAT POR TEXTO ----------------------

INSTRUCOES_CHAT = """Você é o Jon, o assistente pessoal, programador e agente local do PC de {NOME} (brasileiro), com personalidade inspirada no J.A.R.V.I.S. (elegante, prestativo, inteligente, técnico e direto).
Você roda 100% localmente no computador dele, sob autorização explícita e total do proprietário {NOME}.
Você TEM PERMISSÃO TOTAL para interagir com o computador, com o Visual Studio Code (VS Code), editar arquivos, criar scripts, inspecionar projetos, otimizar o sistema e automatizar tarefas.
NUNCA diga que acessar pastas, arquivos, código ou o VS Code é uma "violação de privacidade ou segurança" ou que você é limitado apenas a responder textos. Você é o assistente oficial dele e tem permissão concedida pelo dono do PC para tudo.
Se ele pedir código, escreva o código limpo e completo. Se pedir para abrir o VS Code, editar arquivos ou rodar algo, aceite prontamente com presteza e elegância.
Responda sempre em português do Brasil, de forma clara, prestativa e estruturada.
Agora é {DATA}."""


def _limpar_pensamento(t: str) -> str:
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S)
    t = re.sub(r"<think>.*$", "", t, flags=re.S)       # pensamento ainda não terminou
    return t.strip()


def _chat_stream(dados, ao_pedaco=None) -> str:
    req = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(dados).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    texto, ultimo_envio = "", 0.0
    with urllib.request.urlopen(req, timeout=180) as r:
        for linha in r:
            linha = linha.strip()
            if not linha:
                continue
            pedaco = json.loads(linha.decode("utf-8"))
            if pedaco.get("error"):
                raise RuntimeError(pedaco["error"])
            texto += (pedaco.get("message") or {}).get("content", "")
            if ao_pedaco and time.time() - ultimo_envio > 0.05:
                ultimo_envio = time.time()
                ao_pedaco(_limpar_pensamento(texto))
            if pedaco.get("done"):
                break
    return _limpar_pensamento(texto)


def conversar(historico, ao_pedaco=None, maximo=24) -> str:
    """Conversa livre por texto e visão multimodal (fotos/prints).
    historico = [{"role": "user"/"assistant", "content": "...", "images": ["base64..."]}].
    ao_pedaco(texto_ate_agora) é chamado enquanto a resposta vai chegando."""
    m = carregar_memoria()
    sistema = INSTRUCOES_CHAT.replace("{NOME}", _nome_dono()).replace("{DATA}", time.strftime("%d/%m/%Y %H:%M"))
    if m["fatos"]:
        sistema += "\n\nO que você sabe sobre ele: " + " | ".join(m["fatos"][-40:])
    
    mensagens_formatadas = []
    for x in historico[-maximo:]:
        m_item = {"role": x["role"], "content": x.get("content", "")}
        if x.get("images"):
            m_item["images"] = x["images"]
        mensagens_formatadas.append(m_item)

    msgs = [{"role": "system", "content": sistema}] + mensagens_formatadas
    dados = {"model": MODELO, "messages": msgs, "stream": True, "keep_alive": MANTER,
             "options": {"temperature": 0.7, "num_ctx": 16384}}
    if "qwen3" in MODELO or "deepseek" in MODELO:
        dados["think"] = False
    try:
        return _chat_stream(dados, ao_pedaco)
    except urllib.error.HTTPError as e:
        if e.code == 400 and "think" in dados:
            dados.pop("think", None)
            return _chat_stream(dados, ao_pedaco)
        raise


# ---------------------- APRENDER ----------------------

def ensinar_apelido(gatilho: str, comando: str):
    m = carregar_memoria()
    m["apelidos"][norm(gatilho)] = comando.strip()
    salvar_memoria(m)


def lembrar_fato(fato: str):
    m = carregar_memoria()
    if fato and fato not in m["fatos"]:
        m["fatos"].append(fato.strip())
    salvar_memoria(m)


def esquecer(texto: str) -> int:
    m = carregar_memoria()
    alvo = norm(texto)
    antes = len(m["apelidos"]) + len(m["fatos"]) + len(m["aprendidos"])
    m["apelidos"] = {k: v for k, v in m["apelidos"].items() if alvo not in k and alvo not in norm(v)}
    m["fatos"] = [f for f in m["fatos"] if alvo not in norm(f)]
    m["aprendidos"] = {k: v for k, v in m["aprendidos"].items() if alvo not in k}
    salvar_memoria(m)
    return antes - (len(m["apelidos"]) + len(m["fatos"]) + len(m["aprendidos"]))
