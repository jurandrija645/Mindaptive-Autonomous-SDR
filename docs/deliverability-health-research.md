# Deliverability Health: istraživanje i operativni dizajn

## Izvršni zaključak

Deliverability se ne može pouzdano svesti na jedan broj. Smartlead warm-up reputation je koristan rani signal za pojedini mailbox, ali nije neovisno mjerenje stvarnog inbox placementa kod Gmaila, Microsofta i Yahooa. Najbolji sustav zato kombinira četiri sloja: stanje mailbox veze, Smartlead warm-up signal, DNS/autentikaciju i javne blockliste te povremene seed-list placement testove.

Implementirani health engine koristi Smartlead score za automatsku rehabilitaciju mailboxa, ali ne proglašava domenu zdravom samo zato što joj SPF i DMARC postoje. Blacklist coverage se uvijek imenuje. Ako vanjski provider nije konfiguriran, stanje je `unknown`, a ne lažno zeleno.

Preporučeni ritam je:

- mailbox health svaki dan;
- MX/SPF/DMARC svaki dan zajedno s mailbox provjerom;
- puni blacklist lookup jednom tjedno zbog cijene i API kvota, uz ručni “Check now” kad se pojavi problem;
- SmartDelivery placement test mjesečno za stabilne domene te odmah nakon pada reputacije, naglog rasta bounceova ili prije većeg scale-upa;
- Google Postmaster Tools pratiti dnevno kad domena ima dovoljno Gmail volumena da Google uopće prikaže podatke.

## Smartlead API: potvrđene mogućnosti

`GET /api/v1/email-accounts` vraća mailbox id, adresu, SMTP/IMAP stanje, `message_per_day`, dnevni sent count i `warmup_details`, uključujući warm-up status, spam count, blocked reason i reputation.^1 Dokumentacija pokazuje reputation kao string poput `"95%"`; live Mindaptive response od 9. rujna 2026. to potvrđuje. Live response također vraća `warmup_min_count`, `warmup_max_count` i `max_email_per_day` unutar `warmup_details`, iako su ti detalji potpunije opisani na endpointu za jedan account.^2

`POST /api/v1/email-accounts/{id}` mijenja mailbox daily limit preko polja `max_email_per_day`; sva polja su parcijalna i izostavljena ostaju netaknuta.^3 U stvarnom list responseu ista postavka se prikazuje kao `message_per_day`. To je dokumentacijska nedosljednost koju treba ponovno potvrditi kontroliranim write testom na jednom mailboxu prije uključivanja automatskih promjena na svih 109 Mindaptive mailboxova.

`POST /api/v1/email-accounts/{id}/warmup` službeno podržava uključivanje warm-upa, `total_warmup_per_day`, ramp-up, reply rate i auto-adjust.^4 Smartlead UI i vodiči eksplicitno podržavaju randomizirani warm-up raspon, a live read vraća min/max, ali javni write schema ne navodi min/max polja.^5 Implementacija zato prvo šalje raspon i, samo ako dobije validacijski 422, ponavlja poziv sa službeno dokumentiranim poljima. Dashboard pamti je li varijacija API-jem potvrđena.

`GET /api/v1/email-accounts/{id}/warmup-stats` vraća zadnjih sedam dana warm-up statistike, uključujući spam i delivery po danu.^6 Taj endpoint je koristan kao drugi korak: može objasniti pad scorea, ali za početnu verziju nije nužan jer daily snapshotovi već grade vlastitu povijest bez još 109 API poziva dnevno.

## Rehabilitacijski state machine

| Faza | Ulaz | Cold / campaign cap | Warm-up raspon | Očekivani maksimum | Izlaz |
|---|---|---:|---:|---:|---|
| Full | početno stanje ili završeni comeback | 25 | 18–25 | 50 | reputation < 90% |
| Rehab | reputation < 90% | 5 | 35–45 | 50 | 5 različitih UTC dana na 100% |
| Comeback | rehab uspješno završen | 15 | 25–30 | 45 | 5 različitih UTC dana na 100% |

U rehab se ulazi odmah. Ručni refresh istog dana ne može ubrzati streak jer se računa najviše jedan savršen dan po UTC datumu. U rehab ili comeback fazi rezultat 90–99% resetira streak na nulu, ali ne radi dodatni nagli prijelaz. Rezultat ispod 90% iz bilo koje faze odmah vraća mailbox u rehab. Nepoznat score ne mijenja fazu.

