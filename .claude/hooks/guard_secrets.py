"""
Hook PreToolUse (Bash|PowerShell) — guarda de segredos.

Bloqueia comandos que:
  1. contenham uma chave da Anthropic inline (sk-ant-...);
  2. imprimam o conteudo do .env (cat/type/Get-Content etc.);
  3. forcem o .env para o git (git add -f .env).

Alinhado ao principio de soberania de dados: a chave do cliente
nunca deve aparecer em transcript, commit ou log.

Saida: JSON com permissionDecision=deny quando bloqueia; silencio quando ok.
"""

import json
import re
import sys


def deny(reason: str):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        sys.exit(0)  # sem payload legivel -> nao bloqueia

    command = str(payload.get("tool_input", {}).get("command", ""))
    if not command:
        sys.exit(0)

    # 1. chave da Anthropic inline no comando
    if re.search(r"sk-ant-[A-Za-z0-9_-]{8,}", command):
        deny(
            "Comando contem uma chave de API da Anthropic em texto puro. "
            "Nunca cole chaves em comandos; use a variavel de ambiente do .env."
        )

    # 2. leitura do conteudo do .env (valores das chaves)
    readers = r"(?:cat|type|more|less|bat|head|tail|Get-Content|gc|Select-String|grep|rg|findstr)"
    if re.search(rf"\b{readers}\b[^|;&]*(?<![\w.])\.env\b", command):
        # permitido: extrair so os NOMES das variaveis (cut -d= -f1)
        if not re.search(r"cut\s+-d=?\s*['\"]?=", command):
            deny(
                "Comando leria o conteudo do .env (valores das chaves de API). "
                "Para listar apenas os nomes das variaveis use: cut -d= -f1 .env"
            )

    # 3. git add forcado do .env (burla o .gitignore)
    if re.search(r"git\s+add\b.*(?:-f\b|--force\b).*\.env\b", command) or re.search(
        r"git\s+add\b.*\.env\b.*(?:-f\b|--force\b)", command
    ):
        deny(
            "git add --force do .env burlaria o .gitignore e commitaria "
            "as chaves de API. Bloqueado."
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
