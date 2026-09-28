"""Orquestração das etapas: CT5 → escopo → CT2 → tabelas → conciliação."""
import calendar
import datetime

from .config import TITULOS, BASES, LPS
from .ct5 import RegrasCT5, mapear_ct5, campos, alias_do_campo, modulo_do_lp
from .leitura import ler_generico
from .mapeamento import mapear, registros, campos_combo_numerico

CAMPOS_BASE = {  # campos de relacionamento/chave que o motor usa além dos da regra
    "SD1": ["D1_FILIAL", "D1_DOC", "D1_SERIE", "D1_FORNECE", "D1_LOJA", "D1_COD", "D1_ITEM", "D1_TES", "D1_TIPO", "D1_DTDIGIT", "D1_VALDESC"],
    "SF1": ["F1_FILIAL", "F1_DOC", "F1_SERIE", "F1_FORNECE", "F1_LOJA", "F1_TIPO", "F1_DTDIGIT"],
    "SD2": ["D2_DOC", "D2_SERIE", "D2_CLIENTE", "D2_LOJA", "D2_ITEM", "D2_TES", "D2_TIPO", "D2_EMISSAO"],
    "SF2": ["F2_DOC", "F2_SERIE", "F2_CLIENTE", "F2_LOJA", "F2_EMISSAO"],
    "SDE": ["DE_DOC", "DE_SERIE", "DE_FORNECE", "DE_LOJA", "DE_ITEMNF", "DE_PERC"],
    "SE5": ["E5_FILIAL", "E5_DATA", "E5_DTDISPO", "E5_TIPODOC", "E5_PREFIXO", "E5_NUMERO", "E5_PARCELA", "E5_TIPO",
            "E5_CLIFOR", "E5_LOJA", "E5_SEQ", "E5_RECPAG", "E5_MOTBX", "E5_SITUACA", "E5_NATUREZ", "E5_VALOR", "E5_LA"],
    "SE1": ["E1_FILIAL", "E1_PREFIXO", "E1_NUM", "E1_PARCELA", "E1_TIPO", "E1_CLIENTE", "E1_LOJA", "E1_NATUREZ", "E1_EMIS1"],
    "SE2": ["E2_FILIAL", "E2_PREFIXO", "E2_NUM", "E2_PARCELA", "E2_TIPO", "E2_FORNECE", "E2_LOJA", "E2_NATUREZ", "E2_EMIS1"],
    "SF4": ["F4_CODIGO"], "SA1": ["A1_COD", "A1_LOJA"], "SA2": ["A2_COD", "A2_LOJA"], "SED": ["ED_CODIGO"],
    "SB1": ["B1_COD"], "SA6": ["A6_COD"],
}
OBRIGATORIAS_CONTABEIS = ["CT2"]
OPCIONAIS = ["CV3", "ZC1", "ZC3"]


def periodo_mes(ano, mes):
    return datetime.date(ano, mes, 1), datetime.date(ano, mes, calendar.monthrange(ano, mes)[1])


def lps_do_escopo(regras, modulos=None):
    """modulos=None: conciliação completa."""
    lps = regras.lps()
    return set(lps) if modulos is None else {lp for lp in lps if modulo_do_lp(lp) in modulos}


def campos_esperados(alias, regras, lps):
    """{campo: [títulos]} para a tabela: config + campos que as regras do escopo usam."""
    cfg = dict(TITULOS.get(alias, {}))
    usados = set(CAMPOS_BASE.get(alias, []))
    for d in regras.ativas():
        if d["LP"] not in lps:
            continue
        for col in ("CT5_VLR01", "CT5_HIST", "CT5_DEBITO", "CT5_CREDIT"):
            usados |= {c for c in campos(d[col]) if alias_do_campo(c) == alias}
    esperados = {c: cfg.get(c, []) for c in usados}
    for c, t in cfg.items():
        esperados.setdefault(c, t)
    return esperados


def campos_de_valor(alias, regras, lps):
    s = set(CAMPOS_BASE.get(alias, []))
    for d in regras.ativas():
        if d["LP"] in lps:
            s |= {c for c in campos(d["CT5_VLR01"]) if alias_do_campo(c) == alias}
    return s


def preparar(tabela, regras, lps, fixos=None):
    esperados = campos_esperados(tabela.alias, regras, lps)
    mapa = mapear(tabela.cabecalho, esperados, fixos)
    combo = campos_combo_numerico(d["CT5_VLR01"] for d in regras.ativas())
    return mapa, registros(tabela, mapa, combo)


def filtro_sugerido(alias, ini, fim, lps):
    """Expressão para o filtro do genéricos, ou None quando a tabela deve ir completa."""
    f = lambda c: f"DTOS({c}) >= '{ini:%Y%m%d}' .AND. DTOS({c}) <= '{fim:%Y%m%d}'"
    n = {int(lp) for lp in lps if lp.isdigit()}
    if alias == "SE5":
        return f"({f('E5_DTDISPO')}) .OR. ({f('E5_DATA')})"
    if alias == "SE1":
        return None if any(520 <= x <= 529 or x in (588, 596) for x in n) else f("E1_EMIS1")
    if alias == "SE2":
        return None if any(530 <= x <= 539 or x in (589, 594, 597) for x in n) else f("E2_EMIS1")
    if alias == "CT2":
        return f("CT2_DATA")
    datas = {b["tabela"]: b["data"] for b in BASES.values()}
    if alias in datas and alias not in ("SN3",):
        return f(datas[alias])
    return None
