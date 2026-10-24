#!/usr/bin/env python3
"""Passo 1 — Ingestão para a camada BRONZE.

Guarda cada linha tal como chegou (texto JSON bruto), com a ordem de chegada e o
lote. O bronze nunca rejeita nada: é a cópia fiel da origem, a partir da qual
qualquer camada pode ser reconstruída.

Uso: python p1_ingestao.py ../gerador/saida/escala_1_semente_42
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

from comum import FONTES, camada, cronometro, guardar, ligar, pq


def correr(pasta_dados):
    pasta = Path(pasta_dados)
    con = ligar()
    camada("bronze")
    lote = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    tempos, linhas = {}, {}
    for fonte in FONTES:
        origem = pasta / f"{fonte}.jsonl"
        with cronometro(tempos, fonte):
            # cada linha lida como texto, sem interpretar: nada se perde nem se corrige aqui
            con.execute(f"""
                COPY (
                  SELECT row_number() OVER () AS seq_chegada,
                         raw,
                         '{fonte}' AS fonte,
                         '{lote}' AS lote,
                         now() AS ingerido_em
                  FROM read_csv('{origem}', columns={{'raw': 'VARCHAR'}}, header=false,
                                delim='\x1f', quote='', escape='', auto_detect=false)
                ) TO '{pq("bronze", fonte)}' (FORMAT parquet, COMPRESSION zstd)""")
        linhas[fonte] = con.execute(f"SELECT count(*) FROM '{pq('bronze', fonte)}'").fetchone()[0]
    total = sum(linhas.values())
    duracao = sum(tempos.values())
    res = {"lote": lote, "origem": str(pasta), "linhas": linhas, "tempo_s": tempos,
           "total_linhas": total, "debito_linhas_s": round(total / duracao) if duracao else None,
           "tamanho_jsonl_mb": round(sum((pasta / f"{f}.jsonl").stat().st_size for f in FONTES) / 2**20, 1),
           "tamanho_bronze_parquet_mb": round(sum(Path(pq("bronze", f)).stat().st_size for f in FONTES) / 2**20, 1)}
    guardar("p1_ingestao.json", res)
    print(f"Bronze: {total:,} linhas em {duracao:.1f}s ({res['debito_linhas_s']:,} linhas/s); "
          f"JSONL {res['tamanho_jsonl_mb']} MB -> Parquet {res['tamanho_bronze_parquet_mb']} MB")
    return res


if __name__ == "__main__":
    correr(sys.argv[1])
