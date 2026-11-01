# ScentHunter — matrice degli store e dei connettori

**Branch di riferimento:** `refactor/catalog-first-architecture`  
**Data dell'audit statico:** 2026-11-01  
**Ambito:** sorgenti presenti in `backend/scrapers/` e relativi connettori.  
**Metodo:** lettura del codice versionato. Non è stato eseguito un test live su ogni negozio; la presenza di un file scraper non dimostra che il negozio sia raggiungibile o operativo in produzione.

## Legenda e cautele

- **Confermato nel codice** significa che l'endpoint o il parser è implementato nel branch esaminato.
- **Non configurato / non verificato** significa che il codice prevede la funzione, ma non è stata verificata la presenza di credenziali, autorizzazioni, feed attivo o risposte live.
- Gli URL di ricerca sono endpoint generici; gli URL prodotto sono URL individuali restituiti dal negozio, non un unico URL fisso.
- I campi elencati sono quelli letti o costruiti dall'adapter. Un campo può mancare nella singola risposta.
- Prezzo, disponibilità e variante devono essere verificati sulla pagina/prodotto corretto. Un risultato di ricerca o uno snippet esterno non equivale a un'offerta live verificata.

## Inventario

Nel percorso `backend/scrapers/` sono presenti 11 connettori retailer, oltre al client condiviso Amazon Creators API:

1. Amazon.de
2. Amazon.fr
3. Bplatz
4. Deloox
5. Easycosmetic
6. Notino
7. Orioudh
8. ParfumCity
9. ParfumZentrum
10. PerfumeMarket
11. Sabina

---

## Schede per store

### 1. Deloox

- **Sorgente:** `backend/scrapers/deloox/scraper.py`
- **Mercati/host ammessi nel codice:** `deloox.be`, `deloox.nl`, `deloox.com`, `deloox.lu`. Host primario configurato: `https://www.deloox.be`.
- **Ricerca:** route pubblica primaria `/chercher.html?q=...`; il codice prevede altre superfici generiche come fallback, paginazione limitata e discovery tramite categorie/sitemap se la ricerca non produce candidati.
- **URL prodotto:** link prodotto Deloox individuati dalla ricerca/categorie/sitemap e poi scaricati e validati. Non viene costruito un URL prodotto fisso.
- **Campi letti/esposti:** nome, marca quando disponibile, prezzo, valuta, disponibilità, immagine, volume ml, concentrazione e URL sorgente; identità/attributi possono includere dati strutturati della pagina e degli offer.
- **API/feed:** non risulta un feed affiliato o una API retailer dedicata nel connettore esaminato. Usa superfici pubbliche HTML e dati strutturati JSON-LD.
- **Varianti:** il parser controlla la dimensione richiesta rispetto ai dati prodotto e agli offer; considera dimensioni a livello prodotto e a livello offer senza confondere offer fratelli. Il volume non deve essere dedotto dal solo slug URL.
- **Disponibilità:** priorità ai segnali visibili e specifici della pagina prodotto; JSON-LD viene usato quando i controlli visibili non danno un segnale decisivo. Stati normalizzati includono `in_stock`, `out_of_stock` e stato non determinabile.
- **Problemi/rischi da verificare:** storico progetto: è stato segnalato un link Deloox che portava al mercato spagnolo. L'allowlist attuale non include `deloox.es`, ma occorre testare URL finali e redirect reali per ogni mercato. Il dominio/mercato deve restare coerente con l'offerta; non accettare un prezzo senza confermare volume e pagina finale. Le chiamate hanno timeout e limiti di discovery/paginazione: un timeout non equivale a prodotto inesistente.

### 2. Sabina

