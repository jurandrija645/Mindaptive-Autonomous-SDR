"""Pre-written, zero-token translations of the Auto-Reply nudge message.

The nudge asks whoever auto-replied to forward Andrew/Mia's cold email to the
right person — it's fully generic, with nothing personalized per lead, so
there's no reason to spend a Sonnet/Opus call drafting and translating it for
every auto-reply lead. Instead it's translated once (see the one-time Sonnet
call used to produce these, not run at request time) and picked by Smartlead's
own per-lead `language_code` custom field (see smartlead.normalize_lead).

Only covers the languages below. `get()` returns None for anything else, and
the caller (pipeline.create_draft) falls back to a live Claude draft via
drafter.AUTOREPLY_SYSTEM_PROMPT — so an uncommon language still gets a draft,
it just isn't free.
"""

ENGLISH_TEXT = """Hi, funny timing. I got your auto-reply about delayed responses right after sending an email about how slow responses cost businesses missed jobs. Not a dig at you, just kind of proves the point.

If this is better suited for someone on the ops/leads side, mind forwarding it over? Appreciate it!

Thanks,
Mia"""

# language_code (Smartlead's custom field, lowercase ISO 639-1) -> localized body.
# A persona signature is appended separately (same as every other draft) — do
# not add a rich signature here, just the plain-text sign-off.
TEMPLATES: dict[str, str] = {
    "en": ENGLISH_TEXT,
    "de": """Hi, witziges Timing. Ich habe Ihre automatische Antwort zu verzögerten Rückmeldungen bekommen, direkt nachdem ich eine E-Mail darüber verschickt hatte, wie langsame Antworten Unternehmen Aufträge kosten. Kein Seitenhieb gegen Sie, das beweist quasi nur den Punkt.

Falls das eher zu jemandem aus dem Ops- oder Leads-Bereich passt, könnten Sie es weiterleiten? Danke Ihnen!

Danke,
Mia""",
    "fr": """Salut, drôle de timing. J'ai reçu votre réponse automatique sur les délais de réponse juste après avoir envoyé un e-mail expliquant comment des réponses trop lentes font perdre des contrats aux entreprises. Ce n'est pas une pique, ça illustre juste le propos.

Si c'est plus adapté à quelqu'un côté ops ou leads, ça vous dérange de transférer ? Merci beaucoup !

Merci,
Mia""",
    "es": """Hola, qué casualidad. Recibí tu respuesta automática sobre demoras justo después de enviar un correo sobre cómo las respuestas lentas le cuestan trabajos a las empresas. No es una indirecta, más bien confirma el punto.

Si esto le corresponde más a alguien del área de operaciones o leads, ¿te importaría reenviarlo? ¡Gracias!

Saludos,
Mia""",
    "nl": """Hoi, grappige timing. Ik kreeg jouw automatische antwoord over vertraagde reacties net nadat ik een mail had verstuurd over hoe trage reacties bedrijven klanten kosten. Geen steek onder water, het bewijst gewoon mooi mijn punt.

Als dit beter bij iemand van ops of leads past, zou je het kunnen doorsturen? Alvast bedankt!

Groetjes,
Mia""",
    "sv": """Hej, lustig timing. Jag fick ditt autosvar om fördröjda svar precis efter att jag skickat ett mejl om hur långsamma svar kostar företag affärer. Ingen känga mot dig, det bara bevisar poängen.

Om det här passar bättre hos någon på ops- eller leads-sidan, skulle du kunna skicka det vidare? Uppskattar det!

Tack,
Mia""",
    "it": """Ciao, che tempismo. Ho ricevuto la tua risposta automatica sui ritardi proprio dopo aver inviato un'email su come le risposte lente facciano perdere lavori alle aziende. Non è una frecciatina, dimostra solo il punto.

Se questo è più adatto a qualcuno del team operativo o leads, ti dispiacerebbe inoltrarlo? Grazie mille!

Grazie,
Mia""",
    "pt": """Oi, que coincidência engraçada. Recebi sua resposta automática sobre atrasos logo depois de enviar um e-mail sobre como respostas lentas fazem as empresas perderem negócios. Não é uma indireta, só prova o ponto.

Se isso for mais adequado para alguém da área de operações ou leads, você poderia encaminhar? Agradeço!

Obrigada,
Mia""",
    "da": """Hej, sjovt timing. Jeg fik dit autosvar om forsinkede svar lige efter jeg sendte en mail om, hvordan langsomme svar koster virksomheder tabte opgaver. Ikke et hip til dig, det beviser bare pointen.

Hvis det her passer bedre til en fra ops- eller leads-siden, vil du så sende det videre? Sætter pris på det!

Tak,
Mia""",
    "no": """Hei, morsomt timing. Jeg fikk autosvaret ditt om forsinkede svar rett etter at jeg sendte en e-post om hvordan trege svar koster bedrifter oppdrag. Ikke et stikk til deg, det bare beviser poenget.

Hvis dette passer bedre for noen på ops- eller leads-siden, kan du sende det videre? Setter pris på det!

Takk,
Mia""",
    "pl": """Cześć, ale zbieg okoliczności. Dostałam Twoją automatyczną odpowiedź o opóźnionych odpowiedziach zaraz po tym, jak wysłałam maila o tym, jak wolne odpowiedzi kosztują firmy utracone zlecenia. Nie chcę robić przytyku, to po prostu potwierdza tezę.

Jeśli to bardziej pasuje do kogoś z działu operacyjnego albo od leadów, mógłbyś to przekazać? Dzięki wielkie!

Pozdrawiam,
Mia""",
    "sk": """Ahoj, vtipné načasovanie. Dostala som tvoju automatickú odpoveď o oneskorených reakciách hneď po tom, čo som poslala e-mail o tom, ako pomalé odpovede stoja firmy stratené zákazky. Nie je to narážka na teba, len to celkom potvrdzuje môj bod.

Ak je to vhodnejšie pre niekoho z ops alebo leads tímu, mohol by si to preposlať? Vopred ďakujem!

Ďakujem,
Mia""",
    "hr": """Bok, baš smiješno vrijeme. Dobila sam tvoj automatski odgovor o kašnjenju u odgovorima odmah nakon što sam poslala mail o tome kako spori odgovori koštaju tvrtke izgubljenih poslova. Nije to peckanje tebe, samo dokazuje poantu.

Ako je ovo prikladnije za nekoga iz ops ili leads tima, možeš li to proslijediti? Hvala unaprijed!

Hvala,
Mia""",
    "cs": """Ahoj, vtipné načasování. Dostala jsem tvou automatickou odpověď o zpožděných reakcích hned po tom, co jsem poslala e-mail o tom, jak pomalé odpovědi stojí firmy ztracené zakázky. Není to narážka na tebe, jen to celkem potvrzuje můj bod.

Pokud je tohle vhodnější pro někoho z ops nebo leads týmu, mohl bys to prosím přeposlat? Díky moc!

Díky,
Mia""",
}


def get(language_code: str | None) -> str | None:
    if not language_code:
        return None
    return TEMPLATES.get(language_code.strip().lower()[:2])
