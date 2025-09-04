from pathlib import Path                      # тип пути к файлам
import typer                                  # библиотека для CLI
from rich.console import Console              # красивый вывод в консоль
from rich.panel import Panel                  # рамочки для итогов
from rich.markdown import Markdown            # чтобы печатать Markdown красиво
from .loader import load_spec                 # наша функция загрузки спеки
from .checks import check_unique_operation_ids  # наша проверка

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

    # 2) Пишем Markdown-отчёт
    all_issues = []
    if opid_issues:
        all_issues.append("## operationId\n" + "\n".join(f"- {x}" for x in opid_issues))

    # если нет проблем — сохранится "No issues found."
    write_markdown_report(out, all_issues)

    console.print(Markdown(f"\n**Report saved to:** `{out}`"))