"""Conciliador contábil Protheus · Streamlit.

Fluxo: CT5 (regras de LP) → período e escopo → CT2 → tabelas de origem → conciliação.
Todas as tabelas são exportadas pela rotina Genéricos (Configurador) em .xlsx.
"""
import datetime
import json
from collections import Counter

import pandas as pd
import streamlit as st

from conciliador.config import LPS, FUNCOES_TBC, SX3_CT5
from conciliador.ct5 import RegrasCT5, mapear_ct5, modulo_do_lp, NOMES_TABELA
from conciliador.leitura import ler_generico
from conciliador.mapeamento import mapear
from conciliador.motor import Motor, br
from conciliador.pipeline import (periodo_mes, lps_do_escopo, preparar, campos_de_valor, campos_esperados,
                                  filtro_sugerido, OPCIONAIS)
from conciliador.relatorio import excel, html_relatorio, STATUS

st.set_page_config(page_title="Conciliador contábil Protheus", page_icon="🧾", layout="wide")
ss = st.session_state
ss.setdefault("fixos", {})          # {alias: {campo: título}} correlações confirmadas pelo usuário
ss.setdefault("tabelas", {})        # {alias: Tabela}
ss.setdefault("nao_aplica", set())  # tabelas que o cliente não usa / sem movimento

ETAPAS = ["1 · Importar CT5", "2 · Período e escopo", "3 · Importar CT2", "4 · Tabelas de origem", "5 · Conciliação"]
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro",
         "Novembro", "Dezembro"]


@st.cache_data(show_spinner="Lendo o arquivo do genéricos…")
def ler(conteudo, nome):
    return ler_generico(conteudo, nome)


def pronto(chave):
    return chave in ss and ss[chave] is not None


# ---------------------------------------------------------------- barra lateral
with st.sidebar:
    st.markdown("### 🧾 Conciliador contábil")
    st.caption("Protheus · CT5 × CT2 × origem")
    feito = [pronto("regras"), pronto("periodo"), pronto("ct2"), bool(ss.tabelas), pronto("motor")]
    etapa = st.radio("Etapas", ETAPAS, format_func=lambda e: ("✅ " if feito[ETAPAS.index(e)] else "⬜ ") + e,
                     label_visibility="collapsed", key="etapa")
    st.divider()
    st.caption("Mapeamento de campos")
    st.download_button("Baixar correlações (JSON)", json.dumps(ss.fixos, ensure_ascii=False, indent=1),
                       "correlacoes.json", "application/json", width="stretch")
    arq = st.file_uploader("Carregar correlações salvas", type="json", key="up_fixos")
    if arq is not None and not ss.get("fixos_carregado"):
        ss.fixos.update(json.load(arq))
        ss.fixos_carregado = True
        st.success("Correlações carregadas")


def editor_mapeamento(alias, cabecalho, mapa, obrigatorios, prefixo):
    """Mostra o mapeamento e permite corrigir manualmente os campos incertos/ausentes."""
    linhas = [dict(Campo=c, Título=m["titulo"] or "—", Similaridade=m["score"],
                   Situação={"exato": "✅ exato", "auto": "⚠️ automático", "manual": "✍️ manual", "ausente": "❌ ausente"}[m["status"]],
                   Uso="valor/chave" if c in obrigatorios else "conta/histórico")
              for c, m in sorted(mapa.items())]
    pend = [c for c, m in mapa.items() if m["status"] in ("auto", "ausente") and c in obrigatorios]
    if pend:
        st.warning(f"{len(pend)} campo(s) usados em regra de valor ou chave precisam de confirmação. Faça a correlação manual:")
        cols = st.columns(3)
        opcoes = ["— não existe nesta base —"] + cabecalho
        for i, c in enumerate(sorted(pend)):
            atual = mapa[c]["titulo"]
            esc = cols[i % 3].selectbox(c, opcoes, index=opcoes.index(atual) if atual in opcoes else 0, key=f"{prefixo}_{alias}_{c}")
            if esc != opcoes[0]:
                ss.fixos.setdefault(alias, {})[c] = esc
    with st.expander(f"Ver os {len(linhas)} campos correlacionados"):
        st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")


