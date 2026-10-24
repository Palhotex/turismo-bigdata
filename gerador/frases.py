"""Frases para compor avaliações sintéticas em 5 idiomas.

Cada avaliação genuína = abertura + 1 a 3 aspetos + fecho, com a polaridade
do sentimento real. As avaliações neutras misturam um aspeto positivo e um
negativo. As falsas usam modelos genéricos e repetitivos.
"""

ASPECTOS = ["limpeza", "localizacao", "ruido", "anfitriao", "conforto", "wifi", "preco"]

FRASES = {
    "pt": {
        "abre": {"pos": ["Estadia excelente.", "Adorámos a casa.", "Tudo correu muito bem."],
                 "neg": ["Não recomendo.", "Foi uma desilusão.", "Esperávamos muito mais."],
                 "neu": ["Estadia razoável.", "Experiência mista."]},
        "fecha": {"pos": ["Voltaremos de certeza!", "Recomendo vivamente."],
                  "neg": ["Não voltaremos.", "Evitem este alojamento."],
                  "neu": ["No geral, aceitável.", "Cumpre o básico."]},
        "aspectos": {
            "limpeza": {"pos": "O apartamento estava impecavelmente limpo.", "neg": "A casa de banho estava suja."},
            "localizacao": {"pos": "A localização é perfeita, perto de tudo.", "neg": "Fica muito longe dos transportes."},
            "ruido": {"pos": "A zona é muito sossegada à noite.", "neg": "Havia muito barulho da rua à noite."},
            "anfitriao": {"pos": "O anfitrião foi muito simpático e prestável.", "neg": "O anfitrião nunca respondeu às mensagens."},
            "conforto": {"pos": "A cama era muito confortável.", "neg": "O colchão era muito desconfortável."},
            "wifi": {"pos": "O wifi funcionou sempre bem.", "neg": "O wifi não funcionava."},
            "preco": {"pos": "Ótima relação qualidade-preço.", "neg": "Demasiado caro para o que oferece."},
        },
        "falsas": ["Melhor alojamento de sempre!!! Tudo perfeito, 5 estrelas!",
                   "Perfeito perfeito perfeito, recomendo a todos!!"],
        "pii": "Falem com {nome} pelo {telefone} ou {email}.",
    },
    "en": {
        "abre": {"pos": ["Excellent stay.", "We loved the place.", "Everything went really well."],
                 "neg": ["Would not recommend.", "It was a disappointment.", "We expected much more."],
                 "neu": ["Reasonable stay.", "Mixed experience."]},
        "fecha": {"pos": ["We will definitely come back!", "Highly recommended."],
                  "neg": ["We will not return.", "Avoid this place."],
                  "neu": ["Overall, acceptable.", "Does the basics."]},
        "aspectos": {
            "limpeza": {"pos": "The flat was spotlessly clean.", "neg": "The bathroom was dirty."},
            "localizacao": {"pos": "The location is perfect, close to everything.", "neg": "It is very far from public transport."},
            "ruido": {"pos": "The area is very quiet at night.", "neg": "There was a lot of street noise at night."},
            "anfitriao": {"pos": "The host was very friendly and helpful.", "neg": "The host never answered our messages."},
            "conforto": {"pos": "The bed was very comfortable.", "neg": "The mattress was really uncomfortable."},
            "wifi": {"pos": "The wifi always worked well.", "neg": "The wifi did not work."},
            "preco": {"pos": "Great value for money.", "neg": "Too expensive for what it offers."},
        },
        "falsas": ["Best place ever!!! Everything perfect, 5 stars!",
                   "Perfect perfect perfect, highly recommend to everyone!!"],
        "pii": "Contact {nome} at {telefone} or {email}.",
    },
    "es": {
        "abre": {"pos": ["Estancia excelente.", "Nos encantó la casa.", "Todo salió muy bien."],
                 "neg": ["No lo recomiendo.", "Fue una decepción.", "Esperábamos mucho más."],
                 "neu": ["Estancia razonable.", "Experiencia mixta."]},
        "fecha": {"pos": ["¡Volveremos seguro!", "Muy recomendable."],
                  "neg": ["No volveremos.", "Evitad este alojamiento."],
                  "neu": ["En general, aceptable.", "Cumple lo básico."]},
        "aspectos": {
            "limpeza": {"pos": "El apartamento estaba impecable.", "neg": "El baño estaba sucio."},
            "localizacao": {"pos": "La ubicación es perfecta, cerca de todo.", "neg": "Está muy lejos del transporte público."},
            "ruido": {"pos": "La zona es muy tranquila por la noche.", "neg": "Había mucho ruido de la calle por la noche."},
            "anfitriao": {"pos": "El anfitrión fue muy amable y atento.", "neg": "El anfitrión nunca respondió a los mensajes."},
            "conforto": {"pos": "La cama era muy cómoda.", "neg": "El colchón era muy incómodo."},
            "wifi": {"pos": "El wifi funcionó siempre bien.", "neg": "El wifi no funcionaba."},
            "preco": {"pos": "Muy buena relación calidad-precio.", "neg": "Demasiado caro para lo que ofrece."},
        },
        "falsas": ["¡¡¡El mejor alojamiento de todos!!! Todo perfecto, 5 estrellas!",
                   "Perfecto perfecto perfecto, ¡lo recomiendo a todos!!"],
        "pii": "Contactad con {nome} en el {telefone} o {email}.",
    },
    "fr": {
        "abre": {"pos": ["Séjour excellent.", "Nous avons adoré le logement.", "Tout s'est très bien passé."],
                 "neg": ["Je ne recommande pas.", "Ce fut une déception.", "Nous attendions beaucoup plus."],
                 "neu": ["Séjour correct.", "Expérience mitigée."]},
        "fecha": {"pos": ["Nous reviendrons sans hésiter !", "Je recommande vivement."],
                  "neg": ["Nous ne reviendrons pas.", "À éviter."],
                  "neu": ["Dans l'ensemble, acceptable.", "Le minimum est assuré."]},
        "aspectos": {
            "limpeza": {"pos": "L'appartement était d'une propreté impeccable.", "neg": "La salle de bain était sale."},
            "localizacao": {"pos": "L'emplacement est parfait, proche de tout.", "neg": "C'est très loin des transports."},
            "ruido": {"pos": "Le quartier est très calme la nuit.", "neg": "Il y avait beaucoup de bruit dans la rue la nuit."},
            "anfitriao": {"pos": "L'hôte était très sympathique et serviable.", "neg": "L'hôte n'a jamais répondu aux messages."},
            "conforto": {"pos": "Le lit était très confortable.", "neg": "Le matelas était très inconfortable."},
            "wifi": {"pos": "Le wifi a toujours bien fonctionné.", "neg": "Le wifi ne fonctionnait pas."},
            "preco": {"pos": "Excellent rapport qualité-prix.", "neg": "Trop cher pour ce qui est proposé."},
        },
        "falsas": ["Meilleur logement de tous les temps !!! Tout parfait, 5 étoiles !",
                   "Parfait parfait parfait, je recommande à tous !!"],
        "pii": "Contactez {nome} au {telefone} ou {email}.",
    },
    "de": {
        "abre": {"pos": ["Hervorragender Aufenthalt.", "Wir haben die Unterkunft geliebt.", "Alles lief sehr gut."],
                 "neg": ["Nicht zu empfehlen.", "Es war eine Enttäuschung.", "Wir hatten viel mehr erwartet."],
                 "neu": ["Ordentlicher Aufenthalt.", "Gemischte Erfahrung."]},
        "fecha": {"pos": ["Wir kommen bestimmt wieder!", "Sehr zu empfehlen."],
                  "neg": ["Wir kommen nicht wieder.", "Meidet diese Unterkunft."],
                  "neu": ["Insgesamt akzeptabel.", "Das Nötigste ist da."]},
        "aspectos": {
            "limpeza": {"pos": "Die Wohnung war blitzsauber.", "neg": "Das Bad war schmutzig."},
            "localizacao": {"pos": "Die Lage ist perfekt, alles in der Nähe.", "neg": "Es ist sehr weit von öffentlichen Verkehrsmitteln entfernt."},
            "ruido": {"pos": "Die Gegend ist nachts sehr ruhig.", "neg": "Nachts gab es viel Straßenlärm."},
            "anfitriao": {"pos": "Der Gastgeber war sehr freundlich und hilfsbereit.", "neg": "Der Gastgeber hat nie auf Nachrichten geantwortet."},
            "conforto": {"pos": "Das Bett war sehr bequem.", "neg": "Die Matratze war sehr unbequem."},
            "wifi": {"pos": "Das WLAN hat immer gut funktioniert.", "neg": "Das WLAN hat nicht funktioniert."},
            "preco": {"pos": "Sehr gutes Preis-Leistungs-Verhältnis.", "neg": "Zu teuer für das Gebotene."},
        },
        "falsas": ["Beste Unterkunft aller Zeiten!!! Alles perfekt, 5 Sterne!",
                   "Perfekt perfekt perfekt, empfehle ich allen!!"],
        "pii": "Kontaktiert {nome} unter {telefone} oder {email}.",
    },
}

NOMES = ["Ana", "João", "Maria", "Pedro", "Inês", "Tiago", "Sofia", "Miguel", "Emma", "Liam",
         "Olivia", "Noah", "Lucía", "Mateo", "Camille", "Lucas", "Léa", "Hugo", "Lena", "Jonas",
         "Mia", "Felix", "Beatriz", "Rui"]
APELIDOS = ["Silva", "Santos", "Ferreira", "Costa", "Smith", "Brown", "García", "López", "Martin",
            "Bernard", "Müller", "Schmidt", "Rossi", "Pereira", "Oliveira", "Moreau", "Wagner",
            "Fernández", "Taylor", "Rodrigues"]
