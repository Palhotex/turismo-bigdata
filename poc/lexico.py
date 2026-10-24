"""Léxicos simples para idioma, sentimento e temas (sem modelos pesados).

Resposta à questão-guia "que partes do texto exigem NLP e quais bastam métricas
simples": aqui testa-se até onde chegam listas de palavras. O F1 medido serve de
linha de base para comparar com um modelo de linguagem, se o grupo o usar.
Limitação: o texto sintético usa as mesmas palavras de forma regular, por isso o
resultado é otimista face a avaliações reais.
"""

STOPWORDS = {
    "pt": "o a os as de do da e é não muito um uma foi estava para com que à ao no na pelo".split(),
    "en": "the was is and very of to we it at for our not there did".split(),
    "es": "el la los las de del y es muy un una fue estaba por con que lo no había".split(),
    "fr": "le la les de du et est très un une était pour avec que nous à au pas il".split(),
    "de": "der die das und ist sehr ein eine war für mit wir es nicht hat gab".split(),
}

POSITIVAS = {
    "pt": "excelente adorámos bem limpo impecavelmente perfeita perfeito sossegada simpático prestável confortável ótima recomendo vivamente voltaremos bom fantástico".split(),
    "en": "excellent loved well clean spotlessly perfect quiet friendly helpful comfortable great recommended definitely good amazing".split(),
    "es": "excelente encantó bien impecable perfecta perfecto tranquila amable atento cómoda buena recomendable volveremos bueno".split(),
    "fr": "excellent adoré bien propreté impeccable parfait calme sympathique serviable confortable recommande vivement reviendrons bon".split(),
    "de": "hervorragender geliebt gut blitzsauber perfekt ruhig freundlich hilfsbereit bequem empfehle bestimmt".split(),
}

NEGATIVAS = {
    "pt": "desilusão sujo suja longe barulho nunca desconfortável caro demasiado evitem mau péssimo".split(),
    "en": "disappointment dirty far noise never uncomfortable expensive too avoid bad terrible".split(),
    "es": "decepción sucio lejos ruido nunca incómodo caro demasiado evitad malo".split(),
    "fr": "déception sale loin bruit jamais inconfortable cher trop éviter".split(),
    "de": "enttäuschung schmutzig weit straßenlärm nie unbequem teuer meidet schlecht".split(),
}

# negação simples: inverte a palavra positiva seguinte ("não recomendo", "not return")
NEGACOES = {"pt": ["não"], "en": ["not", "never"], "es": ["no"], "fr": ["ne", "pas"], "de": ["nicht", "nie"]}

TEMAS = {
    "limpeza": "limpo limpa impecavelmente suja sujo clean spotlessly dirty bathroom impecable sucio baño propreté sale blitzsauber schmutzig".split(),
    "localizacao": "localização transportes longe location transport far ubicación transporte lejos emplacement transports loin lage verkehrsmitteln entfernt".split(),
    "ruido": "sossegada barulho quiet noise tranquila ruido calme bruit ruhig straßenlärm".split(),
    "anfitriao": "anfitrião host anfitrión hôte gastgeber".split(),
    "conforto": "cama colchão bed mattress colchón lit matelas bett matratze".split(),
    "wifi": "wifi wlan".split(),
    "preco": "preço caro money expensive precio calidad caro prix cher preis teuer leistungs".split(),
}


def tabelas_sql():
    """Linhas (lang, palavra, valor) para carregar no DuckDB."""
    stop = [(l, w) for l, ws in STOPWORDS.items() for w in ws]
    pol = [(l, w, 1) for l, ws in POSITIVAS.items() for w in ws] + \
          [(l, w, -1) for l, ws in NEGATIVAS.items() for w in ws]
    neg = [(l, w) for l, ws in NEGACOES.items() for w in ws]
    temas = sorted({(t, w) for t, ws in TEMAS.items() for w in ws})
    return stop, pol, neg, temas
