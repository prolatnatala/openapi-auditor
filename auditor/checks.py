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

# ---- schema completeness & types/formats ----
_ALLOWED_TYPES = {"string", "number", "integer", "boolean", "array", "object"}
_ALLOWED_FORMATS = {
    "string": {"date", "date-time", "uuid", "email", "uri", "binary", "byte", "password"},
    "integer": {"int32", "int64"},
    "number": {"float", "double"},
    # boolean/array/object обычно без format
}

def _iter_object_schemas(spec: Dict):
    """
    Итерируемся по всем 'object'-схемам в components и в request/response (application/json).
    Отдаём кортежи: (where, schema_dict), где where — удобная строка-метка.
    """
    # a) components.schemas.* (только словари)
    comps = spec.get("components", {}) or {}
    schemas = comps.get("schemas", {}) or {}
    for name, sch in schemas.items():
        if isinstance(sch, Dict):
            yield (f"components.schemas.{name}", sch)

    # b) paths.*.*.requestBody / responses.* (application/json)
    paths = spec.get("paths", {}) or {}
    for pth, item in paths.items():
        if not isinstance(item, Dict):
            continue
        for method, op in item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(op, Dict):
                continue

            # requestBody
            rb = op.get("requestBody")
            if isinstance(rb, Dict):
                content = rb.get("content", {}) or {}
                if isinstance(content, Dict):
                    aj = content.get("application/json")
                    if isinstance(aj, Dict):
                        sch = aj.get("schema")
                        if isinstance(sch, Dict):
                            yield (f"{method.upper()} {pth} requestBody", sch)

            # responses
            responses = op.get("responses", {}) or {}
            for code, r in responses.items():
                if not isinstance(r, Dict):
                    continue
                content = r.get("content", {}) or {}
                if isinstance(content, Dict):
                    aj = content.get("application/json")
                    if isinstance(aj, Dict):
                        sch = aj.get("schema")
                        if isinstance(sch, Dict):
                            yield (f"{method.upper()} {pth} response {code}", sch)

def _schema_props_and_required(schema: Dict):
    """Возвращает (properties:dict, required:set[str]) для object-схемы (если не object — пустые)."""
    if not isinstance(schema, Dict):
        return {}, set()
    # может быть $ref/allOf/oneOf/anyOf — для MVP обрабатываем простые object
    if schema.get("type") != "object" and "properties" not in schema:
        return {}, set()
    props = schema.get("properties", {}) or {}
    req = set(schema.get("required", []) or [])
    # фильтруем имена только-строки
    props = {k: v for k, v in props.items() if isinstance(k, str) and isinstance(v, Dict)}
    req = {x for x in req if isinstance(x, str)}
    return props, req

def check_schema_types_and_required(spec: Dict) -> List[str]:
    """
    Проверяем:
      - required указывает только существующие свойства
      - у каждого свойства есть type (если нет $ref/oneOf/anyOf/allOf)
      - type из допустимых значений
      - format согласован с type (если указан)
    """
    issues: List[str] = []
    for where, sch in _iter_object_schemas(spec):
        props, req = _schema_props_and_required(sch)

        # required -> существующие поля
        for name in sorted(req):
            if name not in props:
                issues.append(f"[{where}] required lists '{name}', but no such property in 'properties'")

        # валидность свойств
        for name, meta in props.items():
            # если это $ref/композиция — пропустим на этом шаге
            if "$ref" in meta or any(k in meta for k in ("oneOf", "anyOf", "allOf")):
                continue

            ty = meta.get("type")
            if not ty:
                issues.append(f"[{where}] property '{name}' missing 'type'")
                continue
            if ty not in _ALLOWED_TYPES:
                issues.append(f"[{where}] property '{name}' has unknown type '{ty}'")

            fmt = meta.get("format")
            if fmt:
                allowed = _ALLOWED_FORMATS.get(ty, set())
                if allowed and fmt not in allowed:
                    issues.append(f"[{where}] property '{name}' uses format '{fmt}' not typical for type '{ty}'")
    return issues

