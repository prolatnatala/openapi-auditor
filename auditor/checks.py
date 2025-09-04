import re
from typing import Dict, List, Tuple, Iterator, Set # типы для подсказок и понятности

# Множество HTTP-методов, которые нас интересуют в OpenAPI "paths"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
PARAM_PATTERN = re.compile(r"\{([^}/]+)\}")  # ищем {param} внутри пути

# ---- naming style helpers ----
_CAMEL_RE = re.compile(r"^[a-z]+(?:[A-Z][a-z0-9]+)*$")      # userId, createdAt
_SNAKE_RE = re.compile(r"^[a-z]+(?:_[a-z0-9]+)*$")          # user_id, created_at
# (при желании можно добавить kebab: ^[a-z]+(?:-[a-z0-9]+)*$)

def detect_style(name: str) -> str:
    """Вернёт 'camel', 'snake' или 'other' по имени поля/параметра."""
    if _CAMEL_RE.match(name):
        return "camel"
    if _SNAKE_RE.match(name):
        return "snake"
    return "other"

def iter_operations(spec: Dict) -> Iterator[Tuple[str, str, Dict]]:
    """
    Генератор по всем операциям в спецификации.
    На каждой итерации отдаём (path, method, operation_object).
    """
    paths = spec.get("paths", {}) or {}          # берём раздел paths; если None — подставим {}
    for path, item in paths.items():             # path — строка ('/users'), item — dict с методами
        if not isinstance(item, dict):           # защита от кривых данных
            continue
        for method, op in item.items():          # method — 'get'/'post'..., op — тело операции (dict)
            if method.lower() in HTTP_METHODS and isinstance(op, dict):
                # отдаём наружу одну операцию за раз
                yield path, method.lower(), op

def check_unique_operation_ids(spec: Dict) -> List[str]:
    """
    Проверяет, что у всех операций:
    1) operationId задан
    2) operationId не повторяется
    Возвращает список строк-проблем.
    """
    issues: List[str] = []                      # сюда собираем найденные проблемы
    seen: Dict[str, Tuple[str, str]] = {}       # {operationId: (path, method)}

    for path, method, op in iter_operations(spec):   # обходим все операции
        op_id = op.get("operationId")               # пытемся взять operationId
        if not op_id:
            # если его нет — фиксируем проблему
            issues.append(f"[{method.upper()} {path}] missing operationId")
            continue

        if op_id in seen:
            # нашли дубль: сообщаем где он уже был
            prev_path, prev_method = seen[op_id]
            issues.append(
                f"Duplicate operationId '{op_id}' at {method.upper()} {path} "
                f"(already used at {prev_method.upper()} {prev_path})"
            )
        else:
            # запоминаем первый раз, где встретили этот operationId
            seen[op_id] = (path, method)

    return issues
def check_path_params_defined(spec: Dict) -> List[str]:
    """
    Для каждого пути вида /users/{id} проверяем:
      - что параметр 'id' объявлен в parameters с in: path
      - что он помечен required: true
    Проверяем параметры и на уровне path, и на уровне operation.
    Возвращаем список проблем.
    """
    issues: List[str] = []
    paths = spec.get("paths", {}) or {}

    for path, item in paths.items():
        if not isinstance(item, Dict):
            continue

        # 1) Собираем все {param} из самого пути
        expected_params = set(PARAM_PATTERN.findall(path))  # например, {'id', 'postId'}
        if not expected_params:
            # если в пути нет {param}, дальше по этому path нечего проверять
            continue

        # 2) Собираем параметры, объявленные на уровне path (shared)
        declared_path_level: Dict[str, Dict] = {}
        for p in item.get("parameters", []) or []:
            if isinstance(p, Dict) and p.get("in") == "path" and isinstance(p.get("name"), str):
                declared_path_level[p["name"]] = p

        # 3) Идём по операциям (get/post/...)
        for path_value, method, op in iter_operations(spec):
            if path_value != path:
                continue

            # параметры объявленные на уровне операции
            declared_op_level: Dict[str, Dict] = {}
            for p in op.get("parameters", []) or []:
                if isinstance(p, Dict) and p.get("in") == "path" and isinstance(p.get("name"), str):
                    declared_op_level[p["name"]] = p

            # Объединённый «видимый» набор параметров для операции:
            # приоритет у уровня операции (он перекрывает path-level)
            merged: Dict[str, Dict] = {**declared_path_level, **declared_op_level}

            # 4) Проверяем, что каждый {param} из пути объявлен и required: true
            for param_name in expected_params:
                meta = merged.get(param_name)
                if not meta:
                    issues.append(
                        f"[{method.upper()} {path}] path parameter '{{{param_name}}}' "
                        f"missing from parameters (in: path)"
                    )
                    continue

                if meta.get("in") != "path":
                    issues.append(
                        f"[{method.upper()} {path}] parameter '{param_name}' should have in: path"
                    )
                if meta.get("required") is not True:
                    issues.append(
                        f"[{method.upper()} {path}] parameter '{param_name}' must be required: true"
                    )

            # 5) Дополнительно предупреждаем о «лишних» path-параметрах,
            # объявленных в parameters, но отсутствующих в самом пути
            for declared_name, meta in merged.items():
                if meta.get("in") == "path" and declared_name not in expected_params:
                    issues.append(
                        f"[{method.upper()} {path}] parameter '{declared_name}' declared in: path "
                        f"but not present in the URL template"
                    )

    return issues
