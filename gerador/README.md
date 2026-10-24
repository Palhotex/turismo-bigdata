# Gerador de dados sintéticos — Enunciado 7 (Turismo)

Gera os dados para a prova de conceito: alojamentos, avaliações em 5 idiomas com
sentimento conhecido, avaliações falsas, pesquisas e reservas em tempo real com um pico
de procura, disponibilidade e uma API externa de eventos que **muda de formato a meio**.

Não usa dados pessoais reais: nomes combinados de listas próprias, emails `@example.com`
(domínio reservado, RFC 2606), telefones `+351 999 …` e IPs das gamas de documentação
(`192.0.2.x`, `198.51.100.x`, `203.0.113.x`, RFC 5737).

## Como usar

Só precisa de Python 3.9 ou superior (biblioteca padrão; nada a instalar).

```bash
python gerador.py                        # 1×, 1 dia, semente 42 (~33 MB, 2 s)
python gerador.py --escala 10            # ~330 MB
python gerador.py --escala 100           # ~3,3 GB: gerar, medir e apagar
python gerador.py --semente 7            # outro conjunto de dados, igualmente reprodutível

python verificar.py saida/escala_1_semente_42                 # taxas observadas
python verificar.py saida/escala_1_semente_42 outra/escala_1_semente_42   # mesmos dados?

pip install kafka-python
python reproduzir.py saida/escala_1_semente_42/pesquisas.jsonl --topico pesquisas --rapidez 60 --chave zone_id
```

`--rapidez 60` = 1 hora simulada por minuto real; `--rapidez 0` = o mais depressa possível
(teste de carga). Com `--dias` diferente de 1, os horários dos cenários são reescalados
para manter a mesma posição relativa.

## Quatro exigências do enunciado

| Exigência | Como é cumprida |
|---|---|
| Parametrizável | `--escala`, `--dias`; ritmo em `reproduzir.py --rapidez`; todas as taxas em `config.json` |
| Defeitos realistas | Duplicados, fora de ordem, valores impossíveis, campos em falta, pico de carga, avaliações falsas, mudança de formato |
| Reprodutível | Semente fixa (`42`), um gerador aleatório por fluxo, versão `1.0.0`; `manifesto.json` guarda o SHA-256 de cada ficheiro |
| Documentado | Este ficheiro + `manifesto.json` (configuração usada e contagens) |

**Reprodutibilidade verificada:** duas execuções com `--escala 1 --semente 42` deram
ficheiros iguais byte a byte (`verificar.py` compara os SHA-256).

## Ficheiros gerados

Em `saida/escala_<N>_semente_<S>/`. Os ficheiros de stream estão **pela ordem de chegada**
(não pela hora do evento), como um consumidor Kafka os receberia.

| Ficheiro | Tipo | Conteúdo |
|---|---|---|
| `alojamentos.jsonl` | Referência | ID, cidade, zona, tipo, capacidade, preço base, anfitrião |
| `avaliacoes_historico.jsonl` | Batch | Avaliações dos últimos 2 anos (carga inicial do lake) |
| `avaliacoes_stream.jsonl` | Stream | Avaliações novas + campanha de falsas |
| `pesquisas.jsonl` | Stream | Pesquisas: cidade, zona, datas, hóspedes, sessão, IP |
| `reservas.jsonl` | Stream | Reservas com dados do hóspede e do pagamento (para testar a governação) |
| `disponibilidade.jsonl` | Snapshot diário | Disponibilidade e preço de cada alojamento nos 14 dias seguintes |
| `agenda_api.jsonl` | Pull horário | Resposta da API externa de eventos (v1, depois v2) |
| `verdade/avaliacoes_verdade.jsonl` | Rótulos | Sentimento e idioma reais, falsa ou não, campanha, PII no texto |
| `verdade/defeitos.jsonl` | Rótulos | Cada defeito injetado: ficheiro, ID, tipo, detalhe |
| `verdade/cenarios.jsonl` | Rótulos | Janelas do pico, da mudança de formato e da campanha |
| `manifesto.json` | Metadados | Versão, semente, configuração, contagens, SHA-256 |

A pasta `verdade/` **não deve entrar no pipeline**: serve para medir se o sistema deteta os
problemas (precisão e recall das falsas, F1 do sentimento, defeitos apanhados).

## Distribuições e taxas assumidas

Os resultados da prova de conceito só valem para estas hipóteses. O grupo deve justificar
cada uma no relatório; a coluna "Porquê" é um ponto de partida.

### Volumes (escala 1×)

| Parâmetro | Valor 1× | Porquê |
|---|---|---|
| Alojamentos | 500 | Amostra reduzida para caber num portátil |
| Avaliações históricas | 10.000 | 0,1% dos 10 M do enunciado; a 100× = 1 M. Os resultados valem para esta amostra, não para o volume real |
| Avaliações novas | 2/hora | Hipótese simples para 1 dia de simulação |
| Pesquisas | 0,5/s em média (hipótese) | O enunciado não indica; o que interessa é comparar 1×, 10× e 100× |
| Conversão pesquisa → reserva | 3% (5% no evento) | Hipótese; a conversão sobe quando a procura é urgente |
| Hóspedes distintos | 10.000 | — |
| Disponibilidade | 7 dias seguintes por alojamento | Chega para cobrir o evento |