- **Sorgente:** `backend/scrapers/sabina/scraper.py`
- **Host:** `https://www.sabina.com`
- **Ricerca:** endpoint nativi generici `/es/buscar?search_query=...`, `/it/ricerca?s=...` e `/it/search?s=...`. Il codice usa anche Sellboost: `https://api.sellboost.com/finder/search`, con parametri shop/country/lingua/valuta configurati per Italia, oltre a fallback browser e sitemap.
- **URL prodotto:** link prodotto Sabina estratti dai risultati e normalizzati sul dominio Sabina.
- **Campi letti/esposti:** titolo/nome, marca, prezzo e fonte del prezzo, valuta EUR, URL, immagine, volume ml, dati JSON-LD e segnali di disponibilità; il parser può leggere SKU/GTIN quando presenti nei dati strutturati.
- **API/feed:** Sellboost è un endpoint di ricerca esterno effettivamente referenziato nel codice. Non equivale a un feed completo e non prova da solo la disponibilità di ogni prodotto. La pagina prodotto resta necessaria per validare prezzo, variante e stock. Nessun feed affiliato statico è documentato nel file.
- **Varianti:** estrae il volume da campi specifici della pagina prodotto, selettori variante e titolo. Evita di usare le card di prodotti correlati come fonte primaria del volume.
- **Disponibilità:** prima controlla controlli di acquisto specifici del prodotto; poi segnali strutturati di esaurimento e blocchi di notifica/data disponibilità. Se non c'è evidenza affidabile, restituisce `unknown`.
- **Problemi/rischi da verificare:** ricerca e parametri Sellboost sono configurati per il mercato italiano mentre l'host è condiviso; verificare che link, lingua, valuta e mercato siano coerenti. Il fallback sitemap è limitato e la discovery browser ha timeout. Un risultato trovato dal motore di ricerca non prova da solo lo stock.

### 3. Easycosmetic

- **Sorgente:** `backend/scrapers/easycosmetic/scraper.py`
- **Host:** `https://www.easycosmetic.de`
- **Ricerca:** `/suche?searchfor={query}`.
- **URL prodotto:** URL di prodotto sul dominio tedesco; i parametri di tracking vengono rimossi. Se è presente un ID numerico `variant`, viene conservato.
- **Campi letti/esposti:** nome, marca, prezzo, valuta, disponibilità, immagine, volume ml, concentrazione, URL e identificatore variante quando disponibile nei dati pagina.
- **API/feed:** non risulta un feed/API retailer dedicato nel connettore. Ricerca HTML, parsing pagina e JSON-LD.
- **Varianti:** seleziona il JSON-LD Product corrispondente all'URL/ID variante richiesto. Se un ID variante richiesto non trova un oggetto strutturato corrispondente, il parser non deve assegnare silenziosamente i dati di un'altra variante. Gli URL di altri mercati non vengono riscritti sul dominio tedesco.
- **Disponibilità:** letta da Offer JSON-LD e segnali della pagina; se i dati sono incompleti può restare sconosciuta.
- **Problemi/rischi da verificare:** un URL variante senza corrispondenza nei dati strutturati può produrre un'offerta incompleta, scelta corretta rispetto a un prezzo errato. Il connettore è legato al mercato `.de`: non riutilizzare automaticamente prezzi o URL su altri mercati.

### 4. ParfumZentrum

- **Sorgente:** `backend/scrapers/parfumzentrum/scraper.py`
- **Host:** `https://www.parfum-zentrum.de`
- **Ricerca:** `/suchen/`; sitemap `/sitemap.xml` come fallback quando la discovery di ricerca non restituisce candidati. La sitemap è memorizzata in cache in-process per 30 minuti.
- **URL prodotto:** link prodotto estratti dalla ricerca o sitemap, normalizzati e verificati prima del parsing.
- **Campi letti/esposti:** nome, marca quando disponibile, prezzo EUR, valuta, disponibilità, URL, volume e concentrazione come attributi, immagini e dati JSON-LD/HTML.
- **API/feed:** nessuna API/feed retailer dedicata individuata nel file. Usa ricerca HTML, sitemap e JSON-LD/elementi semantici della pagina.
- **Varianti:** **limite importante:** il codice dichiara che volume e concentrazione vengono estratti come attributi, ma non sono usati per decidere identità canonica o selezione della variante. Non considerare quindi garantito il match esatto del formato solo perché il parser restituisce un volume.
- **Disponibilità:** parsing dei segnali testuali specifici, controllando prima i marcatori negativi (es. non disponibile) per evitare falsi `in_stock`; usa anche Offer JSON-LD.
- **Problemi/rischi da verificare:** il punto più critico è la separazione tra taglia estratta e selezione effettiva della variante. Prima di pubblicare un'offerta, serve un controllo indipendente che confermi volume/concentrazione della pagina e dell'offerta. La ricerca a zero risultati è trattata come autorevole e impedisce il recupero indiscriminato di vecchi URL da sitemap.

### 5. Bplatz