SMTP ili IMAP disconnect i warm-up blocked reason šalju zasebno upozorenje. To je važno jer mailbox može imati stari score 100%, a tehnički više ne može slati ili čitati odgovore.

Automatski apply je namjerno zatvoren iza dva uvjeta: `DELIVERABILITY_AUTO_APPLY=true` i `DRY_RUN=false`. Monitor-only je siguran default. Prije uključivanja treba odabrati jedan nekritičan mailbox, ručno zapisati njegove postavke, pustiti jedan phase update i potvrditi u Smartleadu da su se promijenili baš campaign limit i warm-up raspon, bez drugih account polja.

Read-only presjek Mindaptive računa 9. rujna 2026. pokazao je 109 mailboxova na 39 domena, bez connection problema i bez reputation rezultata ispod 90%; 107 mailboxova bilo je na 100%. Postavke već nose trag postojećih faza: 73 mailboxa imaju 25 cold i 18–25 warm, devet imaju 5 cold i približno 33–40 warm, a dio je na 15 cold / 30 warm konfiguraciji. Zato prvi lokalni check prepoznaje postojeći 5/40 oblik kao rehab i 15/30 oblik kao comeback, umjesto da ih zbog trenutačnih 100% odmah proglasi full i prerano povisi cold limit.

## Što Smartlead warm-up score ne govori

Warm-up pool mjeri ponašanje unutar Smartleadove mreže. Stvarni receiveri imaju vlastite modele reputacije, rate limitinga, complaint signale i filtering. Google izričito navodi da Postmaster Tools prikazuje spam rate, reputaciju, autentikaciju i delivery errors za mail prema osobnim Gmail računima, uz kašnjenje koje je tipično do 24 sata i moguć nedostatak podataka kod malog volumena.^7 Google također navodi da reputation nije jedini faktor i da njezini reputation dashboardi mogu biti pogrešno protumačeni.^8

Zato je Smartlead score trigger za konzervativno smanjenje volumena, a ne dokaz da je deliverability izliječen. Pet dana na 100% je dobar operativni guardrail koji je tražen za ovaj workflow, ali povratak u full treba pratiti bounceovima, stvarnim replyovima i, gdje je dostupan, placement testom.

## Domene, blockliste i DNS

Za svaku domenu izvedenu iz aktivnih Smartlead sending mailboxova aplikacija provjerava:

- MX postoji li domena i ima li mail routing;
- SPF postoji li TXT zapis koji počinje s `v=spf1`;
- DMARC postoji li `_dmarc` zapis i je li policy `none`, `quarantine` ili `reject`;
- vanjski blacklist rezultat i točno ime providera;
- vrijeme DNS provjere, vrijeme blacklist provjere i idući planirani check.

DKIM se ne može korektno provjeriti samo iz domene jer treba selector. Aplikacija ga zato ne pogađa. Sljedeća iteracija može dobiti selector iz SmartDelivery DKIM reporta, iz provjerenih klijentskih postavki ili iz stvarnih outbound headera.

Google za sve sendere traži SPF ili DKIM, valjan forward/reverse DNS, TLS, RFC format i spam rate ispod 0,3%; za bulk sendere zahtjevi su stroži.^9 Yahoo također traži autentikaciju, nizak complaint rate i valjan DNS, a za bulk sendere SPF i DKIM, DMARC i jednostavan unsubscribe.^10 Sama činjenica da je DNS sintaktički prisutan zato nije isto što i DMARC alignment ili stvarni pass rate.

### Procjena blacklist izvora

**APIVoid Domain Reputation API** je odabran kao primarni vanjski provider. Jedan uspješan domain lookup troši jedan credit i vraća pojedinačni rezultat, confidence i referencu za svaki engine. Basic paket ima 50.000 credita, što je daleko iznad približno 1.170 mjesečnih provjera za 39 domena jednom dnevno.^11 Aplikacija sprema točan popis enginea koji je provider stvarno vratio. Prazan ili neispravan payload, timeout i HTTP greška ostaju `unknown`; nikada se ne pretvaraju u čisti rezultat. Zadnji poznati listing ostaje vidljiv tijekom privremenog outagea.

