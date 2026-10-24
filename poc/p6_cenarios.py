#!/usr/bin/env python3
"""Passo 6 — Avaliar os cenários contra a verdade do gerador.

Compara o que o pipeline produziu com as respostas certas (pasta verdade/ do gerador),
que nunca entraram no pipeline. Responde à pergunta "o sistema comportou-se bem?".

Uso: python p6_cenarios.py ../gerador/saida/escala_1_semente_42
"""
import sys
from pathlib import Path

from comum import guardar, ler_resultado, ligar, pq


def f1(p, r):
    return round(2 * p * r / (p + r), 3) if p + r else 0.0


def correr(pasta_dados):
    v = Path(pasta_dados) / "verdade"
    con = ligar()
    con.execute(f"CREATE TEMP VIEW verdade AS SELECT * FROM read_json_auto('{v / 'avaliacoes_verdade.jsonl'}', sample_size=-1)")
    con.execute(f"CREATE TEMP VIEW defeitos AS SELECT * FROM read_json_auto('{v / 'defeitos.jsonl'}', sample_size=-1)")
    con.execute(f"CREATE TEMP VIEW cenarios AS SELECT * FROM read_json_auto('{v / 'cenarios.jsonl'}', union_by_name=true)")
    av = pq("ouro", "avaliacoes_enriquecidas")
    res = {}

    # 1. avaliações falsas em massa
    vp, fp, fn, camp_total, camp_apanhadas = con.execute(f"""
        SELECT count(*) FILTER (a.suspeita AND v.falsa), count(*) FILTER (a.suspeita AND NOT v.falsa),
               count(*) FILTER (NOT a.suspeita AND v.falsa),
               count(*) FILTER (v.campanha IS NOT NULL), count(*) FILTER (v.campanha IS NOT NULL AND a.suspeita)
        FROM '{av}' a JOIN verdade v USING (review_id)""").fetchone()
    prec, rec = vp / (vp + fp) if vp + fp else 0, vp / (vp + fn) if vp + fn else 0
    efeito = con.execute(f"""
        SELECT round(avg(rating) FILTER (WHERE NOT suspeita), 2), round(avg(rating), 2)
        FROM '{av}' WHERE listing_id IN (SELECT unnest(alojamentos_alvo) FROM cenarios WHERE cenario = 'campanha_falsas')
    """).fetchone()
    res["avaliacoes_falsas"] = {
        "precisao": round(prec, 3), "recall": round(rec, 3), "f1": f1(prec, rec),
        "verdadeiros_positivos": vp, "falsos_positivos": fp, "falsas_nao_detetadas": fn,
        "recall_campanha": round(camp_apanhadas / camp_total, 3) if camp_total else None,
        "nota_media_alvos_sem_suspeitas": efeito[0], "nota_media_alvos_com_suspeitas": efeito[1]}

    # 2. sentimento (só genuínas): texto vs. nota
    linhas = con.execute(f"""
        SELECT v.sentimento_real, a.sentimento, a.sentimento_pela_nota
        FROM '{av}' a JOIN verdade v USING (review_id) WHERE NOT v.falsa""").fetchall()
    def metricas(idx):
        acc = sum(l[0] == l[idx] for l in linhas) / len(linhas)
        f1s = []
        for c in ("pos", "neu", "neg"):
            tp = sum(l[0] == c and l[idx] == c for l in linhas)
            p = tp / max(1, sum(l[idx] == c for l in linhas))
            r = tp / max(1, sum(l[0] == c for l in linhas))
            f1s.append(f1(p, r))
        return {"exatidao": round(acc, 3), "f1_macro": round(sum(f1s) / 3, 3)}
    res["sentimento"] = {"pelo_texto_lexico": metricas(1), "so_pela_nota": metricas(2), "n": len(linhas)}

    # 3. idioma
    res["idioma"] = dict(zip(["detetado_certo", "declarado_certo"], [round(x, 3) for x in con.execute(f"""
        SELECT avg((a.lang_det = v.idioma_real)::int), avg((a.lang_declarado = v.idioma_real)::int)
        FROM '{av}' a JOIN verdade v USING (review_id)""").fetchone()]))

    # 4. qualidade à entrada: defeitos injetados vs. apanhados
    q = ler_resultado("p2_qualidade.json")["qualidade"]
    injetados = dict(con.execute("""
        SELECT ficheiro || ':' || defeito, count(*) FROM defeitos GROUP BY 1""").fetchall())
    def inj(fich, *tipos):
        return sum(injetados.get(f"{fich}:{t}", 0) for t in tipos)
    res["qualidade"] = {
        nome: {"duplicados_injetados": inj(f, "duplicado") if nome != "avaliacoes" else
                   inj("avaliacoes_historico.jsonl", "duplicado") + inj("avaliacoes_stream.jsonl", "duplicado"),
               "duplicados_removidos": q[nome]["duplicados_removidos"],
               "invalidos_injetados": inj(f, "campo_em_falta", "valor_impossivel") if nome != "avaliacoes" else
                   sum(inj(x, "campo_em_falta", "valor_impossivel") for x in ("avaliacoes_historico.jsonl", "avaliacoes_stream.jsonl")),
               "enviados_para_quarentena": q[nome]["quarentena_total"]}
        for nome, f in [("pesquisas", "pesquisas.jsonl"), ("reservas", "reservas.jsonl"), ("avaliacoes", None)]}
    res["qualidade"]["nota"] = ("Campos em falta que não são obrigatórios (ex.: lang) não vão para a "
                                "quarentena, por isso 'enviados' pode ser menor que 'injetados'.")

    # 5. fonte que muda de formato
    sem_v2 = ler_resultado("p2_qualidade_sem_v2.json")
    agenda = pq("prata", "agenda")
    pico_visto = con.execute(f"SELECT count(*) > 0 FROM '{agenda}' WHERE event_id = 'EV-PICO'").fetchone()[0]
    res["mudanca_formato"] = {
        "polls_v2_postos_em_quarentena_antes_da_correcao": (sem_v2 or {}).get("qualidade", {}).get("agenda", {}).get("quarentena", {}),
        "registos_mal_formados_na_prata": con.execute(f"SELECT count(*) FROM '{agenda}' WHERE inicio IS NULL OR zone_id IS NULL").fetchone()[0],
        "grande_evento_visivel_apos_reprocessamento": bool(pico_visto)}

    # 6. evento que dispara a procura
    cidade, janela = con.execute("SELECT cidade, janela_procura FROM cenarios WHERE cenario = 'evento_pico'").fetchone()
    ini = str(janela[0]).replace("T", " ").rstrip("Z")[:19]   # o leitor JSON pode já devolver datetime
    ps, ph = pq("ouro", "preco_sugerido"), pq("ouro", "procura_hora")
    antes, durante = con.execute(f"""
        SELECT round(avg(fator) FILTER (WHERE hora_preco < TIMESTAMP '{ini}'), 3),
               round(avg(fator) FILTER (WHERE hora_preco >= TIMESTAMP '{ini}'), 3)
        FROM '{ps}' WHERE city = '{cidade}'""").fetchone()
    reacao = con.execute(f"""
        SELECT min(hora_preco) FROM (SELECT hora_preco, avg(fator) f FROM '{ps}'
        WHERE city = '{cidade}' AND hora_preco >= TIMESTAMP '{ini}' GROUP BY 1) WHERE f > {antes} * 1.05""").fetchone()[0]
    proc = con.execute(f"""
        SELECT round(avg(pesquisas) FILTER (WHERE hora < TIMESTAMP '{ini}')), round(avg(pesquisas) FILTER (WHERE hora >= TIMESTAMP '{ini}'))
        FROM (SELECT hora, sum(pesquisas) pesquisas FROM '{ph}' WHERE city = '{cidade}' GROUP BY 1)""").fetchone()
    cortados = con.execute(f"SELECT round(avg(cortado_pelo_limite::int), 3) FROM '{ps}' WHERE city = '{cidade}' AND hora_preco >= TIMESTAMP '{ini}'").fetchone()[0]
    res["evento_pico"] = {
        "cidade": cidade, "inicio_janela": ini,
        "pesquisas_por_hora_antes": proc[0], "pesquisas_por_hora_durante": proc[1],
        "fator_preco_medio_antes": antes, "fator_preco_medio_durante": durante,
        "primeira_hora_com_preco_ajustado_5pct": str(reacao) if reacao else None,
        "fracao_precos_cortados_pelo_limite": cortados}

    guardar("p6_cenarios.json", res)
    fa, s, e = res["avaliacoes_falsas"], res["sentimento"], res["evento_pico"]
    print(f"Falsas: precisão {fa['precisao']}, recall {fa['recall']} (campanha {fa['recall_campanha']})")
    print(f"Sentimento: texto F1 {s['pelo_texto_lexico']['f1_macro']} vs. só nota {s['so_pela_nota']['f1_macro']}")
    print(f"Mudança de formato: evento visível após correção = {res['mudanca_formato']['grande_evento_visivel_apos_reprocessamento']}")
    print(f"Pico ({cidade}): pesquisas/h {e['pesquisas_por_hora_antes']} -> {e['pesquisas_por_hora_durante']}; "
          f"fator de preço {e['fator_preco_medio_antes']} -> {e['fator_preco_medio_durante']}; "
          f"reagiu às {e['primeira_hora_com_preco_ajustado_5pct']}")
    return res


if __name__ == "__main__":
    correr(sys.argv[1])