# Небольшой список триггер-слов (можно расширять)
VERB_TRIGGERS = {
    "create", "update", "delete", "remove", "add", "set", "get",
    "make", "do", "run", "execute", "generate"
}

def _last_segment(path: str) -> str:
    # Берём последний «кусочек» пути без слэшей, напр. "/users/createUser" -> "createUser"
    segs = [s for s in path.split("/") if s]
    return segs[-1] if segs else ""

def check_verbs_in_path(spec: Dict) -> List[str]:
    """
    Если путь выглядит как глагол в segment-е (например, /createUser),
    предупреждаем. Это эвристика: ищем триггер-глагол как префикс.
    """
    issues: List[str] = []
    paths = spec.get("paths", {}) or {}

    for path in paths.keys():
        last = _last_segment(path)
        lower = last.lower()
        # эвристика: если начинается с известного глагола — warn
        if any(lower.startswith(v) for v in VERB_TRIGGERS):
            issues.append(f"[PATH {path}] avoid verbs in URL; use resource nouns + HTTP methods")
    return issues
def _path_has_template(path: str) -> bool:
    # Есть ли {param} в самом пути
    return bool(PARAM_PATTERN.search(path))

def check_plural_collections(spec: Dict) -> List[str]:
    """
    Для GET-операций по коллекции (path без {id}) рекомендуем множественное число в последнем сегменте.
    Эвристика: последний сегмент заканчивается на 's'.
    """
    issues: List[str] = []
    for path, method, op in iter_operations(spec):
        if method != "get":
            continue
        if _path_has_template(path):
            # это не коллекция, а элемент (например, /users/{id})
            continue

        last = _last_segment(path)
        # простая эвристика: нет 's' на конце → вероятно, не множественное
        if not last.endswith("s"):
            issues.append(f"[GET {path}] collection names should be plural (e.g., '/users')")
    return issues

def _collect_json_property_names(spec: Dict) -> List[str]:
    names: List[str] = []

    # a) components.schemas.*.properties
    comps = spec.get("components", {}) or {}
    schemas = comps.get("schemas", {}) or {}
    for sch in schemas.values():
        if not isinstance(sch, Dict):
            continue
        props = sch.get("properties", {}) or {}
        for prop_name in props.keys():
            if isinstance(prop_name, str):
                names.append(prop_name)

    # b) paths.*.*.responses.*.content.application/json.schema.properties
    paths = spec.get("paths", {}) or {}
    for _, item in paths.items():
        if not isinstance(item, Dict):
            continue
        for method, op in item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(op, Dict):
                continue
            responses = op.get("responses", {}) or {}
            for _, r in responses.items():
                if not isinstance(r, Dict):
                    continue
                content = r.get("content", {}) or {}
                app_json = content.get("application/json")
                if not isinstance(app_json, Dict):
                    continue
                schema = app_json.get("schema", {}) or {}
                if not isinstance(schema, Dict):
                    continue
                props = schema.get("properties", {}) or {}
                for prop_name in props.keys():
                    if isinstance(prop_name, str):
                        names.append(prop_name)

    return names