APIVoidov domain endpoint uključuje više threat-intelligence i phishing izvora, pa nije sam po sebi mjera Gmail/Microsoft inbox placementa. Spamhaus engine također traži zaseban Spamhaus DQS ključ. Zato se APIVoid koristi kao blacklist/abuse alarm uz Smartlead warmup, DNS autentikaciju i povremene SmartDelivery placement testove, a ne kao univerzalni “domain score”.

**MXToolbox** nije odabran: planovi s korisnim blacklist monitoringom ograničeni su na mali broj domena i ekonomski ne odgovaraju portfelju od približno 39 sending domena.

**Spamhaus DBL/DQS** je kvalitetan primarni izvor za domain reputation, ali njihov free DNS Query servis je prema aktualnim uvjetima za nekomercijalne male organizacije i pojedince. Komercijalna uporaba traži odgovarajuću licencu.^12 Uz to Spamhaus upozorava da upiti preko javnih resolvera ili DigitalOcean infrastrukture mogu vratiti posebne error rezultate umjesto valjanog listing statusa.^13 Zbog toga aplikacija ne radi nesiguran, nelicenciran `dbl.spamhaus.org` lookup preko Google DNS-a. Spamhaus se može dodati kao zaseban provider kad postoji DQS/WQS ključ s odgovarajućim pravima.

**SmartDelivery domain blacklist report** postoji u Smartlead API-ju, ali vezan je uz konkretan `spamTestId` i Smartlead navodi da je dio zasebnog SmartDelivery deliverability paketa.^14 Nije zamjena za neovisni daily domain monitor bez aktivnog testa.

## SmartDelivery placement testovi

SmartDelivery podržava manual i automated placement testove, provider-wise izvještaj, spam filter report, DKIM, SPF, rDNS, IP blacklist i domain blacklist izvještaje. API je na zasebnom `smartdelivery.smartlead.ai` hostu i Smartlead za pristup upućuje na support.^14

Smartlead navodi sedam besplatnih manual placement testova za početak, nakon čega je SmartDelivery zaseban plaćeni add-on. Automated test može raditi dnevno ili tjedno, ali troši placement credits.^15 Zbog toga ga ne treba pokretati za svaki mailbox svaki dan. Razumniji model je:

1. grupirati mailboxove po domeni i provideru;
2. mjesečno testirati reprezentativni mailbox svake aktivne domene;
3. odmah testirati domenu kada bilo koji mailbox uđe u rehab, kada DNS/auth upozorenje nastane ili kada bounce/reply trend naglo odstupi;
4. ne automatizirati kreiranje testova dok se ne potvrdi da klijent ima SmartDelivery entitlement i koliko creditsa troši jedan run.

Campaign Copy Warmup je dodatno dostupan samo na određenim SmartDelivery planovima, pa ga ne treba pretpostaviti kao osnovnu funkciju.^16

## Ostale mjere koje daju veći efekt od “domain scorea”

1. **Bounce i complaint guardrails.** Prekinuti ili smanjiti slanje kada bounce trend poraste, a ne čekati warm-up score. Gmail i Yahoo oba stavljaju complaint rate oko 0,3% kao gornju granicu; Google preporučuje ciljati ispod 0,1%.^9,10
2. **Verifikacija leadova prije slanja.** Catch-all i stari poslovni mailovi povećavaju hard/soft bounceove. Smartlead također preporučuje verification prije dodavanja leadova.
3. **Jedan sending alat po mailboxu.** Paralelni alati stvaraju neočekivani ukupni volumen i nepredvidiv cadence.
4. **Stabilan tempo.** Bez naglih burstova; Smartleadov vlastiti vodič navodi 10–15 minuta između slanja i postupan ramp-up nakon problema.^17
5. **SPF/DKIM/DMARC alignment, ne samo prisutnost.** DNS ekran je prva linija, a DMARC aggregate reports ili Postmaster Authentication dashboard potvrđuju stvarni pass.
6. **Isključeno open/click tracking kad nije potreban.** Tracking pixel i zajednički link-domain dodaju filter signale. Ovaj responder već dokumentira da su open/click podaci namjerno nepouzdani kad je tracking isključen.
7. **Segmentacija po receiving provideru.** Postojeći campaign deliverability modul već dijeli odgovore po Google/Microsoft/other MX grupama. Taj trend treba pokazati uz health ekran u kasnijoj iteraciji kako bi se razlikovao copy problem od provider-specific placement problema.
8. **Google Postmaster Tools.** Besplatno je i daje najbliži first-party signal za Gmail, ali mali cold-email volumeni često neće prijeći privacy threshold pa prazno nije “zdravo”.^7
9. **Yahoo Complaint Feedback Loop.** Koristan je za DKIM-signed mail prema Yahoo/AOL public mailboxovima i daje stvarne user complaints.^10
10. **Microsoft SNDS/JMRP samo kad ima smisla.** Za shared Google/Microsoft sending infrastrukturu obično se ne kontrolira outbound IP, pa IP-owner alati nisu potpuni domain-health proizvod. Placement testovi i stvarni bounce/reply trend ostaju praktičniji.

