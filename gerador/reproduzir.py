#!/usr/bin/env python3
"""Reproduz um ficheiro JSONL gerado como um fluxo em tempo real (Kafka ou ecrã).

Respeita os intervalos entre eventos (pela ordem do ficheiro = ordem de chegada),
acelerados pelo fator --rapidez. Assim o "ritmo" é configurável sem regenerar dados.

Exemplos:
    # 1 hora simulada por minuto real, para o tópico 'pesquisas'
    python reproduzir.py saida/escala_1_semente_42/pesquisas.jsonl --topico pesquisas --rapidez 60 --chave zone_id

    # o mais depressa possível (teste de carga), só no ecrã
    python reproduzir.py saida/escala_1_semente_42/reservas.jsonl --rapidez 0 --ecra

Requer, para Kafka:  pip install kafka-python
"""
import argparse
import json
import sys
import time
from datetime import datetime


def instante(r):
    """Tempo do evento, qualquer que seja o formato do registo (inclui agenda v1/v2)."""
    for campo in ("event_ts", "created_at", "poll_ts", "snapshot_ts"):
        v = r.get(campo)
        if isinstance(v, str) and not v.startswith("2099"):
            try:
                return datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").timestamp()
            except ValueError:
                return None
    if isinstance(r.get("pollTimestamp"), int):
        return float(r["pollTimestamp"])
    return None  # registo com campo de tempo em falta ou impossível: envia logo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ficheiro")
    ap.add_argument("--topico", help="tópico Kafka (por omissão, o nome do ficheiro)")
    ap.add_argument("--servidor", default="localhost:9092")
    ap.add_argument("--rapidez", type=float, default=60.0,
                    help="segundos simulados por segundo real (0 = sem pausas)")
    ap.add_argument("--chave", help="campo usado como chave da mensagem (ex.: listing_id, zone_id)")
    ap.add_argument("--ecra", action="store_true", help="escrever no ecrã em vez de enviar ao Kafka")
    a = ap.parse_args()
    topico = a.topico or a.ficheiro.rsplit("/", 1)[-1].replace(".jsonl", "")

    produtor = None
    if not a.ecra:
        try:
            from kafka import KafkaProducer
        except ImportError:
            sys.exit("kafka-python não instalado: pip install kafka-python (ou use --ecra)")
        produtor = KafkaProducer(bootstrap_servers=a.servidor, linger_ms=20, acks="all")

    t_sim0 = t_real0 = None
    n = 0
    inicio = time.time()
    with open(a.ficheiro, encoding="utf-8") as f:
        for linha in f:
            r = json.loads(linha)
            t = instante(r)
            if a.rapidez > 0 and t is not None:
                if t_sim0 is None:
                    t_sim0, t_real0 = t, time.time()
                espera = t_real0 + (t - t_sim0) / a.rapidez - time.time()
                if espera > 0:
                    time.sleep(espera)
            chave = str(r.get(a.chave, "")).encode() if a.chave else None
            if produtor:
                produtor.send(topico, key=chave, value=linha.strip().encode("utf-8"))
            else:
                print(linha, end="")
            n += 1
            if n % 50000 == 0:
                print(f"[{topico}] {n:,} enviados · {n / (time.time() - inicio):,.0f} msg/s", file=sys.stderr)
    if produtor:
        produtor.flush()
    print(f"[{topico}] terminado: {n:,} mensagens em {time.time() - inicio:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
