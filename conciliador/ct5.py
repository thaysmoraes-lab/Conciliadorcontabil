"""Leitura e análise das regras de lançamento padrão (CT5)."""
import re
from collections import defaultdict, OrderedDict

from .config import SX3_CT5, FUNCOES_TBC, LPS
from .advpl import funcoes_usadas, NATIVAS, traduzir
from .mapeamento import mapear

COLUNAS_ENTIDADE = ["CT5_DEBITO", "CT5_CREDIT", "CT5_HIST", "CT5_CCD", "CT5_CCC", "CT5_ITEMD", "CT5_ITEMC",
                    "CT5_CLVLDB", "CT5_CLVLCR"]
NOMES_TABELA = {"SE1": "Contas a receber", "SE2": "Contas a pagar", "SE5": "Movimentação bancária",
                "SED": "Naturezas financeiras", "SA1": "Clientes", "SA2": "Fornecedores", "SA6": "Bancos",
                "SF1": "Cabeçalho NF entrada", "SD1": "Itens NF entrada", "SF2": "Cabeçalho NF saída",
                "SD2": "Itens NF saída", "SF4": "Tipos de entrada e saída (TES)", "SB1": "Produtos",
                "SD3": "Movimentações internas", "SDE": "Rateio NF entrada", "SEU": "Caixinha",
                "SN1": "Ativo imobilizado", "SN3": "Saldos do ativo", "SN4": "Movimentações do ativo",
                "SEV": "Multinatureza", "SFT": "Livros fiscais por item", "SEF": "Cheques",
                "ZC1": "Amarrações contábeis (acelerador TBC)", "ZC3": "Regras longas (acelerador TBC)",
                "CT2": "Lançamentos contábeis", "CV3": "Rastreamento contábil"}
TABELAS_FUNCAO = {"U_RETCTA": ["ZC1"], "U_CTBREGRA": ["ZC3"], "U_RETCTAST": ["ZC1"], "U_RETTESDEB": ["SF4", "ZC1"],
                  "U_RETTESCRE": ["SF4", "ZC1"], "U_RCTBE001": ["SF2", "SE1"], "U_RCTBE002": ["SE1"],
                  "U_RCTBE003": ["SE2"], "U_RETVLPCC": ["SE2"], "U_SEV2SE1": ["SEV", "SE1"], "U_SEV2SE2": ["SEV", "SE2"]}


def mapear_ct5(tabela, fixos=None):
    esperados = {c: [t] for c, t in SX3_CT5["campos"].items()}
    return mapear(tabela.cabecalho, esperados, fixos)


def aliases(expr):
    e = (expr or "").upper()
    a = set(re.findall(r"\b([A-Z][A-Z0-9]{2})\s*->", e))
    a |= set(re.findall(r"POSICIONE\(\s*[\"']([A-Z0-9]{3})", e))
    return a


def campos(expr):
    return set(re.findall(r"\b([A-Z][A-Z0-9]{1,2}_[A-Z0-9]+)\b", re.sub(r"'[^']*'|\"[^\"]*\"", "", (expr or "").upper())))


def alias_do_campo(c):
    p = c.split("_")[0]
    return p if len(p) == 3 else "S" + p


