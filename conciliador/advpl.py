"""Interpretador das expressões AdvPL usadas no CT5_VLR01.

A expressão é traduzida para Python uma única vez (com cache) e avaliada com um
resolvedor de campos. Cobre o que as regras de valor usam na prática:
IIF/IF, EMPTY, operadores .AND./.OR./.NOT./!, $, =, ==, <>, !=, ALIAS->CAMPO,
ALIAS->(expressão), números, strings e funções U_ registradas em funcoes.py.
"""
import re
import datetime


class S(str):
    """String AdvPL: comparação ignora espaços à direita; `%` faz o papel do operador $."""

    def __eq__(a, b):
        return str(a).rstrip() == str(b).rstrip()

    def __ne__(a, b):
        return not a.__eq__(b)

    __hash__ = str.__hash__

    def __mod__(a, b):
        return str(a).rstrip() in str(b)

    def __add__(a, b):
        return S(str(a) + str(b))


def _iif(c, a, b):
    return a if c else b


def _empty(x):
    if x is None:
        return True
    if isinstance(x, str):
        return not x.strip()
    if isinstance(x, (int, float)):
        return x == 0
    return False


def _dtos(d):
    return d.strftime("%Y%m%d") if isinstance(d, (datetime.date, datetime.datetime)) else ""


PADRAO = {
    "IIF": _iif, "IF": _iif, "EMPTY": _empty, "S": S,
    "ROUND": lambda v, n=0: round(float(v or 0), int(n)),
    "ABS": lambda v: abs(float(v or 0)),
    "VAL": lambda v: float(str(v).strip() or 0) if re.match(r"^\s*-?[\d.]+\s*$", str(v)) else 0.0,
    "ALLTRIM": lambda v: S(str(v).strip()), "TRIM": lambda v: S(str(v).rstrip()),
    "LEFT": lambda v, n: S(str(v)[:int(n)]), "RIGHT": lambda v, n: S(str(v)[-int(n):]),
    "SUBSTR": lambda v, i, n=None: S(str(v)[int(i) - 1:(int(i) - 1 + int(n)) if n else None]),
    "DTOS": _dtos, "YEAR": lambda d: d.year if d else 0, "MONTH": lambda d: d.month if d else 0,
    "UPPER": lambda v: S(str(v).upper()),
}
# Funções nativas reconhecidas na classificação das regras (não bloqueiam a conciliação)
NATIVAS = set(PADRAO) | {"POSICIONE", "XFILIAL", "STR", "PADR", "PADL", "GETMV", "SUPERGETMV", "LERSTR",
                         "LERVAL", "LERDATA", "LEN", "INT", "DDATABASE", "CTOD", "STOD", "DAY", "AT",
                         "STRZERO", "TRANSFORM", "ISINCALLSTACK", "FUNNAME", "EXISTBLOCK", "EXECBLOCK"}

_cache = {}


def traduzir(expr):
    """Traduz AdvPL -> (code, texto_python). Levanta SyntaxError se não for traduzível."""
    if expr in _cache:
        return _cache[expr]
    lits = []

    def guarda(m):
        lits.append(m.group(0))
        return f"\x00{len(lits) - 1}\x00"

    e = re.sub(r"'[^']*'|\"[^\"]*\"", guarda, expr)
    e = re.sub(r"\b[A-Za-z][A-Za-z0-9]{2}\s*->\s*\(", "(", e)
    e = re.sub(r"\b[A-Za-z][A-Za-z0-9]{2}\s*->\s*", "", e)
    e = re.sub(r"\.AND\.", " and ", e, flags=re.I)
    e = re.sub(r"\.OR\.", " or ", e, flags=re.I)
    e = re.sub(r"\.NOT\.", " not ", e, flags=re.I)
    e = re.sub(r"\.T\.", "True", e, flags=re.I)
    e = re.sub(r"\.F\.", "False", e, flags=re.I)
    e = e.replace("<>", " != ")
    e = re.sub(r"!(?!=)", " not ", e)
    e = re.sub(r"(?<![<>!=])=(?!=)", "==", e)
    e = e.replace("$", " % ")
    # funções: U_XXX(...) e nativas conhecidas
    e = re.sub(r"\b(U_[A-Za-z0-9_]+)\s*\(", lambda m: f'FN("{m.group(1).upper()}")(', e)
    e = re.sub(r"\b([A-Za-z][A-Za-z0-9]*)\s*\(",
               lambda m: (m.group(1).upper() + "(") if m.group(1).upper() in PADRAO or m.group(1) == "FN"
               else f'FN("{m.group(1).upper()}")(', e)
    # campos XX_CAMPO / XXX_CAMPO
    e = re.sub(r'(?<!")\b([A-Za-z][A-Za-z0-9]{1,2}_[A-Za-z0-9]+)\b(?!")',
               lambda m: f'F("{m.group(1).upper()}")', e)
    e = re.sub("\x00(\\d+)\x00", lambda m: "S(" + lits[int(m.group(1))] + ")", e)
    code = compile(e.strip(), "<advpl>", "eval")
    _cache[expr] = (code, e.strip())
    return _cache[expr]


def funcoes_usadas(expr):
    """Nomes de funções chamadas na expressão (em maiúsculas)."""
    sem_str = re.sub(r"'[^']*'|\"[^\"]*\"", "", expr or "")
    return {m.upper() for m in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", sem_str)} - {"AND", "OR", "NOT"}


def avaliar(expr, campo, funcao):
    """Avalia `expr`. `campo(nome)` devolve o valor do campo; `funcao(nome)` devolve a função U_/nativa."""
    code, _ = traduzir(expr)
    return eval(code, dict(PADRAO, F=campo, FN=funcao))
