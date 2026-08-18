"""Funções auxiliares usadas pelas telas do painel web."""

import csv
import os
from datetime import datetime


def ler_historico_desligamentos():
    """Lê o CSV de histórico de desligamentos, remove duplicidades por CPF
    (mantendo só o desligamento mais recente de cada pessoa) e retorna uma
    lista de dicts com o registro mais recente primeiro."""
    from server import DESLIGAMENTOS_CSV

    if not os.path.exists(DESLIGAMENTOS_CSV):
        return []

    with open(DESLIGAMENTOS_CSV, mode="r", encoding="utf-8-sig", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo))

    linhas = _deduplicar_por_cpf_mais_recente(linhas)
    linhas.reverse()
    return linhas


def _data_ordenavel(linha):
    """Converte a linha num valor comparável de data, pra decidir qual
    registro é o 'mais recente' quando o mesmo CPF aparece mais de uma vez.
    Prioriza a data de desligamento (formato DD/MM/AAAA, padrão do sistema);
    se estiver vazia ou em formato inesperado, cai pra data de registro
    (sempre bem formatada, 'AAAA-MM-DD HH:MM:SS')."""
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
    """Se o mesmo CPF aparecer mais de uma vez no histórico (ex.: reprocessamento,
    ou a pessoa foi desligada mais de uma vez), mantém só o registro com a
    data de desligamento mais recente - evita contar/exibir a mesma pessoa
    duplicada no dashboard."""
    escolhidas = {}   # chave -> linha escolhida
    posicoes = {}      # chave -> posição original (pra manter a ordem do arquivo)
    contador_sem_cpf = 0

    for indice, linha in enumerate(linhas):
        cpf = "".join(c for c in (linha.get("cpf") or "") if c.isdigit())

        if not cpf:
            # sem CPF não dá pra deduplicar com segurança; mantém como está
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
    """Mascara o CPF para exibição na tela (mesma lógica usada nos logs do server.py)."""
    if not cpf:
        return "N/A"
    somente_numeros = "".join(c for c in cpf if c.isdigit())
    if len(somente_numeros) != 11:
        return cpf
    return f"***.***.***-{somente_numeros[-2:]}"


def obter_demissoes_em_execucao():
    """Retorna quantas demissões vindas de webhook estão sendo processadas agora."""
    from server import cpfs_processados, cpfs_lock

    with cpfs_lock:
        return sum(1 for info in cpfs_processados.values() if info.get("processando"))


def ler_ultimas_linhas(caminho_arquivo, quantidade=300):
    """Lê as últimas N linhas de um arquivo de log."""
    if not os.path.exists(caminho_arquivo):
        return []

    with open(caminho_arquivo, "r", encoding="utf-8", errors="replace") as arquivo:
        linhas = arquivo.readlines()

    return [linha.rstrip("\n") for linha in linhas[-quantidade:]]


def filtrar_historico_por_periodo(historico, inicio=None, fim=None):
    """
    Filtra o histórico por uma faixa de datas (inicio/fim no formato
    'YYYY-MM-DD'), comparando contra a data em que o desligamento foi
    REGISTRADO no sistema - é o único campo de data com formato garantido
    no CSV (a "data de desligamento" vem do Solides em formato livre).
    """
    filtrado = []
    for linha in historico:
        data_registro = (linha.get("data_registro") or "")[:10]  # 'YYYY-MM-DD'
        if inicio and data_registro < inicio:
            continue
        if fim and data_registro > fim:
            continue
        filtrado.append(linha)
    return filtrado


def contar_desligamentos_por_setor(historico, inicio=None, fim=None, top=10):
    """
    Conta desligamentos por setor dentro de uma faixa de datas opcional.
    Retorna uma lista de dicts [{'setor': ..., 'quantidade': ...}, ...],
    ordenada do maior para o menor, limitada a `top` setores.
    """
    contagem = {}

    for linha in filtrar_historico_por_periodo(historico, inicio, fim):
        setor = (linha.get("setor") or "").strip() or "Não informado"
        contagem[setor] = contagem.get(setor, 0) + 1

    ranking = sorted(contagem.items(), key=lambda item: item[1], reverse=True)[:top]
    return [{"setor": setor, "quantidade": quantidade} for setor, quantidade in ranking]
