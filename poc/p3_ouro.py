#!/usr/bin/env python3
"""Passo 3 — PRATA -> OURO.

Produz:
  avaliacoes_enriquecidas  idioma detetado, sentimento (léxico), temas, sinais de avaliação falsa
  procura_hora             pesquisas e reservas por zona e hora
  preco_sugerido           preço por alojamento e hora (job horário)
  painel_zona              temas e sentimento por zona, sem e com as avaliações suspeitas

Uso: python p3_ouro.py
"""
from comum import camada, cronometro, escrever_atomico, guardar, ligar, pq
from lexico import tabelas_sql

# parâmetros do preço (hipóteses do grupo, a justificar no relatório)
SENSIBILIDADE = 0.15        # +15% de preço por cada +100% de procura face à véspera
LIMITES = (0.80, 1.50)      # guardrail: o preço sugerido fica entre 80% e 150% do preço base
EVENTO_MIN_PESSOAS = 10000  # evento "grande" na cidade nas 48 h seguintes
BONUS_EVENTO = 1.10
PESO_OCUPACAO = 0.20        # ajuste pela ocupação da zona nos 7 dias seguintes
OCUPACAO_REF = 0.55
LIMIAR_SUSPEITA = 2         # nº mínimo de sinais para marcar uma avaliação como suspeita


def valores(linhas):
    def q(v):
        return str(v) if isinstance(v, int) else "'" + str(v).replace("'", "''") + "'"
    return ", ".join("(" + ", ".join(q(v) for v in l) + ")" for l in linhas)