def check_json_keys_style(spec: Dict) -> List[str]:
    """
    Собираем имена JSON-полей (properties) и проверяем, что стиль единый.
    Разрешаем только один из: camelCase или snake_case. Остальное — 'other'.
    """
    issues: List[str] = []
    names = _collect_json_property_names(spec)
    if not names:
        return issues  # нет данных — нет проблем

    styles = {"camel": 0, "snake": 0, "other": 0}
    for n in names:
        styles[detect_style(n)] += 1

    used = {k for k, v in styles.items() if v > 0}
    # если одновременно и camel, и snake → предупреждаем
    if "camel" in used and "snake" in used:
        issues.append(
            f"JSON keys mix styles: camelCase ({styles['camel']}) and snake_case ({styles['snake']}). "
            "Choose one convention."
        )
    # если много 'other' — тоже подсветим
    if styles["other"] > 0 and (styles["camel"] + styles["snake"]) > 0:
        issues.append(
            f"JSON keys contain non-standard style ({styles['other']} keys). Prefer camelCase or snake_case."
        )

    return issues


def _collect_param_names(spec: Dict) -> List[str]:
    names: List[str] = []
    paths = spec.get("paths", {}) or {}
    for path, item in paths.items():
        if not isinstance(item, Dict):
            continue

        # параметры уровня path
        for p in item.get("parameters", []) or []:
            if isinstance(p, Dict) and p.get("in") in {"path", "query"} and isinstance(p.get("name"), str):
                names.append(p["name"])

        # параметры уровня operation
        for method, op in item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(op, Dict):
                continue
            for p in op.get("parameters", []) or []:
                if isinstance(p, Dict) and p.get("in") in {"path", "query"} and isinstance(p.get("name"), str):
                    names.append(p["name"])
    return names

def check_param_names_style(spec: Dict) -> List[str]:
    """
    Проверяем, что имена параметров (path/query) не смешивают camelCase и snake_case.
    """
    issues: List[str] = []
    names = _collect_param_names(spec)
    if not names:
        return issues

    styles = {"camel": 0, "snake": 0, "other": 0}
    for n in names:
        styles[detect_style(n)] += 1

    if styles["camel"] > 0 and styles["snake"] > 0:
        issues.append(
            f"Parameter names mix styles: camelCase ({styles['camel']}) and snake_case ({styles['snake']}). "
            "Use one convention across API."
        )
    if styles["other"] > 0 and (styles["camel"] + styles["snake"]) > 0:
        issues.append(
            f"Parameter names contain non-standard style ({styles['other']} params). "
            "Prefer camelCase or snake_case."
        )
    return issues


_VER_RE = re.compile(r"/v\d+(?:\b|/)")  # ловим /v1, /v2/, /v10 ...

def check_versioning_present(spec: Dict) -> List[str]:
    """
    OAS3: servers[].url должен содержать /vN
    Swagger 2.0: basePath должен содержать /vN
    """
    issues: List[str] = []
    if "openapi" in spec:
        servers = spec.get("servers", []) or []
        if not servers:
            issues.append("No servers defined; consider providing versioned base URL like `/api/v1`.")
            return issues
        ok = False
        for s in servers:
            if not isinstance(s, Dict):
                continue
            url = s.get("url", "")
            if isinstance(url, str) and _VER_RE.search(url):
                ok = True
                break
        if not ok:
            issues.append("No version segment found in servers[].url; prefer `/.../v1` style.")
        return issues

    # Swagger 2.0
    if "swagger" in spec:
        base = spec.get("basePath", "")
        if not isinstance(base, str) or not base:
            issues.append("No basePath defined; consider versioned base path like `/api/v1`.")
            return issues
        if not _VER_RE.search(base):
            issues.append("No version segment found in basePath; prefer `/.../v1` style.")
        return issues

    # если формат не распознан — промолчим
    return issues