import os
import time
from datetime import datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ADJUSTMENT_API_URL = "https://employer.tangerino.com.br/adjustment/find-all"
EMPLOYEE_API_URL = "https://employer.tangerino.com.br/employee/find-all"
EMPLOYEE_FIND_URL = "https://employer.tangerino.com.br/employee/find"
WORKPLACE_API_URL = "https://employer.tangerino.com.br/workplace/find-all"
JOB_ROLE_API_URL = "https://employer.tangerino.com.br/job-role/find-all"

DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_READ_TIMEOUT = 60
DEFAULT_RETRY_TOTAL = 3
DEFAULT_RETRY_BACKOFF = 1.0
DEFAULT_WORKPLACE_CACHE_TTL_SECONDS = 600
DEFAULT_JOB_ROLE_CACHE_TTL_SECONDS = 600
DEFAULT_EMPLOYEES_CACHE_TTL_SECONDS = 90
LOCAL_TZ = timezone(timedelta(hours=-3))

WORKPLACE_CACHE = {"expires_at": 0.0, "name_map": {}}
JOB_ROLE_CACHE = {"expires_at": 0.0, "name_map": {}}
EMPLOYEES_CACHE = {
    "ativos": {"expires_at": 0.0, "itens": []},
    "demitidos": {"expires_at": 0.0, "itens": []},
}
VACATION_CACHE = {"expires_at": 0.0, "itens": []}


class TangerinoConfigError(Exception):
    pass


def get_headers_from_env() -> dict:
    auth = os.getenv("TANGERINO_AUTH", "").strip()
    if not auth:
        raise TangerinoConfigError("Defina TANGERINO_AUTH no .env (ex: 'Basic ...').")
    return {
        "Authorization": auth,
        "accept": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0",
    }


