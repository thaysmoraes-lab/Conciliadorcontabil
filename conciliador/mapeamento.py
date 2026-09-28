"""Correlação campo (X3_CAMPO) × título do genéricos (X3_TITULO) e conversão dos valores."""
import datetime
import difflib
import re
import unicodedata

from .advpl import S

LIMIAR_AUTO = 0.80


def normalizar(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9#]", "", t)


def similaridade(a, b):
    a, b = normalizar(a), normalizar(b)
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()


def mapear(cabecalho, esperados, fixos=None):
    """esperados: {campo: [títulos possíveis]}. fixos: {campo: título} já confirmados pelo usuário.
    Retorna {campo: {'titulo', 'score', 'status'}} com status 'exato', 'auto', 'manual' ou 'ausente'."""
    fixos = fixos or {}
    usados = set()
    res = {}
    for campo, titulos in esperados.items():
        if campo in fixos and fixos[campo] in cabecalho:
            res[campo] = dict(titulo=fixos[campo], score=1.0, status="manual")
            usados.add(fixos[campo])
            continue
        melhor, sc = None, 0.0
        for t in titulos:
            for h in cabecalho:
                if h in usados:
                    continue
                s = similaridade(h, t)
                if s > sc:
                    melhor, sc = h, s
        if sc >= 0.999:
            st = "exato"
        elif sc >= LIMIAR_AUTO:
            st = "auto"
        else:
            st, melhor = "ausente", None
        if melhor:
            usados.add(melhor)
        res[campo] = dict(titulo=melhor, score=round(sc, 2), status=st)
    return res


def campos_combo_numerico(expressoes):
    """Campos comparados com literal numérico ('1', '2') nas regras: nesses, Sim/Não viram 1/2."""
    out = set()
    for e in expressoes:
        for m in re.finditer(r"\b([A-Z][A-Z0-9]{1,2}_[A-Z0-9]+)\s*(?:==|=|<>|!=)\s*['\"]\d['\"]", (e or "").upper()):
            out.add(m.group(1))
    return out


_DESCR = {"SIM": "S", "NAO": "N", "NÃO": "N", "PS": "P", "BON": "B", "ICMS": "I"}


def decodificar(campo, valor, combo_numerico):
    """O genéricos exporta a descrição do combo (Sim/Não/...). Converte para o código gravado."""
    if not isinstance(valor, str):
        return valor
    s = valor.strip()
    k = s.upper()
    if k in _DESCR:
        cod = _DESCR[k]
        if campo in combo_numerico:
            return {"S": "1", "N": "2"}.get(cod, cod)
        return cod
    return valor


def registros(tabela, mapa, combo_numerico=frozenset()):
    """Converte linhas cruas em dicionários campo→valor tipado (float, datetime ou S)."""
    idx = {c: tabela.coluna(m["titulo"]) for c, m in mapa.items() if m.get("titulo")}
    numericos = {c for c, i in idx.items() if any(isinstance(r[i], (int, float)) for r in tabela.linhas[:2000] if i < len(r))}
    out = []
    for r in tabela.linhas:
        d = {}
        for c, i in idx.items():
            v = r[i] if i < len(r) else None
            if c in numericos:
                v = float(v) if isinstance(v, (int, float)) else float(str(v).replace(",", ".") or 0) if v not in (None, "") and re.match(r"^-?[\d.,]+$", str(v)) else 0.0
            elif isinstance(v, (datetime.datetime, datetime.date)):
                pass
            else:
                v = S(decodificar(c, "" if v is None else str(v), combo_numerico))
            d[c] = v
        out.append(d)
    return out
