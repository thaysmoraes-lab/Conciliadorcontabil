import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conciliador.advpl import avaliar, traduzir, S, funcoes_usadas
from conciliador.leitura import Tabela
from conciliador.mapeamento import mapear, decodificar, campos_combo_numerico, normalizar
from conciliador.ct5 import RegrasCT5, mapear_ct5
from conciliador.config import SX3_CT5
from conciliador.motor import Motor


def _av(expr, ctx):
    return avaliar(expr, lambda c: ctx[c], lambda n: (_ for _ in ()).throw(KeyError(n)))


def test_operadores_advpl():
    ctx = {"E5_TIPO": S("NF "), "E5_MOTBX": S("NOR"), "E5_VALOR": 100.0, "E5_VLJUROS": 2.0, "E5_VLMULTA": 0.0, "E5_VLDESCO": 1.0}
    e = "IIF(SE5->E5_TIPO<>'CH'.AND.SE5->E5_MOTBX$'NOR,DEB,FAT',SE5->(E5_VALOR-E5_VLMULTA-E5_VLJUROS+E5_VLDESCO),0)"
    assert _av(e, ctx) == 99.0
    assert _av("IF(!SE5->E5_TIPO$'CH',1,0)", ctx) == 1
    assert _av("IIF(SE5->E5_TIPO='NF',1,0)", ctx) == 1          # compara ignorando espaços à direita


def test_funcoes_usadas():
    assert funcoes_usadas("U_RetVlPCC(SF1->F1_DOC,'PIS')+IIF(.T.,1,0)") == {"U_RETVLPCC", "IIF"}


def test_mapeamento_titulos():
    m = mapear(["Filial", "Vlr.Total", "DT Digitacao", "Documento"],
               {"D1_TOTAL": ["Vlr.Total"], "D1_DTDIGIT": ["Dt. Digitação"], "D1_XPTO": ["Campo Inexistente"]})
    assert m["D1_TOTAL"]["status"] == "exato"
    assert m["D1_DTDIGIT"]["status"] in ("exato", "auto")
    assert m["D1_XPTO"]["status"] == "ausente"
    assert normalizar("Cód. Cliente") == "codcliente"


def test_combo_do_generico():
    num = campos_combo_numerico(["IF(SD1->D1_RATEIO<>'1',1,0)"])
    assert decodificar("D1_RATEIO", "Sim", num) == "1"
    assert decodificar("F4_XCONT", "Bon", num) == "B"
    assert decodificar("F4_ESTOQUE", "Não", num) == "N"


def _ct5(regras):
    campos = list(SX3_CT5["campos"].items())
    cab = [t for _, t in campos]
    linhas = []
    for r in regras:
        d = {c: "" for c, _ in campos}
        d.update(r)
        linhas.append(tuple(d[c] for c, _ in campos))
    t = Tabela("CT5", cab, linhas, 1)
    return RegrasCT5(t, mapear_ct5(t))


def test_conciliacao_nota_de_entrada():
    R = _ct5([dict(CT5_LANPAD="650", CT5_SEQUEN="001", CT5_STATUS="Ativo", CT5_DC="Debito", CT5_DESC="ITEM",
                   CT5_VLR01="IF(SF4->F4_XCONT='S',SD1->(D1_TOTAL-D1_VALICM),0)", CT5_ORIGEM="650-001",
                   CT5_HIST="LEFT('NF '+SF1->F1_DOC,40)")])
    dt = datetime.datetime(2026, 1, 5)
    sd1 = [dict(D1_FILIAL=S("01"), D1_DOC=S("123"), D1_SERIE=S("1"), D1_FORNECE=S("000001"), D1_LOJA=S("01"),
                D1_COD=S("P1"), D1_ITEM=S("0001"), D1_TES=S("101"), D1_TIPO=S("N"), D1_DTDIGIT=dt,
                D1_TOTAL=1000.0, D1_VALICM=120.0, D1_VALDESC=0.0)]
    sf1 = [dict(F1_FILIAL=S("01"), F1_DOC=S("123"), F1_SERIE=S("1"), F1_FORNECE=S("000001"), F1_LOJA=S("01"),
                F1_TIPO=S("N"), F1_DTDIGIT=dt)]
    sf4 = [dict(F4_CODIGO=S("101"), F4_XCONT=S("S"))]
    ct2 = [dict(CT2_FILIAL=S("01"), CT2_DATA=dt, CT2_LP=S("650"), CT2_ORIGEM=S("650-001"), CT2_VALOR=880.0,
                CT2_KEY=S("01123      1  00000101P1             0001"), CT2_HIST=S("NF 123"), CT2_MANUAL=S("2"))]
    M = Motor(R, ct2, {"SD1": sd1, "SF1": sf1, "SF4": sf4}, (datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)),
              {"650"}).conciliar()
    assert M.bases["650"] == "SD1"
    assert [x["status"] for x in M.resultado] == ["ok"]
    ct2[0]["CT2_VALOR"] = 900.0
    M = Motor(R, ct2, {"SD1": sd1, "SF1": sf1, "SF4": sf4}, (datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)),
              {"650"}).conciliar()
    assert M.resultado[0]["status"] == "valor" and M.resultado[0]["dif"] == 20.0


def test_funcao_customizada_bloqueia_lp():
    R = _ct5([dict(CT5_LANPAD="999", CT5_SEQUEN="001", CT5_STATUS="Ativo", CT5_VLR01="U_MINHAREGRA(SD1->D1_TOTAL)")])
    assert R.regras[0]["CLASSE"] == "custom"
