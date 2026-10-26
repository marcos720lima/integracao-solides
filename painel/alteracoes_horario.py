"""Alteracoes temporarias de horario de logon no AD (liberacoes por data).

O AD so guarda um horario por dia da semana, que se repete toda semana. Para
liberar horas numa DATA especifica, o sistema mexe so na coluna daquele dia da
semana, e so enquanto a data esta valendo:

  - horario base: o horario da pessoa no AD antes da alteracao (guardado em
    data/horarios_base.json enquanto houver alteracao valendo);
  - horario desejado agora = horario base + horas extras das solicitacoes de HOJE;
  - um laco no servidor (a cada minuto) compara o desejado com o AD e corrige.

As horas pedidas sao SOMADAS ao horario da pessoa (nunca substituem). Como o AD
so aceita hora cheia, o inicio e arredondado para baixo e o fim para cima
(13:30-14:30 vira 13:00-15:00), para nunca liberar menos do que foi pedido.

Se alguem mudar o horario da pessoa direto (aba Active Directory ou ADUC)
durante uma alteracao, o novo horario vira a base: ao terminar, volta para ele.
"""

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone

from painel.ad_gestao import (
    DAYS_PT,
    ad_obter_logon_hours_raw,
    ad_update_logon_hours_by_sam,
    build_utc_bits_from_local,
    bytes_to_bits_lsb_first,
    decode_logon_hours,
    hours_to_bits_bytes,
)

logger = logging.getLogger("server")

_lock = threading.RLock()
_laco_iniciado = False
INTERVALO_SEGUNDOS = 60

DIAS_SEMANA_LONGO = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"]
_PADRAO_HORA = re.compile(r"^(\d{1,2}):(\d{2})$")


# ---------------------------------------------------------------- utilidades

def _utc_offset():
    try:
        return int(os.getenv("UTC_OFFSET_HOURS", "-3"))
    except ValueError:
        return -3


def hoje_local():
    return (datetime.now(timezone.utc) + timedelta(hours=_utc_offset())).date()


def _agora_iso():
    return (datetime.now(timezone.utc) + timedelta(hours=_utc_offset())).strftime("%Y-%m-%dT%H:%M:%S")


def _dia_semana_ad(d: date) -> int:
    """Indice usado pelo AD/DAYS_PT: 0=domingo ... 6=sabado."""
    return (d.weekday() + 1) % 7


def _caminho(nome):
    from server import DATA_DIR
    return os.path.join(DATA_DIR, nome)


def _carregar(nome, padrao):
    caminho = _caminho(nome)
    if not os.path.exists(caminho):
        return padrao
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao


def _salvar(nome, dados):
    caminho = _caminho(nome)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, caminho)


def _carregar_solicitacoes():
    return _carregar("alteracoes_horario.json", [])


def _salvar_solicitacoes(lista):
    _salvar("alteracoes_horario.json", lista)


def _carregar_bases():
    return _carregar("horarios_base.json", {})


def _salvar_bases(dados):
    _salvar("horarios_base.json", dados)


def _evento(texto):
    return {"quando": _agora_iso(), "texto": texto}


# ------------------------------------------------------- horas e arredondamento

