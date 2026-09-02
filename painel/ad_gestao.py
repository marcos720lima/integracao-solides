import re
from typing import Dict, List, Optional, Tuple

from ldap3 import ALL, MODIFY_REPLACE, SUBTREE, Connection, Server

DAYS_PT = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]
DAY_INPUTS = [
    ("seg", "Segunda-feira", 1),
    ("ter", "Terça-feira", 2),
    ("qua", "Quarta-feira", 3),
    ("qui", "Quinta-feira", 4),
    ("sex", "Sexta-feira", 5),
    ("sab", "Sábado", 6),
    ("dom", "Domingo", 0),
]


def _conexao_ad():
    from server import AD_URL, AD_USER, AD_PASS, BASE_DN
    servidor = Server(AD_URL, get_info=ALL)
    conexao = Connection(servidor, user=AD_USER, password=AD_PASS, auto_bind=True)
    return conexao, BASE_DN


def bytes_to_bits_lsb_first(data: bytes) -> List[int]:
    bits: List[int] = []
    for b in data:
        for i in range(8):
            bits.append((b >> i) & 1)
    return bits[:168]


def build_local_matrix(bits_utc: List[int], utc_offset_hours: int) -> List[List[int]]:
    matrix = [[0 for _ in range(24)] for _ in range(7)]
    for d_utc in range(7):
        for h_utc in range(24):
            idx = d_utc * 24 + h_utc
            allowed = bits_utc[idx]
            raw_local_h = h_utc + utc_offset_hours
            day_shift = 1 if raw_local_h >= 24 else (-1 if raw_local_h < 0 else 0)
            local_h = raw_local_h % 24
            local_d = (d_utc + day_shift) % 7
            matrix[local_d][local_h] = allowed
    return matrix


def compress_ranges(day_hours: List[int]) -> str:
    ranges: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for h in range(25):
        val = day_hours[h] if h < 24 else 0
        if val == 1 and start is None:
            start = h
        elif val == 0 and start is not None:
            ranges.append((start, h))
            start = None
    if not ranges:
        return "Nenhum"
    return ", ".join([f"{s:02d}:00-{e:02d}:00" for s, e in ranges])


def decode_logon_hours(logon_hours_raw, utc_offset_hours: int) -> Dict[str, str]:
    if not logon_hours_raw:
        return {"*": "Sem restrição"}

    raw = logon_hours_raw[0] if isinstance(logon_hours_raw, (list, tuple)) else logon_hours_raw
    if not isinstance(raw, (bytes, bytearray)):
        return {"!": "Formato inesperado"}

    matrix = build_local_matrix(bytes_to_bits_lsb_first(raw), utc_offset_hours)
    return {DAYS_PT[d]: compress_ranges(matrix[d]) for d in range(7)}