# ================================================================ 1 · CT5
if etapa == ETAPAS[0]:
    st.header("Importar CT5 — regras de lançamento padrão")
    st.write("Exporte a CT5 pela rotina Genéricos. O cabeçalho vem com o `X3_TITULO`; a correlação com o campo é automática.")
    f = st.file_uploader("CT5 (.xlsx do genéricos)", type=["xlsx"], key="up_ct5")
    if f:
        tab = ler(f.getvalue(), f.name)
        mapa = mapear_ct5(tab, ss.fixos.get("CT5"))
        memo = set(SX3_CT5["memo"])
        for c in memo:
            if mapa[c]["status"] == "ausente":
                st.info(f"`{c}` é campo memo e não é exportado pelo genéricos. Não interfere na conciliação.")
        obrig = {"CT5_LANPAD", "CT5_SEQUEN", "CT5_STATUS", "CT5_VLR01", "CT5_HIST", "CT5_ORIGEM", "CT5_DESC", "CT5_DC"}
        editor_mapeamento("CT5", tab.cabecalho, {c: m for c, m in mapa.items() if c not in memo}, obrig, "ct5")
        mapa = mapear_ct5(tab, ss.fixos.get("CT5"))
        if any(mapa[c]["status"] == "ausente" for c in obrig):
            st.error("Campos essenciais da CT5 sem correlação. Corrija acima para continuar.")
            st.stop()
        R = RegrasCT5(tab, mapa)
        ss.regras = R
        cl = Counter(d["CLASSE"] for d in R.ativas())
        c = st.columns(6)
        c[0].metric("Lançamentos padrão", len(R.lps()))
        c[1].metric("Sequências ativas", len(R.ativas()))
        c[2].metric("Padrão", cl["padrao"])
        c[3].metric("Acelerador TBC", cl["tbc"] + cl["tbc_pendente"])
        c[4].metric("Customizadas (U_)", cl["custom"])
        c[5].metric("Origem TXT", cl["txt"])
        bloq = [d for d in R.ativas() if d["CLASSE"] in ("custom", "tbc_pendente")]
        if bloq:
            st.error("LPs com função de usuário não parametrizada no conciliador. Eles **não serão conciliados** até a "
                     "função ser implementada em `conciliador/funcoes.py`:")
            st.dataframe(pd.DataFrame([dict(LP=d["LP"], Seq=d["SEQ"], Funções=", ".join(d["FUNC_BLOQ"]),
                                            Tipo="Acelerador TBC" if d["CLASSE"] == "tbc_pendente" else "Customizada",
                                            Regra=d["CT5_VLR01"]) for d in bloq]), hide_index=True, width="stretch")
        st.subheader("Alertas da CT5")
        for d in R.ativas():
            for e in d["ERRO_SINTAXE"]:
                st.error(f"LP {d['LP']}/{d['SEQ']} · {e}")
            if d["ALERTA_ORIGEM"]:
                st.warning(f"LP {d['LP']}/{d['SEQ']} · {d['ALERTA_ORIGEM']} (a CT2 não vai casar por CT2_ORIGEM)")
        div = R.divergencias_estorno()
        if div:
            with st.expander(f"⚠️ {len(div)} regras de estorno diferentes da inclusão que estornam"):
                st.dataframe(pd.DataFrame(div), hide_index=True, width="stretch")
        with st.expander("Regras de valor (CT5_VLR01) por LP"):
            st.dataframe(pd.DataFrame([dict(LP=d["LP"], Seq=d["SEQ"], Status="Ativo" if d["ATIVO"] else "Inativo", Tipo=d["CT5_DC"],
                                            Descrição=d["CT5_DESC"], Classe=d["CLASSE"], Regra=d["CT5_VLR01"],
                                            **{"Tabelas do valor": ", ".join(d["TAB_VALOR"]), "Documento no histórico": ", ".join(d["DOC_HIST"])})
                                       for d in R.regras]), hide_index=True, width="stretch", height=420)
        with st.expander("Funções do acelerador TBC reconhecidas (MIT072)"):
            st.dataframe(pd.DataFrame(FUNCOES_TBC.values()), hide_index=True, width="stretch")
        st.success("CT5 pronta. Siga para **2 · Período e escopo**.")

