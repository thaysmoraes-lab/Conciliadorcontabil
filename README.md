# Conciliador contábil Protheus

Aplicação Streamlit que concilia a contabilidade do Protheus (CT2) com as tabelas de origem, usando como
ponto de partida a regra de valor de cada lançamento padrão (`CT5_VLR01`).

Todas as tabelas entram como `.xlsx` exportado pela rotina **Genéricos** (Configurador). O cabeçalho vem com o
`X3_TITULO`, e o conciliador correlaciona cada título ao campo automaticamente. Quando a correlação é incerta,
ele pede a confirmação na tela.

## Fluxo

| Etapa | O que acontece |
|---|---|
| 1 · Importar CT5 | Lê as regras de LP, correlaciona os campos pela SX3 e classifica cada sequência: padrão, acelerador TBC, customizada (`U_` não parametrizada, bloqueia o LP) ou origem TXT. Aponta erros de sintaxe, `CT5_ORIGEM` inconsistente e estornos com regra diferente da inclusão. |
| 2 · Período e escopo | Competência (mês ou intervalo) e abrangência: completa ou por módulo (Compras, Faturamento, Financeiro, Estoque, Fiscal, Ativo, Folha). |
| 3 · Importar CT2 | Localiza o cabeçalho sozinho, confere se a CT2 cobre o período e mostra o perfil (aglutinados, manuais, sem LP). |
| 4 · Tabelas de origem | Lista as tabelas exigidas pelas regras do escopo com o filtro sugerido para o genéricos. Aceita vários arquivos de uma vez e mostra a correlação de campos de cada um. |
| 5 · Conciliação | Recalcula o `CT5_VLR01` sobre a origem e compara com a CT2. Gera planilha Excel e relatório HTML. |

## Como a conciliação funciona

1. **LP e sequência** vêm do `CT2_ORIGEM` (formato `650-002`; nos estornos gerados pelo RCTBM002, do texto `AUTO-LCPD … Estorno do lcto`).
2. **Registro de origem** é localizado, nesta ordem: pela `CT2_KEY` (chave do índice da tabela de origem, comparada
   sem espaços, o que dispensa conhecer o tamanho de cada campo), pelo histórico com natureza e data (movimentos
   bancários sem chave, LPs 562/563) e, se importada, pela CV3 como evidência complementar. A tabela base de cada
   LP é confirmada automaticamente pela taxa de acerto das chaves.
3. **Valor esperado** é o `CT5_VLR01` avaliado sobre o registro, com SF1/SF2, SF4 (TES), SA1/SA2, SED, SDE, SE1/SE2
   posicionados. Nas regras de cabeçalho a SF4 fica na TES do último item, como no Protheus.
4. **Nível de comparação**: LPs de item (SD1/SD2) são comparados por documento, porque a CT2 aglutina itens de mesma
   conta. Regras de item cujo valor vem só do cabeçalho (ex.: `SF1->F1_VALBRUT`) contam uma vez por nota.
5. **Data**: `CT2_DATA` × data da origem (`D1_DTDIGIT`, `F2_EMISSAO`, `E5_DTDISPO`, `E1_EMIS1`, `E2_EMIS1`…).
6. **Tolerância**: R$ 0,01 por linha da CT2 (arredondamento de rateio).
7. **Explicações automáticas** para diferenças: lançamento manual ou automático sem LP com o mesmo documento e o
   valor exato da diferença, desconto de item (`D1_VALDESC`) não deduzido pela regra, e baixas aglutinadas com outra
   parcela do mesmo título.
8. **Origem sem lançamento**: documentos do período em que a regra retorna valor e não existe linha na CT2
   (usa `condicao_origem` de `config/lps.json`), e movimentos principais do SE5 sem lançamento, classificados.

## Estrutura

```
app.py                      interface Streamlit (etapas 1 a 5)
conciliador/
  leitura.py                leitura do .xlsx do genéricos (python-calamine, com openpyxl de reserva)
  mapeamento.py             título × campo, similaridade, decodificação de combos (Sim/Não → S/N ou 1/2)
  advpl.py                  interpretador das expressões AdvPL do CT5_VLR01
  ct5.py                    leitura e análise das regras
  funcoes.py                funções U_ parametrizadas para o recálculo
  motor.py                  conciliação
  pipeline.py               orquestração, escopo e filtros sugeridos
  relatorio.py              Excel e HTML
config/
  sx3_ct5.json              X3_TITULO da CT5
  titulos.json              X3_TITULO esperado por campo, por tabela
  bases.json                tabelas de origem: data de referência, documento e composições da CT2_KEY
  cadastros.json            índice 1 das tabelas de posicionamento
  lps.json                  módulos, base e condição de origem por LP, regras do financeiro
  funcoes_tbc.json          catálogo do acelerador contábil TBC (MIT072)
  parametros.json           MV_ usados pelas funções do acelerador
tests/                      testes com dados sintéticos
```

## Rodar localmente

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Publicar no Streamlit Community Cloud

1. Suba este repositório no GitHub (os `.xlsx` de clientes ficam fora pelo `.gitignore`).
2. Em share.streamlit.io, **New app** → escolha o repositório, branch `main` e arquivo `app.py`.
3. O limite de upload está em 500 MB (`.streamlit/config.toml`).

## Exportação pelo genéricos

- Exporte cada tabela em `.xlsx`. A tabela é identificada pela célula A1 (ex.: `SD1`) ou pelo nome do arquivo.
- Inclua na exportação os campos customizados usados na CT5 (ex.: `F4_XCONT`, `ED_XCTB`, `B1_XCONTAD`).
- Use os filtros sugeridos na etapa 4. SE1 e SE2 vão sem filtro de data quando o escopo tem baixas, porque o título
  baixado no mês pode ter sido emitido antes. Cadastros vão completos.
- Campos de combo saem com a descrição ("Sim", "Não", "Bon"…); o conciliador converte para o código usando o tipo
  de literal que a própria CT5 compara.

## Parametrizar uma função de usuário

LPs cujo `CT5_VLR01` chama uma função `U_` que não está em `conciliador/funcoes.py` ficam bloqueados. Para liberar:

```python
@registrar("U_MINHAFUNCAO")
def minha_funcao(motor, ctx, arg1, arg2):
    # motor.tab("SE2") -> registros da tabela; ctx["SF1"] -> registro posicionado
    return 0.0
```

Já implementadas: `U_RETVLPCC`, `U_RCTBE003`, `U_LPLSG` (usa `config/parametros.json`), `U_SEV2SE1`, `U_SEV2SE2`.
Funções que só retornam conta ou entidade (`U_RetCta`, `U_RetTesDeb`…) não afetam a conciliação de valor.

## Correlações de campos

Correlações feitas manualmente ficam na sessão e podem ser baixadas/carregadas em JSON pela barra lateral, para
reaproveitar no mesmo cliente. Para tornar uma correlação padrão, inclua o título em `config/titulos.json`.

## Limitações conhecidas

- Os títulos das tabelas de Ativo (SN1/SN3/SN4), SD3 e SEU em `config/titulos.json` precisam ser validados na
  primeira base que usar esses módulos.
- A CV3 exportada pelo genéricos não traz o RECNO das tabelas de origem; ela entra como evidência (rastros sem
  lançamento correspondente), não como chave.
- Movimentos sem `CT2_KEY` só são conciliados quando o histórico traz a natureza (LPs 562/563/564/565).

## Testes

```bash
pip install -r requirements-dev.txt
pytest -q
```
