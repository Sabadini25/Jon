# -*- coding: utf-8 -*-
"""
Gerenciador de Conversas e Tópicos do Jon (estilo Antigravity / IDE).
Armazena conversas organizadas por pastas/projetos e tópicos.
"""
import json
import os
import time
import uuid

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_TOPICOS = os.path.join(PASTA, "chat_topicos.json")


def carregar_dados():
    if os.path.exists(ARQ_TOPICOS):
        try:
            with open(ARQ_TOPICOS, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    novo_id = str(uuid.uuid4())
    dados_padrao = {
        "ativo_id": novo_id,
        "projetos": [
            {
                "nome": "Jon",
                "topicos": [
                    {
                        "id": novo_id,
                        "titulo": "O Que É Este Projeto",
                        "criado_em": time.strftime("%Y-%m-%d %H:%M"),
                        "mensagens": []
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "titulo": "Carplay Caseiro com Inteligência",
                        "criado_em": time.strftime("%Y-%m-%d %H:%M"),
                        "mensagens": []
                    }
                ]
            },
            {
                "nome": "testes_antigravity",
                "topicos": [
                    {
                        "id": str(uuid.uuid4()),
                        "titulo": "Criador De Aplicativo De F...",
                        "criado_em": time.strftime("%Y-%m-%d %H:%M"),
                        "mensagens": []
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "titulo": "Using Multiple Google Acc...",
                        "criado_em": time.strftime("%Y-%m-%d %H:%M"),
                        "mensagens": []
                    }
                ]
            }
        ]
    }
    salvar_dados(dados_padrao)
    return dados_padrao


def salvar_dados(dados):
    tmp = ARQ_TOPICOS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ARQ_TOPICOS)


def obter_topico_ativo(dados):
    ativo_id = dados.get("ativo_id")
    for proj in dados.get("projetos", []):
        for top in proj.get("topicos", []):
            if top.get("id") == ativo_id:
                return proj, top
    if dados.get("projetos") and dados["projetos"][0].get("topicos"):
        primeiro = dados["projetos"][0]["topicos"][0]
        dados["ativo_id"] = primeiro["id"]
        salvar_dados(dados)
        return dados["projetos"][0], primeiro
    return criar_topico(dados, "Jon", "Nova Conversa")


def criar_topico(dados, nome_projeto="Jon", titulo="Nova Conversa"):
    novo_id = str(uuid.uuid4())
    topico = {
        "id": novo_id,
        "titulo": titulo,
        "criado_em": time.strftime("%Y-%m-%d %H:%M"),
        "mensagens": []
    }
    proj_encontrado = None
    for proj in dados.get("projetos", []):
        if proj["nome"].lower() == nome_projeto.lower():
            proj_encontrado = proj
            break
            
    if not proj_encontrado:
        proj_encontrado = {"nome": nome_projeto, "topicos": []}
        dados.setdefault("projetos", []).append(proj_encontrado)
        
    proj_encontrado["topicos"].insert(0, topico)
    dados["ativo_id"] = novo_id
    salvar_dados(dados)
    return proj_encontrado, topico


def excluir_topico(dados, topico_id):
    """Exclui um tópico/chat específico."""
    for proj in dados.get("projetos", []):
        for i, top in enumerate(proj.get("topicos", [])):
            if top.get("id") == topico_id:
                proj["topicos"].pop(i)
                # Se era o ativo, muda para outro
                if dados.get("ativo_id") == topico_id:
                    proj_ativo, top_ativo = obter_topico_ativo(dados)
                    dados["ativo_id"] = top_ativo["id"]
                salvar_dados(dados)
                return True
    return False


def excluir_projeto(dados, nome_projeto):
    """Exclui uma pasta/projeto inteira com seus tópicos."""
    for i, proj in enumerate(dados.get("projetos", [])):
        if proj.get("nome", "").lower() == nome_projeto.lower():
            dados["projetos"].pop(i)
            proj_ativo, top_ativo = obter_topico_ativo(dados)
            dados["ativo_id"] = top_ativo["id"]
            salvar_dados(dados)
            return True
    return False


def renomear_topico(dados, topico_id, novo_titulo):
    for proj in dados.get("projetos", []):
        for top in proj.get("topicos", []):
            if top.get("id") == topico_id:
                top["titulo"] = novo_titulo.strip()
                salvar_dados(dados)
                return True
    return False


def salvar_mensagens_topico(dados, topico_id, mensagens):
    for proj in dados.get("projetos", []):
        for top in proj.get("topicos", []):
            if top.get("id") == topico_id:
                top["mensagens"] = mensagens
                if top["titulo"] in ("Nova Conversa", "O Que É Este Projeto") and mensagens:
                    for m in mensagens:
                        if m.get("role") == "user" and m.get("content"):
                            primeira_frase = m["content"].strip().split("\n")[0][:28]
                            if len(primeira_frase) > 3:
                                top["titulo"] = primeira_frase.capitalize()
                            break
                salvar_dados(dados)
                return True
    return False