# ================================================================ 2 · período e escopo
elif etapa == ETAPAS[1]:
    st.header("Período e escopo da conciliação")
    if not pronto("regras"):
        st.info("Importe a CT5 primeiro.")
        st.stop()
    R = ss.regras
    c1, c2 = st.columns(2)
    with c1:
        modo = st.radio("Competência", ["Mês", "Intervalo"], horizontal=True)
        if modo == "Mês":
            hoje = datetime.date.today()
            a, m = st.columns(2)
            ano = a.number_input("Ano", 2000, 2100, hoje.year, 1)
            mes = m.selectbox("Mês", range(1, 13), index=hoje.month - 1, format_func=lambda i: MESES[i - 1])
            ini, fim = periodo_mes(int(ano), int(mes))
        else:
            ini = st.date_input("De", datetime.date.today().replace(day=1), format="DD/MM/YYYY")
            fim = st.date_input("Até", datetime.date.today(), format="DD/MM/YYYY")
        if ini > fim:
            st.error("A data inicial é maior que a final.")
            st.stop()
        st.caption(f"Período: {ini:%d/%m/%Y} a {fim:%d/%m/%Y}")
    with c2:
        abr = st.radio("Abrangência", ["Completa", "Módulos específicos"], horizontal=True)
        por_mod = {m["id"]: [lp for lp in R.lps() if modulo_do_lp(lp) == m["id"]] for m in LPS["modulos"]}
        disponiveis = [m for m in LPS["modulos"] if por_mod[m["id"]]]
        if abr == "Completa":
            mods = None
        else:
            mods = set(st.multiselect("Módulos", [m["id"] for m in disponiveis],
                                      format_func=lambda i: next(m["nome"] for m in LPS["modulos"] if m["id"] == i)))
        incluir = st.checkbox("Incluir lançamentos manuais e sem LP (categoria própria)", True)
    for m in disponiveis:
        st.caption(f"**{m['nome']}** — {m['descricao']} · LPs {', '.join(por_mod[m['id']])}")
    lps = lps_do_escopo(R, mods)
    if mods is not None:
        lps |= {lp for lp in R.lps() if modulo_do_lp(lp) == "out"}
    if not lps:
        st.warning("Selecione ao menos um módulo.")
        st.stop()
    ss.periodo, ss.lps, ss.incluir_manuais = (ini, fim), lps, incluir
    st.success(f"{len(lps)} LPs no escopo. Siga para **3 · Importar CT2**.")

# ================================================================ 3 · CT2
elif etapa == ETAPAS[2]:
    st.header("Importar CT2 — lançamentos contábeis")
    if not pronto("periodo"):
        st.info("Defina o período e o escopo primeiro.")
        st.stop()
    ini, fim = ss.periodo
    st.code(filtro_sugerido("CT2", ini, fim, ss.lps), language=None)
    st.caption("Filtro sugerido para exportar a CT2 no genéricos.")
    f = st.file_uploader("CT2 (.xlsx do genéricos)", type=["xlsx"], key="up_ct2")
    if f:
        tab = ler(f.getvalue(), f.name)
        mapa, regs = preparar(tab, ss.regras, ss.lps, ss.fixos.get("CT2"))
        editor_mapeamento("CT2", tab.cabecalho, mapa, {"CT2_DATA", "CT2_VALOR", "CT2_LP", "CT2_ORIGEM", "CT2_KEY", "CT2_HIST", "CT2_MANUAL"}, "ct2")
        mapa, regs = preparar(tab, ss.regras, ss.lps, ss.fixos.get("CT2"))
        ss.ct2 = regs
        datas = [r["CT2_DATA"] for r in regs if r.get("CT2_DATA")]
        dmin, dmax = min(datas), max(datas)
        dmin, dmax = (getattr(dmin, "date", lambda: dmin)(), getattr(dmax, "date", lambda: dmax)())
        c = st.columns(5)
        c[0].metric("Lançamentos", f"{len(regs):,}".replace(",", "."))
        c[1].metric("Filiais", ", ".join(sorted({str(r.get('CT2_FILIAL', '')).strip() for r in regs})))
        c[2].metric("Aglutinados", sum(1 for r in regs if str(r.get("CT2_AGLUT", "")).strip() == "1"))
        c[3].metric("Manuais", sum(1 for r in regs if str(r.get("CT2_MANUAL", "")).strip() == "1"))
        c[4].metric("Automáticos sem LP", sum(1 for r in regs if not str(r.get("CT2_LP", "")).strip() and str(r.get("CT2_MANUAL", "")).strip() != "1"))
        if dmax < ini or dmin > fim:
            st.error(f"A CT2 cobre {dmin:%d/%m/%Y} a {dmax:%d/%m/%Y}, fora do período selecionado.")
        else:
            st.success(f"CT2 de {dmin:%d/%m/%Y} a {dmax:%d/%m/%Y}, dentro do período. Siga para **4 · Tabelas de origem**.")
        st.caption("Rotinas: " + " · ".join(f"{k} {v}" for k, v in Counter(str(r.get('CT2_ROTINA', '')).strip() for r in regs).most_common()))

