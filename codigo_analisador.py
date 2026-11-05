# -*- coding: utf-8 -*-
"""
Ferramentas de Análise de Código e Pastas para o Jon (estilo Antigravity / IDE).
Lê a estrutura de pastas, arquivos de código e gera contexto limpo para a IA.
"""
import os
import mimetypes

EXTENSOES_CODIGO = {
    ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json", ".sql",
    ".md", ".txt", ".bat", ".ps1", ".sh", ".c", ".cpp", ".h", ".cs", ".java",
    ".rs", ".go", ".php", ".rb", ".yaml", ".yml", ".toml", ".ini", ".xml"
}

IGNORAR_DIR = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env", "dist", "build",
    ".next", ".nuxt", "coverage", ".idea", ".vscode", "backups"
}

IGNORAR_ARQ = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "assistente.log"
}


def arvore_projeto(caminho_base: str, max_profundidade: int = 3, limite_itens: int = 150) -> str:
    """Gera uma representação textual em árvore de uma pasta/projeto."""
    caminho_base = os.path.abspath(caminho_base)
    if not os.path.exists(caminho_base):
        return f"Caminho não encontrado: {caminho_base}"

    linhas = [f"📁 {os.path.basename(caminho_base)}/"]
    total = 0

    def _varrer(diretorio, prefixo, prof):
        nonlocal total
        if prof > max_profundidade or total >= limite_itens:
            return
        try:
            entradas = sorted(os.scandir(diretorio), key=lambda e: (not e.is_dir(), e.name.lower()))
        except Exception:
            return

        entradas_filtradas = [
            e for e in entradas
            if (e.is_dir() and e.name not in IGNORAR_DIR and not e.name.startswith("."))
            or (e.is_file() and e.name not in IGNORAR_ARQ and not e.name.startswith("."))
        ]

        count = len(entradas_filtradas)
        for i, entrada in enumerate(entradas_filtradas):
            if total >= limite_itens:
                linhas.append(f"{prefixo}└── ... (limite de arquivos atingido)")
                break
            total += 1
            ultimo = (i == count - 1)
            ramo = "└── " if ultimo else "├── "
            extensao = "    " if ultimo else "│   "

            if entrada.is_dir():
                linhas.append(f"{prefixo}{ramo}📁 {entrada.name}/")
                _varrer(entrada.path, prefixo + extensao, prof + 1)
            else:
                linhas.append(f"{prefixo}{ramo}📄 {entrada.name}")

    _varrer(caminho_base, "", 1)
    return "\n".join(linhas)


def ler_codigo_completo(caminho_pasta: str, max_tamanho_kb: int = 100, max_arquivos: int = 40) -> str:
    """Lê todos os arquivos de código de uma pasta para montar o contexto de engenharia."""
    caminho_pasta = os.path.abspath(caminho_pasta)
    if not os.path.exists(caminho_pasta):
        return f"Pasta não encontrada: {caminho_pasta}"

    saida = [f"### VISÃO GERAL DO PROJETO EM: {caminho_pasta}\n"]
    arvore = arvore_projeto(caminho_pasta, max_profundidade=3, limite_itens=80)
    saida.append("#### Estrutura de Arquivos:\n```\n" + arvore + "\n```\n")

    arquivos_lidos = 0
    bytes_totais = 0
    max_bytes_total = 40 * 1024  # ~10 mil tokens: cabe no contexto da IA local

    for raiz, dirs, arqs in os.walk(caminho_pasta):
        dirs[:] = [d for d in dirs if d not in IGNORAR_DIR and not d.startswith(".")]

        for arq in sorted(arqs):
            if arquivos_lidos >= max_arquivos or bytes_totais >= max_bytes_total:
                saida.append("\n... [Demais arquivos omitidos para manter performance]")
                return "\n".join(saida)

            _, ext = os.path.splitext(arq)
            if ext.lower() not in EXTENSOES_CODIGO or arq in IGNORAR_ARQ or arq.startswith("."):
                continue

            caminho_completo = os.path.join(raiz, arq)
            rel = os.path.relpath(caminho_completo, caminho_pasta).replace("\\", "/")

            try:
                tam = os.path.getsize(caminho_completo)
                if tam > max_tamanho_kb * 1024:
                    saida.append(f"#### Arquivo: `{rel}` (ignorado por ser grande: {tam//1024} KB)\n")
                    continue

                with open(caminho_completo, "r", encoding="utf-8", errors="replace") as f:
                    conteudo = f.read()

                saida.append(f"#### Arquivo: `{rel}`\n```{ext.lstrip('.')}\n{conteudo}\n```\n")
                arquivos_lidos += 1
                bytes_totais += len(conteudo.encode("utf-8"))
            except Exception as e:
                saida.append(f"#### Arquivo: `{rel}` (erro ao ler: {e})\n")

    return "\n".join(saida)