def check_nullable_vs_optional(spec: Dict) -> List[str]:
    """
    Предостережения:
      - поле 'nullable: true' и одновременно НЕ в required → возможно, лучше сделать поле опциональным без null
      - использование JSON Schema 'null' без OAS 'nullable' (эвристика)
    """
    issues: List[str] = []
    for where, sch in _iter_object_schemas(spec):
        props, req = _schema_props_and_required(sch)

        for name, meta in props.items():
            nullable = meta.get("nullable") is True
            is_required = name in req

            # 1) nullable + not required → предупреждение (эвристика)
            if nullable and not is_required:
                issues.append(f"[{where}] property '{name}' is nullable but not required; "
                              "consider using optional (omit) vs explicit null")

            # 2) JSON Schema 'null' без nullable
            # cases: type: ['string','null']  или anyOf/oneOf содержит {'type':'null'}
            ty = meta.get("type")
            has_null_in_type = isinstance(ty, list) and "null" in ty or ty == "null"
            has_null_in_any = any(isinstance(alt, Dict) and alt.get("type") == "null"
                                  for key in ("oneOf","anyOf") if isinstance(meta.get(key), list)
                                  for alt in meta.get(key)) if any(k in meta for k in ("oneOf","anyOf")) else False

            if (has_null_in_type or has_null_in_any) and not nullable:
                issues.append(f"[{where}] property '{name}' allows JSON Schema null but 'nullable: true' is not set")
    return issues

def check_examples_presence(spec: Dict) -> List[str]:
    """
    Требуем хотя бы один example для:
      - requestBody (application/json)
      - 2xx response (application/json)
    Дополнительно: крупные компоненты-схемы (>=3 свойств) — пример желателен.
    """
    issues: List[str] = []

    # operations: request/response
    for path, method, op in iter_operations(spec):
        # request
        rb = op.get("requestBody")
        if isinstance(rb, Dict):
            content = rb.get("content", {}) or {}
            aj = content.get("application/json")
            if isinstance(aj, Dict):
                has = bool(aj.get("example") or aj.get("examples"))
                schema = aj.get("schema", {}) or {}
                if not has and isinstance(schema, Dict) and not (schema.get("example") or schema.get("examples")):
                    issues.append(f"[{method.upper()} {path}] requestBody (application/json) has no example")

        # 2xx responses
        responses = op.get("responses", {}) or {}
        for code, r in responses.items():
            if not isinstance(r, Dict):
                continue
            if not str(code).startswith("2"):
                continue
            content = r.get("content", {}) or {}
            aj = content.get("application/json")
            if isinstance(aj, Dict):
                has = bool(aj.get("example") or aj.get("examples"))
                schema = aj.get("schema", {}) or {}
                if not has and isinstance(schema, Dict) and not (schema.get("example") or schema.get("examples")):
                    issues.append(f"[{method.upper()} {path}] response {code} (application/json) has no example")

    # components: большие схемы — желательно иметь example
    comps = spec.get("components", {}) or {}
    schemas = comps.get("schemas", {}) or {}
    for name, sch in schemas.items():
        if not isinstance(sch, Dict):
            continue
        props = sch.get("properties", {}) or {}
        if isinstance(props, Dict) and len(props) >= 3:
            if not (sch.get("example") or sch.get("examples")):
                issues.append(f"[components.schemas.{name}] consider adding example for larger schema")

    return issues

def _is_large_inline_object(schema: Dict, min_props: int = 5) -> bool:
    if not isinstance(schema, Dict):
        return False
    if "$ref" in schema:
        return False
    if schema.get("type") == "object" and isinstance(schema.get("properties"), Dict):
        return len(schema["properties"]) >= min_props
    return False

def check_dry_refs(spec: Dict) -> List[str]:
    """
    Ищем крупные inline object-схемы (>=5 свойств) в request/response и рекомендуем вынести в components + $ref.
    """
    issues: List[str] = []
    for where, sch in _iter_object_schemas(spec):
        if _is_large_inline_object(sch, min_props=5):
            issues.append(f"[{where}] large inline object; consider extracting to components/schemas and using $ref")
    return issues

