#!/usr/bin/env python3
"""Gerador de dados sintéticos — UC de Big Data, Enunciado 7 (Turismo).

Gera alojamentos, avaliações multilíngues (com sentimento conhecido e campanhas
de avaliações falsas), pesquisas e reservas em tempo real com picos de procura,
disponibilidade e uma API externa de eventos que muda de formato a meio.

Defeitos injetados: duplicados, eventos fora de ordem, valores impossíveis e
campos em falta. A "verdade" (rótulos e defeitos) é escrita à parte, em
saida/.../verdade/, para medir a deteção.

Uso:
    python gerador.py                      # escala 1×, config.json
    python gerador.py --escala 10
    python gerador.py --escala 100 --dias 1
    python gerador.py --semente 7 --saida dados/
Só usa a biblioteca padrão do Python (>= 3.9).
"""
import argparse
import bisect
import hashlib
import heapq
import json
import math
import platform
import random
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from frases import APELIDOS, ASPECTOS, FRASES, NOMES

VERSAO = "1.0.0"


# ---------------------------------------------------------------- utilitários
def iso(ts):
    """Segundos epoch -> ISO 8601 UTC com segundos."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dia(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def poisson(rng, lam):
    """Amostra de Poisson; aproximação normal para lambda grande."""
    if lam <= 0:
        return 0
    if lam < 30:
        limite, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= limite:
                return k
            k += 1
    return max(0, round(rng.gauss(lam, math.sqrt(lam))))


def sem_acentos(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def escolher_pesado(rng, itens, cum):
    """Escolha ponderada com pesos acumulados (bisect, O(log n))."""
    return itens[bisect.bisect_left(cum, rng.random() * cum[-1])]


def acumular(pesos):
    cum, s = [], 0.0
    for p in pesos:
        s += p
        cum.append(s)
    return cum


def hospede(i):
    """Hóspede fictício determinístico a partir do índice (mesmo nome em todos os ficheiros)."""
    nome = NOMES[i % len(NOMES)]
    apelido = APELIDOS[(i // len(NOMES)) % len(APELIDOS)]
    # domínio example.com (RFC 2606) e prefixo +351 999 (não atribuído) -> fictícios
    return {
        "guest_id": f"G{i:07d}",
        "name": f"{nome} {apelido}",
        "email": f"{sem_acentos(nome)}.{sem_acentos(apelido)}{i}@example.com",
        "phone": f"+351 999 {i % 1000:03d} {(i // 1000) % 1000:03d}",
    }


# ---------------------------------------------------------------- escritores
class Saida:
    """Gere os ficheiros JSONL, contagens e o registo de defeitos."""

    def __init__(self, pasta):
        self.pasta = Path(pasta)
        (self.pasta / "verdade").mkdir(parents=True, exist_ok=True)
        self.fich = {}
        self.contagem = {}
        self.defeitos = {}

    def escrever(self, nome, registo):
        if nome not in self.fich:
            self.fich[nome] = open(self.pasta / nome, "w", encoding="utf-8")
            self.contagem[nome] = 0
        self.fich[nome].write(json.dumps(registo, ensure_ascii=False, sort_keys=True) + "\n")
        self.contagem[nome] += 1

    def defeito(self, ficheiro, rid, tipo, detalhe=""):
        self.escrever("verdade/defeitos.jsonl",
                      {"ficheiro": ficheiro, "id": rid, "defeito": tipo, "detalhe": detalhe})
        chave = f"{ficheiro}:{tipo}"
        self.defeitos[chave] = self.defeitos.get(chave, 0) + 1

    def fechar(self):
        for f in self.fich.values():
            f.close()


# ---------------------------------------------------------------- defeitos
EM_FALTA = {
    "pesquisas.jsonl": ["zone_id", "checkin", "city"],
    "reservas.jsonl": ["listing_id", "price_paid", "checkin"],
    "avaliacoes_stream.jsonl": ["text", "lang", "rating", "listing_id"],
    "avaliacoes_historico.jsonl": ["text", "lang", "rating", "listing_id"],
}


def tornar_impossivel(rng, ficheiro, r):
    """Altera um campo para um valor impossível; devolve a descrição."""
    if ficheiro == "pesquisas.jsonl":
        if rng.random() < 0.5:
            r["guests"] = rng.choice([0, 99])
            return f"guests={r['guests']}"
        r["checkin"], r["checkout"] = r["checkout"], r["checkin"]
        return "checkout antes do checkin"
    if ficheiro == "reservas.jsonl":
        x = rng.random()
        if x < 0.4:
            r["price_paid"] = -abs(r["price_paid"])
            return "preço negativo"
        if x < 0.8:
            r["checkin"], r["checkout"] = r["checkout"], r["checkin"]
            return "checkout antes do checkin"
        r["guests"] = 0
        return "guests=0"
    # avaliações
    if rng.random() < 0.7:
        r["rating"] = rng.choice([0, 6, 9])
        return f"rating={r['rating']}"
    r["created_at"] = "2099-01-01T00:00:00Z"
    return "data no futuro"


def defeitos_de_conteudo(rng, cfg, out, ficheiro, r, rid):
    """Campos em falta ou valores impossíveis (mutuamente exclusivos)."""
    d = cfg["defeitos"]
    if rng.random() < d["campos_em_falta"]:
        campo = rng.choice(EM_FALTA[ficheiro])
        r.pop(campo, None)
        out.defeito(ficheiro, rid, "campo_em_falta", campo)
    elif rng.random() < d["valores_impossiveis"]:
        out.defeito(ficheiro, rid, "valor_impossivel", tornar_impossivel(rng, ficheiro, r))


# ---------------------------------------------------------------- texto
def texto_avaliacao(rng, lang, sent):
    f = FRASES[lang]
    if sent == "neu":
        a, b = rng.sample(ASPECTOS, 2)
        partes = [rng.choice(f["abre"]["neu"]), f["aspectos"][a]["pos"],
                  f["aspectos"][b]["neg"], rng.choice(f["fecha"]["neu"])]
        return " ".join(partes), [a, b]
    aspectos = rng.sample(ASPECTOS, rng.randint(1, 3))
    partes = [rng.choice(f["abre"][sent])]
    partes += [f["aspectos"][a][sent] for a in aspectos]
    partes.append(rng.choice(f["fecha"][sent]))
    return " ".join(partes), aspectos


def texto_falso(rng, lang, modelo):
    base = FRASES[lang]["falsas"][modelo]
    # quase-duplicados: só muda pontuação e emoji
    return base + "!" * rng.randint(0, 3) + rng.choice(["", " 😍", " 👍", " ⭐⭐⭐⭐⭐"])


def nota_para(rng, sent):
    return {"pos": rng.choice([4, 5, 5]), "neu": 3, "neg": rng.choice([1, 2])}[sent]


def nota_contraria(rng, sent):
    return {"pos": rng.choice([1, 2]), "neu": rng.choice([1, 5]), "neg": rng.choice([4, 5])}[sent]


# ---------------------------------------------------------------- gerador
class Gerador:
    def __init__(self, cfg):
        self.cfg = cfg
        self.k = cfg["escala"]
        s = cfg["semente"]
        # um gerador aleatório por fluxo: mudar um fluxo não altera os outros
        self.rng = {n: random.Random(f"{s}-{n}") for n in
                    ["alojamentos", "historico", "stream", "agenda", "disp", "defeitos"]}
        self.t0 = datetime.fromisoformat(cfg["inicio"]).timestamp()
        self.t_fim = self.t0 + cfg["dias"] * 86400
        self.n_hospedes = cfg["hospedes_base"] * self.k
        self.langs = list(cfg["idiomas"])
        self.lang_cum = acumular(cfg["idiomas"].values())
        self.sents = list(cfg["sentimento"])
        self.sent_cum = acumular(cfg["sentimento"].values())
        self.seq_review = 0

    # ---------- alojamentos
    def alojamentos(self, out):
        rng, cfg = self.rng["alojamentos"], self.cfg
        self.zonas = {}
        for cidade, c in cfg["cidades"].items():
            pref = sem_acentos(cidade)[:3].upper()
            for i, z in enumerate(c["zonas"]):
                self.zonas[(cidade, z)] = f"{pref}-{i + 1:02d}"
        cidades = list(cfg["cidades"])
        cid_cum = acumular(c["peso_procura"] for c in cfg["cidades"].values())
        n = cfg["alojamentos_base"] * self.k
        ranks = list(range(1, n + 1))
        rng.shuffle(ranks)
        self.lst = []
        for i in range(n):
            cidade = escolher_pesado(rng, cidades, cid_cum)
            zona = rng.choice(cfg["cidades"][cidade]["zonas"])
            hid = i // 3
            a = {
                "listing_id": f"L{i:07d}",
                "city": cidade,
                "zone_id": self.zonas[(cidade, zona)],
                "zone_name": zona,
                "type": rng.choice(["apartamento", "apartamento", "quarto", "moradia", "estúdio"]),
                "capacity": rng.choice([1, 2, 2, 3, 4, 4, 6]),
                "base_price": round(cfg["preco_base_mediana_eur"] *
                                    math.exp(rng.gauss(0, cfg["preco_base_sigma_log"])), 2),
                "host": {"host_id": f"H{hid:06d}",
                         "name": f"{NOMES[(hid * 7) % len(NOMES)]} {APELIDOS[(hid * 3) % len(APELIDOS)]}"},
                "_peso": 1.0 / ranks[i] ** cfg["popularidade_zipf_s"],
            }
            self.lst.append(a)
            out.escrever("alojamentos.jsonl", {k: v for k, v in a.items() if k != "_peso"})
        self.lst_cum = acumular(a["_peso"] for a in self.lst)
        self.por_zona = {}
        for a in self.lst:
            self.por_zona.setdefault(a["zone_id"], []).append(a)
        self.por_zona_cum = {z: acumular(a["_peso"] for a in l) for z, l in self.por_zona.items()}

    # ---------- avaliações
    def nova_avaliacao(self, rng, ts, ficheiro, out, alojamento=None, falsa=False,
                       conta_falsa=None, modelo_falso=0, campanha=None):
        self.seq_review += 1
        rid = f"R{self.seq_review:09d}"
        a = alojamento or escolher_pesado(rng, self.lst, self.lst_cum)
        lang = escolher_pesado(rng, self.langs, self.lang_cum)
        tem_pii = contraria = False
        if falsa:
            sent, texto, aspectos = "pos", texto_falso(rng, lang, modelo_falso), []
            nota = 5
            autor = {"guest_id": conta_falsa, "name": f"user{conta_falsa[-4:]}"}
            reserva = None
        else:
            sent = escolher_pesado(rng, self.sents, self.sent_cum)
            texto, aspectos = texto_avaliacao(rng, lang, sent)
            contraria = rng.random() < self.cfg["nota_contraria_ao_texto"]
            nota = nota_contraria(rng, sent) if contraria else nota_para(rng, sent)
            h = hospede(rng.randrange(self.n_hospedes))
            autor = {"guest_id": h["guest_id"], "name": h["name"]}
            reserva = f"B{rng.randrange(10 ** 9):09d}"
            if rng.random() < self.cfg["pii_no_texto"]:
                outro = hospede(rng.randrange(self.n_hospedes))
                texto += " " + FRASES[lang]["pii"].format(
                    nome=outro["name"], telefone=outro["phone"], email=outro["email"])
                tem_pii = True
        declarado = lang
        if rng.random() < self.cfg["idioma_declarado_errado"]:
            declarado = rng.choice([l for l in self.langs if l != lang])
        r = {"review_id": rid, "listing_id": a["listing_id"], "zone_id": a["zone_id"],
             "guest_id": autor["guest_id"], "guest_name": autor["name"], "booking_id": reserva,
             "lang": declarado, "rating": nota, "text": texto, "created_at": iso(ts)}
        out.escrever("verdade/avaliacoes_verdade.jsonl", {
            "review_id": rid, "sentimento_real": sent, "idioma_real": lang, "aspectos": aspectos,
            "falsa": falsa, "campanha": campanha, "tem_pii_no_texto": tem_pii,
            "nota_contraria": contraria, "idioma_declarado_errado": declarado != lang})
        defeitos_de_conteudo(self.rng["defeitos"], self.cfg, out, ficheiro, r, rid)
        return rid, r

    def historico(self, out):
        rng, cfg = self.rng["historico"], self.cfg
        n = cfg["avaliacoes_historico_base"] * self.k
        contas = [f"F{i:06d}" for i in range(max(10, 50 * self.k))]
        inicio = self.t0 - cfg["historico_dias"] * 86400
        for _ in range(n):
            ts = inicio + rng.random() * (self.t0 - inicio)
            falsa = rng.random() < cfg["falsas_historico"]
            rid, r = self.nova_avaliacao(rng, ts, "avaliacoes_historico.jsonl", out, falsa=falsa,
                                         conta_falsa=rng.choice(contas) if falsa else None,
                                         modelo_falso=rng.randrange(2))
            out.escrever("avaliacoes_historico.jsonl", r)
            if self.rng["defeitos"].random() < cfg["defeitos"]["duplicados"]:
                out.escrever("avaliacoes_historico.jsonl", dict(r))
                out.defeito("avaliacoes_historico.jsonl", rid, "duplicado")

    # ---------- eventos locais (API externa)
    def eventos(self):
        rng, cfg = self.rng["agenda"], self.cfg
        ev = cfg["evento_pico"]
        lista = [{"id": "EV-PICO", "name": ev["nome"], "city": ev["cidade"],
                  "zone_id": self.zonas[(ev["cidade"], ev["zona"])],
                  "start": self.t0 + ev["inicio_h"] * 3600, "dur_h": ev["duracao_h"],
                  "attendance": ev["assistencia"], "anunciado": self.t0 + ev["anunciado_h"] * 3600}]
        tipos = ["Feira", "Festival de rua", "Exposição", "Jogo de futebol", "Conferência", "Mercado"]
        for i in range(cfg["eventos_menores"]):
            cidade = rng.choice(list(cfg["cidades"]))
            zona = rng.choice(cfg["cidades"][cidade]["zonas"])
            lista.append({"id": f"EV-{i:03d}", "name": f"{rng.choice(tipos)} {zona}", "city": cidade,
                          "zone_id": self.zonas[(cidade, zona)],
                          "start": self.t0 + rng.uniform(0, cfg["dias"] * 86400 + 7 * 86400),
                          "dur_h": rng.choice([2, 3, 4, 6, 8]),
                          "attendance": rng.choice([500, 1000, 2000, 3500, 5000]), "anunciado": self.t0})
        self.lista_eventos = lista

    def poll_agenda(self, ts, out):
        mudanca = self.t0 + self.cfg["agenda_api"]["mudanca_formato_h"] * 3600
        visiveis = [e for e in self.lista_eventos if e["anunciado"] <= ts]
        if ts < mudanca:   # formato v1
            payload = [{"id": e["id"], "title": e["name"], "city": e["city"], "zone": e["zone_id"],
                        "date": dia(e["start"]),
                        "start": datetime.fromtimestamp(e["start"], tz=timezone.utc).strftime("%H:%M"),
                        "duration_hours": e["dur_h"], "attendance": e["attendance"]}
                       for e in visiveis]
            out.escrever("agenda_api.jsonl", {"poll_ts": iso(ts), "source": "agenda_api",
                                              "status": 200, "events": payload})
        else:              # formato v2: nomes, estrutura e tipos diferentes, sem aviso nem versão
            payload = [{"eventId": e["id"], "name": e["name"],
                        "location": {"city": e["city"], "zoneCode": e["zone_id"]},
                        "start_time": int(e["start"]), "end_time": int(e["start"] + e["dur_h"] * 3600),
                        "expected_attendance": f"{e['attendance'] / 1000:g}k"}
                       for e in visiveis]
            out.escrever("agenda_api.jsonl", {"pollTimestamp": int(ts), "source": "agenda_api",
                                              "data": {"items": payload, "count": len(payload)}})

    # ---------- disponibilidade (snapshot diário)
    def disponibilidade(self, ts, out):
        rng, cfg = self.rng["disp"], self.cfg
        ev = cfg["evento_pico"]
        dia_evento = dia(self.t0 + ev["inicio_h"] * 3600)
        for a in self.lst:
            for d in range(cfg["disponibilidade_dias_futuros"]):
                data = dia(ts + d * 86400)
                ocup = cfg["ocupacao_base"]
                fator = 1.0
                if data == dia_evento and a["city"] == ev["cidade"]:
                    ocup, fator = ev["ocupacao_no_dia"], ev["fator_preco"]
                out.escrever("disponibilidade.jsonl", {
                    "snapshot_ts": iso(ts), "listing_id": a["listing_id"], "date": data,
                    "available": rng.random() >= ocup, "price": round(a["base_price"] * fator, 2)})

    # ---------- fluxos em tempo real
    def fator_diario(self, ts):
        h = ((ts - self.t0) / 3600) % 24
        c = self.cfg
        return 1 + c["variacao_diaria_amplitude"] * math.cos(2 * math.pi * (h - c["variacao_diaria_pico_h"]) / 24)

    def em_janela_pico(self, ts):
        ev = self.cfg["evento_pico"]
        ini = self.t0 + (ev["inicio_h"] - ev["pico_procura_antes_h"]) * 3600
        return ini <= ts < self.t0 + (ev["inicio_h"] + ev["duracao_h"]) * 3600

    def enviar(self, heap, ficheiro, r, rid, ts):
        """Coloca um registo na fila de chegada, com atraso, fora de ordem e duplicados."""
        rng, d = self.rng["defeitos"], self.cfg["defeitos"]
        chegada = ts + rng.uniform(0.05, 2.0)
        if rng.random() < d["fora_de_ordem"]:
            atraso = rng.uniform(*d["atraso_fora_de_ordem_s"])
            chegada += atraso
            self.out.defeito(ficheiro, rid, "fora_de_ordem", f"atraso {atraso:.0f}s")
        self.seq += 1
        heapq.heappush(heap, (chegada, self.seq, ficheiro, r))
        if rng.random() < d["duplicados"]:
            self.seq += 1
            heapq.heappush(heap, (chegada + rng.uniform(0.5, 10), self.seq, ficheiro, dict(r)))
            self.out.defeito(ficheiro, rid, "duplicado", "reenvio")

    def stream(self, out):
        rng, cfg = self.rng["stream"], self.cfg
        ev = cfg["evento_pico"]
        ev_zona = self.zonas[(ev["cidade"], ev["zona"])]
        dia_evento_ts = datetime.fromisoformat(dia(self.t0 + ev["inicio_h"] * 3600) + "T00:00:00+00:00").timestamp()
        camp = cfg["campanha_falsas"]
        camp_ini = self.t0 + camp["inicio_h"] * 3600
        camp_fim = camp_ini + camp["duracao_h"] * 3600
        # alvos da campanha: alojamentos pouco populares (é onde as falsas mais pesam)
        alvos = [self.lst[i] for i in sorted(range(len(self.lst)), key=lambda i: self.lst[i]["_peso"])[:camp["alojamentos_alvo"]]]
        contas = [f"F9{i:05d}" for i in range(camp["contas_falsas"])]
        n_camp = camp["avaliacoes_base"] * self.k
        cidades = list(cfg["cidades"])
        self.out, self.seq, heap = out, 0, []
        n_pesq = n_res = 0
        prox_poll = self.t0
        prox_disp = self.t0
        t = self.t0
        while t < self.t_fim:
            fim = t + 60
            if t >= prox_disp:
                self.disponibilidade(t, out)
                prox_disp += 86400
            if t >= prox_poll:
                self.poll_agenda(t, out)
                prox_poll += cfg["agenda_api"]["intervalo_poll_min"] * 60
            fd = self.fator_diario(t)
            pico = self.em_janela_pico(t)
            for cidade in cidades:
                lam = cfg["pesquisas_por_segundo_base"] * self.k * cfg["cidades"][cidade]["peso_procura"] * fd * 60
                evento = pico and cidade == ev["cidade"]
                if evento:
                    lam *= ev["multiplicador_procura"]
                for _ in range(poisson(rng, lam)):
                    ts = t + rng.random() * 60
                    zona = rng.choice(cfg["cidades"][cidade]["zonas"])
                    zid = self.zonas[(cidade, zona)]
                    if evento and rng.random() < ev["fracao_checkin_no_dia"]:
                        checkin = dia_evento_ts
                        zid = ev_zona if rng.random() < 0.5 else zid
                    else:
                        checkin = ts + rng.randint(1, 60) * 86400
                    noites = min(14, 1 + int(rng.expovariate(1 / 2.0)))
                    n_pesq += 1
                    pid = f"S{n_pesq:010d}"
                    h = rng.randrange(self.n_hospedes)
                    r = {"event_id": pid, "event_type": "search", "event_ts": iso(ts),
                         "session_id": f"sess-{h:07d}-{int(ts // 1800)}",
                         "ip": f"{rng.choice(['192.0.2', '198.51.100', '203.0.113'])}.{rng.randint(1, 254)}",
                         "city": cidade, "zone_id": zid, "checkin": dia(checkin),
                         "checkout": dia(checkin + noites * 86400), "guests": rng.choice([1, 2, 2, 2, 3, 4])}
                    reserva = None
                    conv = cfg["conversao_reserva_evento"] if evento else cfg["conversao_reserva"]
                    if rng.random() < conv:
                        a = escolher_pesado(rng, self.por_zona[zid], self.por_zona_cum[zid])
                        fator = ev["fator_preco"] if (evento and checkin == dia_evento_ts) else 1.0
                        n_res += 1
                        bid = f"B{n_res:010d}"
                        hh = hospede(h)
                        reserva = (bid, ts + rng.uniform(30, 900), {
                            "event_id": bid, "event_type": "booking", "booking_id": bid,
                            "listing_id": a["listing_id"], "zone_id": a["zone_id"], "search_id": pid,
                            "guest": hh, "payment": {"method": rng.choice(["card", "card", "mbway", "paypal"]),
                                                     "card_last4": f"{rng.randrange(10000):04d}"},
                            "checkin": r["checkin"], "checkout": r["checkout"], "guests": r["guests"],
                            "price_paid": round(a["base_price"] * fator * noites, 2), "currency": "EUR",
                            "status": "confirmed"})
                    defeitos_de_conteudo(self.rng["defeitos"], cfg, out, "pesquisas.jsonl", r, pid)
                    self.enviar(heap, "pesquisas.jsonl", r, pid, ts)
                    if reserva:
                        bid, bts, br = reserva
                        br["event_ts"] = iso(bts)
                        defeitos_de_conteudo(self.rng["defeitos"], cfg, out, "reservas.jsonl", br, bid)
                        self.enviar(heap, "reservas.jsonl", br, bid, bts)
            # avaliações em tempo real (genuínas)
            for _ in range(poisson(rng, cfg["avaliacoes_por_hora_base"] * self.k / 60)):
                ts = t + rng.random() * 60
                rid, r = self.nova_avaliacao(rng, ts, "avaliacoes_stream.jsonl", out)
                self.enviar(heap, "avaliacoes_stream.jsonl", r, rid, ts)
            # campanha de avaliações falsas em massa
            if camp_ini <= t < camp_fim:
                por_min = n_camp / (camp["duracao_h"] * 60)
                modelo = 0
                for _ in range(poisson(rng, por_min)):
                    ts = t + rng.random() * 60
                    rid, r = self.nova_avaliacao(rng, ts, "avaliacoes_stream.jsonl", out,
                                                 alojamento=rng.choice(alvos), falsa=True,
                                                 conta_falsa=rng.choice(contas), modelo_falso=modelo,
                                                 campanha="CAMP-01")
                    self.enviar(heap, "avaliacoes_stream.jsonl", r, rid, ts)
            # escrever por ordem de chegada tudo o que chegou até ao fim deste minuto
            while heap and heap[0][0] < fim:
                _, _, ficheiro, r = heapq.heappop(heap)
                out.escrever(ficheiro, r)
            t = fim
        while heap:
            _, _, ficheiro, r = heapq.heappop(heap)
            out.escrever(ficheiro, r)
        # cenário de procura e de mudança de formato, para comparar com o que o pipeline deteta
        out.escrever("verdade/cenarios.jsonl", {
            "cenario": "evento_pico", "cidade": ev["cidade"], "zone_id": ev_zona,
            "janela_procura": [iso(self.t0 + (ev["inicio_h"] - ev["pico_procura_antes_h"]) * 3600),
                               iso(self.t0 + (ev["inicio_h"] + ev["duracao_h"]) * 3600)],
            "multiplicador": ev["multiplicador_procura"], "anunciado_na_agenda": iso(self.t0 + ev["anunciado_h"] * 3600)})
        out.escrever("verdade/cenarios.jsonl", {
            "cenario": "mudanca_formato_agenda",
            "momento": iso(self.t0 + cfg["agenda_api"]["mudanca_formato_h"] * 3600),
            "nota": "v1 -> v2 sem aviso: campos renomeados, start_time em epoch, assistência como texto ('40k')"})
        out.escrever("verdade/cenarios.jsonl", {
            "cenario": "campanha_falsas", "id": "CAMP-01", "janela": [iso(camp_ini), iso(camp_fim)],
            "alojamentos_alvo": [a["listing_id"] for a in alvos], "contas": contas,
            "avaliacoes_previstas": n_camp})

    def correr(self, pasta):
        out = Saida(pasta)
        self.alojamentos(out)
        self.historico(out)
        self.eventos()
        self.stream(out)
        out.fechar()
        return out


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="Gerador de dados sintéticos — Enunciado 7 (Turismo)")
    ap.add_argument("--config", default=Path(__file__).with_name("config.json"))
    ap.add_argument("--escala", type=int, help="multiplicador de volume (1, 10, 100)")
    ap.add_argument("--semente", type=int)
    ap.add_argument("--dias", type=int, help="duração da simulação em tempo real")
    ap.add_argument("--saida", default="saida")
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    dias_cfg = cfg["dias"]
    for campo in ("escala", "semente", "dias"):
        if getattr(a, campo) is not None:
            cfg[campo] = getattr(a, campo)
    if cfg["dias"] != dias_cfg:
        # os cenários mantêm a mesma posição relativa na simulação (durações fixas)
        f = cfg["dias"] / dias_cfg
        ev, camp = cfg["evento_pico"], cfg["campanha_falsas"]
        for d, k in [(ev, "anunciado_h"), (ev, "inicio_h"), (ev, "pico_procura_antes_h"),
                     (camp, "inicio_h"), (cfg["agenda_api"], "mudanca_formato_h")]:
            d[k] = round(d[k] * f, 2)
        print(f"Aviso: {cfg['dias']} dia(s) em vez de {dias_cfg}; horários dos cenários reescalados ×{f:.2f}")
    pasta = Path(a.saida) / f"escala_{cfg['escala']}_semente_{cfg['semente']}"
    inicio = datetime.now()
    out = Gerador(cfg).correr(pasta)
    duracao = (datetime.now() - inicio).total_seconds()
    ficheiros = sorted(out.contagem)
    manifesto = {
        "gerador_versao": VERSAO, "python": platform.python_version(),
        "semente": cfg["semente"], "escala": cfg["escala"], "config": cfg,
        "registos": {f: out.contagem[f] for f in ficheiros},
        "defeitos_injetados": dict(sorted(out.defeitos.items())),
        "sha256": {f: sha256(pasta / f) for f in ficheiros},
        "duracao_geracao_s": round(duracao, 1),
    }
    (pasta / "manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gerado em {pasta} ({duracao:.1f}s)")
    for f in ficheiros:
        print(f"  {f:40s} {out.contagem[f]:>12,d}")


if __name__ == "__main__":
    main()
