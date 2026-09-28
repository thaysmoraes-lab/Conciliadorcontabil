"""Motor de conciliação: CT2 × origem recalculada pelo CT5_VLR01."""
import datetime
import re
from collections import defaultdict, OrderedDict, Counter

from .advpl import avaliar, S, PADRAO
from .config import BASES, CADASTROS, LPS, PARAMETROS
from .funcoes import REGISTRO

PRINCIPAIS = tuple(LPS["financeiro"]["tipos_principais"])
IGNORA_SE5_NAT = PRINCIPAIS + ("JR", "DC", "MT", "RA", "PA", "CM", "D2", "J2", "M2", "ES", "EC")


class Falta(Exception):
    """Tabela ou campo necessário à regra não foi importado/mapeado."""


def compacta(*vals):
    return "".join(str(v).replace(" ", "") for v in vals)


def dk(*v):
    return tuple(str(x).strip() for x in v)


def br(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _d(x):
    if isinstance(x, datetime.datetime):
        return x.date()
    return x if isinstance(x, datetime.date) else None


class Motor:
    def __init__(self, regras, ct2, tabelas, periodo, lps_escopo, incluir_manuais=True, cv3=None):
        self.R = regras
        self.ct2 = ct2
        self.T = tabelas
        self.ini, self.fim = periodo
        self.escopo = set(lps_escopo)
        self.incluir_manuais = incluir_manuais
        self.cv3 = cv3 or []
        self.filial = next((str(l.get("CT2_FILIAL", "")).strip() for l in ct2 if l.get("CT2_FILIAL")), "")
        self._indices()

    # ------------------------------------------------------------------ utilidades
    def tab(self, al):
        return self.T.get(al, [])

    def no_periodo(self, d):
        d = _d(d)
        return d is not None and self.ini <= d <= self.fim

    # ------------------------------------------------------------------ índices
    def _indices(self):
        self.cad = {}
        for al, campos in CADASTROS.items():
            self.cad[al] = {dk(*(r.get(c, "") for c in campos)): r for r in self.tab(al)}
        self.cad_compacto = {al: {compacta(*k): r for k, r in d.items()} for al, d in self.cad.items()}
        self.f1 = {dk(r.get("F1_DOC"), r.get("F1_SERIE"), r.get("F1_FORNECE"), r.get("F1_LOJA")): r for r in self.tab("SF1")}
        self.d1 = defaultdict(list)
        for r in self.tab("SD1"):
            self.d1[dk(r.get("D1_DOC"), r.get("D1_SERIE"), r.get("D1_FORNECE"), r.get("D1_LOJA"))].append(r)
        self.de = defaultdict(list)
        for r in self.tab("SDE"):
            self.de[dk(r.get("DE_DOC"), r.get("DE_SERIE"), r.get("DE_FORNECE"), r.get("DE_LOJA"), r.get("DE_ITEMNF"))].append(r)
        self.f2 = {dk(r.get("F2_DOC"), r.get("F2_SERIE"), r.get("F2_CLIENTE"), r.get("F2_LOJA")): r for r in self.tab("SF2")}
        self.d2 = defaultdict(list)
        for r in self.tab("SD2"):
            self.d2[dk(r.get("D2_DOC"), r.get("D2_SERIE"), r.get("D2_CLIENTE"), r.get("D2_LOJA"))].append(r)
        self.e1 = {dk(r.get("E1_PREFIXO"), r.get("E1_NUM"), r.get("E1_PARCELA"), r.get("E1_TIPO")): r for r in self.tab("SE1")}
        self.e2 = {dk(r.get("E2_PREFIXO"), r.get("E2_NUM"), r.get("E2_PARCELA"), r.get("E2_TIPO"), r.get("E2_FORNECE"), r.get("E2_LOJA")): r
                   for r in self.tab("SE2")}
        # chaves de origem por base
        self.chaves = defaultdict(lambda: defaultdict(list))   # base -> chave compacta -> [registros]
        for base, cfg in BASES.items():
            regs = self.tab(cfg["tabela"])
            if not regs:
                continue
            for r in regs:
                if cfg["tabela"] == "SE5" and not self.se5_valido(r):
                    continue
                if cfg.get("somente_principal") and str(r.get("E5_TIPODOC", "")).strip() not in PRINCIPAIS:
                    continue
                for comp in cfg["indices"]:
                    k = self._chave(r, comp)
                    if k is not None:
                        self.chaves[base][k].append(r)
                        break

    def _chave(self, r, comp):
        partes = []
        for c in comp:
            if c == "|DATA":
                continue
            m = re.match(r"DTOS\((\w+)\)", c)
            if m:
                d = r.get(m.group(1))
                if not isinstance(d, (datetime.date, datetime.datetime)):
                    return None
                partes.append(d.strftime("%Y%m%d"))
            elif c.endswith("_FILIAL") and c not in r:
                partes.append(self.filial)
            elif c not in r:
                return None
            else:
                partes.append(r[c])
        k = compacta(*partes)
        if "|DATA" in comp:
            data = next((r.get(c) for c in ("E5_DATA",) if r.get(c)), None)
            k += "|" + (data.strftime("%Y%m%d") if data else "")
        return k

    @staticmethod
    def se5_valido(e):
        return str(e.get("E5_SITUACA", "")).strip() != "C" and str(e.get("E5_TIPODOC", "")).strip() not in ("ES", "EC")

    # ------------------------------------------------------------------ contextos
    def _cad(self, al, *k):
        return self.cad.get(al, {}).get(dk(*k))

    def ctx_sd1(self, d):
        kd = dk(d.get("D1_DOC"), d.get("D1_SERIE"), d.get("D1_FORNECE"), d.get("D1_LOJA"))
        c = {"SD1": d, "SF4": self._cad("SF4", d.get("D1_TES")), "SB1": self._cad("SB1", d.get("D1_COD"))}
        f1 = self.f1.get(kd)
        if f1:
            c["SF1"] = f1
        if str(d.get("D1_TIPO", "")).strip() in ("D", "B"):
            c["SA1"] = self._cad("SA1", *kd[2:])
        else:
            c["SA2"] = self._cad("SA2", *kd[2:])
        return c

    def ctx_sd1_rateio(self, d):
        base = self.ctx_sd1(d)
        des = self.de.get(dk(d.get("D1_DOC"), d.get("D1_SERIE"), d.get("D1_FORNECE"), d.get("D1_LOJA"), d.get("D1_ITEM")), [])
        return [dict(base, SDE=x) for x in des] or [base]

    def ctx_sf1(self, f):
        it = sorted(self.d1.get(dk(f.get("F1_DOC"), f.get("F1_SERIE"), f.get("F1_FORNECE"), f.get("F1_LOJA")), []),
                    key=lambda x: str(x.get("D1_ITEM")))
        c = {"SF1": f, "SA2": self._cad("SA2", f.get("F1_FORNECE"), f.get("F1_LOJA"))}
        if it:   # regra de cabeçalho: SF4 fica posicionada na TES do último item
            c["SF4"] = self._cad("SF4", it[-1].get("D1_TES"))
            c["SD1"] = it[-1]
        return c

    def ctx_sd2(self, d):
        kd = dk(d.get("D2_DOC"), d.get("D2_SERIE"), d.get("D2_CLIENTE"), d.get("D2_LOJA"))
        c = {"SD2": d, "SF4": self._cad("SF4", d.get("D2_TES")), "SB1": self._cad("SB1", d.get("D2_COD"))}
        if kd in self.f2:
            c["SF2"] = self.f2[kd]
        c["SA2" if str(d.get("D2_TIPO", "")).strip() in ("D", "B") else "SA1"] = \
            self._cad("SA2" if str(d.get("D2_TIPO", "")).strip() in ("D", "B") else "SA1", *kd[2:])
        return c

    def ctx_sf2(self, f):
        kd = dk(f.get("F2_DOC"), f.get("F2_SERIE"), f.get("F2_CLIENTE"), f.get("F2_LOJA"))
        it = sorted(self.d2.get(kd, []), key=lambda x: str(x.get("D2_ITEM")))
        c = {"SF2": f, "SA1": self._cad("SA1", *kd[2:])}
        if it:
            c["SF4"] = self._cad("SF4", it[-1].get("D2_TES"))
            c["SD2"] = it[-1]
        return c

    def ctx_se5(self, e):
        c = {"SE5": e, "SED": self._cad("SED", e.get("E5_NATUREZ")), "SA6": self._cad("SA6", e.get("E5_BANCO"))}
        t = dk(e.get("E5_PREFIXO"), e.get("E5_NUMERO"), e.get("E5_PARCELA"), e.get("E5_TIPO"))
        if str(e.get("E5_RECPAG", "")).strip() == "R":
            if t in self.e1:
                c["SE1"] = self.e1[t]
            c["SA1"] = self._cad("SA1", e.get("E5_CLIFOR"), e.get("E5_LOJA"))
        else:
            t2 = t + dk(e.get("E5_CLIFOR"), e.get("E5_LOJA"))
            if t2 in self.e2:
                c["SE2"] = self.e2[t2]
            c["SA2"] = self._cad("SA2", e.get("E5_CLIFOR"), e.get("E5_LOJA"))
        return c

    def ctx_se1(self, e):
        return {"SE1": e, "SED": self._cad("SED", e.get("E1_NATUREZ")), "SA1": self._cad("SA1", e.get("E1_CLIENTE"), e.get("E1_LOJA"))}

    def ctx_se2(self, e):
        return {"SE2": e, "SED": self._cad("SED", e.get("E2_NATUREZ")), "SA2": self._cad("SA2", e.get("E2_FORNECE"), e.get("E2_LOJA"))}

    def contextos(self, base, reg, lp):
        rateio = LPS["lps"].get(lp, {}).get("rateio")
        if base == "SD1":
            return self.ctx_sd1_rateio(reg) if rateio else [self.ctx_sd1(reg)]
        f = {"SF1": self.ctx_sf1, "SD2": self.ctx_sd2, "SF2": self.ctx_sf2, "SE5": self.ctx_se5, "SE5T": self.ctx_se5,
             "SE5NAT": self.ctx_se5, "SE1": self.ctx_se1, "SE2": self.ctx_se2}.get(base)
        return [f(reg)] if f else [{BASES.get(base, {}).get("tabela", base): reg}]

    # ------------------------------------------------------------------ avaliação
    def valor(self, expr, ctx):
        def F(nome):
            p = nome.split("_")[0]
            al = p if len(p) == 3 else "S" + p
            row = ctx.get(al)
            if row is None:
                raise Falta(al)
            if nome not in row:
                raise Falta(nome)
            return row[nome]

        def FN(nome):
            if nome in REGISTRO:
                return lambda *a: REGISTRO[nome](self, ctx, *a)
            if nome == "XFILIAL":
                return lambda *a: S("")
            if nome in ("GETMV", "SUPERGETMV"):
                return lambda p, *a: PARAMETROS.get(str(p).strip(), a[0] if a else "")
            if nome == "POSICIONE":
                return self._posicione
            if nome == "STR":
                return lambda v, *a: S(str(v))
            if nome in ("PADR", "PADL"):
                return lambda v, n, *a: S(str(v).ljust(int(n))[:int(n)] if nome == "PADR" else str(v).rjust(int(n))[-int(n):])
            raise Falta(f"função {nome}")

        return avaliar(expr, F, FN)

    def _posicione(self, alias, ordem, chave, campo):
        al = str(alias).strip().upper()
        k = compacta(chave)
        d = self.cad_compacto.get(al, {})
        r = d.get(k) or (d.get(k[len(self.filial):]) if self.filial and k.startswith(self.filial) else None)
        if r is None:
            return S("")
        return r.get(str(campo).strip().upper(), S(""))

    def valor_lp(self, lp, seq, base, reg):
        d = self.R.regra(lp, seq)
        return sum(float(self.valor(d["CT5_VLR01"], cx) or 0) for cx in self.contextos(base, reg, lp))

    # ------------------------------------------------------------------ bases por LP
    def base_do_lp(self, lp, linhas):
        cfg = LPS["lps"].get(lp, {}).get("base")
        if cfg == "SE5NAT":
            return "SE5NAT"
        chaves = [(compacta(l.get("CT2_KEY", "")), _d(l.get("CT2_DATA"))) for l in linhas[:300]]
        chaves = [(k, d) for k, d in chaves if k and k != self.filial]
        if not chaves:
            return "SE5NAT" if cfg == "SE5NAT" else None
        placar = Counter()
        for base, idx in self.chaves.items():
            for k, d in chaves:
                if k in idx or (d and f"{k}|{d.strftime('%Y%m%d')}" in idx):
                    placar[base] += 1
        if not placar:
            return cfg if cfg in BASES else None
        if cfg in placar and placar[cfg] >= max(placar.values()) * 0.9:
            return cfg
        return placar.most_common(1)[0][0]

    # ------------------------------------------------------------------ conciliação
    def conciliar(self):
        cat = Counter(); catv = defaultdict(float)
        soltas = []
        por_lp = defaultdict(list)
        for l in self.ct2:
            if not self.no_periodo(l.get("CT2_DATA")):
                continue
            lp = str(l.get("CT2_LP", "")).strip()
            v = float(l.get("CT2_VALOR") or 0)
            if str(l.get("CT2_MANUAL", "")).strip() == "1":
                soltas.append(self._solta(l, True))
                if self.incluir_manuais:
                    cat["Manual"] += 1; catv["Manual"] += v
                continue
            if not lp:
                soltas.append(self._solta(l, False))
                if self.incluir_manuais:
                    cat["Automático sem LP"] += 1; catv["Automático sem LP"] += v
                continue
            if lp not in self.escopo:
                cat["LP fora do escopo"] += 1; catv["LP fora do escopo"] += v
                continue
            por_lp[lp].append(l)
        self.bases = {}
        grupos = OrderedDict()
        for lp, linhas in sorted(por_lp.items()):
            classes = {d["CLASSE"] for d in self.R.ativas() if d["LP"] == lp}
            if classes and classes <= {"txt"}:
                cat["Origem TXT"] += len(linhas); catv["Origem TXT"] += sum(float(l.get("CT2_VALOR") or 0) for l in linhas)
                continue
            base = self.base_do_lp(lp, linhas)
            self.bases[lp] = base
            for l in linhas:
                org = str(l.get("CT2_ORIGEM", "")).strip()
                sq = org.split("-")[1] if "-" in org else ""
                regra = self.R.regra(lp, sq) if sq else None
                v = float(l.get("CT2_VALOR") or 0)
                if not regra:
                    cat["Sequência não encontrada na CT5"] += 1; catv["Sequência não encontrada na CT5"] += v
                    continue
                if regra["CLASSE"] in ("custom", "tbc_pendente"):
                    cat["LP com função não parametrizada"] += 1; catv["LP com função não parametrizada"] += v
                    continue
                if base is None:
                    cat["LP sem origem identificável"] += 1; catv["LP sem origem identificável"] += v
                    continue
                dt = _d(l.get("CT2_DATA"))
                key = compacta(l.get("CT2_KEY", ""))
                if base == "SE5T":
                    key = f"{key}|{dt.strftime('%Y%m%d')}"
                elif base == "SE5NAT":
                    m = re.search(r"DOC\s+(\S+)", str(l.get("CT2_HIST", "")))
                    key = f"NAT:{m.group(1) if m else '?'}|{dt.strftime('%Y%m%d')}"
                doc = BASES.get(base, {}).get("documento")
                if doc:
                    regs = self.chaves[base].get(key, [])
                    if regs:
                        key = "DOC:" + "|".join(dk(*(regs[0].get(c) for c in doc)))
                g = grupos.setdefault((lp, sq, key), dict(lp=lp, seq=sq, chave=key, base=base, data=dt, valor=0.0, linhas=0,
                                                          hist=str(l.get("CT2_HIST", "")).strip(), agl=l.get("CT2_AGLUT")))
                g["valor"] += v
                g["linhas"] += 1
        self._natureza_se5()
        usados = set()
        res = []
        for (lp, sq, key), g in grupos.items():
            origens = self._origens(g)
            regra = self.R.regra(lp, sq)
            so_cab = self._regra_cabecalho(regra["CT5_VLR01"], g["base"])
            if so_cab:
                origens = origens[:1]
            esperado, erro, datas = 0.0, None, set()
            for base, reg in origens:
                usados.add(id(reg))
                cfg = BASES.get(base, BASES.get("SE5"))
                datas.add(_d(reg.get(cfg["data"])))
                try:
                    esperado += self.valor_lp(lp, sq, base, reg)
                except Falta as e:
                    erro = f"Não disponível: {e}"
                except Exception as e:  # noqa: BLE001
                    erro = f"Erro ao avaliar a regra: {e}"
            st = "ok"
            dif = g["valor"] - esperado
            if not origens:
                st = "sem_origem"
            elif erro:
                st = "erro"
            elif abs(dif) > max(0.01, 0.01 * g["linhas"]):
                st = "valor"
            elif abs(dif) > 0.005:
                st = "arred"
            if st in ("ok", "arred") and any(d and d != g["data"] for d in datas):
                st = "data"
            res.append(dict(g, esperado=round(esperado, 2), valor=round(g["valor"], 2), dif=round(dif, 2), status=st,
                            erro=erro, registros=len(origens), data_origem=min((d for d in datas if d), default=None),
                            explicacao=""))
        self.resultado = res
        self.soltas = soltas
        self.categorias = dict(cat)
        self.categorias_valor = {k: round(v, 2) for k, v in catv.items()}
        self._explicar(usados)
        self.sem_lancamento = self._origem_sem_lancamento(grupos)
        self.financeiro_sem_lancamento = self._financeiro_sem_lancamento(grupos, usados)
        return self

    def _solta(self, l, manual):
        return dict(manual=manual, rotina=str(l.get("CT2_ROTINA", "")).strip(), data=_d(l.get("CT2_DATA")),
                    valor=round(float(l.get("CT2_VALOR") or 0), 2), hist=str(l.get("CT2_HIST", "")).strip())

    @staticmethod
    def _regra_cabecalho(expr, base):
        """Regra de LP de item cujo valor vem só do cabeçalho (ex.: SF1->F1_VALBRUT): conta uma vez por nota."""
        if base not in ("SD1", "SD2"):
            return False
        corpo = expr.split(",", 1)[1] if "," in expr else expr
        cab, it = ("F1_", "D1_") if base == "SD1" else ("F2_", "D2_")
        return bool(re.search(cab + r"(VAL|INSS|IRRF|BASE)", corpo)) and not re.search(it + r"(TOTAL|VAL|CUSTO|DESPESA|QUANT)", expr)

    def _natureza_se5(self):
        self.nat = defaultdict(list)
        for e in self.tab("SE5"):
            if self.se5_valido(e) and str(e.get("E5_TIPODOC", "")).strip() not in IGNORA_SE5_NAT and e.get("E5_DATA"):
                self.nat[f"NAT:{str(e.get('E5_NATUREZ', '')).strip()}|{e['E5_DATA'].strftime('%Y%m%d')}"].append(e)

    def _origens(self, g):
        base, key = g["base"], g["chave"]
        if base == "SE5NAT":
            rp = LPS["lps"].get(g["lp"], {}).get("recpag")
            return [("SE5NAT", e) for e in self.nat.get(key, []) if not rp or str(e.get("E5_RECPAG", "")).strip() == rp]
        if key.startswith("DOC:"):
            doc = tuple(key[4:].split("|"))
            fonte = self.d1 if base == "SD1" else self.d2
            return [(base, r) for r in sorted(fonte.get(doc, []), key=lambda x: str(x.get("D1_ITEM", x.get("D2_ITEM", ""))))]
        return [(base, r) for r in self.chaves[base].get(key, [])]

    # ------------------------------------------------------------------ explicações
    def _explicar(self, usados):
        nums = lambda h: set(re.findall(r"\d{2,}", h or ""))
        for x in self.resultado:
            if x["status"] != "valor":
                continue
            for so in self.soltas:
                if abs(abs(x["dif"]) - so["valor"]) <= 0.01 and nums(so["hist"]) & nums(x["hist"]):
                    tipo = "lançamento manual" if so["manual"] else "lançamento automático sem LP"
                    x["explicacao"] = f"Diferença coberta por {tipo} ({so['rotina']} · {so['hist'][:45]} · {br(so['valor'])})"
                    x["status"] = "explicada"
                    break
            if x["status"] != "valor":
                continue
            if x["chave"].startswith("DOC:") and x["base"] == "SD1":
                its = self.d1.get(tuple(x["chave"][4:].split("|")), [])
                ds = round(sum(float(i.get("D1_VALDESC", 0) or 0) for i in its), 2)
                if ds and abs(abs(x["dif"]) - ds) <= 0.02:
                    x["explicacao"] = f"Diferença igual ao desconto dos itens (D1_VALDESC {br(ds)}), que a regra não deduz"
                    x["status"] = "explicada"
                    continue
            if x["base"] == "SE5":
                regs = self.chaves["SE5"].get(x["chave"], [])
                if regs:
                    e = regs[0]
                    outros = [o for o in self.tab("SE5") if self.se5_valido(o) and o.get("E5_NUMERO") == e.get("E5_NUMERO")
                              and o.get("E5_DATA") == e.get("E5_DATA") and o.get("E5_TIPODOC") == e.get("E5_TIPODOC") and o is not e]
                    soma = round(sum(o.get("E5_VALOR", 0) for o in outros), 2)
                    if outros and abs(soma - x["dif"]) <= 0.01:
                        x["explicacao"] = ("CT2 aglutinou este movimento com o da parcela " +
                                           ", ".join(str(o.get("E5_PARCELA", "")).strip() for o in outros) +
                                           f" do mesmo título, na mesma data ({br(soma)})")
                        x["status"] = "explicada"
                        usados.update(id(o) for o in outros)
                        continue
                    for so in self.soltas:
                        if not so["manual"] and abs(so["valor"] - x["esperado"]) <= 0.01:
                            x["explicacao"] = (f"A chave aponta para o movimento de {br(x['esperado'])}, que está na CT2 como "
                                               f"lançamento sem LP ({so['hist'][:40]}). O valor da linha ({br(x['valor'])}) "
                                               "não tem movimento SE5 com essa chave.")
                            break

    # ------------------------------------------------------------------ origem sem lançamento
    def _origem_sem_lancamento(self, grupos):
        existe = defaultdict(set)
        for (lp, sq, key) in grupos:
            existe[key].add((lp, sq))
        out = []
        for lp in sorted(self.escopo):
            cfg = LPS["lps"].get(lp, {})
            cond, base = cfg.get("condicao_origem"), cfg.get("base")
            if not cond or base not in ("SD1", "SF1", "SD2", "SF2") or not self.tab(base):
                continue
            seqs = [d for d in self.R.ativas() if d["LP"] == lp and d["CLASSE"] in ("padrao", "tbc")]
            if not seqs:
                continue
            doccfg = BASES[base].get("documento")
            acc = OrderedDict()
            for reg in self.tab(base):
                if not self.no_periodo(reg.get(BASES[base]["data"])):
                    continue
                cx0 = self.contextos(base, reg, lp)[0]
                try:
                    if not self.valor(cond, cx0):
                        continue
                except Exception:  # noqa: BLE001
                    continue
                if doccfg:
                    key = "DOC:" + "|".join(dk(*(reg.get(c) for c in doccfg)))
                else:
                    key = self._chave(reg, BASES[base]["indices"][0])
                for d in seqs:
                    k3 = (lp, d["SEQ"], key)
                    if self._regra_cabecalho(d["CT5_VLR01"], base) and k3 in acc:
                        continue
                    try:
                        v = self.valor_lp(lp, d["SEQ"], base, reg)
                    except Exception:  # noqa: BLE001
                        continue
                    if v > 0.005:
                        a = acc.setdefault(k3, dict(lp=lp, seq=d["SEQ"], chave=key, base=base, valor=0.0, reg=reg))
                        a["valor"] += v
            for (l, s, k), a in acc.items():
                if (l, s) in existe.get(k, ()):
                    continue
                r = a["reg"]
                p = base[1:]
                out.append(dict(lp=l, seq=s, base=base, documento=str(r.get(f"{p}_DOC", "")).strip(),
                                participante=str(r.get(f"{p}_FORNECE", r.get(f"{p}_CLIENTE", ""))).strip(),
                                data=_d(r.get(BASES[base]["data"])), valor=round(a["valor"], 2)))
        return out

    def _financeiro_sem_lancamento(self, grupos, usados):
        if not self.tab("SE5"):
            return []
        existe = {key for (_, _, key) in grupos}
        regras = LPS["financeiro"]["regras"]
        soltas_auto = [so for so in self.soltas if not so["manual"]]
        out = []
        for e in self.tab("SE5"):
            if not self.se5_valido(e) or not self.no_periodo(e.get("E5_DTDISPO") or e.get("E5_DATA")) or id(e) in usados:
                continue
            td = str(e.get("E5_TIPODOC", "")).strip()
            if td not in PRINCIPAIS:
                continue
            k2 = self._chave(e, BASES["SE5"]["indices"][0])
            kt = self._chave(e, BASES["SE5T"]["indices"][0])
            if k2 in existe or kt in existe:
                continue
            cx = self.ctx_se5(e)
            classe, lp = None, None
            for rg in regras:
                try:
                    if self.valor(rg["quando"], cx):
                        classe, lp = rg.get("classe"), rg.get("lp")
                        break
                except Exception:  # noqa: BLE001
                    continue
            if lp:
                l, s = lp.split("/")
                if l not in self.escopo:
                    continue
                d = self.R.regra(l, s)
                try:
                    v = float(self.valor(d["CT5_VLR01"], cx)) if d else None
                except Exception:  # noqa: BLE001
                    v = None
                if v == 0:
                    classe = f"Regra do LP {lp} retorna zero (não deveria contabilizar)"
                elif any(abs(so["valor"] - float(e.get("E5_VALOR", 0))) <= 0.01 for so in soltas_auto):
                    classe = "Lançado na CT2 sem LP (rotina automática)"
                else:
                    classe = f"Sem lançamento: regra do LP {lp} retorna valor"
            if not classe:
                continue
            out.append(dict(classe=classe, tipodoc=td, recpag=str(e.get("E5_RECPAG", "")).strip(),
                            motivo=str(e.get("E5_MOTBX", "")).strip(),
                            titulo=f"{str(e.get('E5_PREFIXO', '')).strip()}-{str(e.get('E5_NUMERO', '')).strip()}-"
                                   f"{str(e.get('E5_PARCELA', '')).strip()} {str(e.get('E5_TIPO', '')).strip()}",
                            clifor=str(e.get("E5_CLIFOR", "")).strip(), data=_d(e.get("E5_DTDISPO")),
                            valor=round(float(e.get("E5_VALOR", 0)), 2), ident_la=str(e.get("E5_LA", "")).strip()))
        return out

    # ------------------------------------------------------------------ resumo
    def resumo_por_lp(self):
        s = OrderedDict()
        for x in sorted(self.resultado, key=lambda x: (x["lp"], x["seq"])):
            k = (x["lp"], x["seq"])
            d = self.R.regra(*k)
            r = s.setdefault(k, dict(lp=x["lp"], seq=x["seq"], descricao=d["CT5_DESC"] if d else "", base=x["base"],
                                     linhas=0, chaves=0, ct2=0.0, esperado=0.0, conciliadas=0, explicadas=0,
                                     divergentes=0, sem_origem=0, sem_lancamento=0, valor_sem_lancamento=0.0))
            r["linhas"] += x["linhas"]; r["chaves"] += 1; r["ct2"] += x["valor"]; r["esperado"] += x["esperado"]
            if x["status"] in ("ok", "arred"):
                r["conciliadas"] += 1
            elif x["status"] == "explicada":
                r["explicadas"] += 1
            elif x["status"] == "sem_origem":
                r["sem_origem"] += 1
            else:
                r["divergentes"] += 1
        for m in self.sem_lancamento:
            k = (m["lp"], m["seq"])
            d = self.R.regra(*k)
            r = s.setdefault(k, dict(lp=m["lp"], seq=m["seq"], descricao=d["CT5_DESC"] if d else "", base=m["base"],
                                     linhas=0, chaves=0, ct2=0.0, esperado=0.0, conciliadas=0, explicadas=0,
                                     divergentes=0, sem_origem=0, sem_lancamento=0, valor_sem_lancamento=0.0))
            r["sem_lancamento"] += 1; r["valor_sem_lancamento"] += m["valor"]
        return sorted(s.values(), key=lambda r: (r["lp"], r["seq"]))

    def totais(self):
        R = self.resultado
        return dict(linhas=sum(x["linhas"] for x in R), chaves=len(R),
                    conciliadas=sum(1 for x in R if x["status"] in ("ok", "arred")),
                    explicadas=sum(1 for x in R if x["status"] == "explicada"),
                    divergentes=sum(1 for x in R if x["status"] in ("valor", "erro")),
                    sem_origem=sum(1 for x in R if x["status"] == "sem_origem"),
                    data=sum(1 for x in R if x["status"] == "data"),
                    ct2=round(sum(x["valor"] for x in R), 2), esperado=round(sum(x["esperado"] for x in R), 2),
                    sem_lancamento=len(self.sem_lancamento),
                    valor_sem_lancamento=round(sum(m["valor"] for m in self.sem_lancamento), 2))

    # ------------------------------------------------------------------ CV3 (opcional)
    def resumo_cv3(self):
        if not self.cv3:
            return None
        grupos = defaultdict(float); hist = {}
        for r in self.cv3:
            k = (str(r.get("CV3_SEQUEN", "")).strip(), str(r.get("CV3_LP", "")).strip(), str(r.get("CV3_LPSEQ", "")).strip(),
                 str(r.get("CV3_RECDES", "")).strip())
            grupos[k] += float(r.get("CV3_VLR01") or 0)
            hist[k] = str(r.get("CV3_HIST", "")).strip()[:40]
        cv = Counter((k[0], k[1], k[2], round(v, 2), hist[k]) for k, v in grupos.items())
        ct = Counter((str(l.get("CT2_SEQUEN", "")).strip(), str(l.get("CT2_LP", "")).strip(),
                      str(l.get("CT2_ORIGEM", "-")).split("-")[-1], round(float(l.get("CT2_VALOR") or 0), 2),
                      str(l.get("CT2_HIST", "")).strip()[:40]) for l in self.ct2 if l.get("CT2_LP"))
        return dict(registros=len(self.cv3), destinos=len(grupos), batem=sum((cv & ct).values()),
                    so_cv3=sum((cv - ct).values()), so_ct2=sum((ct - cv).values()))