def _get_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _get_float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def get_timeout() -> tuple:
    return (
        _get_float_env("TANGERINO_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT),
        _get_float_env("TANGERINO_READ_TIMEOUT", DEFAULT_READ_TIMEOUT),
    )


def build_http_session() -> requests.Session:
    retries = Retry(
        total=_get_int_env("TANGERINO_RETRY_TOTAL", DEFAULT_RETRY_TOTAL),
        backoff_factor=_get_float_env("TANGERINO_RETRY_BACKOFF", DEFAULT_RETRY_BACKOFF),
        allowed_methods=frozenset(["GET"]),
        status_forcelist=(429, 500, 502, 503, 504),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def ms_to_local_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=LOCAL_TZ).strftime("%d/%m/%Y %H:%M")


def to_date_str(value):
    if value is None:
        return "-", None

    dt = None
    if isinstance(value, (int, float)):
        ts_ms = int(value if value > 10_000_000_000 else value * 1000)
        try:
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        except Exception:
            dt = None
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return "-", None
        if raw.isdigit():
            return to_date_str(int(raw))
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except ValueError:
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue

    if dt is None:
        return str(value), None
    return dt.strftime("%d/%m/%Y"), int(dt.timestamp() * 1000)


def get_first_present(employee: dict, keys):
    for key in keys:
        if key in employee and employee.get(key) not in (None, ""):
            return employee.get(key)
    return None


def normalizar_cpf(valor):
    digitos = "".join(c for c in str(valor or "") if c.isdigit())
    if digitos and len(digitos) < 11:
        digitos = digitos.zfill(11)
    return digitos


def to_date_yyyy_mm_dd(s: str):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def overlaps_interval(start_ms: int, end_ms: int, from_d, to_d) -> bool:
    from_ms = int(datetime(from_d.year, from_d.month, from_d.day, 0, 0, 0, tzinfo=LOCAL_TZ).timestamp() * 1000) if from_d else None
    to_ms = int(datetime(to_d.year, to_d.month, to_d.day, 23, 59, 59, tzinfo=LOCAL_TZ).timestamp() * 1000) if to_d else None

    if from_ms is not None and end_ms < from_ms:
        return False
    if to_ms is not None and start_ms > to_ms:
        return False
    return True


def _extract_items_and_total_pages(data):
    if isinstance(data, list):
        return data, None
    if not isinstance(data, dict):
        return [], None

    if isinstance(data.get("content"), list):
        total_pages = data.get("totalPages")
        return data.get("content") or [], total_pages if isinstance(total_pages, int) else None

    for key in ("items", "data", "result"):
        value = data.get(key)
        if isinstance(value, list):
            return value, None
    return [], None


def _fetch_single_page(session, url, headers, timeout, params):
    r = session.get(url, headers=headers, params=params, timeout=timeout)
    debug_url = r.url
    r.raise_for_status()
    items, total_pages = _extract_items_and_total_pages(r.json())
    return items, total_pages, debug_url


def _buscar_employees_por_particao(session, headers, timeout, show_fired_flag, api_page_size=200):
    resultado = []
    vistos = set()
    page = 0
    total_pages = None

    while True:
        items, total_pages_found, _ = _fetch_single_page(
            session, EMPLOYEE_API_URL, headers, timeout,
            {"showFired": show_fired_flag, "page": page, "size": api_page_size, "managerDetails": "true"},
        )
        if total_pages is None:
            total_pages = total_pages_found

        for item in items:
            if not isinstance(item, dict):
                continue
            chave = item.get("id")
            if chave is not None:
                if chave in vistos:
                    continue
                vistos.add(chave)
            resultado.append(item)

        if total_pages is not None and page >= (total_pages - 1):
            break
        if not items:
            break
        page += 1

    return resultado


def get_employees_cache_ttl_seconds() -> int:
    return max(15, _get_int_env("EMPLOYEES_CACHE_TTL_SECONDS", DEFAULT_EMPLOYEES_CACHE_TTL_SECONDS))


def _buscar_employees_por_particao_cacheado(session, headers, timeout, show_fired_flag, api_page_size=200):
    chave = "demitidos" if show_fired_flag == 1 else "ativos"
    cache = EMPLOYEES_CACHE[chave]
    now = time.time()

    if cache["itens"] and cache["expires_at"] > now:
        return cache["itens"]

    itens = _buscar_employees_por_particao(session, headers, timeout, show_fired_flag, api_page_size)
    cache["itens"] = itens
    cache["expires_at"] = now + get_employees_cache_ttl_seconds()
    return itens


def buscar_todos_employees_brutos(session, headers, timeout, api_page_size=200, incluir_demitidos=True):
    ativos = _buscar_employees_por_particao_cacheado(session, headers, timeout, 0, api_page_size)
    if not incluir_demitidos:
        return ativos

    demitidos = _buscar_employees_por_particao_cacheado(session, headers, timeout, 1, api_page_size)
    vistos = {emp.get("id") for emp in ativos if isinstance(emp.get("id"), int)}
    combinados = list(ativos)
    for emp in demitidos:
        id_ = emp.get("id")
        if isinstance(id_, int) and id_ in vistos:
            continue
        combinados.append(emp)
        if isinstance(id_, int):
            vistos.add(id_)

    return combinados


def contar_colaboradores_por_status():
    headers = get_headers_from_env()
    session = build_http_session()
    timeout = get_timeout()

    ativos = _buscar_employees_por_particao_cacheado(session, headers, timeout, 0)
    demitidos = _buscar_employees_por_particao_cacheado(session, headers, timeout, 1)

    ids_ativos = {emp.get("id") for emp in ativos if isinstance(emp.get("id"), int)}
    total_demitidos_sem_duplicar = sum(1 for emp in demitidos if emp.get("id") not in ids_ativos)

    return len(ativos), total_demitidos_sem_duplicar


def contar_em_ferias_agora():
    _, _, total_now = fetch_vacation_rows_page(
        from_d=None, to_d=None, status_filter=None, only_now=True,
        ui_page=1, ui_page_size=100000, api_page_size=200,
    )
    return total_now


def get_workplace_cache_ttl_seconds() -> int:
    return max(30, _get_int_env("WORKPLACE_CACHE_TTL_SECONDS", DEFAULT_WORKPLACE_CACHE_TTL_SECONDS))


def get_job_role_cache_ttl_seconds() -> int:
    return max(30, _get_int_env("JOB_ROLE_CACHE_TTL_SECONDS", DEFAULT_JOB_ROLE_CACHE_TTL_SECONDS))


def build_workplace_name_map(workplaces) -> dict:
    result = {}
    for wp in workplaces:
        wp_id = wp.get("id")
        if isinstance(wp_id, int):
            result[wp_id] = str(wp.get("name") or wp.get("description") or wp.get("title") or f"ID {wp_id}")
    return result


def build_job_role_name_map(job_roles) -> dict:
    result = {}
    for role in job_roles:
        role_id = role.get("id")
        if isinstance(role_id, int):
            result[role_id] = str(role.get("description") or role.get("name") or role.get("title") or f"ID {role_id}")
    return result


def _fetch_all_pages(session, url, headers, timeout, api_page_size):
    page = 0
    total_pages = None
    all_items = []
    while True:
        items, total_pages_found, _ = _fetch_single_page(session, url, headers, timeout, {"page": page, "size": api_page_size})
        all_items.extend(items)
        if total_pages is None:
            total_pages = total_pages_found
        if total_pages is not None and page >= (total_pages - 1):
            break
        if not items:
            break
        page += 1
    return all_items


def get_workplace_name_map_cached(session, headers, timeout, api_page_size) -> dict:
    now = time.time()
    if WORKPLACE_CACHE["name_map"] and WORKPLACE_CACHE["expires_at"] > now:
        return WORKPLACE_CACHE["name_map"]

    name_map = build_workplace_name_map(_fetch_all_pages(session, WORKPLACE_API_URL, headers, timeout, api_page_size))
    WORKPLACE_CACHE["name_map"] = name_map
    WORKPLACE_CACHE["expires_at"] = now + get_workplace_cache_ttl_seconds()
    return name_map


def get_job_role_name_map_cached(session, headers, timeout, api_page_size) -> dict:
    now = time.time()
    if JOB_ROLE_CACHE["name_map"] and JOB_ROLE_CACHE["expires_at"] > now:
        return JOB_ROLE_CACHE["name_map"]

    name_map = build_job_role_name_map(_fetch_all_pages(session, JOB_ROLE_API_URL, headers, timeout, api_page_size))
    JOB_ROLE_CACHE["name_map"] = name_map
    JOB_ROLE_CACHE["expires_at"] = now + get_job_role_cache_ttl_seconds()
    return name_map


def _buscar_todos_ajustes_ferias_cacheado(session, headers, timeout, api_page_size=200):
    now = time.time()
    if VACATION_CACHE["itens"] and VACATION_CACHE["expires_at"] > now:
        return VACATION_CACHE["itens"]

    resultado = []
    vistos = set()
    page = 0
    total_pages = None

    while True:
        items, total_pages_found, _ = _fetch_single_page(
            session, ADJUSTMENT_API_URL, headers, timeout,
            {"adjustmentReasonId": 1, "page": page, "size": api_page_size},
        )
        if total_pages is None:
            total_pages = total_pages_found

        for it in items:
            if not isinstance(it, dict):
                continue
            chave = it.get("id")
            if chave is None:
                emp = it.get("employeeDTO") or {}
                chave = (emp.get("id") or emp.get("email") or emp.get("name"), it.get("startDate"), it.get("endDate"), it.get("status"))
            if chave in vistos:
                continue
            vistos.add(chave)
            resultado.append(it)

        if total_pages is not None and page >= (total_pages - 1):
            break
        if not items:
            break
        page += 1

    VACATION_CACHE["itens"] = resultado
    VACATION_CACHE["expires_at"] = now + get_employees_cache_ttl_seconds()
    return resultado


def fetch_vacation_rows_page(from_d, to_d, status_filter, only_now, ui_page, ui_page_size, api_page_size):
    headers = get_headers_from_env()
    session = build_http_session()
    timeout = get_timeout()
    agora_ms = int(time.time() * 1000)

    ajustes = _buscar_todos_ajustes_ferias_cacheado(session, headers, timeout, api_page_size)

    matches = []
    total_em_ferias_agora = 0

    for it in ajustes:
        st, en = it.get("startDate"), it.get("endDate")
        if st is None or en is None:
            continue

        in_now = (it.get("status") == "APROVADO") and (st <= agora_ms <= en)
        if in_now:
            total_em_ferias_agora += 1

        if status_filter and it.get("status") != status_filter:
            continue
        if (from_d or to_d) and not overlaps_interval(st, en, from_d, to_d):
            continue
        if only_now and not in_now:
            continue

        emp = it.get("employeeDTO") or {}
        matches.append({
            "name": emp.get("name", f"ID {emp.get('id', '?')}"),
            "email": emp.get("email"),
            "start_str": ms_to_local_str(st),
            "end_str": ms_to_local_str(en),
            "status": it.get("status", "-"),
            "in_now": in_now,
        })

    matches.sort(key=lambda x: x.get("start_str", ""))
    target_start = (ui_page - 1) * ui_page_size
    page_rows = matches[target_start: target_start + ui_page_size]
    has_next = len(matches) > (target_start + ui_page_size)
    total_now = total_em_ferias_agora
    return page_rows, has_next, total_now


def infer_employment_status(employee: dict) -> str:
    for key in ("fired", "isFired", "dismissed", "demitted", "terminated"):
        value = employee.get(key)
        if isinstance(value, bool):
            return "DEMITIDO" if value else "EMPREGADO"

    for key in ("dismissalDate", "demissionDate", "terminationDate"):
        if employee.get(key):
            return "DEMITIDO"

    active = employee.get("active")
    if isinstance(active, bool):
        return "EMPREGADO" if active else "DEMITIDO"

    raw_status = str(employee.get("status", "")).upper()
    if any(token in raw_status for token in ("DEMIT", "FIRED", "DISMISS", "INATIVO")):
        return "DEMITIDO"
    return "EMPREGADO"


def extract_workplace_ids(employee: dict):
    ids = []
    for item in employee.get("workplaceList") or []:
        if isinstance(item, int):
            ids.append(item)
        elif isinstance(item, dict) and isinstance(item.get("id"), int):
            ids.append(item.get("id"))
    return ids


def extract_job_role_id(employee: dict):
    for key in ("jobRoleId", "jobroleId", "roleId", "officeId", "positionId"):
        value = employee.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    for item in (employee.get("jobRoleDTO"), employee.get("jobRole"), employee.get("role"), employee.get("office"), employee.get("position")):
        if isinstance(item, dict):
            nested_id = item.get("id")
            if isinstance(nested_id, int):
                return nested_id
            if isinstance(nested_id, str) and nested_id.isdigit():
                return int(nested_id)
    return None


def extract_job_role_description(employee: dict) -> str:
    for value in (employee.get("jobRoleDescription"), employee.get("roleDescription"), employee.get("officeDescription"), employee.get("positionDescription")):
        if isinstance(value, str) and value.strip():
            return value.strip()

    for item in (employee.get("jobRoleDTO"), employee.get("jobRole"), employee.get("role"), employee.get("office"), employee.get("position")):
        if isinstance(item, dict):
            for key in ("description", "name", "title"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def sort_employee_rows(rows, sort_by: str, sort_dir: str) -> None:
    reverse = sort_dir == "desc"
    if sort_by == "admission_date":
        rows.sort(key=lambda x: (x["admission_ts"] is None, x["admission_ts"] or 0), reverse=reverse)
    elif sort_by == "dismissal_date":
        rows.sort(key=lambda x: (x["dismissal_ts"] is None, x["dismissal_ts"] or 0), reverse=reverse)
    elif sort_by == "workplace":
        rows.sort(key=lambda x: (x["workplaces_sort"] == "", x["workplaces_sort"]), reverse=reverse)
    elif sort_by == "job_role":
        rows.sort(key=lambda x: (x["job_role_sort"] == "", x["job_role_sort"]), reverse=reverse)
    else:
        rows.sort(key=lambda x: x["name"].lower(), reverse=reverse)


def buscar_todos_colaboradores_com_admissao():
    return fetch_employee_rows_page(
        employment_status="", q="", show_fired=True,
        sort_by="name", sort_dir="asc", employee_mode="global",
        ui_page=1, ui_page_size=100000, api_page_size=200,
    )[0]


def contar_admissoes_por_setor(rows, inicio=None, fim=None, top=10):
    contagem = {}

    for linha in rows:
        ts = linha.get("admission_ts")
        if not ts:
            continue

        data_iso = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if inicio and data_iso < inicio:
            continue
        if fim and data_iso > fim:
            continue

        setor = (linha.get("workplaces") or "").split(",")[0].strip() or "Não informado"
        contagem[setor] = contagem.get(setor, 0) + 1

    ranking = sorted(contagem.items(), key=lambda item: item[1], reverse=True)[:top]
    return [{"setor": setor, "quantidade": quantidade} for setor, quantidade in ranking]


def fetch_employee_rows_page(employment_status, q, show_fired, sort_by, sort_dir, employee_mode, ui_page, ui_page_size, api_page_size):
    headers = get_headers_from_env()
    session = build_http_session()
    timeout = get_timeout()
    workplace_name_map = get_workplace_name_map_cached(session, headers, timeout, max(api_page_size, 100))
    job_role_name_map = get_job_role_name_map_cached(session, headers, timeout, max(api_page_size, 100))

    brutos = buscar_todos_employees_brutos(session, headers, timeout, api_page_size, incluir_demitidos=show_fired)

    target_start = (ui_page - 1) * ui_page_size
    q_lower = q.lower()
    all_rows = []

    for emp in brutos:
        name = str(emp.get("name") or emp.get("fullName") or f"ID {emp.get('id', '?')}")
        cpf_normalizado = normalizar_cpf(get_first_present(emp, ("cpf", "cpfNumber", "documento", "numeroCpf", "docNumber"))) or None

        if q_lower:
            q_digitos = "".join(c for c in q_lower if c.isdigit())
            bate_nome = q_lower in name.lower()
            bate_cpf = bool(q_digitos) and bool(cpf_normalizado) and q_digitos in cpf_normalizado
            if not (bate_nome or bate_cpf):
                continue

        emp_status = infer_employment_status(emp)
        if employment_status and emp_status != employment_status:
            continue

        workplace_names = [workplace_name_map.get(wp_id, f"ID {wp_id}") for wp_id in extract_workplace_ids(emp)]
        job_role_id = extract_job_role_id(emp)
        job_role_name = extract_job_role_description(emp) or (job_role_name_map.get(job_role_id) if job_role_id is not None else "") or "-"

        admission_raw = get_first_present(emp, ("admissionDate", "hireDate", "hiringDate", "admission", "admittedAt", "createdAt"))
        dismissal_raw = get_first_present(emp, ("resignationDate", "dismissalDate", "demissionDate", "terminationDate", "firedAt", "terminatedAt"))
        admission_date_str, admission_ts = to_date_str(admission_raw)
        dismissal_date_str, dismissal_ts = to_date_str(dismissal_raw)

        all_rows.append({
            "name": name,
            "email": emp.get("email"),
            "cpf": cpf_normalizado,
            "id_tangerino": emp.get("id"),
            "employment_status": emp_status,
            "admission_date_str": admission_date_str,
            "dismissal_date_str": dismissal_date_str,
            "admission_ts": admission_ts,
            "dismissal_ts": dismissal_ts,
            "job_role": job_role_name,
            "job_role_sort": "" if job_role_name == "-" else job_role_name.lower(),
            "workplaces": ", ".join(workplace_names),
            "workplaces_sort": (", ".join(workplace_names)).lower(),
        })

    sort_employee_rows(all_rows, sort_by=sort_by, sort_dir=sort_dir)
    page_rows = all_rows[target_start: target_start + ui_page_size]
    has_next = len(all_rows) > (target_start + ui_page_size)

    return page_rows, has_next


def _extrair_colaborador_da_listagem(emp, session, headers, timeout, api_page_size=200):
    workplace_name_map = get_workplace_name_map_cached(session, headers, timeout, max(api_page_size, 100))
    job_role_name_map = get_job_role_name_map_cached(session, headers, timeout, max(api_page_size, 100))

    workplace_names = [workplace_name_map.get(wp_id, f"ID {wp_id}") for wp_id in extract_workplace_ids(emp)]
    job_role_id = extract_job_role_id(emp)
    job_role_name = extract_job_role_description(emp) or (job_role_name_map.get(job_role_id) if job_role_id is not None else "") or ""

    telefone_raw = get_first_present(emp, ("phone", "telephone", "cellphone", "mobilePhone", "phoneNumber"))
    nascimento_raw = get_first_present(emp, ("birthDate", "dateOfBirth", "birthday"))
    nascimento_str = to_date_str(nascimento_raw)[0] if nascimento_raw else None
    matricula_raw = emp.get("externalId")

    return {
        "nome": str(emp.get("name") or emp.get("fullName") or ""),
        "cpf": normalizar_cpf(get_first_present(emp, ("cpf", "cpfNumber", "documento", "numeroCpf", "docNumber"))),
        "matricula": str(matricula_raw) if matricula_raw else None,
        "telefone": str(telefone_raw) if telefone_raw else None,
        "data_nascimento": nascimento_str,
        "setor": workplace_names[0] if workplace_names else None,
        "cargo": job_role_name or None,
        "email_pessoal": emp.get("email"),
    }


def buscar_colaborador_por_cpf(cpf_busca, api_page_size=200):
    cpf_normalizado = normalizar_cpf(cpf_busca)
    if not cpf_normalizado:
        return None

    headers = get_headers_from_env()
    session = build_http_session()
    timeout = get_timeout()

    brutos = buscar_todos_employees_brutos(session, headers, timeout, api_page_size, incluir_demitidos=True)

    for emp in brutos:
        cpf_emp = normalizar_cpf(get_first_present(emp, ("cpf", "cpfNumber", "documento", "numeroCpf", "docNumber")))
        if cpf_emp and cpf_emp == cpf_normalizado:
            return _extrair_colaborador_da_listagem(emp, session, headers, timeout, api_page_size)

    return None
