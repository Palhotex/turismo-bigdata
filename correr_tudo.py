#!/usr/bin/env python3
"""Corre a prova de conceito inteira, do gerador às medições.

    python correr_tudo.py              # 1×, MongoDB simulado (mongomock), nada a instalar além do requirements
    python correr_tudo.py --escala 10
    MONGO_URI="mongodb+srv://..." python correr_tudo.py --mongo     # MongoDB a sério (ex.: Atlas gratuito)

Os resultados ficam em poc/resultados/*.json (são esses os números para o relatório).
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
POC, GER = RAIZ / "poc", RAIZ / "gerador"


def passo(titulo, *cmd, cwd=POC, falha_esperada=False):
    print(f"\n=== {titulo}")
    t = time.perf_counter()
    r = subprocess.run([sys.executable, *cmd], cwd=cwd, env=os.environ.copy())
    dur = time.perf_counter() - t
    if r.returncode != 0 and not falha_esperada:
        sys.exit(f"Falhou: {titulo}")
    return dur


def tamanho_mb(p):
    return round(sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file()) / 2**20, 1) if Path(p).exists() else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--escala", type=int, default=1)
    ap.add_argument("--mongo", action="store_true", help="usar o MongoDB de MONGO_URI em vez do simulado")
    a = ap.parse_args()
    dados = GER / "saida" / f"escala_{a.escala}_semente_42"
    mock = [] if a.mongo else ["--mock"]
    tempos = {}

    tempos["gerar"] = passo(f"Gerar dados sintéticos ({a.escala}×)", "gerador.py", "--escala", str(a.escala), cwd=GER)
    tempos["ingestao_bronze"] = passo("1. Ingestão -> bronze", "p1_ingestao.py", str(dados))
    tempos["prata_sem_v2"] = passo("2a. Bronze -> prata (parser só conhece a agenda v1)", "p2_prata.py")
    tempos["prata_corrigida"] = passo("2b. Parser corrigido: reprocessar a partir do bronze", "p2_prata.py", "--aceitar-v2")

    # cenário de falha de componente: o processamento cai a meio
    antes = {f.name: f.stat().st_size for f in (POC / "lake" / "prata").glob("*.parquet")}
    passo("Cenário de falha: processamento cai depois das pesquisas", "p2_prata.py", "--aceitar-v2",
          "--falhar-apos", "pesquisas", falha_esperada=True)
    depois = {f.name: f.stat().st_size for f in (POC / "lake" / "prata").glob("*.parquet")}
    sobras = list((POC / "lake" / "prata").glob("*.tmp"))
    rec = passo("Recuperação: correr outra vez", "p2_prata.py", "--aceitar-v2")
    falha = {"ficheiros_prata_intactos": sorted(antes) == sorted(depois), "ficheiros_meio_escritos": len(sobras),
             "tempo_recuperacao_s": round(rec, 2)}

    tempos["ouro"] = passo("3. Prata -> ouro (sentimento, falsas, preço, painel)", "p3_ouro.py")
    if a.mongo or a.escala == 1:
        tempos["serving_mongodb"] = passo("4. Ouro -> MongoDB", "p4_serving.py", *mock)
        tempos["medicoes_mongodb"] = passo("5. Consultas e medição com/sem Subset", "p5_medir.py", *mock)
    else:
        # o MongoDB simulado não tem índices: acima de 1× fica muito lento e os tempos não contam
        print("\n=== 4-5. MongoDB simulado só a 1×; para medir a esta escala use --mongo (ex.: Atlas)")
    tempos["avaliar_cenarios"] = passo("6. Avaliar cenários contra a verdade", "p6_cenarios.py", str(dados))

    resumo = {"escala": a.escala, "mongodb": "real" if a.mongo else "simulado (mongomock)",
              "tempos_s": {k: round(v, 1) for k, v in tempos.items()}, "cenario_falha": falha,
              "espaco_mb": {"dados_gerados": tamanho_mb(dados), "lake_parquet": tamanho_mb(POC / "lake")}}
    (POC / "resultados").mkdir(exist_ok=True)
    (POC / "resultados" / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== Resumo")
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
