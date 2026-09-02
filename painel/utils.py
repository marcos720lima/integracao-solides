import csv
import os
import re
import secrets
import string
import unicodedata
from datetime import datetime


def ler_historico_desligamentos():
    from server import DESLIGAMENTOS_CSV

    if not os.path.exists(DESLIGAMENTOS_CSV):
        return []

    with open(DESLIGAMENTOS_CSV, mode="r", encoding="utf-8-sig", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo))

    linhas = _deduplicar_por_cpf_mais_recente(linhas)
    linhas.reverse()
    return linhas


def _data_ordenavel(linha):
    bruta = (linha.get("data_desligamento") or "").strip()
    if bruta:
        try:
            return datetime.strptime(bruta, "%d/%m/%Y")
        except ValueError:
            pass

    try:
        return datetime.strptime((linha.get("data_registro") or "")[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.min


def _deduplicar_por_cpf_mais_recente(linhas):
    escolhidas = {}
    posicoes = {}
    contador_sem_cpf = 0

    for indice, linha in enumerate(linhas):
        cpf = "".join(c for c in (linha.get("cpf") or "") if c.isdigit())

        if not cpf:
            chave = f"_sem_cpf_{contador_sem_cpf}"
            contador_sem_cpf += 1
        else:
            chave = cpf

        atual = escolhidas.get(chave)
        if atual is None or _data_ordenavel(linha) >= _data_ordenavel(atual):
            escolhidas[chave] = linha
            posicoes[chave] = indice

    return [escolhidas[chave] for chave in sorted(escolhidas, key=lambda c: posicoes[c])]


def mascarar_cpf(cpf):
    if not cpf:
        return "N/A"
    somente_numeros = "".join(c for c in cpf if c.isdigit())
    if len(somente_numeros) != 11:
        return cpf
    return f"***.***.***-{somente_numeros[-2:]}"


def formatar_cpf(cpf):
    if not cpf:
        return None
    somente_numeros = "".join(c for c in cpf if c.isdigit())
    if len(somente_numeros) != 11:
        return cpf
    return f"{somente_numeros[0:3]}.{somente_numeros[3:6]}.{somente_numeros[6:9]}-{somente_numeros[9:11]}"


def obter_demissoes_em_execucao():
    from server import cpfs_processados, cpfs_lock

    with cpfs_lock:
        return sum(1 for info in cpfs_processados.values() if info.get("processando"))


def ler_ultimas_linhas(caminho_arquivo, quantidade=300):
    if not os.path.exists(caminho_arquivo):
        return []

    with open(caminho_arquivo, "r", encoding="utf-8", errors="replace") as arquivo:
        linhas = arquivo.readlines()

    return [linha.rstrip("\n") for linha in linhas[-quantidade:]]


def filtrar_historico_por_periodo(historico, inicio=None, fim=None):
    filtrado = []
    for linha in historico:
        data_registro = (linha.get("data_registro") or "")[:10]
        if inicio and data_registro < inicio:
            continue
        if fim and data_registro > fim:
            continue
        filtrado.append(linha)
    return filtrado


def contar_desligamentos_por_setor(historico, inicio=None, fim=None, top=10):
    contagem = {}

    for linha in filtrar_historico_por_periodo(historico, inicio, fim):
        setor = (linha.get("setor") or "").strip() or "Não informado"
        contagem[setor] = contagem.get(setor, 0) + 1

    ranking = sorted(contagem.items(), key=lambda item: item[1], reverse=True)[:top]
    return [{"setor": setor, "quantidade": quantidade} for setor, quantidade in ranking]


def gerar_senha_temporaria(tamanho=14):
    alfabeto = string.ascii_lowercase + string.ascii_uppercase + string.digits + "!@#$%&*"
    while True:
        senha = "".join(secrets.choice(alfabeto) for _ in range(tamanho))
        if (
            any(c.islower() for c in senha)
            and any(c.isupper() for c in senha)
            and any(c.isdigit() for c in senha)
            and any(c in "!@#$%&*" for c in senha)
        ):
            return senha


def sugerir_login(nome_completo):
    nome = unicodedata.normalize("NFKD", nome_completo or "").encode("ascii", "ignore").decode("ascii")
    partes = [re.sub(r"[^a-z]", "", p.lower()) for p in nome.strip().split()]
    partes = [p for p in partes if p]
    if not partes:
        return ""
    if len(partes) == 1:
        return partes[0]
    return f"{partes[0]}.{partes[-1]}"
