# Prova de conceito — Enunciado 7 (Turismo)

Versão mínima que cumpre o que o enunciado exige: **dados sintéticos, ingestão,
processamento e uma consulta final**, mais a medição dos cenários e de uma escolha de
modelação (com e sem Subset).

É uma versão reduzida da arquitetura proposta no registo de prompts. Em vez de Kafka,
Spark e Delta Lake, usa ficheiros Parquet e DuckDB, que correm num portátil sem servidores.
A lógica das camadas (bronze → prata → ouro, quarentena, pseudonimização) é a mesma.

| Arquitetura proposta | Nesta prova de conceito | Porquê |
|---|---|---|
| Kafka | Ficheiros JSONL pela ordem de chegada | Sem servidor; `gerador/reproduzir.py` envia para Kafka se for preciso |
| Delta Lake + Spark | Parquet + DuckDB | Mesmo SQL e mesmas camadas, ~40 MB em vez de GBs |
| Redis + OpenSearch | MongoDB | Uma só base de dados para o preço e o painel |

## Estrutura

```
gerador/          dados sintéticos (ver gerador/README.md: distribuições e taxas)
poc/
  p1_ingestao.py  JSONL -> bronze (cópia fiel, nunca rejeita)
  p2_prata.py     bronze -> prata: contrato de dados, duplicados, pseudonimização; erros -> quarentena
  p3_ouro.py      prata -> ouro: idioma, sentimento, temas, avaliações suspeitas, procura, preço sugerido, painel
  p4_serving.py   ouro -> MongoDB (padrões Subset, Extended Reference, Computed, Schema Versioning)
  p5_medir.py     consultas finais + medição com/sem Subset (mediana e p95)
  p6_cenarios.py  compara os resultados com a verdade do gerador
  lake/           bronze, prata, ouro, quarentena (criado ao correr)
  resultados/     os números para o relatório (JSON)
correr_tudo.py    corre tudo por ordem
```

## Como correr

Precisa de Python 3.10 ou superior.

```bash
pip install -r requirements.txt
python correr_tudo.py
```

Demora cerca de 20 segundos a 1× e ocupa ~42 MB. Para os testes de escala:
`python correr_tudo.py --escala 10` (~330 MB, ~1 min). Acima de 1×, os passos 4 e 5 (MongoDB) só correm com `--mongo`, porque o MongoDB simulado não tem índices e fica muito lento. A 100× gera ~3,3 GB: corram, guardem
`poc/resultados/` e apaguem logo os dados (ver abaixo).

### MongoDB a sério (para os tempos do relatório)

Sem nada indicado, o passo 4 usa um MongoDB **simulado** (`mongomock`): serve para ver o
código a funcionar, mas **os tempos não valem para o relatório**. Para medir a sério sem
instalar nada no PC, usem o **MongoDB Atlas gratuito** (cluster M0, na cloud):

1. Criar conta em mongodb.com/atlas e um cluster M0 (grátis).
2. Em *Database Access* criar um utilizador; em *Network Access* permitir o vosso IP.
3. Copiar a *connection string* e correr:

```bash
# Windows (PowerShell)
$env:MONGO_URI="mongodb+srv://utilizador:password@cluster0.xxxxx.mongodb.net"
python correr_tudo.py --mongo

# macOS / Linux
MONGO_URI="mongodb+srv://utilizador:password@cluster0.xxxxx.mongodb.net" python correr_tudo.py --mongo
```

Os tempos no Atlas incluem a latência da rede até à cloud; digam isso no relatório.

## O que cada resultado prova

| Ficheiro em `poc/resultados/` | Responde a |
|---|---|
| `p1_ingestao.json` | Débito da ingestão; compressão JSONL → Parquet |
| `p2_qualidade_sem_v2.json` | Fonte muda de formato: os polls v2 vão para a quarentena, nada mal formado entra na prata |
| `p2_qualidade.json` | Qualidade à entrada: duplicados removidos, registos em quarentena e porquê |
| `p3_ouro.json` | Tempo do NLP e do cálculo do preço |
| `p5_medicoes.json` | **Medição obrigatória:** página do alojamento com e sem Subset; painel pré-agregado vs. agregado na leitura |
| `p6_cenarios.json` | Avaliações falsas (precisão/recall), sentimento (F1 texto vs. só nota), pico de procura (reação do preço), mudança de formato |
| `resumo.json` | Tempos de cada passo, **cenário de falha** (prata intacta e tempo de recuperação), espaço ocupado |

## Como apagar

Tudo o que a prova de conceito cria fica **dentro desta pasta**. Não escreve em mais
lado nenhum do PC.

**Só os dados (mantém o código, para correr outra vez):**

```bash
# Windows (PowerShell), dentro da pasta do projeto
Remove-Item -Recurse -Force gerador\saida, poc\lake

# macOS / Linux
rm -rf gerador/saida poc/lake
```

Ou, no Explorador de Ficheiros / Finder, apagar as pastas `gerador/saida` e `poc/lake`.
Mantenham `poc/resultados/`: são os números do relatório (ocupa poucos KB).

**Tudo:** apagar a pasta do projeto inteira.

**As bibliotecas Python instaladas:**

```bash
pip uninstall -y duckdb pymongo mongomock
```

**O cluster no Atlas** (se o criaram): no site do Atlas, no cluster, *… → Terminate*.

## Limitações (para o relatório)

- Os dados são sintéticos e regulares: a deteção de falsas (100%) e o sentimento são
  otimistas face a dados reais.
- O sentimento usa léxicos simples (linha de base), não um modelo de linguagem.
- Não há streaming real: os ficheiros já vêm pela ordem de chegada e são processados em lote.
- Não foram testados: a leitura no Redis, o OpenSearch e o pedido de apagamento RGPD.
