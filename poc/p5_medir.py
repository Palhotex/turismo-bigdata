#!/usr/bin/env python3
"""Passo 5 — Consultas finais e medição do efeito das escolhas de modelação.

Medição obrigatória do enunciado: a mesma consulta com e sem o padrão Subset.
  COM Subset:  página do alojamento = 1 leitura (find_one) com as 10 avaliações embebidas
  SEM Subset:  find_one do alojamento + find nas avaliações com sort + limit (usa o índice)
Também: painel da zona pré-agregado (Computed) vs agregação na leitura, e leitura do preço.

Uso:
  MONGO_URI=mongodb://localhost:27017 python p5_medir.py
  python p5_medir.py --mock     # carrega em mongomock e mede (tempos NÃO representativos)
"""
import argparse
import random
import time

import bson

from comum import guardar, percentis
from p4_serving import BASE, N_SUBSET, cliente

N_AMOSTRAS = 500
AQUECIMENTO = 20


def medir(f, args):
    t = time.perf_counter()
    f(*args)
    return (time.perf_counter() - t) * 1000


def correr(mock=False):
    db = cliente(mock)[BASE]
    rng = random.Random(42)
    ids = [d["_id"] for d in db.alojamentos.find({}, {"_id": 1})]
    zonas = [d["_id"] for d in db.painel_zona.find({}, {"_id": 1})]
    n_amostras = 100 if mock else N_AMOSTRAS   # o mock é lento e os tempos dele não contam
    amostra = [rng.choice(ids) for _ in range(n_amostras)]

    def com_subset(lid):
        return db.alojamentos.find_one({"_id": lid})

    def sem_subset(lid):
        d = db.alojamentos.find_one({"_id": lid}, {"recent_reviews": 0})
        d["recent_reviews"] = list(db.avaliacoes.find({"listing_id": lid, "suspect": False},
                                                      {"text": 0}).sort("created_at", -1).limit(N_SUBSET))
        return d

    def painel_pre(z):
        return db.painel_zona.find_one({"_id": z})

    def painel_leitura(z):
        return list(db.avaliacoes.aggregate([
            {"$match": {"zone_id": z, "suspect": False}},
            {"$unwind": "$topics"},
            {"$group": {"_id": "$topics", "reviews": {"$sum": 1}, "avg_rating": {"$avg": "$rating"}}}]))

    def preco(lid):
        return db.alojamentos.find_one({"_id": lid}, {"suggested_price": 1})

    # as duas versões devolvem as mesmas avaliações? (senão a comparação não é justa)
    iguais = all([r["review_id"] for r in com_subset(l)["recent_reviews"]] ==
                 [r["_id"] for r in sem_subset(l)["recent_reviews"]] for l in amostra[:50])

    for l in amostra[:AQUECIMENTO]:
        com_subset(l), sem_subset(l)
    t_com, t_sem, t_preco = [], [], []
    for l in amostra:                      # alternar evita favorecer uma versão pela cache
        t_com.append(medir(com_subset, (l,)))
        t_sem.append(medir(sem_subset, (l,)))
        t_preco.append(medir(preco, (l,)))
    t_pre, t_ler = [], []
    for _ in range(1 if mock else max(1, 200 // len(zonas))):
        for z in zonas:
            t_pre.append(medir(painel_pre, (z,)))
            t_ler.append(medir(painel_leitura, (z,)))

    docs = list(db.alojamentos.find({"_id": {"$in": amostra[:200]}}))
    tam_com = sum(len(bson.encode(d)) for d in docs) / len(docs)
    tam_sem = sum(len(bson.encode({k: v for k, v in d.items() if k != "recent_reviews"})) for d in docs) / len(docs)

    res = {
        "mock": mock, "aviso": "mongomock: tempos não representam um servidor MongoDB" if mock else None,
        "amostras": n_amostras, "mesmas_avaliacoes_nas_duas_versoes": iguais,
        "pagina_alojamento_com_subset": percentis(t_com),
        "pagina_alojamento_sem_subset": percentis(t_sem),
        "painel_pre_agregado": percentis(t_pre),
        "painel_agregado_na_leitura": percentis(t_ler),
        "leitura_preco": percentis(t_preco),
        "tamanho_medio_doc_alojamento_bytes": {"com_subset": round(tam_com), "sem_subset": round(tam_sem)},
        "n_avaliacoes": db.avaliacoes.estimated_document_count(),
    }
    guardar("p5_medicoes.json", res)
    c, s = res["pagina_alojamento_com_subset"], res["pagina_alojamento_sem_subset"]
    print(f"Página do alojamento: com Subset mediana {c['mediana_ms']} ms / p95 {c['p95_ms']} ms; "
          f"sem Subset {s['mediana_ms']} / {s['p95_ms']} ms{'  [mock]' if mock else ''}")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    if a.mock:
        from p4_serving import correr as carregar
        carregar(mock=True)
    correr(a.mock)
