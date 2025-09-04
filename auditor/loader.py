import json               # стандартный модуль — читать .json
import yaml               # внешняя библиотека PyYAML — читать .yaml/.yml
from pathlib import Path  # удобный класс для работы с путями к файлам


def load_spec(path: Path) -> dict:
    """
    Загружает OpenAPI-спеку из .yaml/.yml или .json в словарь Python (dict).
    """
    if not path.exists():                             # проверяем, что файл вообще есть
        raise FileNotFoundError(f"Spec not found: {path}")

    text = path.read_text(encoding="utf-8")          # читаем файл как текст (строку)
    ext = path.suffix.lower()                        # получаем расширение файла, напр. ".yaml"

    if ext in {".yaml", ".yml"}:                     # если это YAML
        # safe_load: безопасный парсер YAML → Python-объекты (dict, list, str, int…)
        return yaml.safe_load(text) or {}            # если None, вернём пустой dict

    if ext == ".json":                               # если это JSON
        return json.loads(text) or {}                # превращаем JSON-строку в dict

    # Если расширение не поддерживаем — бросаем понятную ошибку
    raise ValueError(f"Unsupported file extension: {ext}. Use .yaml, .yml, or .json.")