## Operativni rollout

Prva faza je monitor-only u sva tri containera. Konfigurirati `APIVOID_API_KEY`, pokrenuti ručni check, potvrditi popis domena i broj vraćenih enginea te riješiti DNS upozorenja. Webhook zatim može proslijediti samo nove probleme u željeni kanal.

Druga faza je dry-run automatskih prijelaza: uključiti `DELIVERABILITY_AUTO_APPLY=true`, ostaviti `DRY_RUN=true` i pet dana pregledavati phase history. Time se potvrđuje da dnevni scheduler ne broji više puta isti dan i da pragovi odgovaraju stvarnim mailboxovima.

Treća faza je kontrolirani write test na jednom mailboxu. Tek nakon potvrde polja uključiti `DRY_RUN=false` za cijeli klijentov container. Budući da svaki klijent ima vlastiti proces, DB i API key, Mindaptive, AeroDefense i OneBodyLDN ostaju potpuno odvojeni.

## Izvori

1. Smartlead. [Get All Email Accounts](https://api.smartlead.ai/api-reference/email-accounts/get-all).
2. Smartlead. [Get Email Account by ID](https://api.smartlead.ai/api-reference/email-accounts/get-by-id).
3. Smartlead. [Update Email Account](https://api.smartlead.ai/api-reference/email-accounts/update).
4. Smartlead. [Update Warmup Settings](https://api.smartlead.ai/api-reference/email-accounts/warmup-settings).
5. Smartlead. [How to enable AI email account warm-ups](https://helpcenter.smartlead.ai/en/articles/52-how-to-enable-ai-email-account-warm-ups).
6. Smartlead. [Get Warmup Statistics](https://api.smartlead.ai/api-reference/email-accounts/warmup-stats).
7. Google. [Postmaster Tools dashboards](https://support.google.com/mail/answer/14668346?hl=en).
8. Google. [Deprecation of the old Postmaster Tools interface](https://support.google.com/mail/answer/16594218?hl=en).
9. Google. [Email sender guidelines](https://support.google.com/mail/answer/81126?hl=en).
10. Yahoo Sender Hub. [Sender Best Practices](https://senders.yahooinc.com/best-practices/?is_listing=false).
11. APIVoid. [Domain Reputation API](https://docs.apivoid.com/domain-reputation-api/) i [Pricing](https://www.apivoid.com/pricing/).
12. Spamhaus Technology. [Terms of Use and Fair Use Policy for Blocklists via DNS Query](https://www.spamhaus.com/terms-of-use-fair-use-policy-for-free-data-query-service/).
13. Spamhaus Technology. [DigitalOcean users and the Data Query Service](https://www.spamhaus.com/resource-center/if-you-query-spamhaus-projects-legacy-dnsbls-via-digitalocean-move-to-the-free-data-query-service/).
14. Smartlead. [SmartDelivery Domain Blacklist API](https://api.smartlead.ai/api-reference/smart-delivery/domain-blacklist).
15. Smartlead. [SmartDelivery tests with non-connected accounts](https://helpcenter.smartlead.ai/en/articles/235-how-to-run-a-deliverability-test-in-smartdelivery-with-non-connected-email-accounts).
16. Smartlead. [Campaign Copy Warmup in SmartDelivery](https://helpcenter.smartlead.ai/en/articles/261-what-is-campaign-copy-warmup-in-smartdelivery-and-how-to-enable-it).
17. Smartlead. [Understanding Email Account Disconnection Reasons](https://helpcenter.smartlead.ai/en/articles/65-understanding-email-account-disconnection-reasons-in-smartlead).