def _minutos(texto):
    m = _PADRAO_HORA.match((texto or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h == 24 and mi == 0:
        return 24 * 60
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return h * 60 + mi


def faixa_no_ad(inicio, fim):
    """(hora_inicial, hora_final) em horas cheias como fica no AD, ou erro."""
    ini, fi = _minutos(inicio), _minutos(fim)
    if ini is None or fi is None:
        return None, "Use o formato HH:MM."
    if fi <= ini:
        return None, "O fim precisa ser depois do início (no mesmo dia)."
    return (ini // 60, -(-fi // 60)), None


def _bits_extras_do_dia(itens_do_dia, dia_semana):
    """Bits UTC (168) com as horas extras de um dia da semana local."""
    matriz = [[0] * 24 for _ in range(7)]
    for item in itens_do_dia:
        faixa, _ = faixa_no_ad(item["inicio"], item["fim"])
        if not faixa:
            continue
        for h in range(faixa[0], faixa[1]):
            matriz[dia_semana][h] = 1
    return build_utc_bits_from_local(matriz, _utc_offset())


def _somar(base_bytes, extras_bits):
    bits = bytes_to_bits_lsb_first(base_bytes)
    return hours_to_bits_bytes([1 if (a or b) else 0 for a, b in zip(bits, extras_bits)])


def _texto_do_dia(bytes_horario, dia_semana):
    if bytes_horario is None:
        return "Sem restrição"
    return decode_logon_hours(bytes_horario, _utc_offset()).get(DAYS_PT[dia_semana], "Nenhum")


# ------------------------------------------------------------- solicitacoes

def validar_itens(itens_brutos):
    """Valida e normaliza a lista de {data, inicio, fim}. Retorna (itens, erros)."""
    itens, erros = [], []
    hoje = hoje_local().isoformat()
    for n, bruto in enumerate(itens_brutos or [], start=1):
        data = (bruto.get("data") or "").strip()
        inicio = (bruto.get("inicio") or "").strip()
        fim = (bruto.get("fim") or "").strip()
        try:
            date.fromisoformat(data)
        except ValueError:
            erros.append(f"Linha {n}: data inválida.")
            continue
        if data < hoje:
            erros.append(f"Linha {n}: a data {_data_br(data)} já passou.")
            continue
        _, erro = faixa_no_ad(inicio, fim)
        if erro:
            erros.append(f"Linha {n}: {erro}")
            continue
        itens.append({"data": data, "inicio": inicio, "fim": fim})
    if not itens and not erros:
        erros.append("Adicione pelo menos uma data.")
    itens.sort(key=lambda i: (i["data"], i["inicio"]))
    return itens, erros


def _data_br(iso):
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def previa(sam, itens):
    """Para cada data: horario atual daquele dia e como vai ficar."""
    encontrado, base = ad_obter_logon_hours_raw(sam)
    if not encontrado:
        raise ValueError(f"Usuário {sam} não encontrado no AD.")

    with _lock:
        registro_base = _carregar_bases().get(sam.lower())
    if registro_base and registro_base.get("base_hex"):
        base = bytes.fromhex(registro_base["base_hex"])

    por_data = {}
    for item in itens:
        por_data.setdefault(item["data"], []).append(item)

    linhas = []
    for data_iso in sorted(por_data):
        d = date.fromisoformat(data_iso)
        dia = _dia_semana_ad(d)
        faixas = []
        for item in por_data[data_iso]:
            faixa, _ = faixa_no_ad(item["inicio"], item["fim"])
            if faixa:
                faixas.append(f"{faixa[0]:02d}:00-{faixa[1]:02d}:00")
        if base is None:
            fica = "Sem restrição (nada a alterar)"
        else:
            fica = _texto_do_dia(_somar(base, _bits_extras_do_dia(por_data[data_iso], dia)), dia)
        linhas.append({
            "data": data_iso,
            "data_br": d.strftime("%d/%m/%Y"),
            "dia_semana": DIAS_SEMANA_LONGO[dia],
            "pedido_no_ad": ", ".join(faixas),
            "atual": _texto_do_dia(base, dia),
            "vai_ficar": fica,
        })
    return {"sem_restricao": base is None, "linhas": linhas}


def _pessoa(p):
    if not p or not p.get("sam"):
        return None
    return {"sam": p["sam"], "nome": p.get("nome") or p["sam"]}


def criar_solicitacao(colaborador, itens, motivo, criado_por, gestor=None, aprovador_gp=None,
                      possui_formulario=False, data_solicitacao=None):
    registro = {
        "id": uuid.uuid4().hex[:12],
        "sam": colaborador["sam"],
        "nome": colaborador.get("nome") or colaborador["sam"],
        "cpf": colaborador.get("cpf") or "",
        "setor": colaborador.get("setor") or "",
        "email": colaborador.get("email") or "",
        "itens": [dict(i, aplicado_em=None, restaurado_em=None) for i in itens],
        "motivo": (motivo or "").strip(),
        "gestor": _pessoa(gestor),
        "aprovador_gp": _pessoa(aprovador_gp),
        "possui_formulario": bool(possui_formulario),
        "data_solicitacao": data_solicitacao or hoje_local().isoformat(),
        "criado_por": criado_por or "",
        "criado_em": _agora_iso(),
        "estado": "ativa",
        "erro": None,
        "historico": [_evento(f"Solicitação criada por {criado_por or '—'}")],
    }
    with _lock:
        lista = _carregar_solicitacoes()
        lista.append(registro)
        _salvar_solicitacoes(lista)
    reconciliar_colaborador(registro["sam"])
    return registro


def cancelar_solicitacao(id_solicitacao, usuario):
    with _lock:
        lista = _carregar_solicitacoes()
        alvo = next((s for s in lista if s["id"] == id_solicitacao), None)
        if not alvo:
            return False, "Solicitação não encontrada."
        if alvo["estado"] == "cancelada":
            return False, "Essa solicitação já está cancelada."
        if status_da_solicitacao(alvo) == "concluida":
            return False, "Essa solicitação já terminou."
        alvo["estado"] = "cancelada"
        alvo["historico"].append(_evento(f"Cancelada por {usuario or '—'}"))
        _salvar_solicitacoes(lista)
        sam = alvo["sam"]
    reconciliar_colaborador(sam)
    return True, "Solicitação cancelada. Se estava valendo hoje, o horário original já foi restaurado."


def status_da_solicitacao(s, hoje=None):
    if s.get("estado") == "cancelada":
        return "cancelada"
    hoje = hoje or hoje_local().isoformat()
    datas = [i["data"] for i in s.get("itens", [])]
    if s.get("erro") and hoje in datas:
        return "erro"
    if not datas or max(datas) < hoje:
        return "concluida"
    if hoje in datas:
        return "em_andamento"
    if min(datas) < hoje:
        return "em_andamento"
    return "agendada"


def listar(de=None, ate=None, colaborador=None):
    with _lock:
        lista = _carregar_solicitacoes()
    termo = (colaborador or "").strip().lower()
    termo_digitos = "".join(c for c in termo if c.isdigit())
    resultado = []
    for s in lista:
        datas = [i["data"] for i in s.get("itens", [])]
        if de and not any(d >= de for d in datas):
            continue
        if ate and not any(d <= ate for d in datas):
            continue
        if de and ate and not any(de <= d <= ate for d in datas):
            continue
        if termo:
            alvo = f"{s.get('nome', '')} {s.get('sam', '')} {s.get('setor', '')} {s.get('email', '')}".lower()
            bate_cpf = bool(termo_digitos) and termo_digitos in (s.get("cpf") or "")
            if termo not in alvo and not bate_cpf:
                continue
        copia = dict(s)
        copia["status"] = status_da_solicitacao(s)
        copia["data_solicitacao_br"] = _data_br(s.get("data_solicitacao") or "")
        copia["itens"] = [dict(i, data_br=_data_br(i["data"]), faixa_ad=_faixa_texto(i)) for i in s.get("itens", [])]
        resultado.append(copia)
    ordem = {"em_andamento": 0, "erro": 0, "agendada": 1, "concluida": 2, "cancelada": 3}
    resultado.sort(key=lambda s: s.get("criado_em", ""), reverse=True)
    resultado.sort(key=lambda s: ordem.get(s["status"], 9))
    return resultado


def _faixa_texto(item):
    faixa, _ = faixa_no_ad(item["inicio"], item["fim"])
    return f"{faixa[0]:02d}:00–{faixa[1]:02d}:00" if faixa else ""


# --------------------------------------------------------------- reconciliacao

def _itens_de_hoje(solicitacoes, sam, hoje_iso):
    pares = []
    for s in solicitacoes:
        if s["sam"].lower() != sam or s.get("estado") == "cancelada":
            continue
        for item in s.get("itens", []):
            if item["data"] == hoje_iso:
                pares.append((s, item))
    return pares


def reconciliar_colaborador(sam):
    """Deixa o AD de UM colaborador como deveria estar agora."""
    with _lock:
        _reconciliar(sam.lower(), hoje_local())


def reconciliar_todos():
    with _lock:
        solicitacoes = _carregar_solicitacoes()
        bases = _carregar_bases()
        hoje_iso = hoje_local().isoformat()
        sams = set(bases.keys())
        for s in solicitacoes:
            if s.get("estado") != "cancelada" and any(i["data"] == hoje_iso for i in s.get("itens", [])):
                sams.add(s["sam"].lower())
        for sam in sorted(sams):
            try:
                _reconciliar(sam, hoje_local())
            except Exception as e:
                logger.error(f"[HORARIO] Falha ao reconciliar {sam}: {e}")


def _reconciliar(sam, hoje):
    hoje_iso = hoje.isoformat()
    solicitacoes = _carregar_solicitacoes()
    bases = _carregar_bases()
    pares = _itens_de_hoje(solicitacoes, sam, hoje_iso)
    registro = bases.get(sam)

    if not pares and not registro:
        return

    try:
        encontrado, atual = ad_obter_logon_hours_raw(sam)
    except Exception as e:
        _marcar_erro(solicitacoes, sam, hoje_iso, f"Não foi possível ler o AD: {e}")
        _salvar_solicitacoes(solicitacoes)
        return

    if not encontrado:
        _marcar_erro(solicitacoes, sam, hoje_iso, "Usuário não encontrado no AD.")
        _salvar_solicitacoes(solicitacoes)
        return

    if registro and atual is None:
        # tiraram a restricao de horario por fora: nao ha mais o que controlar
        bases.pop(sam, None)
        _salvar_bases(bases)
        return

    if registro:
        base = bytes.fromhex(registro["base_hex"])
        aplicado = registro.get("aplicado_hex")
        if atual is not None and aplicado and atual.hex() != aplicado:
            # alguem mudou o horario por fora durante a alteracao: vira a nova base
            base = atual
            logger.info(f"[HORARIO] {sam}: horário mudado manualmente, adotado como novo horário base")
    else:
        if atual is None:
            for s, item in pares:
                if not item.get("aplicado_em"):
                    item["aplicado_em"] = _agora_iso()
                    item["observacao"] = "Conta sem restrição de horário no AD — nada a alterar."
            _salvar_solicitacoes(solicitacoes)
            return
        base = atual

    if pares:
        extras = _bits_extras_do_dia([item for _, item in pares], _dia_semana_ad(hoje))
        desejado = _somar(base, extras)
    else:
        desejado = base

    if atual is None or atual != desejado:
        ok, mensagem = ad_update_logon_hours_by_sam(sam, desejado)
        if not ok:
            _marcar_erro(solicitacoes, sam, hoje_iso, mensagem)
            _salvar_solicitacoes(solicitacoes)
            return
        if pares:
            logger.info(f"[HORARIO] {sam}: horas extras de {_data_br(hoje_iso)} liberadas no AD")
        else:
            logger.info(f"[HORARIO] {sam}: horário original restaurado no AD")

    agora = _agora_iso()
    for s in solicitacoes:
        if s["sam"].lower() != sam:
            continue
        mudou = False
        for item in s.get("itens", []):
            if item["data"] == hoje_iso and s.get("estado") != "cancelada" and not item.get("aplicado_em"):
                item["aplicado_em"] = agora
                s["historico"].append(_evento(f"Horas extras de {_data_br(item['data'])} liberadas no AD"))
                mudou = True
            ja_saiu = item["data"] < hoje_iso or s.get("estado") == "cancelada"
            if ja_saiu and item.get("aplicado_em") and not item.get("restaurado_em") and not item.get("observacao"):
                item["restaurado_em"] = agora
                s["historico"].append(_evento(f"Horário original restaurado após {_data_br(item['data'])}"))
                mudou = True
        if s.get("erro"):
            s["erro"] = None
            s["historico"].append(_evento("Erro resolvido: horário sincronizado com o AD"))

    if pares:
        bases[sam] = {"base_hex": base.hex(), "aplicado_hex": desejado.hex(), "atualizado_em": agora}
    else:
        bases.pop(sam, None)

    _salvar_solicitacoes(solicitacoes)
    _salvar_bases(bases)


def _marcar_erro(solicitacoes, sam, hoje_iso, mensagem):
    logger.error(f"[HORARIO] {sam}: {mensagem}")
    for s in solicitacoes:
        if s["sam"].lower() == sam and s.get("estado") != "cancelada":
            if s.get("erro") != mensagem:
                s["historico"].append(_evento(f"Erro: {mensagem}"))
            s["erro"] = mensagem


# ---------------------------------------------------------------------- laco

def iniciar_laco():
    """Roda a reconciliacao a cada minuto dentro do servidor. Se o servidor
    ficar desligado na virada do dia, corrige assim que voltar."""
    global _laco_iniciado
    with _lock:
        if _laco_iniciado:
            return
        _laco_iniciado = True

    def laco():
        while True:
            try:
                reconciliar_todos()
            except Exception as e:
                logger.error(f"[HORARIO] Falha no laço de alterações de horário: {e}")
            time.sleep(INTERVALO_SEGUNDOS)

    threading.Thread(target=laco, daemon=True, name="alteracoes-horario").start()