# ================================================================ 4 · tabelas
elif etapa == ETAPAS[3]:
    st.header("Tabelas de origem")
    if not pronto("ct2"):
        st.info("Importe a CT2 primeiro.")
        st.stop()
    R, lps = ss.regras, ss.lps
    ini, fim = ss.periodo
    nec = R.tabelas_necessarias(lps)
    lista = sorted(nec, key=lambda a: (-nec[a]["valor"], -nec[a]["outras"]))
    st.write("Exporte cada tabela pelo genéricos com o filtro indicado e envie todas de uma vez (ou aos poucos). "
             "A tabela é identificada pela célula A1 do arquivo (ex.: `SD1`) ou pelo nome do arquivo.")
    ups = st.file_uploader("Tabelas (.xlsx do genéricos)", type=["xlsx"], accept_multiple_files=True, key="up_tabs")
    for f in ups or []:
        t = ler(f.getvalue(), f.name)
        if t.alias and t.alias not in ("CT5", "CT2"):
            ss.tabelas[t.alias] = t
    linhas = []
    for a in lista + [x for x in OPCIONAIS if x not in lista]:
        n = nec.get(a, dict(valor=0, outras=0))
        st_ = "Importada" if a in ss.tabelas else ("Não se aplica" if a in ss.nao_aplica else "Pendente")
        linhas.append({"Tabela": a, "Descrição": NOMES_TABELA.get(a, ""), "Uso": "Regra de valor" if n["valor"] else ("Opcional" if a in OPCIONAIS else "Complementar"),
                       "Regras": n["valor"] or n["outras"], "Situação": st_,
                       "Registros": len(ss.tabelas[a]) if a in ss.tabelas else None,
                       "Filtro sugerido no genéricos": filtro_sugerido(a, ini, fim, lps) or "Completa (sem filtro de data)"})
    st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")
    pend = [l["Tabela"] for l in linhas if l["Situação"] == "Pendente"]
    if pend:
        na = st.multiselect("Tabelas que o cliente não usa ou estão sem movimento no período", pend)
        ss.nao_aplica |= set(na)
    for a, t in sorted(ss.tabelas.items()):
        with st.expander(f"{a} · {len(t):,} registros · correlação de campos".replace(",", ".")):
            mapa = mapear(t.cabecalho, campos_esperados(a, R, lps), ss.fixos.get(a))
            editor_mapeamento(a, t.cabecalho, mapa, campos_de_valor(a, R, lps), "tab")
    faltam = [l["Tabela"] for l in linhas if l["Situação"] == "Pendente" and l["Uso"] == "Regra de valor"]
    if faltam:
        st.warning("Faltam tabelas usadas em regras de valor: " + ", ".join(faltam) +
                   ". Os LPs que dependem delas vão aparecer como “não disponível”.")
    else:
        st.success("Tabelas de valor completas. Siga para **5 · Conciliação**.")

