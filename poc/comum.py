"""Funções partilhadas pela prova de conceito."""
import json
import os
import statistics
import time
from contextlib import contextmanager
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent
LAKE = Path(os.environ.get("LAKE", RAIZ / "lake"))
RESULTADOS = RAIZ / "resultados"

# Chave secreta da pseudonimização. Em produção viria de um cofre de chaves (KMS), nunca do código.
CHAVE_PSEUDO = os.environ.get("CHAVE_PSEUDO", "chave-de-teste-nao-usar-em-producao")

FONTES = ["alojamentos", "avaliacoes_historico", "avaliacoes_stream", "pesquisas",
          "reservas", "disponibilidade", "agenda_api"]


def ligar():
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    con.execute("SET TimeZone = 'UTC'")
    return con


def escrever_atomico(con, sql_select, destino):
    """Escreve um Parquet num ficheiro temporário e só no fim o troca pelo definitivo.
    Uma falha a meio deixa a versão anterior intacta (nunca um ficheiro meio escrito)."""
    destino = Path(destino)
    tmp = destino.with_suffix(".parquet.tmp")
    con.execute(f"COPY ({sql_select}) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)")
    os.replace(tmp, destino)


def camada(nome):
    p = LAKE / nome
    p.mkdir(parents=True, exist_ok=True)
    return p


def pq(camada_nome, tabela):
    """Caminho do Parquet de uma tabela numa camada (como string para SQL)."""
    return str(LAKE / camada_nome / f"{tabela}.parquet")


@contextmanager
def cronometro(registo, nome):
    t = time.perf_counter()
    yield
    registo[nome] = round(time.perf_counter() - t, 3)


def percentis(valores_ms):
    v = sorted(valores_ms)
    return {"n": len(v), "mediana_ms": round(statistics.median(v), 3),
            "p95_ms": round(v[int(0.95 * (len(v) - 1))], 3), "max_ms": round(v[-1], 3)}


def guardar(nome, dados):
    RESULTADOS.mkdir(exist_ok=True)
    (RESULTADOS / nome).write_text(json.dumps(dados, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def ler_resultado(nome):
    p = RESULTADOS / nome
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
