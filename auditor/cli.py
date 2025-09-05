from pathlib import Path                      # тип пути к файлам
import typer                                  # библиотека для CLI
from rich.console import Console              # красивый вывод в консоль
from rich.panel import Panel                  # рамочки для итогов
from rich.markdown import Markdown            # чтобы печатать Markdown красиво
from .loader import load_spec                 # наша функция загрузки спеки
from .checks import (check_unique_operation_ids, 
                     check_path_params_defined, 
                     check_verbs_in_path, 
                     check_plural_collections, 
                     check_json_keys_style, 
                     check_param_names_style, 
                     check_versioning_present, 
                     check_schema_types_and_required, 
                     check_nullable_vs_optional, 
                     check_examples_presence, 
                     check_dry_refs)

app = typer.Typer(help="OpenAPI Auditor (MVP)")   # создаём CLI-приложение
console = Console()                               # объект для красивого вывода

def write_markdown_report(target: Path, lines: list[str]) -> None:
    """
    Сохраняет Markdown-отчёт в файл.
    """
    header = "# OpenAPI Audit Report\n\n"
    body = "\n".join(f"- {line}" for line in lines) if lines else "_No issues found._"
    target.write_text(header + body + "\n", encoding="utf-8")

@app.command("audit")                           # ЯВНО называем команду "audit"
def audit(spec_path: Path, out: Path = Path("audit_report.md")):
    """
    Команда: проверяет спецификацию и пишет отчёт.
    Аргументы:
    - spec_path: путь к .yaml/.yml или .json
    - out: путь к markdown-отчёту (по умолчанию audit_report.md)
    """
    spec = load_spec(spec_path)                 # читаем спецификацию
    version = spec.get("openapi") or spec.get("swagger")

    console.print(Panel.fit(f"Spec: [bold]{spec_path}[/bold]\nOpenAPI version: [bold]{version}[/bold]",
                            title="OpenAPI Auditor"))

    # 1) Первая реальная проверка: уникальность operationId
    opid_issues = check_unique_operation_ids(spec)

    if not opid_issues:
        console.print("[green]:white_check_mark: operationId — OK (all unique and present)[/green]")
    else:
        console.print("[yellow]:warning: operationId issues found:[/yellow]")
        for line in opid_issues:
            console.print(f"  • {line}")

    # 2) Проверка соответствия {pathParam} ↔ parameters (in: path, required: true)
    path_param_issues = check_path_params_defined(spec)
    if not path_param_issues:
        console.print("[green]:white_check_mark: path parameters — OK[/green]")
    else:
        console.print("[yellow]:warning: path parameter issues found:[/yellow]")
        for line in path_param_issues:
            console.print(f"  • {line}")

    # 3) Глаголы в path
    verb_path_issues = check_verbs_in_path(spec)
    if not verb_path_issues:
        console.print("[green]:white_check_mark: path verbs — OK[/green]")
    else:
        console.print("[yellow]:warning: verb-in-path issues found:[/yellow]")
        for line in verb_path_issues:
            console.print(f"  • {line}")

    # 4) Множественное число для коллекций
    plural_issues = check_plural_collections(spec)
    if not plural_issues:
        console.print("[green]:white_check_mark: plural collections — OK[/green]")
    else:
        console.print("[yellow]:warning: pluralization issues found:[/yellow]")
        for line in plural_issues:
            console.print(f"  • {line}")   

    # 5) Стиль JSON-ключей
    json_style_issues = check_json_keys_style(spec)
    if not json_style_issues:
        console.print("[green]:white_check_mark: JSON key style — OK[/green]")
    else:
        console.print("[yellow]:warning: JSON key style issues:[/yellow]")
        for line in json_style_issues:
            console.print(f"  • {line}")

    # 6) Стиль имён параметров (path/query)
    param_style_issues = check_param_names_style(spec)
    if not param_style_issues:
        console.print("[green]:white_check_mark: parameter name style — OK[/green]")
    else:
        console.print("[yellow]:warning: parameter name style issues:[/yellow]")
        for line in param_style_issues:
            console.print(f"  • {line}")

    # 7) Версионирование
    versioning_issues = check_versioning_present(spec)
    if not versioning_issues:
        console.print("[green]:white_check_mark: versioning (servers/basePath) — OK[/green]")
    else:
        console.print("[yellow]:warning: versioning issues:[/yellow]")
        for line in versioning_issues:
            console.print(f"  • {line}")

    # 8) Типы/required и полнота схем
    schema_req_issues = check_schema_types_and_required(spec)
    if not schema_req_issues:
        console.print("[green]:white_check_mark: schema types/required — OK[/green]")
    else:
        console.print("[yellow]:warning: schema types/required issues:[/yellow]")
        for line in schema_req_issues:
            console.print(f"  • {line}")

    # 9) Nullable vs optional
    nullable_issues = check_nullable_vs_optional(spec)
    if not nullable_issues:
        console.print("[green]:white_check_mark: nullable vs optional — OK[/green]")
    else:
        console.print("[yellow]:warning: nullable vs optional issues:[/yellow]")
        for line in nullable_issues:
            console.print(f"  • {line}")

    # 10) Примеры в request/response и крупных схемах
    examples_issues = check_examples_presence(spec)
    if not examples_issues:
        console.print("[green]:white_check_mark: examples — OK[/green]")
    else:
        console.print("[yellow]:warning: examples issues:[/yellow]")
        for line in examples_issues:
            console.print(f"  • {line}")

    # 11) DRY / крупные inline-схемы → предложить $ref
    dry_ref_issues = check_dry_refs(spec)
    if not dry_ref_issues:
        console.print("[green]:white_check_mark: DRY ($ref) — OK[/green]")
    else:
        console.print("[yellow]:warning: DRY/$ref suggestions:[/yellow]")
        for line in dry_ref_issues:
            console.print(f"  • {line}")                             

    # 12) Пишем Markdown-отчёт
    all_issues = []
    if opid_issues:
        all_issues.append("## operationId\n" + "\n".join(f"- {x}" for x in opid_issues))
    if path_param_issues:
        all_issues.append("## path parameters\n" + "\n".join(f"- {x}" for x in path_param_issues))
    if verb_path_issues:
        all_issues.append("## verbs in path\n" + "\n".join(f"- {x}" for x in verb_path_issues))
    if plural_issues:
        all_issues.append("## plural collections\n" + "\n".join(f"- {x}" for x in plural_issues))
    if json_style_issues:
        all_issues.append("## JSON key style\n" + "\n".join(f"- {x}" for x in json_style_issues))
    if param_style_issues:
        all_issues.append("## parameter name style\n" + "\n".join(f"- {x}" for x in param_style_issues))
    if versioning_issues:
        all_issues.append("## versioning\n" + "\n".join(f"- {x}" for x in versioning_issues))
    if schema_req_issues:
        all_issues.append("## schema types & required\n" + "\n".join(f"- {x}" for x in schema_req_issues))
    if nullable_issues:
        all_issues.append("## nullable vs optional\n" + "\n".join(f"- {x}" for x in nullable_issues))
    if examples_issues:
        all_issues.append("## examples\n" + "\n".join(f"- {x}" for x in examples_issues))
    if dry_ref_issues:
        all_issues.append("## DRY ($ref)\n" + "\n".join(f"- {x}" for x in dry_ref_issues))
            

    # если нет проблем — сохранится "No issues found."
    write_markdown_report(out, all_issues)

    console.print(Markdown(f"\n**Report saved to:** `{out}`"))