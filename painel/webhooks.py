"""
Registro e reprocessamento dos webhooks recebidos do Solides — alimenta a
tela /painel/webhooks (inspetor estilo ngrok: lista de requisições, status
de cada uma, payload bruto e opção de reprocessar).

Guarda os eventos em data/webhooks_recebidos.json (lista, mais recente
primeiro, limitada a MAX_EVENTOS) para sobreviver a reinícios do servidor.
"""

import json
import os
import threading
import uuid
from datetime import datetime

MAX_EVENTOS = 300

_lock = threading.Lock()
_webhooks = []
_carregado = False


def _caminho_arquivo():
    from server import DATA_DIR
    return os.path.join(DATA_DIR, 'webhooks_recebidos.json')


def _garantir_carregado():
    global _carregado
    if _carregado:
        return
    caminho = _caminho_arquivo()
    if os.path.exists(caminho):
        try:
            with open(caminho, 'r', encoding='utf-8') as arquivo:
                _webhooks.extend(json.load(arquivo))
        except Exception:
            pass  # arquivo corrompido/vazio: segue com lista em memória vazia
    _carregado = True


def _persistir():
    caminho = _caminho_arquivo()
    try:
        with open(caminho, 'w', encoding='utf-8') as arquivo:
            json.dump(_webhooks[:MAX_EVENTOS], arquivo, ensure_ascii=False, default=str)
    except Exception:
        pass  # falha ao persistir não deve derrubar o processamento do webhook


def registrar_webhook_recebido(payload, ip_origem, status, cpf=None, nome=None, acao=None, motivo=None, reprocessado_de=None):
    """Cria um novo evento na lista (mais recente primeiro) e retorna seu id."""
    _garantir_carregado()

    evento = {
        'id': uuid.uuid4().hex[:12],
        'recebido_em': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        'ip_origem': ip_origem,
        'acao': acao or (payload or {}).get('acao'),
        'cpf': cpf,
        'nome': nome,
        'status': status,
        'motivo': motivo,
        'payload': payload,
        'resultado': None,
        'concluido_em': None,
        'reprocessado_de': reprocessado_de,
    }

    with _lock:
        _webhooks.insert(0, evento)
        del _webhooks[MAX_EVENTOS:]
        _persistir()

    return evento['id']


def marcar_webhook_concluido(webhook_id, resultado):
    """Atualiza o evento com o resultado do processamento (chamado ao final da thread)."""
    _garantir_carregado()

    resultado = resultado or {'status_geral': 'erro', 'erro': 'Sem retorno do processamento'}
    status_geral = resultado.get('status_geral', 'erro')
    status_final = {
        'sucesso': 'concluido_sucesso',
        'parcial': 'concluido_parcial',
        'erro': 'concluido_erro',
    }.get(status_geral, 'concluido_erro')

    with _lock:
        for evento in _webhooks:
            if evento['id'] == webhook_id:
                evento['status'] = status_final
                evento['resultado'] = resultado
                evento['concluido_em'] = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                break
        _persistir()


def listar_webhooks(limit=200):
    _garantir_carregado()
    with _lock:
        return list(_webhooks[:limit])


def obter_webhook(webhook_id):
    _garantir_carregado()
    with _lock:
        for evento in _webhooks:
            if evento['id'] == webhook_id:
                return dict(evento)
    return None


def reprocessar_webhook(webhook_id):
    """
    Dispara novamente o processamento de um webhook já recebido, usando o
    payload original armazenado. Cria um NOVO evento (não sobrescreve o
    antigo) pra manter o histórico de tentativas, igual um "replay".
    """
    original = obter_webhook(webhook_id)
    if not original:
        raise ValueError('Webhook não encontrado.')

    payload = original.get('payload') or {}
    if payload.get('acao') != 'demissao_colaborador':
        raise ValueError('Só é possível reprocessar webhooks de demissão de colaborador.')

    dados = payload.get('dados', {})

    # Import tardio evita import circular com server.py
    from server import limpar_cpf, cpfs_lock, cpfs_processados, processar_demissao_async

    cpf_bruto = dados.get('documentos', {}).get('cpf')
    cpf = limpar_cpf(cpf_bruto) if cpf_bruto else original.get('cpf')
    if not cpf:
        raise ValueError('Payload sem CPF válido para reprocessar.')

    novo_id = registrar_webhook_recebido(
        payload=payload, ip_origem=original.get('ip_origem'), status='processando',
        cpf=cpf, nome=dados.get('nome') or original.get('nome'), acao='demissao_colaborador',
        motivo='Reprocessamento manual', reprocessado_de=webhook_id,
    )

    # Libera o CPF do bloqueio de duplicata, já que isso é um reprocessamento intencional
    with cpfs_lock:
        cpfs_processados[cpf] = {'timestamp': datetime.now(), 'processando': True}

    def _executar():
        resultado = processar_demissao_async(dados, cpf)
        marcar_webhook_concluido(novo_id, resultado)

    thread = threading.Thread(target=_executar, daemon=False)
    thread.start()

    return novo_id
