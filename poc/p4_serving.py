#!/usr/bin/env python3
"""Passo 4 — OURO -> MongoDB (camada de serving).

Coleções e padrões de modelação (catálogo do enunciado):
  alojamentos  Subset (recent_reviews: as 10 mais recentes, não suspeitas)
               Extended Reference (zone: id, nome e cidade copiados, sem junção)
               Computed (review_stats e suggested_price calculados no ouro, não em cada leitura)
               Schema Versioning (schema_version)
  avaliacoes   histórico completo, uma avaliação por documento (evita o array ilimitado)
  painel_zona  um documento por zona com os temas já agregados (Computed)

Uso:
  MONGO_URI=mongodb://localhost:27017 python p4_serving.py
  python p4_serving.py --mock          # sem servidor (mongomock), só para testar o código
"""
import argparse
import os

from comum import cronometro, guardar, ligar, pq

N_SUBSET = 10
BASE = "turismo_poc"


def cliente(mock=False):
    if mock:
        import mongomock
        if not hasattr(cliente, "_mock"):
            cliente._mock = mongomock.MongoClient()
        return cliente._mock
    from pymongo import MongoClient
    return MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=5000)


def em_lotes(col, docs, tamanho=5000):
    for i in range(0, len(docs), tamanho):
        col.insert_many(docs[i:i + tamanho], ordered=False)


def correr(mock=False):
    con = ligar()
    db = cliente(mock)[BASE]
    t = {}
    av = pq("ouro", "avaliacoes_enriquecidas")
    hora_atual = con.execute(f"SELECT max(hora_preco) FROM '{pq('ouro', 'preco_sugerido')}'").fetchone()[0]

    with cronometro(t, "construir_documentos"):
        linhas = con.execute(f"""
            WITH recentes AS (
                SELECT listing_id, list({{'review_id': review_id, 'rating': rating, 'sentiment': sentimento,
                         'lang': lang_det, 'excerpt': left(texto, 120), 'created_at': created_at}}
                         ORDER BY created_at DESC) AS recent_reviews
                FROM (SELECT *, row_number() OVER (PARTITION BY listing_id ORDER BY created_at DESC) AS r
                      FROM '{av}' WHERE NOT suspeita) WHERE r <= {N_SUBSET} GROUP BY 1),
                 stats AS (
                SELECT listing_id, count(*) AS n, round(avg(rating), 2) AS nota,
                       round(avg(CASE sentimento WHEN 'pos' THEN 1 WHEN 'neg' THEN -1 ELSE 0 END), 3) AS sent
                FROM '{av}' WHERE NOT suspeita GROUP BY 1),
                 preco AS (SELECT * FROM '{pq('ouro', 'preco_sugerido')}' WHERE hora_preco = TIMESTAMP '{hora_atual}')
            SELECT l.listing_id, l.zone_id, l.zone_name, l.city, l.tipo, l.capacity, l.base_price,
                   p.preco_sugerido, p.hora_preco, p.fator, p.fallback, p.modelo_versao,
                   coalesce(s.n, 0), s.nota, s.sent, coalesce(r.recent_reviews, [])
            FROM '{pq('prata', 'alojamentos')}' l LEFT JOIN preco p USING (listing_id)
            LEFT JOIN stats s USING (listing_id) LEFT JOIN recentes r USING (listing_id)""").fetchall()
        alojamentos = [{
            "_id": lid, "schema_version": 1,
            "zone": {"zone_id": zid, "name": zn, "city": city},
            "type": tipo, "capacity": cap, "base_price": bp,
            "suggested_price": {"value": ps, "valid_hour": hp, "factor": f, "fallback": fb, "model": mv},
            "review_stats": {"count": n, "avg_rating": nota, "avg_sentiment": sent},
            "recent_reviews": rr,
        } for lid, zid, zn, city, tipo, cap, bp, ps, hp, f, fb, mv, n, nota, sent, rr in linhas]

        avaliacoes = [{"_id": r[0], "listing_id": r[1], "zone_id": r[2], "rating": r[3], "sentiment": r[4],
                       "lang": r[5], "topics": r[6], "text": r[7], "created_at": r[8], "suspect": r[9]}
                      for r in con.execute(f"""SELECT review_id, listing_id, zone_id, rating, sentimento, lang_det,
                                               temas, texto, created_at, suspeita FROM '{av}'""").fetchall()]

        painel = {}
        for zid, zn, city, tema, n, s, n2, s2 in con.execute(f"SELECT * FROM '{pq('ouro', 'painel_zona')}' ORDER BY 1, 5 DESC").fetchall():
            d = painel.setdefault(zid, {"_id": zid, "name": zn, "city": city, "schema_version": 1, "topics": []})
            d["topics"].append({"topic": tema, "reviews": n, "avg_sentiment": s,
                                "reviews_incl_suspect": n2, "avg_sentiment_incl_suspect": s2})

    with cronometro(t, "carregar_mongodb"):
        for nome in ("alojamentos", "avaliacoes", "painel_zona"):
            db[nome].drop()                     # carga idempotente: correr duas vezes dá o mesmo resultado
        em_lotes(db.alojamentos, alojamentos)
        em_lotes(db.avaliacoes, avaliacoes)
        em_lotes(db.painel_zona, list(painel.values()))

    with cronometro(t, "criar_indices"):
        db.avaliacoes.create_index([("listing_id", 1), ("created_at", -1)])   # página do alojamento sem Subset
        db.avaliacoes.create_index([("zone_id", 1), ("created_at", -1)])      # painel calculado na leitura
        db.alojamentos.create_index([("zone.zone_id", 1)])

    res = {"documentos": {"alojamentos": len(alojamentos), "avaliacoes": len(avaliacoes), "painel_zona": len(painel)},
           "hora_preco_servida": hora_atual, "tempos_s": t, "mock": mock}
    guardar("p4_serving.json", res)
    print(f"MongoDB{' (mock)' if mock else ''}: {res['documentos']} em {sum(t.values()):.1f}s")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    correr(ap.parse_args().mock)