- **Sorgente:** `backend/scrapers/bplatz/scraper.py`
- **Host:** `https://en.bplatz.de`
- **Ricerca:** Shopify Predictive Search `/search/suggest.json`; Shopify Search JSON `/search.json`; catalogo pubblico `/products.json`; sitemap `/sitemap.xml`; fallback HTML `/search`.
- **URL prodotto:** URL Shopify `/products/{handle}`, normalizzato sul dominio Bplatz.
- **Campi letti/esposti:** nome, marca/vendor, URL, immagine, prezzo e prezzo numerico, valuta EUR, volume ml, concentrazione, disponibilità; identificativo prodotto ricavabile dall'URL. Il parser usa JSON-LD Product/Offer quando presente.
- **API/feed:** endpoint pubblici Shopify JSON e sitemap; non è un feed affiliato. La pagina prodotto finale è dichiarata fonte autorevole per prezzo e stock.
- **Varianti:** discovery Shopify può individuare il prodotto ma non garantisce da sola la variante corretta. Volume e concentrazione sono estratti da titolo/dati pagina; il record esposto non deve essere considerato una variante Shopify univoca se manca un ID variante.
- **Disponibilità:** JSON-LD Offer e segnali testuali; i marcatori negativi (sold out/unavailable) sono valutati prima dei positivi.
- **Problemi/rischi da verificare:** l'endpoint catalogo può fornire candidati, non prova che la variante sia acquistabile. Il parser deve confermare il prezzo sulla pagina prodotto. Timeout, blocchi HTTP e catalogo Shopify incompleto devono restare errori tecnici, non diventare offerte o assenza prodotto.

### 6. Notino

- **Sorgenti:** `backend/scrapers/notino/scraper.py`, `affiliate_feed.py`, `legacy_public.py`
- **Host principale nel codice:** `https://www.notino.fr`
- **Ricerca pubblica:** `/search.asp?exps={query}` e `/search?query={query}`; il codice prova query normalizzate, parsing HTML/JSON-LD, reader esterno Jina e sitemap come fallback.
- **URL prodotto:** URL Notino riconosciuti e validati sul mercato configurato; la pagina prodotto viene analizzata per titolo, prezzo EUR, disponibilità e taglia.
- **Campi letti/esposti:** nome, marca, prezzo, valuta, stock, volume ml, concentrazione, URL e immagine quando disponibili. Il feed affiliato può fornire SKU, GTIN/EAN, prezzo, valuta, disponibilità, brand, titolo e link.
- **API/feed:** esiste un parser di feed XML CJ/VIV in `affiliate_feed.py`. La candidatura publisher per Notino.fr è stata inviata correttamente e risulta **Pending Application / Application submitted for review**: Notino approva manualmente i publisher. Fino all'approvazione, URL del feed e credenziali non sono disponibili/verificabili; la presenza del parser **non dimostra che il feed sia configurato o accessibile**. Esiste inoltre il percorso pubblico HTML legacy.
- **Varianti:** il parser pubblico estrae taglia e concentrazione da titolo/dati pagina e valida la pagina prodotto. Il feed richiede un volume identificabile per accettare un record. Non confondere prodotti di mercati Notino differenti.
- **Disponibilità:** feed normalizza `in_stock`, `out_of_stock`, `preorder` e `unknown`; il parser pubblico usa segnali di stock/Offer JSON-LD e pagina.
- **Stato affiliazione:** candidatura Notino.fr inviata, in attesa di approvazione manuale. Nessuna credenziale/feed XML va simulata o sostituita con dati inventati. I 114 URL già individuati sono candidati URL prodotto, non 114 offerte validate.
- **Problemi/rischi da verificare:** le ricerche pubbliche e le sitemap possono essere bloccate o instabili; il reader esterno è un fallback, non fonte primaria di prezzo live. Dopo l'approvazione si recuperano URL feed e credenziali, che vanno verificati senza esporre segreti. Il mercato attuale nel codice è FR: non va presentato come prezzo di un altro paese senza una fonte locale.

### 7. Orioudh