def correr():
    con = ligar()
    camada("ouro")
    t = {}
    stop, pol, neg, temas = tabelas_sql()
    con.execute(f"CREATE TEMP TABLE stop(l VARCHAR, w VARCHAR); INSERT INTO stop VALUES {valores(stop)}")
    con.execute(f"CREATE TEMP TABLE pol(l VARCHAR, w VARCHAR, v INT); INSERT INTO pol VALUES {valores(pol)}")
    con.execute(f"CREATE TEMP TABLE negacao(l VARCHAR, w VARCHAR); INSERT INTO negacao VALUES {valores(neg)}")
    con.execute(f"CREATE TEMP TABLE temas(tema VARCHAR, w VARCHAR); INSERT INTO temas VALUES {valores(temas)}")

    # ------------------------------------------------ texto: tokens, idioma, sentimento, temas
    with cronometro(t, "nlp_lexico"):
        con.execute(f"""CREATE TEMP TABLE tok AS
            SELECT review_id, unnest(range(1, len(ws) + 1)) AS pos, unnest(ws) AS w
            FROM (SELECT review_id, string_split(trim(regexp_replace(lower(texto), '[^a-zß-ÿ]+', ' ', 'g')), ' ') AS ws
                  FROM '{pq("prata", "avaliacoes")}')""")
        con.execute(f"""CREATE TEMP TABLE idioma AS
            SELECT a.review_id, coalesce(d.lang_det, a.lang_declarado) AS lang_det
            FROM '{pq("prata", "avaliacoes")}' a
            LEFT JOIN (SELECT review_id, arg_max(l, c) AS lang_det
                       FROM (SELECT t.review_id, s.l, count(*) + CASE s.l WHEN 'pt' THEN 0.1 ELSE 0 END AS c
                             FROM tok t JOIN stop s USING (w) GROUP BY 1, 2) GROUP BY 1) d USING (review_id)""")
        con.execute("""CREATE TEMP TABLE sentimento AS
            SELECT t.review_id,
                   sum(CASE WHEN n.w IS NOT NULL AND p.v > 0 THEN -1 ELSE p.v END) AS score
            FROM tok t JOIN idioma i USING (review_id)
            JOIN pol p ON p.l = i.lang_det AND p.w = t.w
            LEFT JOIN tok anterior ON anterior.review_id = t.review_id AND anterior.pos = t.pos - 1
            LEFT JOIN negacao n ON n.l = i.lang_det AND n.w = anterior.w
            GROUP BY 1""")
        con.execute("""CREATE TEMP TABLE temas_rev AS
            SELECT review_id, list(DISTINCT tema ORDER BY tema) AS temas FROM tok JOIN temas USING (w) GROUP BY 1""")

    # ------------------------------------------------ sinais de avaliação falsa (métricas simples)
    with cronometro(t, "falsas"):
        con.execute(f"""CREATE TEMP TABLE sinais AS
            WITH a AS (SELECT *, regexp_replace(lower(texto), '[^a-zß-ÿ]', '', 'g') AS norm,
                              date_trunc('hour', created_at) AS hora, date_trunc('day', created_at) AS dia
                       FROM '{pq("prata", "avaliacoes")}'),
                 rep AS (SELECT norm, count(*) AS n FROM a GROUP BY 1),
                 raj AS (SELECT listing_id, hora, count(*) AS n FROM a GROUP BY 1, 2),
                 multi AS (SELECT guest_pid, dia, count(DISTINCT listing_id) AS n FROM a GROUP BY 1, 2)
            SELECT a.review_id,
                   (a.booking_id IS NULL) AS sem_reserva,
                   (rep.n >= 5) AS texto_repetido,
                   (raj.n >= 5) AS rajada,
                   (multi.n >= 3) AS conta_multi
            FROM a JOIN rep USING (norm) JOIN raj USING (listing_id, hora) JOIN multi USING (guest_pid, dia)""")

    with cronometro(t, "escrever_avaliacoes"):
        escrever_atomico(con, f"""
            SELECT a.review_id, a.listing_id, a.zone_id, a.guest_pid, a.booking_id, a.rating, a.texto, a.created_at,
                   a.origem, a.lang_declarado, i.lang_det,
                   coalesce(s.score, 0) AS score_sentimento,
                   CASE WHEN coalesce(s.score, 0) > 0 THEN 'pos' WHEN s.score < 0 THEN 'neg' ELSE 'neu' END AS sentimento,
                   CASE WHEN a.rating >= 4 THEN 'pos' WHEN a.rating = 3 THEN 'neu' ELSE 'neg' END AS sentimento_pela_nota,
                   coalesce(tr.temas, []) AS temas,
                   g.sem_reserva, g.texto_repetido, g.rajada, g.conta_multi,
                   (g.sem_reserva::INT + g.texto_repetido::INT + g.rajada::INT + g.conta_multi::INT) AS n_sinais,
                   (g.sem_reserva::INT + g.texto_repetido::INT + g.rajada::INT + g.conta_multi::INT) >= {LIMIAR_SUSPEITA} AS suspeita
            FROM '{pq("prata", "avaliacoes")}' a JOIN idioma i USING (review_id)
            LEFT JOIN sentimento s USING (review_id) LEFT JOIN temas_rev tr USING (review_id)
            JOIN sinais g USING (review_id)""", pq("ouro", "avaliacoes_enriquecidas"))

    # ------------------------------------------------ procura por zona e hora (só o período em tempo real)
    with cronometro(t, "procura_hora"):
        escrever_atomico(con, f"""
            WITH z AS (SELECT DISTINCT zone_id, city FROM '{pq("prata", "alojamentos")}'),
                 limites AS (SELECT date_trunc('hour', min(event_ts)) AS h0, date_trunc('hour', max(event_ts)) AS h1
                             FROM '{pq("prata", "pesquisas")}'),
                 horas AS (SELECT unnest(generate_series(h0, h1, INTERVAL 1 HOUR)) AS hora FROM limites),
                 p AS (SELECT zone_id, date_trunc('hour', event_ts) AS hora, count(*) AS pesquisas
                       FROM '{pq("prata", "pesquisas")}' GROUP BY 1, 2),
                 r AS (SELECT zone_id, date_trunc('hour', event_ts) AS hora, count(*) AS reservas
                       FROM '{pq("prata", "reservas")}' GROUP BY 1, 2)
            SELECT z.zone_id, z.city, h.hora, coalesce(p.pesquisas, 0) AS pesquisas, coalesce(r.reservas, 0) AS reservas
            FROM z CROSS JOIN horas h LEFT JOIN p USING (zone_id, hora) LEFT JOIN r USING (zone_id, hora)""",
            pq("ouro", "procura_hora"))

    # ------------------------------------------------ preço sugerido (job horário)
    # O preço da hora H só usa dados até H (pesquisas da hora H-1 e o que a agenda já anunciou).
    with cronometro(t, "preco_sugerido"):
        con.execute(f"""CREATE TEMP TABLE fatores AS
            WITH ph AS (SELECT * FROM '{pq("ouro", "procura_hora")}'),
                 base AS (SELECT a.zone_id, a.city, a.hora + INTERVAL 1 HOUR AS hora_preco, a.pesquisas,
                                 b.pesquisas AS pesquisas_vespera
                          FROM ph a LEFT JOIN ph b ON b.zone_id = a.zone_id AND b.hora = a.hora - INTERVAL 24 HOUR),
                 ev AS (SELECT b.zone_id, b.hora_preco, max(g.assistencia) AS maior_evento
                        FROM base b JOIN '{pq("prata", "agenda")}' g
                          ON g.city = b.city AND g.poll_ts <= b.hora_preco
                         AND g.inicio BETWEEN b.hora_preco AND b.hora_preco + INTERVAL 48 HOUR
                        GROUP BY 1, 2),
                 oc AS (SELECT l.zone_id, d.snapshot_ts, avg(CASE WHEN d.disponivel THEN 0 ELSE 1 END) AS ocupacao
                        FROM '{pq("prata", "disponibilidade")}' d JOIN '{pq("prata", "alojamentos")}' l USING (listing_id)
                        WHERE d.data < CAST(d.snapshot_ts AS DATE) + 7 GROUP BY 1, 2)
            SELECT b.zone_id, b.hora_preco, b.pesquisas, b.pesquisas_vespera,
                   (b.pesquisas_vespera IS NULL OR b.pesquisas_vespera = 0) AS fallback,
                   CASE WHEN b.pesquisas_vespera > 0 THEN b.pesquisas / b.pesquisas_vespera ELSE 1 END AS racio_procura,
                   coalesce(ev.maior_evento, 0) AS maior_evento_48h,
                   (SELECT o.ocupacao FROM oc o WHERE o.zone_id = b.zone_id AND o.snapshot_ts <= b.hora_preco
                    ORDER BY o.snapshot_ts DESC LIMIT 1) AS ocupacao_7d
            FROM base b LEFT JOIN ev USING (zone_id, hora_preco)""")
        escrever_atomico(con, f"""
            WITH f AS (SELECT *, least({LIMITES[1]}, greatest({LIMITES[0]},
                              (1 + {SENSIBILIDADE} * (racio_procura - 1)) *
                              (1 + {PESO_OCUPACAO} * (coalesce(ocupacao_7d, {OCUPACAO_REF}) - {OCUPACAO_REF})) *
                              CASE WHEN maior_evento_48h >= {EVENTO_MIN_PESSOAS} THEN {BONUS_EVENTO} ELSE 1 END)) AS fator,
                              (1 + {SENSIBILIDADE} * (racio_procura - 1)) *
                              (1 + {PESO_OCUPACAO} * (coalesce(ocupacao_7d, {OCUPACAO_REF}) - {OCUPACAO_REF})) *
                              CASE WHEN maior_evento_48h >= {EVENTO_MIN_PESSOAS} THEN {BONUS_EVENTO} ELSE 1 END AS fator_bruto
                       FROM fatores)
            SELECT l.listing_id, l.zone_id, l.city, f.hora_preco, l.base_price,
                   round(l.base_price * f.fator, 2) AS preco_sugerido, round(f.fator, 4) AS fator,
                   f.fator_bruto NOT BETWEEN {LIMITES[0]} AND {LIMITES[1]} AS cortado_pelo_limite,
                   round(f.racio_procura, 3) AS racio_procura, f.maior_evento_48h, round(f.ocupacao_7d, 3) AS ocupacao_7d,
                   f.fallback, 'regras-v1' AS modelo_versao
            FROM '{pq("prata", "alojamentos")}' l JOIN f USING (zone_id)""", pq("ouro", "preco_sugerido"))

    # ------------------------------------------------ painel por zona
    with cronometro(t, "painel_zona"):
        escrever_atomico(con, f"""
            WITH a AS (SELECT zone_id, unnest(CASE WHEN len(temas) = 0 THEN ['geral'] ELSE temas END) AS tema,
                              CASE sentimento WHEN 'pos' THEN 1 WHEN 'neg' THEN -1 ELSE 0 END AS s, suspeita
                       FROM '{pq("ouro", "avaliacoes_enriquecidas")}')
            SELECT a.zone_id, z.zone_name, z.city, tema,
                   count(*) FILTER (WHERE NOT suspeita) AS n_avaliacoes,
                   round(avg(s) FILTER (WHERE NOT suspeita), 4) AS sentimento_medio,
                   count(*) AS n_com_suspeitas,
                   round(avg(s), 4) AS sentimento_com_suspeitas
            FROM a JOIN (SELECT DISTINCT zone_id, zone_name, city FROM '{pq("prata", "alojamentos")}') z USING (zone_id)
            GROUP BY ALL""", pq("ouro", "painel_zona"))

    n = {tab: con.execute(f"SELECT count(*) FROM '{pq('ouro', tab)}'").fetchone()[0]
         for tab in ["avaliacoes_enriquecidas", "procura_hora", "preco_sugerido", "painel_zona"]}
    s = con.execute(f"SELECT count(*) FILTER (WHERE suspeita), count(*) FROM '{pq('ouro', 'avaliacoes_enriquecidas')}'").fetchone()
    res = {"tempos_s": t, "linhas": n, "suspeitas": s[0], "avaliacoes": s[1],
           "parametros_preco": {"sensibilidade": SENSIBILIDADE, "limites": LIMITES, "evento_min_pessoas": EVENTO_MIN_PESSOAS,
                                "bonus_evento": BONUS_EVENTO, "peso_ocupacao": PESO_OCUPACAO}}
    guardar("p3_ouro.json", res)
    print(f"Ouro: {n} · suspeitas {s[0]:,}/{s[1]:,} · {sum(t.values()):.1f}s")
    return res


if __name__ == "__main__":
    correr()