### Comportamento

| Parâmetro | Distribuição | Porquê |
|---|---|---|
| Popularidade dos alojamentos | Zipf, s = 0,9 | Poucos alojamentos concentram muitas reservas e avaliações (cauda longa) |
| Preço base | Log-normal, mediana 90 €, σ = 0,4 | Preços são positivos e assimétricos à direita |
| Procura ao longo do dia | 1 + 0,6·cos(2π(h−15)/24) | Máximo às 15h, mínimo às 3h |
| Chegadas | Poisson por minuto | Modelo padrão de chegadas independentes |
| Noites por estadia | 1 + exponencial(média 2), máx. 14 | Maioria de estadias curtas |
| Antecedência da pesquisa | Uniforme 1–60 dias | Simplificação |
| Peso de cada cidade | Lisboa 50%, Porto 35%, Faro 15% | Hipótese |

### Avaliações

| Parâmetro | Valor | Porquê |
|---|---|---|
| Idiomas | pt 35%, en 30%, es 15%, fr 12%, de 8% | Hipótese para turismo em Portugal |
| Sentimento (genuínas) | positivo 65%, neutro 15%, negativo 20% | Avaliações de alojamento tendem a ser positivas |
| Nota ↔ sentimento | positivo → 4–5, neutro → 3, negativo → 1–2 | — |
| Nota contrária ao texto | 5% | Testa se o NLP acrescenta valor face à nota |
| Idioma declarado errado | 3% | O campo `lang` vem da app, não do texto |
| PII no texto | 2% | Testa o mascaramento na prata |
| Falsas no histórico | 2%, espalhadas | Fundo de fraude constante |
| Campanha de falsas | 300 × escala em 1 h, 5 alojamentos pouco populares, 10 contas, sem reserva, nota 5, texto quase igual | "Avaliações falsas em massa" do enunciado |

O texto é composto por frases-modelo (abertura + 1 a 3 aspetos + fecho) sobre 7 aspetos:
limpeza, localização, ruído, anfitrião, conforto, wifi, preço. **Limitação:** é muito mais
regular do que texto real, por isso o F1 do sentimento medido aqui será otimista.

### Cenários (simulação de 1 dia, início 2026-07-01 00:00 UTC)

| Cenário | Quando | O que acontece |
|---|---|---|
| Campanha de falsas | 06h–07h | Rajada de avaliações falsas |
| Mudança de formato da agenda | 12h | A API passa de v1 para v2 **sem aviso nem versão**: campos renomeados e aninhados, data em epoch, assistência como texto (`"40k"`) |
| Anúncio do grande evento | 13h | O concerto (Porto, Boavista, 40.000 pessoas) só aparece na agenda **já no formato novo** |
| Pico de procura | 14h–24h (concerto às 20h) | Pesquisas no Porto × 8; 70% com check-in no dia do evento; ocupação 90% e preço × 1,3 nesse dia |

O anúncio depois da mudança de formato é propositado: se o parser não se adaptar à v2, o
pipeline perde exatamente o sinal que explica o pico.

### Defeitos genéricos

| Defeito | Taxa | Onde | Exemplo |
|---|---|---|---|
| Duplicados | 2% | Streams e histórico | Mesmo `event_id`, reenviado 0,5–10 s depois |
| Fora de ordem | 3% | Streams | Chega 1–30 min depois do evento |
| Valores impossíveis | 0,5% | Pesquisas, reservas, avaliações | Preço negativo, checkout antes do checkin, `guests` 0 ou 99, nota 0/6/9, data em 2099 |
| Campos em falta | 1% | Pesquisas, reservas, avaliações | Sem `zone_id`, `listing_id`, `price_paid`, `text`, `lang`… |

### Taxas observadas (escala 1×, semente 42)

Saída de `verificar.py`: falsas 4,77% do total (2% no histórico + campanha); sentimento
64,4 / 15,7 / 19,9%; duplicados ~2%; fora de ordem ~3%; campos em falta ~1%; valores
impossíveis ~0,5%. Todas próximas do configurado.

## Tamanhos e tempos medidos

| Execução | Registos | Disco | Tempo |
|---|---|---|---|
| 1× | 118 mil | 33 MB | 2 s |
| 10× | ~1,2 M | 326 MB | 24 s |
| 100× | ~12 M | estimativa ~3,3 GB | estimativa ~4 min |

Registos = ficheiros de dados, sem a pasta `verdade/`; o disco inclui-a. Medido num contentor Linux; noutro computador os tempos variam, os dados não. Os valores
de 100× são extrapolados de 10×, não medidos.

## Limitações

- O texto das avaliações é gerado por modelos de frases, não por pessoas.
- As reservas não descontam disponibilidade (os dois fluxos são independentes).
- Os horários do evento menor e da agenda são aleatórios mas fixos pela semente.
- A taxa de pesquisas por segundo é uma hipótese do grupo; o enunciado não a fornece.