# ================================================================ 5 · conciliação
elif etapa == ETAPAS[4]:
    st.header("Conciliação")
    if not pronto("ct2") or not ss.tabelas:
        st.info("Importe a CT2 e as tabelas de origem primeiro.")
        st.stop()
    ini, fim = ss.periodo
    titulo = f"Conciliação contábil · {ini:%d/%m/%Y} a {fim:%d/%m/%Y}"
    if st.button("Conciliar", type="primary"):
        with st.spinner("Recalculando as regras e cruzando com a CT2…"):
            regs = {}
            for a, t in ss.tabelas.items():
                regs[a] = preparar(t, ss.regras, ss.lps, ss.fixos.get(a))[1]
            cv3 = regs.pop("CV3", None)
            ss.motor = Motor(ss.regras, ss.ct2, regs, ss.periodo, ss.lps, ss.incluir_manuais, cv3).conciliar()
    if not pronto("motor"):
        st.stop()
    M = ss.motor
    T = M.totais()
    pct = (T["conciliadas"] + T["explicadas"]) / T["chaves"] * 100 if T["chaves"] else 0
    c = st.columns(6)
    c[0].metric("Linhas conciliadas por regra", f"{T['linhas']:,}".replace(",", "."))
    c[1].metric("Conciliadas ou explicadas", f"{pct:.1f}%".replace(".", ","))
    c[2].metric("Explicadas", T["explicadas"])
    c[3].metric("Divergentes", T["divergentes"])
    c[4].metric("Sem origem", T["sem_origem"])
    c[5].metric("Origem sem lançamento", T["sem_lancamento"])
    d1, d2 = st.columns(2)
    d1.download_button("Baixar planilha (Excel)", excel(M, titulo), f"conciliacao_{ini:%Y%m}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    rel = html_relatorio(M, titulo)
    d2.download_button("Baixar relatório (HTML)", rel, f"conciliacao_{ini:%Y%m}.html", "text/html", width="stretch")

    abas = st.tabs(["Resumo por LP", "Divergências", "Origem sem lançamento", "Financeiro sem lançamento", "Fora da regra", "Relatório HTML"])
    with abas[0]:
        df = pd.DataFrame(M.resumo_por_lp())
        if not df.empty:
            df["diferença"] = (df["ct2"] - df["esperado"]).round(2)
            st.dataframe(df[["lp", "seq", "descricao", "base", "chaves", "ct2", "esperado", "diferença", "conciliadas", "explicadas",
                             "divergentes", "sem_origem", "sem_lancamento", "valor_sem_lancamento"]],
                         hide_index=True, width="stretch", height=520,
                         column_config={k: st.column_config.NumberColumn(format="%.2f") for k in ("ct2", "esperado", "diferença", "valor_sem_lancamento")})
        st.caption("Bases identificadas pela CT2_KEY: " + " · ".join(f"{lp}→{b}" for lp, b in M.bases.items()))
    with abas[1]:
        div = [x for x in M.resultado if x["status"] in ("valor", "erro", "explicada", "sem_origem", "data")]
        for x in sorted(div, key=lambda x: x["status"] != "valor"):
            txt = f"**{x['lp']}/{x['seq']} · {x['hist']}** ({x['data']:%d/%m/%Y}) — CT2 {br(x['valor'])} · esperado {br(x['esperado'])} · diferença {br(x['dif'])}  \n{x['explicacao'] or x['erro'] or 'Sem explicação automática — revisar.'}"
            (st.error if x["status"] in ("valor", "erro", "sem_origem") else st.warning)(txt)
        if not div:
            st.success("Nenhuma divergência.")
    with abas[2]:
        st.dataframe(pd.DataFrame(M.sem_lancamento), hide_index=True, width="stretch")
    with abas[3]:
        fin = pd.DataFrame(M.financeiro_sem_lancamento)
        if not fin.empty:
            st.dataframe(fin.groupby("classe").agg(qtd=("valor", "size"), valor=("valor", "sum")).reset_index(), hide_index=True, width="stretch")
            st.dataframe(fin, hide_index=True, width="stretch")
    with abas[4]:
        st.dataframe(pd.DataFrame([dict(Categoria=k, Linhas=v, Valor=M.categorias_valor.get(k, 0)) for k, v in M.categorias.items()]),
                     hide_index=True, width="stretch")
        cv = M.resumo_cv3()
        if cv:
            st.info(f"CV3: {cv['registros']:,} rastros em {cv['destinos']:,} destinos · {cv['batem']:,} batem com a CT2 · "
                    f"{cv['so_cv3']:,} rastros sem lançamento correspondente (contabilizações excluídas ou refeitas) · "
                    f"{cv['so_ct2']:,} linhas da CT2 sem rastro.".replace(",", "."))
        st.dataframe(pd.DataFrame(M.soltas), hide_index=True, width="stretch")
    with abas[5]:
        if hasattr(st, "iframe"):
            st.iframe(rel, height=900)
        else:  # versões antigas do Streamlit
            import streamlit.components.v1 as components
            components.html(rel, height=900, scrolling=True)
