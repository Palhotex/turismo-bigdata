#!/usr/bin/env python3
"""Passo 2 — BRONZE -> PRATA (validação, deduplicação, pseudonimização) + QUARENTENA.

Para cada fonte:
  1. interpreta o JSON bruto;
  2. aplica um contrato de dados (campos obrigatórios, domínios, datas);
  3. remove duplicados pelo identificador (fica a primeira chegada);
  4. pseudonimiza identificadores pessoais e retira nome, email, telefone, IP e pagamento;
  5. o que falha o contrato vai para a quarentena, com o motivo — nunca para a prata.

A agenda externa só é entendida no formato v1 (o único documentado). O formato v2,
que aparece sem aviso a meio, vai para a quarentena até o parser ser corrigido:
    python p2_prata.py --aceitar-v2     # parser corrigido: reprocessa a partir do bronze

Simular uma falha a meio (cenário de falha de componente):
    python p2_prata.py --falhar-apos pesquisas
"""
import argparse

from comum import CHAVE_PSEUDO, camada, cronometro, escrever_atomico, guardar, ligar, pq

WATERMARK_MIN = 15   # tolerância a eventos atrasados na agregação horária

PSEUDO = f"sha256('{CHAVE_PSEUDO}' || {{}})"   # hash com chave secreta (simplificação de HMAC)
RE_EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
RE_TELEF = r"\+[0-9]{1,3}( ?[0-9]{3}){3}"
TS = "try_strptime({}, '%Y-%m-%dT%H:%M:%SZ')"


