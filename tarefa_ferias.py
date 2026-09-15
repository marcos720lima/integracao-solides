"""Tarefa diária de férias — aplica os agendamentos de desativação de acesso.

Rodar via Task Scheduler do Windows todos os dias às 07:00. É autônomo: não
depende do servidor web estar de pé.

  python tarefa_ferias.py

O que faz:
  - Agendamentos cujo período começou (e ainda não inativados): inativa os
    sistemas escolhidos e registra os que foram efetivamente inativados, para
    reativar só esses no fim.
  - Agendamentos cujo período terminou (e ainda não reativados): reativa os
    sistemas registrados.
  - Falhas: incrementa o contador, marca estado de erro (retenta no dia
    seguinte) e inclui no e-mail de resumo.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from painel import agendamento_ferias as ag
from inativar_manual import processar_sistema


def _aplicar(sistema_id, acao, cpf, email, nome):
    """Chama processar_sistema e devolve (ok, status, msg)."""
    try:
        r = processar_sistema(sistema_id, cpf=cpf or None, email=email or None,
                              nome=nome or None, acao=acao)
    except Exception as e:
        return False, "erro", str(e)
    status = (r or {}).get("status", "erro")
    msg = (r or {}).get("msg", "")
    # 'sucesso' e 'pulado' (ex: já no estado) contam como não-falha
    ok = status in ("sucesso", "pulado", "ja_inativo", "ja_ativo")
    return ok, status, msg


def processar_inativacoes(relatorio):
    for a in ag.pendentes_para_inativar():
        inativados_ok = []
        houve_falha = False
        for sid in a["sistemas"]:
            ok, status, msg = _aplicar(sid, "desativar", a["cpf"], a["email"], a["nome"])
            a["historico"].append(ag._evento(f"inativar {sid}: {status} {msg}".strip()))
            if ok:
                if status == "sucesso":
                    inativados_ok.append(sid)
            else:
                houve_falha = True

        # reativa depois só o que foi realmente inativado agora
        a["sistemas_reativar"] = sorted(set(a.get("sistemas_reativar", []) + inativados_ok))

        if houve_falha:
            a["estado"] = "erro_inativacao"
            a["tentativas_falha"] = a.get("tentativas_falha", 0) + 1
            relatorio["falhas"].append(f"Inativação de {a['nome']} (agendamento {a['id']}) teve falhas.")
        else:
            a["estado"] = "inativado"
            a["tentativas_falha"] = 0
            relatorio["inativados"].append(f"{a['nome']} — acessos pausados ({', '.join(inativados_ok) or 'nenhum'}).")
        ag.atualizar(a)


def processar_reativacoes(relatorio):
    for a in ag.pendentes_para_reativar():
        alvo = a.get("sistemas_reativar") or a.get("sistemas", [])
        houve_falha = False
        reativados_ok = []
        for sid in alvo:
            ok, status, msg = _aplicar(sid, "ativar", a["cpf"], a["email"], a["nome"])
            a["historico"].append(ag._evento(f"reativar {sid}: {status} {msg}".strip()))
            if ok:
                reativados_ok.append(sid)
            else:
                houve_falha = True

        if houve_falha:
            a["estado"] = "erro_reativacao"
            a["tentativas_falha"] = a.get("tentativas_falha", 0) + 1
            relatorio["falhas"].append(f"Reativação de {a['nome']} (agendamento {a['id']}) teve falhas — será retentada amanhã.")
        else:
            a["estado"] = "reativado"
            a["tentativas_falha"] = 0
            relatorio["reativados"].append(f"{a['nome']} — acessos restaurados ({', '.join(reativados_ok) or 'nenhum'}).")
        ag.atualizar(a)


def enviar_resumo(relatorio):
    if not any(relatorio.values()):
        return  # nada aconteceu hoje, não manda email
    linhas = []
    if relatorio["inativados"]:
        linhas.append("<b>Acessos pausados (início de férias):</b><br>" + "<br>".join(relatorio["inativados"]))
    if relatorio["reativados"]:
        linhas.append("<b>Acessos restaurados (fim de férias):</b><br>" + "<br>".join(relatorio["reativados"]))
    if relatorio["falhas"]:
        linhas.append("<b style='color:#c0392b'>Falhas (serão retentadas amanhã):</b><br>" + "<br>".join(relatorio["falhas"]))
    corpo = "<br><br>".join(linhas)

    try:
        from server import enviar_email_simples
        enviar_email_simples(
            assunto="Rotina de férias — resumo diário de acessos",
            corpo_html=f"<div style='font-family:Arial,sans-serif;font-size:14px'>{corpo}</div>",
        )
    except Exception as e:
        print(f"[ferias] Não foi possível enviar o e-mail de resumo: {e}", file=sys.stderr)


def main():
    relatorio = {"inativados": [], "reativados": [], "falhas": []}
    print("[ferias] Iniciando rotina diária…")
    processar_reativacoes(relatorio)   # reativa primeiro (mais crítico p/ o usuário)
    processar_inativacoes(relatorio)
    enviar_resumo(relatorio)
    print(f"[ferias] Concluído. Inativados: {len(relatorio['inativados'])}, "
          f"Reativados: {len(relatorio['reativados'])}, Falhas: {len(relatorio['falhas'])}.")


if __name__ == "__main__":
    main()
