#!/usr/bin/env python3
"""Verifica uma pasta gerada: taxas observadas vs. configuradas e reprodutibilidade.

Uso:
    python verificar.py saida/escala_1_semente_42
    python verificar.py saida/escala_1_semente_42 outra/escala_1_semente_42   # compara hashes
"""
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def ler(p):
    with open(p, encoding="utf-8") as f:
        for linha in f:
            yield json.loads(linha)


def pct(a, b):
    return f"{100 * a / b:.2f}%" if b else "—"


def main(pasta, outra=None):
    pasta = Path(pasta)
    m = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))
    cfg = m["config"]
    print(f"Gerador v{m['gerador_versao']} · escala {m['escala']}× · semente {m['semente']}\n")

    # avaliações: rótulos de verdade
    v = list(ler(pasta / "verdade/avaliacoes_verdade.jsonl"))
    n = len(v)
    falsas = sum(r["falsa"] for r in v)
    camp = sum(r["campanha"] is not None for r in v)
    gen = [r for r in v if not r["falsa"]]
    sent = Counter(r["sentimento_real"] for r in gen)
    lang = Counter(r["idioma_real"] for r in v)
    print("AVALIAÇÕES (rótulos reais)")
    print(f"  total únicas: {n:,}   falsas: {falsas:,} ({pct(falsas, n)}), das quais em campanha: {camp:,}")
    print("  sentimento (genuínas): " + ", ".join(f"{k} {pct(c, len(gen))} (cfg {cfg['sentimento'][k]:.0%})" for k, c in sorted(sent.items())))
    print("  idioma: " + ", ".join(f"{k} {pct(c, n)} (cfg {cfg['idiomas'][k]:.0%})" for k, c in sorted(lang.items())))
    for chave, nome in [("nota_contraria", "nota contrária ao texto"), ("tem_pii_no_texto", "PII no texto"),
                        ("idioma_declarado_errado", "idioma declarado errado")]:
        c = sum(r[chave] for r in gen)
        print(f"  {nome}: {pct(c, len(gen))}")

    # defeitos injetados, por ficheiro
    print("\nDEFEITOS INJETADOS (taxa sobre registos únicos do ficheiro)")
    unicos = {}
    for f, total in m["registos"].items():
        dup = m["defeitos_injetados"].get(f"{f}:duplicado", 0)
        unicos[f] = total - dup
    for chave, c in m["defeitos_injetados"].items():
        f, tipo = chave.split(":")
        print(f"  {f:28s} {tipo:18s} {c:>9,d}  {pct(c, unicos[f])}")
    print("  configurado: " + ", ".join(f"{k} {v:.1%}" for k, v in cfg["defeitos"].items() if isinstance(v, float)))

    # ordem de chegada: eventos que chegam mais de 60 s depois de um evento mais recente
    print("\nORDEM DE CHEGADA (atraso > 60 s face ao evento mais recente já recebido)")
    for f in ["pesquisas.jsonl", "reservas.jsonl", "avaliacoes_stream.jsonl"]:
        campo = "created_at" if f.startswith("aval") else "event_ts"
        maximo, atrasados, total = 0.0, 0, 0
        for r in ler(pasta / f):
            ts = r.get(campo)
            if ts is None or ts.startswith("2099"):
                continue
            t = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").timestamp()
            total += 1
            if maximo - t > 60:
                atrasados += 1
            maximo = max(maximo, t)
        print(f"  {f:28s} {atrasados:>9,d}  {pct(atrasados, total)}")

    # procura por hora no Porto, para ver o pico
    print("\nPESQUISAS POR HORA NA CIDADE DO EVENTO")
    ev = cfg["evento_pico"]
    por_hora = Counter(r["event_ts"][:13] for r in ler(pasta / "pesquisas.jsonl") if r.get("city") == ev["cidade"])
    horas = sorted(por_hora)
    for h in horas[::4]:
        print(f"  {h}h  {por_hora[h]:>8,d}  {'█' * (por_hora[h] * 40 // max(por_hora.values()))}")

    # formatos da agenda
    print("\nAGENDA EXTERNA")
    fmts = Counter("v1" if "events" in r else "v2" for r in ler(pasta / "agenda_api.jsonl"))
    print(f"  polls v1: {fmts['v1']}, v2 (sem aviso): {fmts['v2']}")

    if outra:
        m2 = json.loads((Path(outra) / "manifesto.json").read_text(encoding="utf-8"))
        iguais = m["sha256"] == m2["sha256"]
        print(f"\nREPRODUTIBILIDADE: {'IGUAL — mesmos dados byte a byte' if iguais else 'DIFERENTE'}")
        if not iguais:
            for f in m["sha256"]:
                if m["sha256"][f] != m2["sha256"].get(f):
                    print(f"  difere: {f}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