- **Sorgente:** `backend/scrapers/orioudh/scraper.py`
- **Host:** `https://orioudh.com`
- **Ricerca:** Shopify Predictive Search `/search/suggest.json`, con fallback alla ricerca HTML `/search`.
- **URL prodotto:** link Shopify `/products/{handle}`; il connettore interroga anche `/products/{handle}.js` per leggere il prodotto.
- **Campi letti/esposti:** titolo, vendor/marca, prezzo, valuta EUR, disponibilità, immagini, volume ml, concentrazione e identificatori GTIN/SKU/ID prodotto/variante quando forniti da Shopify.
- **API/feed:** endpoint pubblici Shopify JSON (`search/suggest.json` e `products/{handle}.js)); non è un feed affiliato.
- **Varianti:** legge le varianti Shopify e i relativi prezzi/attributi. I prezzi Shopify possono essere espressi in centesimi interi (es. 3185 = 31,85 EUR): il parser contiene una conversione specifica. L'ID variante deve essere mantenuto quando disponibile.
- **Disponibilità:** `available` Shopify e segnali testuali vengono normalizzati in `in_stock`/`out_of_stock`.
- **Problemi/rischi da verificare:** conversione prezzo in centesimi e associazione prezzo-stock alla stessa variante sono punti sensibili. Un errore di scala produrrebbe prezzi 100 volte maggiori/minori. Le richieste possono essere bloccate (403/429) o andare in timeout; non trasformare tali stati in zero risultati.

### 8. ParfumCity

- **Sorgente:** `backend/scrapers/parfumcity/scraper.py`
- **Host:** `https://www.parfumcity.nl`
- **Ricerca:** Shopify Predictive Search `/search/suggest.json`, `/search.json`, catalogo `/products.json`, sitemap `/sitemap.xml` e fallback HTML `/search?q=...`.
- **URL prodotto:** URL Shopify `/products/{handle}`. Il normalizzatore collassa prefissi locali `/de`, `/en`, `/fr`, `/es` sul dominio canonico configurato.
- **Campi letti/esposti:** titolo, vendor/marca, URL, prezzo, valuta EUR, immagine, volume ml e concentrazione; il JSON Shopify può contenere ID prodotto, SKU, varianti e disponibilità.
- **API/feed:** endpoint pubblici Shopify JSON e sitemap; nessun feed affiliato dedicato individuato.
- **Varianti:** il codice legge il catalogo e le varianti Shopify. La normalizzazione dell'URL rimuove query string: non assumere che un URL con parametro variante rimanga selezionato. Verificare che prezzo e disponibilità appartengano alla stessa variante scelta.
- **Disponibilità:** ricavata dai dati Shopify/variante e dalla pagina prodotto; se mancante deve restare sconosciuta.
- **Problemi/rischi da verificare:** la rimozione dei parametri URL può perdere l'ID variante; verificare quindi se il record finale conserva l'identificativo variante separatamente. La normalizzazione dei prefissi locali non prova che prezzi/stock siano uguali tra mercati.

### 9. PerfumeMarket

- **Sorgente:** `backend/scrapers/perfumemarket/scraper.py`
- **Host:** `https://www.perfumemarket.nl`
- **Ricerca:** parsing delle card HTML e catalogo pubblico Shopify `/products.json?limit=250` e `/collections/all-perfumes/products.json?limit=250` con paginazione.
- **URL prodotto:** URL Shopify `/products/{handle}`, ripulito dai parametri query.
- **Campi letti/esposti:** titolo/nome, marca/vendor, prezzo, URL, testo prodotto; il catalogo Shopify espone anche ID, handle, immagini e array di varianti.
- **API/feed:** catalogo pubblico Shopify JSON; non è un feed affiliato.
- **Varianti:** il codice scorre le varianti e preferisce una variante disponibile quando Shopify espone `available`, ma alcuni percorsi di parsing restituiscono un prezzo di prodotto/una prima variante e un URL prodotto senza variante esplicita. Non è quindi garantito che ogni offerta sia un record variante distinto.
- **Disponibilità:** il percorso Shopify considera `available` e conserva anche prodotti esauriti affinché lo stato possa essere riportato a valle. Le card HTML possono invece contenere solo prezzo e URL, senza stock affidabile.
- **Problemi/rischi da verificare:** rischio di prezzo di una variante associato all'URL generico del prodotto o di stato stock non corrispondente alla variante. Serve testare prodotti multi-taglia e mantenere variante/stock/prezzo insieme. La ricerca di catalogo è ampia e può avere paginazione/costi di rete.

### 10. Amazon.de

- **Sorgente:** `backend/scrapers/amazon_de/scraper.py` + client condiviso `backend/scrapers/amazon_creators_api.py`
- **Host:** `https://www.amazon.de`
- **Ricerca pubblica:** pagina risultati Amazon con query di ricerca; se il sito blocca o non restituisce risultati utilizzabili, esiste un fallback Bing RSS che cerca ASIN, titolo e prezzo EUR nello snippet.
- **URL prodotto:** link canonico costruito come `https://www.amazon.de/dp/{ASIN}`, dopo validazione dell'ASIN/host.
- **Campi letti/esposti:** titolo, marca inferita dal titolo/query quando non fornita, prezzo numerico/formattato, valuta EUR, immagine, volume ml e concentrazione. Nel percorso HTML pubblico la disponibilità è normalmente `None`; la provenienza prezzo/snippet è annotata.
- **API/feed:** Amazon Creators API condivisa, se credenziali marketplace-specifiche sono presenti e `AMAZON_CREATORS_API_COMPARISON_APPROVED` è abilitato. Richiede client ID/secret e approvazione esplicita; non è lecito presumere che sia configurata. Il fallback pubblico non è una API.
- **Varianti:** volume e concentrazione vengono estratti dal titolo; il match deve rifiutare titoli non coerenti. Il solo ASIN/slug non prova che formato e concentrazione siano quelli richiesti.
- **Disponibilità:** Creators API accetta solo listing con disponibilità ammessa; HTML pubblico lascia stock sconosciuto. Lo snippet Bing non è verifica live della pagina prodotto.
- **Problemi/rischi da verificare:** blocchi 403/429, timeout e risultati senza prezzo. Un prezzo preso da snippet esterno deve essere marcato come non live e non confrontato come offerta verificata. La disponibilità non va inventata. Credenziali/approvazione API non verificate.

### 11. Amazon.fr

- **Sorgente:** `backend/scrapers/amazon_fr/scraper.py` + client condiviso `backend/scrapers/amazon_creators_api.py`
- **Host:** `https://www.amazon.fr`
- **Ricerca pubblica:** pagina risultati Amazon con query di ricerca; fallback Bing RSS quando necessario.
- **URL prodotto:** `https://www.amazon.fr/dp/{ASIN}`, dopo validazione del marketplace.
- **Campi letti/esposti:** titolo, marca inferita quando non disponibile, prezzo, EUR, immagine, volume ml e concentrazione; stock nullo nel percorso HTML pubblico.
- **API/feed:** stessa Creators API condivisa, solo con credenziali e approvazione esplicita per il confronto prezzi. Configurazione effettiva non verificata.
- **Varianti:** volume/concentrazione estratti dal titolo; l'ASIN deve essere collegato al prodotto e alla variante richiesti.
- **Disponibilità:** Creators API può restituire disponibilità del listing; percorso HTML e snippet esterni non garantiscono stock.
- **Problemi/rischi da verificare:** stessi limiti di Amazon.de: blocchi, timeout, snippet non live e stock sconosciuto. Mantenere rigorosamente il dominio FR e non riutilizzare link/prezzi DE.

---

## Problemi trasversali da tenere sotto controllo

1. **Identità variante:** alcuni adapter estraggono il volume ma non lo usano per selezionare la variante (ParfumZentrum); altri restituiscono URL prodotto generici anche quando leggono varianti Shopify (PerfumeMarket, da testare anche ParfumCity).
2. **Prezzo e stock accoppiati:** prezzo, disponibilità, volume e ID variante devono provenire dallo stesso offer/variant, non da elementi diversi della pagina.
3. **URL mercato:** conservare il dominio corretto per il paese e validare la URL finale dopo redirect. Non convertire automaticamente link di un mercato in un altro.
4. **Stati tecnici:** blocked, rate-limited, timeout, errore parser e credenziali mancanti non sono equivalenti a prodotto inesistente o out of stock.
5. **Snippet esterni:** Bing/Jina e card di ricerca sono strumenti di discovery/fallback; non vanno trattati automaticamente come prezzo/stock live.
6. **Credenziali/feed:** il codice del connettore non dimostra che il servizio sia autorizzato, configurato o raggiungibile. Non inserire segreti nel repository o nel documento.
7. **Copertura live:** questa matrice è un audit statico. Per dichiarare uno store operativo servono test controllati con URL prodotto reali, varianti note, prezzo, stock, mercato e data/ora di verifica.

## Esito dell'audit statico

- **11** directory/store scraper identificati.
- **1** client condiviso Amazon Creators API.
- **Notino:** candidatura publisher Notino.fr inviata e Pending Application; parser XML già presente, feed e credenziali in attesa dell'approvazione.
- **Amazon DE/FR:** integrazione Creators API condizionata a credenziali e approvazione; fallback HTML/snippet con limiti espliciti.
- **Shopify JSON pubblici:** presenti per Bplatz, Orioudh, ParfumCity e PerfumeMarket.
- **Nessuna conclusione di disponibilità live** viene dedotta dalla sola presenza del codice.
