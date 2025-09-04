from typing import Dict, List, Tuple, Iterator  # типы для подсказок и понятности

# Множество HTTP-методов, которые нас интересуют в OpenAPI "paths"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}

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