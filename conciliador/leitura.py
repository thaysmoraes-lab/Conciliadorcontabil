"""Leitura dos arquivos exportados pela rotina Genéricos (Configurador)."""
import re
import io
import openpyxl


class Tabela:
    """Planilha do genéricos: alias, cabeçalho (X3_TITULO) e linhas cruas."""

    def __init__(self, alias, cabecalho, linhas, linha_cabecalho, nome_arquivo=""):
        self.alias = alias
        self.cabecalho = cabecalho          # títulos; repetidos recebem sufixo '#2', '#3'...
        self.linhas = linhas
        self.linha_cabecalho = linha_cabecalho
        self.nome_arquivo = nome_arquivo

    def __len__(self):
        return len(self.linhas)

    def coluna(self, titulo):
        return self.cabecalho.index(titulo)


def _alias_do_nome(nome):
    m = re.match(r"^([A-Za-z][A-Za-z0-9]{2})(?:[^A-Za-z0-9]|$)", nome or "")
    return m.group(1).upper() if m else ""


def _linhas(arquivo):
    """python-calamine é ~8x mais rápido que openpyxl em planilhas grandes (SB1, SA1); openpyxl é o reserva."""
    try:
        from python_calamine import CalamineWorkbook
        arquivo.seek(0)
        return [tuple(r) for r in CalamineWorkbook.from_filelike(arquivo).get_sheet_by_index(0).to_python()]
    except ImportError:
        arquivo.seek(0)
        wb = openpyxl.load_workbook(arquivo, read_only=True, data_only=True)
        linhas = list(wb.active.iter_rows(values_only=True))
        wb.close()
        return linhas


def ler_generico(arquivo, nome_arquivo=""):
    """Lê .xlsx do genéricos. Localiza sozinho a linha de cabeçalho (primeira linha com mais de 50% de
    células de texto) e o alias (célula A1 com 3 caracteres, como 'CT2', ou o nome do arquivo)."""
    if isinstance(arquivo, (bytes, bytearray)):
        arquivo = io.BytesIO(arquivo)
    linhas = _linhas(arquivo)
    if not linhas:
        raise ValueError("Arquivo vazio")
    idx = None
    for i, r in enumerate(linhas[:20]):
        textos = sum(1 for x in r if isinstance(x, str) and x.strip())
        if r and textos > len(r) * 0.5:
            idx = i
            break
    if idx is None:
        raise ValueError("Cabeçalho não localizado nas 20 primeiras linhas")
    vistos = {}
    cab = []
    for x in linhas[idx]:
        t = (x or "").strip() if isinstance(x, str) else ("" if x is None else str(x))
        vistos[t] = vistos.get(t, 0) + 1
        cab.append(t if vistos[t] == 1 else f"{t}#{vistos[t]}")
    dados = [r for r in linhas[idx + 1:] if any(v not in (None, "", " ") for v in r)]
    a1 = linhas[0][0] if linhas[0] else None
    alias = ""
    if idx > 0 and isinstance(a1, str) and re.fullmatch(r"[A-Z][A-Z0-9]{2}", a1.strip()):
        alias = a1.strip()
    alias = alias or _alias_do_nome(nome_arquivo)
    return Tabela(alias, cab, dados, idx + 1, nome_arquivo)
