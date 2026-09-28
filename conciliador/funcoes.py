"""Funções de usuário (U_) implementadas para o recálculo do CT5_VLR01.

Toda função U_ que aparece na regra de valor precisa estar aqui. Se não estiver, o LP é marcado como
customizado/pendente e não entra na conciliação até a função ser parametrizada.

Para parametrizar uma nova função:

    @registrar("U_MINHAFUNCAO")
    def minha_funcao(motor, ctx, arg1, arg2):
        # motor.tab('SE2') -> lista de registros da tabela; ctx['SF1'] -> registro posicionado
        return 0.0

Os argumentos chegam já avaliados (S para texto, float para número, datetime para data).
"""
from .advpl import S
from .config import PARAMETROS

REGISTRO = {}


def registrar(nome):
    def deco(f):
        REGISTRO[nome.upper()] = f
        return f
    return deco


def _s(v):
    return str(v or "").strip()


@registrar("U_RETVLPCC")
def ret_vl_pcc(motor, ctx, nf, serie, fornec, loja, tipo):
    """MIT072 2.26 · soma a retenção do título a pagar da NF (PIS, COF, CSL, IRR)."""
    campo = {"PIS": "E2_VRETPIS", "COF": "E2_VRETCOF", "CSL": "E2_VRETCSL", "IRR": "E2_IRRF"}.get(_s(tipo).upper()[:3])
    if not campo:
        return 0.0
    return sum(e.get(campo, 0.0) for e in motor.tab("SE2")
               if _s(e.get("E2_NUM")) == _s(nf) and _s(e.get("E2_PREFIXO")) == _s(serie)
               and _s(e.get("E2_FORNECE")) == _s(fornec) and _s(e.get("E2_LOJA")) == _s(loja))


@registrar("U_RCTBE003")
def rctbe003(motor, ctx, tipo="IRRF"):
    """MIT072 2.24 · IRRF retido nos títulos da NF posicionada no SE2."""
    e2 = ctx.get("SE2")
    if not e2 or _s(tipo).upper() != "IRRF":
        return 0.0
    return sum(e.get("E2_IRRF", 0.0) for e in motor.tab("SE2")
               if _s(e.get("E2_NUM")) == _s(e2.get("E2_NUM")) and _s(e.get("E2_PREFIXO")) == _s(e2.get("E2_PREFIXO"))
               and _s(e.get("E2_FORNECE")) == _s(e2.get("E2_FORNECE")) and _s(e.get("E2_LOJA")) == _s(e2.get("E2_LOJA")))


@registrar("U_LPLSG")
def lplsg(motor, ctx, nopn):
    """MIT072 1.2 · natureza de leasing/financiamento/juros (parâmetros em config/parametros.json)."""
    lsg, fin, jur = (_s(PARAMETROS.get(p)) for p in ("MV_XNATLSG", "MV_XNATFIN", "MV_XNATJUR"))
    n = int(nopn or 0)
    if n == 1:
        nat = _s((ctx.get("SE2") or {}).get("E2_NATUREZ"))
        return bool(nat) and (nat in lsg or nat in fin)
    nat = _s((ctx.get("SE5") or {}).get("E5_NATUREZ"))
    if not nat:
        return False
    a, j = (nat in lsg or nat in fin), nat in jur
    return {2: a and not j, 3: a and j, 4: a or j}.get(n, False)


@registrar("U_SEV2SE1")
def sev2se1(motor, ctx):
    """MIT072 2.18 · posicionamento; o conciliador já posiciona SE1 pelo título."""
    return True


@registrar("U_SEV2SE2")
def sev2se2(motor, ctx):
    """MIT072 2.19 · posicionamento; o conciliador já posiciona SE2 pelo título."""
    return True