def hours_to_bits_bytes(bits: List[int]) -> bytes:
    out = bytearray(21)
    for idx, bit in enumerate(bits[:168]):
        if bit:
            out[idx // 8] |= 1 << (idx % 8)
    return bytes(out)


def parse_hour_ranges_local(ranges_text: str) -> Tuple[Optional[List[int]], Optional[str]]:
    text = (ranges_text or "").strip()
    if not text:
        return None, "Informe os intervalos, por exemplo: 07:00-12:00,14:00-18:00"

    day_hours = [0] * 24
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return None, "Formato inválido de horários."

    pattern = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*-\s*(\d{1,2})(?::(\d{2}))?$")
    for part in parts:
        m = pattern.match(part)
        if not m:
            return None, f"Intervalo inválido: {part}"

        sh, sm, eh, em = m.groups()
        start_h, end_h = int(sh), int(eh)
        start_m, end_m = int(sm) if sm else 0, int(em) if em else 0

        if start_m != 0 or end_m != 0:
            return None, f"Use apenas horas cheias (minutos :00): {part}"
        if start_h < 0 or start_h > 23:
            return None, f"Hora inicial inválida: {start_h:02d}"
        if end_h < 1 or end_h > 24:
            return None, f"Hora final inválida: {end_h:02d}"
        if end_h <= start_h:
            return None, f"O fim precisa ser maior que o início: {part}"

        for h in range(start_h, end_h):
            day_hours[h] = 1

    return day_hours, None


def build_utc_bits_from_local(local_matrix: List[List[int]], utc_offset_hours: int) -> List[int]:
    bits_utc = [0] * 168
    for local_d in range(7):
        for local_h in range(24):
            if not local_matrix[local_d][local_h]:
                continue
            raw_utc_h = local_h - utc_offset_hours
            day_shift = 1 if raw_utc_h >= 24 else (-1 if raw_utc_h < 0 else 0)
            utc_h = raw_utc_h % 24
            utc_d = (local_d + day_shift) % 7
            bits_utc[(utc_d * 24) + utc_h] = 1
    return bits_utc


def build_logon_hours_bytes(edit_mode: str, ranges_all: str, per_day_ranges: Dict[int, str], utc_offset_hours: int) -> Tuple[Optional[bytes], Optional[str]]:
    local_matrix = [[0 for _ in range(24)] for _ in range(7)]

    if edit_mode == "todos":
        day_hours, err = parse_hour_ranges_local(ranges_all)
        if err:
            return None, err
        for day_idx in range(7):
            local_matrix[day_idx] = list(day_hours or [0] * 24)
    else:
        has_any_day = False
        day_label = {idx: label for _, label, idx in DAY_INPUTS}
        for day_idx in range(7):
            raw = (per_day_ranges.get(day_idx) or "").strip()
            if not raw:
                continue
            has_any_day = True
            day_hours, err = parse_hour_ranges_local(raw)
            if err:
                return None, f"{day_label.get(day_idx, 'Dia')}: {err}"
            local_matrix[day_idx] = list(day_hours or [0] * 24)

        if not has_any_day:
            return None, "No modo personalizado, preencha ao menos um dia."

    bits_utc = build_utc_bits_from_local(local_matrix, utc_offset_hours)
    return hours_to_bits_bytes(bits_utc), None


def extract_ou_path(distinguished_name: str) -> str:
    if not distinguished_name:
        return ""
    ous = re.findall(r"OU=([^,]+)", distinguished_name, flags=re.IGNORECASE)
    return " / ".join(reversed(ous)) if ous else ""


def ad_search_users(query: str, utc_offset_hours: int) -> List[dict]:
    conn, base_dn = _conexao_ad()

    if query:
        q = query.replace("\\", "\\5c").replace("(", "\\28").replace(")", "\\29").replace("*", "\\2a")
        ldap_filter = (
            "(&(objectCategory=person)(objectClass=user)"
            f"(|(cn=*{q}*)(displayName=*{q}*)(mail=*{q}*)(sAMAccountName=*{q}*)))"
        )
    else:
        ldap_filter = "(&(objectCategory=person)(objectClass=user))"

    attrs = ["distinguishedName", "displayName", "sAMAccountName", "mail", "userAccountControl", "logonHours"]

    conn.search(search_base=base_dn, search_filter=ldap_filter, search_scope=SUBTREE, attributes=attrs, size_limit=5000)

    users: List[dict] = []
    for entry in conn.entries:
        e = entry.entry_attributes_as_dict

        uac = e.get("userAccountControl")
        disabled = bool(int(uac[0]) & 2) if isinstance(uac, list) and uac else False

        hours = decode_logon_hours(e.get("logonHours"), utc_offset_hours)
        dn = (e.get("distinguishedName") or [""])[0] if isinstance(e.get("distinguishedName"), list) else (e.get("distinguishedName") or "")

        def _primeiro(campo):
            valor = e.get(campo)
            return (valor or [""])[0] if isinstance(valor, list) else (valor or "")

        users.append({
            "displayName": _primeiro("displayName"),
            "sam": _primeiro("sAMAccountName"),
            "mail": _primeiro("mail"),
            "disabled": disabled,
            "ou": extract_ou_path(dn),
            "hours": hours,
        })

    conn.unbind()
    users.sort(key=lambda x: (x["displayName"] or x["sam"] or "").lower())
    return users


def ad_update_logon_hours_by_sam(sam: str, logon_hours_bytes: bytes) -> Tuple[bool, str]:
    conn, base_dn = _conexao_ad()

    safe_sam = sam.replace("\\", "\\5c").replace("(", "\\28").replace(")", "\\29").replace("*", "\\2a")
    conn.search(
        search_base=base_dn,
        search_filter=f"(&(objectCategory=person)(objectClass=user)(sAMAccountName={safe_sam}))",
        search_scope=SUBTREE, attributes=["distinguishedName"], size_limit=2,
    )

    if len(conn.entries) != 1:
        conn.unbind()
        return False, f"Usuário não encontrado (ou duplicado): {sam}"

    dn = conn.entries[0].entry_dn
    ok = conn.modify(dn, {"logonHours": [(MODIFY_REPLACE, [logon_hours_bytes])]})
    if not ok:
        message = (conn.result or {}).get("message") or "Falha ao atualizar logonHours no AD."
        conn.unbind()
        return False, message

    conn.unbind()
    return True, "Horário de logon atualizado com sucesso."


def ad_buscar_por_employee_id(employee_id, utc_offset_hours=-3):
    conn, base_dn = _conexao_ad()

    safe_id = employee_id.replace("\\", "\\5c").replace("(", "\\28").replace(")", "\\29").replace("*", "\\2a")
    conn.search(
        search_base=base_dn,
        search_filter=f"(&(objectCategory=person)(objectClass=user)(employeeID={safe_id}))",
        search_scope=SUBTREE,
        attributes=["distinguishedName", "displayName", "sAMAccountName", "mail", "userAccountControl", "logonHours", "employeeID"],
        size_limit=2,
    )

    if len(conn.entries) != 1:
        conn.unbind()
        return None

    entry = conn.entries[0]
    e = entry.entry_attributes_as_dict
    uac = e.get("userAccountControl")
    disabled = bool(int(uac[0]) & 2) if isinstance(uac, list) and uac else False
    dn = entry.entry_dn
    hours = decode_logon_hours(e.get("logonHours"), utc_offset_hours)

    def _primeiro(campo):
        valor = e.get(campo)
        return (valor or [""])[0] if isinstance(valor, list) else (valor or "")

    resultado = {
        "displayName": _primeiro("displayName"),
        "sam": _primeiro("sAMAccountName"),
        "mail": _primeiro("mail"),
        "employeeID": _primeiro("employeeID"),
        "disabled": disabled,
        "ou": extract_ou_path(dn),
        "hours": hours,
    }
    conn.unbind()
    return resultado


def ad_redefinir_senha(sam, nova_senha, forcar_troca=True):
    conn, base_dn = _conexao_ad()

    safe_sam = sam.replace("\\", "\\5c").replace("(", "\\28").replace(")", "\\29").replace("*", "\\2a")
    conn.search(
        search_base=base_dn,
        search_filter=f"(&(objectCategory=person)(objectClass=user)(sAMAccountName={safe_sam}))",
        search_scope=SUBTREE, attributes=["distinguishedName"], size_limit=2,
    )

    if len(conn.entries) != 1:
        conn.unbind()
        return False, f"Usuário não encontrado (ou duplicado): {sam}"

    dn = conn.entries[0].entry_dn
    senha_formatada = f'"{nova_senha}"'.encode("utf-16-le")
    ok = conn.modify(dn, {"unicodePwd": [(MODIFY_REPLACE, [senha_formatada])]})
    if not ok:
        motivo = (conn.result or {}).get("message") or "Falha ao redefinir a senha no AD."
        conn.unbind()
        return False, motivo

    conn.modify(dn, {"pwdLastSet": [(MODIFY_REPLACE, [0 if forcar_troca else -1])]})

    conn.unbind()
    return True, "Senha redefinida com sucesso."


def ad_definir_bloqueio(sam, bloquear):
    conn, base_dn = _conexao_ad()

    safe_sam = sam.replace("\\", "\\5c").replace("(", "\\28").replace(")", "\\29").replace("*", "\\2a")
    conn.search(
        search_base=base_dn,
        search_filter=f"(&(objectCategory=person)(objectClass=user)(sAMAccountName={safe_sam}))",
        search_scope=SUBTREE, attributes=["distinguishedName", "userAccountControl"], size_limit=2,
    )

    if len(conn.entries) != 1:
        conn.unbind()
        return False, f"Usuário não encontrado (ou duplicado): {sam}"

    entry = conn.entries[0]
    dn = entry.entry_dn
    uac_bruto = entry.entry_attributes_as_dict.get("userAccountControl")
    uac_atual = int(uac_bruto[0]) if isinstance(uac_bruto, list) and uac_bruto else 512

    novo_uac = (uac_atual | 2) if bloquear else (uac_atual & ~2)

    ok = conn.modify(dn, {"userAccountControl": [(MODIFY_REPLACE, [novo_uac])]})
    if not ok:
        motivo = (conn.result or {}).get("message") or "Falha ao atualizar o status da conta no AD."
        conn.unbind()
        return False, motivo

    conn.unbind()
    return True, ("Conta bloqueada com sucesso." if bloquear else "Conta desbloqueada com sucesso.")


def ad_buscar_por_sam(sam):
    conn, base_dn = _conexao_ad()

    safe_sam = sam.replace("\\", "\\5c").replace("(", "\\28").replace(")", "\\29").replace("*", "\\2a")
    conn.search(
        search_base=base_dn,
        search_filter=f"(&(objectCategory=person)(objectClass=user)(sAMAccountName={safe_sam}))",
        search_scope=SUBTREE,
        attributes=["displayName", "sAMAccountName", "mail", "employeeID"],
        size_limit=2,
    )

    if len(conn.entries) != 1:
        conn.unbind()
        return None

    e = conn.entries[0].entry_attributes_as_dict

    def _primeiro(campo):
        valor = e.get(campo)
        return (valor or [""])[0] if isinstance(valor, list) else (valor or "")

    resultado = {
        "displayName": _primeiro("displayName"),
        "sam": _primeiro("sAMAccountName"),
        "mail": _primeiro("mail"),
        "employeeID": _primeiro("employeeID"),
    }
    conn.unbind()
    return resultado


def criar_usuario_ad(nome_completo, setor, username, email, cpf, senha):
    import os

    ou_destino = os.getenv("AD_OU_NOVOS_USUARIOS", "").strip()
    if not ou_destino:
        return False, "AD_OU_NOVOS_USUARIOS não configurado no .env.", None

    conn, base_dn = _conexao_ad()

    partes_nome = nome_completo.strip().split(" ", 1)
    primeiro_nome = partes_nome[0]
    sobrenome = partes_nome[1] if len(partes_nome) > 1 else primeiro_nome

    cn = re.sub(r"[,+\"\\<>;=]", "", nome_completo.strip())
    dn = f"CN={cn},{ou_destino}"

    atributos = {
        "objectClass": ["top", "person", "organizationalPerson", "user"],
        "sAMAccountName": username,
        "userPrincipalName": email,
        "givenName": primeiro_nome,
        "sn": sobrenome,
        "displayName": nome_completo,
        "description": setor or "",
        "mail": email,
        "employeeID": cpf,
        "userAccountControl": 514,
    }

    ok = conn.add(dn, attributes=atributos)
    if not ok:
        motivo = (conn.result or {}).get("message") or "Falha ao criar usuário no AD."
        conn.unbind()
        return False, motivo, None

    senha_formatada = f'"{senha}"'.encode("utf-16-le")
    ok_senha = conn.modify(dn, {"unicodePwd": [(MODIFY_REPLACE, [senha_formatada])]})
    if not ok_senha:
        motivo = (conn.result or {}).get("message") or "Usuário criado, mas falhou ao definir a senha."
        conn.unbind()
        return False, motivo, dn

    conn.modify(dn, {"pwdLastSet": [(MODIFY_REPLACE, [0])]})
    ok_habilitar = conn.modify(dn, {"userAccountControl": [(MODIFY_REPLACE, [512])]})
    if not ok_habilitar:
        motivo = (conn.result or {}).get("message") or "Usuário criado, mas falhou ao habilitar a conta."
        conn.unbind()
        return False, motivo, dn

    conn.unbind()
    return True, "Usuário criado com sucesso no AD.", dn
