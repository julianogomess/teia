"""
Hook PostToolUse (Edit|Write) — checagem de sintaxe Python.

O projeto nao tem testes nem CI: sem isso, um erro de sintaxe em
server.py so apareceria na proxima vez que o servidor subisse.
Este hook compila o .py editado na hora e devolve o erro ao Claude.

Saida: exit 2 + stderr quando a compilacao falha (feedback ao modelo);
exit 0 em qualquer outro caso.
"""

import json
import py_compile
import sys
from pathlib import Path


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        sys.exit(0)

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path") or payload.get("tool_response", {}).get("filePath")
    if not file_path:
        sys.exit(0)

    path = Path(file_path)
    if path.suffix != ".py" or not path.is_file():
        sys.exit(0)

    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        print(f"Erro de sintaxe em {path.name} apos a edicao:\n{exc}", file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