class RegrasCT5:
    def __init__(self, tabela, mapa):
        self.mapa = mapa
        idx = {c: tabela.coluna(m["titulo"]) for c, m in mapa.items() if m.get("titulo")}
        g = lambda r, c: ("" if c not in idx or r[idx[c]] is None else str(r[idx[c]]).strip())
        self.regras = []
        for r in tabela.linhas:
            d = {c: g(r, c) for c in SX3_CT5["campos"]}
            d["LP"] = d["CT5_LANPAD"]
            d["SEQ"] = d["CT5_SEQUEN"]
            d["ATIVO"] = d["CT5_STATUS"].lower().startswith(("ativ", "1"))
            self.regras.append(d)
        self._analisar()

    # ------------------------------------------------------------------ análise
    def _analisar(self):
        self.funcoes_implementadas = set()
        try:
            from .funcoes import REGISTRO
            self.funcoes_implementadas = set(REGISTRO)
        except Exception:
            pass
        for d in self.regras:
            v = d["CT5_VLR01"]
            d["TAB_VALOR"] = sorted(aliases(v))
            outras = set()
            for c in COLUNAS_ENTIDADE:
                outras |= aliases(d[c])
            d["TAB_OUTRAS"] = sorted(outras - set(d["TAB_VALOR"]))
            fv = funcoes_usadas(v)
            fo = set()
            for c in COLUNAS_ENTIDADE:
                fo |= funcoes_usadas(d[c])
            d["FUNC_TBC"] = sorted(f for f in fv | fo if f in FUNCOES_TBC)
            d["FUNC_CUSTOM"] = sorted(f for f in fv | fo if f.startswith("U_") and f not in FUNCOES_TBC)
            d["FUNC_BLOQ"] = sorted(f for f in fv if f.startswith("U_") and f not in self.funcoes_implementadas)
            if fv & {"LERVAL", "LERSTR", "LERDATA"}:
                d["CLASSE"] = "txt"
            elif d["FUNC_BLOQ"] and any(f not in FUNCOES_TBC for f in d["FUNC_BLOQ"]):
                d["CLASSE"] = "custom"
            elif d["FUNC_BLOQ"]:
                d["CLASSE"] = "tbc_pendente"
            elif d["FUNC_TBC"]:
                d["CLASSE"] = "tbc"
            else:
                d["CLASSE"] = "padrao"
            d["ERRO_SINTAXE"] = []
            for c in ("CT5_VLR01", "CT5_DEBITO", "CT5_CREDIT", "CT5_HIST"):
                for m in re.findall(r"\b([A-Z][A-Z0-9]{2})-(?!>)([A-Z0-9]{2,3}_[A-Z0-9]+)", d[c].upper()):
                    d["ERRO_SINTAXE"].append(f"{c}: '{m[0]}-{m[1]}' (falta '>')")
            if d["CLASSE"] != "txt" and v:
                try:
                    traduzir(v)
                except SyntaxError as e:
                    d["ERRO_SINTAXE"].append(f"CT5_VLR01 não interpretável: {e.msg}")
            og = d["CT5_ORIGEM"]
            m = re.search(r"(\d{3})/(\d{3})\s*-\s*Estorno do lcto:\s*(\d{3})/(\d{3})", og)
            d["ESTORNO_DE"] = f"{m.group(3)}-{m.group(4)}" if m else ""
            d["ORIGEM_ESPERADA"] = f"{m.group(1)}-{m.group(2)}" if m else og.strip("'\" ")
            d["ALERTA_ORIGEM"] = ""
            if not og:
                d["ALERTA_ORIGEM"] = "CT5_ORIGEM vazio"
            elif d["ORIGEM_ESPERADA"] != f"{d['LP']}-{d['SEQ']}":
                d["ALERTA_ORIGEM"] = f"CT5_ORIGEM aponta {d['ORIGEM_ESPERADA']}"
            d["DOC_HIST"] = self._doc_hist(d["CT5_HIST"])

    @staticmethod
    def _doc_hist(h):
        hs = re.sub(r"POSICIONE\((?:[^()]|\([^()]*\))*\)", " ", (h or "").upper())
        return [c for c in dict.fromkeys(re.findall(r"\b[A-Z][A-Z0-9]_[A-Z0-9]+\b", hs))
                if re.search(r"_(DOC|NUM|NUMERO|NFISCAL|DOCUMEN|NUMCHEQ|CBASE|IDENTEE|OP|PREFIXO|PARCELA|SERIE)$", c)]

    # ------------------------------------------------------------------ consultas
    def ativas(self):
        return [d for d in self.regras if d["ATIVO"]]

    def regra(self, lp, seq):
        for d in self.regras:
            if d["LP"] == lp and d["SEQ"] == seq and d["ATIVO"]:
                return d
        return None

    def lps(self):
        return sorted({d["LP"] for d in self.ativas()})

    def tabelas_necessarias(self, lps):
        """{alias: {'valor': n, 'outras': n, 'campos_valor': set, 'campos_outros': set}}"""
        out = defaultdict(lambda: dict(valor=0, outras=0, campos_valor=set(), campos_outros=set()))
        for d in self.ativas():
            if d["LP"] not in lps or d["CLASSE"] == "txt":
                continue
            for a in d["TAB_VALOR"]:
                out[a]["valor"] += 1
            for a in d["TAB_OUTRAS"]:
                out[a]["outras"] += 1
            for f in d["FUNC_TBC"]:
                for a in TABELAS_FUNCAO.get(f, []):
                    out[a]["outras"] += 1
            for c in campos(d["CT5_VLR01"]):
                out[alias_do_campo(c)]["campos_valor"].add(c)
            for col in COLUNAS_ENTIDADE:
                for c in campos(d[col]):
                    out[alias_do_campo(c)]["campos_outros"].add(c)
        return dict(out)

    def divergencias_estorno(self):
        """Compara a regra de valor do estorno (AUTO-LCPD) com a da inclusão que ele estorna."""
        nv = lambda s: re.sub(r"\s+", "", str(s).upper()).replace("IIF(", "IF(")
        res = []
        for d in self.ativas():
            if not d["ESTORNO_DE"]:
                continue
            lp, sq = d["ESTORNO_DE"].split("-")
            inc = self.regra(lp, sq)
            if inc and nv(inc["CT5_VLR01"]) != nv(d["CT5_VLR01"]):
                res.append(dict(inclusao=f"{lp}/{sq}", estorno=f"{d['LP']}/{d['SEQ']}",
                                regra_inclusao=inc["CT5_VLR01"], regra_estorno=d["CT5_VLR01"]))
        return res


def modulo_do_lp(lp):
    for m in LPS["modulos"]:
        for a, b in m["faixas"]:
            if a <= lp <= b and lp not in m.get("exceto", []):
                return m["id"]
    return "out"