def separar(con, nome, sql_parse, chave, contrato, colunas_prata, ordem="seq_chegada"):
    """Cria a vista parseada, aplica o contrato e a deduplicação e escreve prata + quarentena."""
    casos = " ".join(f"WHEN {cond} THEN '{motivo}'" for cond, motivo in contrato)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE t_{nome} AS
        WITH p AS ({sql_parse}),
             v AS (SELECT *, CASE {casos} ELSE NULL END AS motivo,
                          row_number() OVER (PARTITION BY {chave} ORDER BY {ordem}) AS ocorrencia
                   FROM p)
        SELECT * FROM v""")
    escrever_atomico(con, f"SELECT {colunas_prata} FROM t_{nome} WHERE motivo IS NULL AND ocorrencia = 1",
                     pq("prata", nome))
    escrever_atomico(con, f"SELECT seq_chegada, motivo, raw FROM t_{nome} WHERE motivo IS NOT NULL AND ocorrencia = 1",
                     pq("quarentena", nome))
    q = dict(con.execute(f"SELECT motivo, count(*) FROM t_{nome} WHERE motivo IS NOT NULL AND ocorrencia = 1 GROUP BY 1").fetchall())
    total, dups, validos = con.execute(f"""SELECT count(*), count(*) FILTER (WHERE ocorrencia > 1),
        count(*) FILTER (WHERE motivo IS NULL AND ocorrencia = 1) FROM t_{nome}""").fetchone()
    return {"linhas_bronze": total, "duplicados_removidos": dups, "quarentena": q,
            "quarentena_total": sum(q.values()), "validos_prata": validos,
            "taxa_validos": round(validos / max(1, total - dups), 4)}


def correr(aceitar_v2=False, falhar_apos=None):
    con = ligar()
    for c in ("prata", "quarentena"):
        camada(c)
    qualidade, tempos = {}, {}

    def passo(nome, f):
        with cronometro(tempos, nome):
            qualidade[nome] = f()
        if falhar_apos == nome:
            raise RuntimeError(f"Falha simulada depois de '{nome}' (cenário de falha de componente)")

    # ---------------- alojamentos (referência)
    passo("alojamentos", lambda: separar(con, "alojamentos", f"""
        SELECT seq_chegada, raw, raw->>'$.listing_id' AS listing_id, raw->>'$.city' AS city,
               raw->>'$.zone_id' AS zone_id, raw->>'$.zone_name' AS zone_name, raw->>'$.type' AS tipo,
               try_cast(raw->>'$.capacity' AS INT) AS capacity, try_cast(raw->>'$.base_price' AS DOUBLE) AS base_price,
               {PSEUDO.format("(raw->>'$.host.host_id')")} AS host_pid
        FROM '{pq("bronze", "alojamentos")}'""", "listing_id",
        [("listing_id IS NULL", "sem_id"), ("zone_id IS NULL", "sem_zona"),
         ("base_price IS NULL OR base_price <= 0", "preco_invalido")],
        "listing_id, city, zone_id, zone_name, tipo, capacity, base_price, host_pid"))
    con.execute(f"CREATE OR REPLACE TEMP TABLE zonas AS SELECT DISTINCT zone_id, zone_name, city FROM '{pq('prata', 'alojamentos')}'")
    con.execute(f"CREATE OR REPLACE TEMP TABLE ids_aloj AS SELECT listing_id FROM '{pq('prata', 'alojamentos')}'")

    # ---------------- avaliações (histórico + stream)
    def avaliacoes():
        texto = "raw->>'$.text'"
        mascarado = f"regexp_replace(regexp_replace({texto}, '{RE_EMAIL}', '[EMAIL]', 'g'), '{RE_TELEF}', '[TELEFONE]', 'g')"
        partes = []
        for i, f in enumerate(["avaliacoes_historico", "avaliacoes_stream"]):
            partes.append(f"""
              SELECT seq_chegada + {i} * 1000000000 AS seq_chegada, raw, '{f.split('_')[1]}' AS origem,
                     raw->>'$.review_id' AS review_id, raw->>'$.listing_id' AS listing_id, raw->>'$.zone_id' AS zone_id,
                     {PSEUDO.format("(raw->>'$.guest_id')")} AS guest_pid, raw->>'$.booking_id' AS booking_id,
                     raw->>'$.lang' AS lang_declarado, try_cast(raw->>'$.rating' AS INT) AS rating,
                     {mascarado} AS texto, ({texto} IS DISTINCT FROM {mascarado}) AS pii_mascarada,
                     {TS.format("raw->>'$.created_at'")} AS created_at
              FROM '{pq("bronze", f)}'""")
        return separar(con, "avaliacoes", " UNION ALL ".join(partes), "review_id",
            [("review_id IS NULL", "sem_id"), ("listing_id IS NULL", "sem_listing_id"),
             ("listing_id NOT IN (SELECT listing_id FROM ids_aloj)", "listing_desconhecido"),
             ("texto IS NULL", "sem_texto"), ("rating IS NULL", "sem_rating"),
             ("rating NOT BETWEEN 1 AND 5", "rating_invalido"),
             ("created_at IS NULL", "data_invalida"), ("created_at > TIMESTAMP '2030-01-01'", "data_futura")],
            "review_id, listing_id, zone_id, guest_pid, booking_id, lang_declarado, rating, texto, pii_mascarada, created_at, origem")
    passo("avaliacoes", avaliacoes)

    # ---------------- pesquisas
    def pesquisas():
        r = separar(con, "pesquisas", f"""
            SELECT seq_chegada, raw, raw->>'$.event_id' AS event_id, {TS.format("raw->>'$.event_ts'")} AS event_ts,
                   {PSEUDO.format("(raw->>'$.session_id')")} AS session_pid, raw->>'$.city' AS city,
                   raw->>'$.zone_id' AS zone_id, try_cast(raw->>'$.checkin' AS DATE) AS checkin,
                   try_cast(raw->>'$.checkout' AS DATE) AS checkout, try_cast(raw->>'$.guests' AS INT) AS guests
            FROM '{pq("bronze", "pesquisas")}'""", "event_id",
            [("event_id IS NULL", "sem_id"), ("event_ts IS NULL", "data_invalida"),
             ("event_ts > TIMESTAMP '2030-01-01'", "data_futura"), ("zone_id IS NULL", "sem_zona"),
             ("zone_id NOT IN (SELECT zone_id FROM zonas)", "zona_desconhecida"),
             ("checkin IS NULL", "sem_checkin"), ("checkout <= checkin", "datas_invertidas"),
             ("guests NOT BETWEEN 1 AND 16 OR guests IS NULL", "hospedes_invalido")],
            "event_id, event_ts, session_pid, zone_id, checkin, checkout, guests, seq_chegada")
        # eventos atrasados: chegam depois de outro evento mais recente que eles + watermark
        r["chegadas_tardias_watermark"] = con.execute(f"""
            SELECT count(*) FROM (SELECT event_ts, max(event_ts) OVER (ORDER BY seq_chegada
                   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS visto FROM '{pq("prata", "pesquisas")}')
            WHERE event_ts < visto - INTERVAL {WATERMARK_MIN} MINUTE""").fetchone()[0]
        return r
    passo("pesquisas", pesquisas)

    # ---------------- reservas (sem nome, email, telefone nem pagamento na prata)
    passo("reservas", lambda: separar(con, "reservas", f"""
        SELECT seq_chegada, raw, raw->>'$.booking_id' AS booking_id, {TS.format("raw->>'$.event_ts'")} AS event_ts,
               raw->>'$.listing_id' AS listing_id, raw->>'$.zone_id' AS zone_id,
               {PSEUDO.format("(raw->>'$.guest.guest_id')")} AS guest_pid,
               try_cast(raw->>'$.checkin' AS DATE) AS checkin, try_cast(raw->>'$.checkout' AS DATE) AS checkout,
               try_cast(raw->>'$.guests' AS INT) AS guests, try_cast(raw->>'$.price_paid' AS DOUBLE) AS price_paid,
               raw->>'$.status' AS status
        FROM '{pq("bronze", "reservas")}'""", "booking_id",
        [("booking_id IS NULL", "sem_id"), ("event_ts IS NULL", "data_invalida"),
         ("listing_id IS NULL", "sem_listing_id"), ("listing_id NOT IN (SELECT listing_id FROM ids_aloj)", "listing_desconhecido"),
         ("price_paid IS NULL", "sem_preco"), ("price_paid <= 0", "preco_invalido"),
         ("checkin IS NULL", "sem_checkin"), ("checkout <= checkin", "datas_invertidas"),
         ("guests NOT BETWEEN 1 AND 16 OR guests IS NULL", "hospedes_invalido")],
        "booking_id, event_ts, listing_id, zone_id, guest_pid, checkin, checkout, guests, price_paid, status"))

    # ---------------- disponibilidade
    passo("disponibilidade", lambda: separar(con, "disponibilidade", f"""
        SELECT seq_chegada, raw, raw->>'$.listing_id' AS listing_id, try_cast(raw->>'$.date' AS DATE) AS data,
               try_cast(raw->>'$.available' AS BOOLEAN) AS disponivel, try_cast(raw->>'$.price' AS DOUBLE) AS preco,
               {TS.format("raw->>'$.snapshot_ts'")} AS snapshot_ts,
               (raw->>'$.listing_id') || (raw->>'$.date') || (raw->>'$.snapshot_ts') AS chave
        FROM '{pq("bronze", "disponibilidade")}'""", "chave",
        [("listing_id IS NULL OR data IS NULL OR disponivel IS NULL", "campos_em_falta")],
        "listing_id, data, disponivel, preco, snapshot_ts"))

    # ---------------- agenda externa (v1 conhecido; v2 só com --aceitar-v2)
    def agenda():
        v1 = f"""
          SELECT p.seq_chegada, p.raw, 'v1' AS formato, {TS.format("p.raw->>'$.poll_ts'")} AS poll_ts,
                 e->>'$.id' AS event_id, e->>'$.city' AS city, e->>'$.zone' AS zone_id,
                 try_strptime((e->>'$.date') || ' ' || (e->>'$.start'), '%Y-%m-%d %H:%M') AS inicio,
                 try_strptime((e->>'$.date') || ' ' || (e->>'$.start'), '%Y-%m-%d %H:%M')
                   + to_hours(try_cast(e->>'$.duration_hours' AS INT)) AS fim,
                 try_cast(e->>'$.attendance' AS INT) AS assistencia
          FROM '{pq("bronze", "agenda_api")}' p, unnest(from_json(p.raw->'$.events', '["json"]')) AS u(e)
          WHERE json_exists(p.raw, '$.events')"""
        v2 = f"""
          SELECT p.seq_chegada, p.raw, 'v2' AS formato, to_timestamp(try_cast(p.raw->>'$.pollTimestamp' AS BIGINT))::TIMESTAMP,
                 e->>'$.eventId', e->>'$.location.city', e->>'$.location.zoneCode',
                 to_timestamp(try_cast(e->>'$.start_time' AS BIGINT))::TIMESTAMP,
                 to_timestamp(try_cast(e->>'$.end_time' AS BIGINT))::TIMESTAMP,
                 CAST(round(try_cast(replace(e->>'$.expected_attendance', 'k', '') AS DOUBLE) *
                      CASE WHEN (e->>'$.expected_attendance') LIKE '%k' THEN 1000 ELSE 1 END) AS INT)
          FROM '{pq("bronze", "agenda_api")}' p, unnest(from_json(p.raw->'$.data.items', '["json"]')) AS u(e)
          WHERE json_exists(p.raw, '$.data.items')"""
        # polls que não encaixam em nenhum formato conhecido (inclui v2 quando o parser não o conhece)
        desconhecido = f"""
          SELECT seq_chegada, raw, 'desconhecido', NULL::TIMESTAMP, NULL, NULL, NULL, NULL::TIMESTAMP, NULL::TIMESTAMP, NULL::INT
          FROM '{pq("bronze", "agenda_api")}'
          WHERE NOT json_exists(raw, '$.events') {"AND NOT json_exists(raw, '$.data.items')" if aceitar_v2 else ""}"""
        partes = [v1, desconhecido] + ([v2] if aceitar_v2 else [])
        r = separar(con, "agenda", " UNION ALL ".join(partes),
                    "coalesce(event_id, '') || coalesce(CAST(poll_ts AS VARCHAR), CAST(seq_chegada AS VARCHAR))",
                    [("formato = 'desconhecido'", "formato_desconhecido"), ("event_id IS NULL", "sem_id"),
                     ("inicio IS NULL", "data_invalida"), ("assistencia IS NULL", "assistencia_invalida")],
                    "formato, poll_ts, event_id, city, zone_id, inicio, fim, assistencia")
        r["polls_por_formato"] = dict(con.execute(f"""
            SELECT CASE WHEN json_exists(raw, '$.events') THEN 'v1' WHEN json_exists(raw, '$.data.items') THEN 'v2'
                   ELSE 'outro' END, count(*) FROM '{pq("bronze", "agenda_api")}' GROUP BY 1""").fetchall())
        r["parser_aceita_v2"] = aceitar_v2
        return r
    passo("agenda", agenda)

    guardar("p2_qualidade.json" if aceitar_v2 else "p2_qualidade_sem_v2.json", {"tempos_s": tempos, "qualidade": qualidade})
    for f, q in qualidade.items():
        print(f"  {f:16s} válidos {q['validos_prata']:>10,d}  dup {q['duplicados_removidos']:>7,d}  "
              f"quarentena {q['quarentena_total']:>7,d}  {q['quarentena'] or ''}")
    return {"tempos_s": tempos, "qualidade": qualidade}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--aceitar-v2", action="store_true", help="parser da agenda corrigido para o formato novo")
    ap.add_argument("--falhar-apos", help="simula uma falha depois desta fonte")
    a = ap.parse_args()
    correr(a.aceitar_v2, a.falhar_apos)
