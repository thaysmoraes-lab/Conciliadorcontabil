import json
import os

PASTA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")


def carregar(nome):
    with open(os.path.join(PASTA, nome), encoding="utf-8") as f:
        return json.load(f)


SX3_CT5 = carregar("sx3_ct5.json")
TITULOS = carregar("titulos.json")["tabelas"]
BASES = {k: v for k, v in carregar("bases.json").items() if not k.startswith("_")}
CADASTROS = {k: v for k, v in carregar("cadastros.json").items() if not k.startswith("_")}
LPS = carregar("lps.json")
PARAMETROS = {k: v for k, v in carregar("parametros.json").items() if not k.startswith("_")}
FUNCOES_TBC = {f["nome"]: f for f in carregar("funcoes_tbc.json")["funcoes"]}
