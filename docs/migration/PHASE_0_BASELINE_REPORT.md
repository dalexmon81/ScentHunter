# Phase 0 — report quantitativo catalogo e offerte

## Generatore

Il report è prodotto da `backend/scenthunter_next_engine/baseline_report.py`.

Esecuzione dalla root del repository:

```bash
cd backend
python -m scenthunter_next_engine.baseline_report
```

Percorsi personalizzati:

```bash
python -m scenthunter_next_engine.baseline_report \
  --catalog ./product_catalog.json \
  --db ./store_catalog.sqlite3 \
  --output ./reports/phase-0-retailer-baseline.csv
```

Il generatore apre il database SQLite in modalità **sola lettura**. Non esegue scraping, non effettua chiamate di rete e non modifica catalogo o database.

## Contenuto CSV

Una riga per ciascuno dei **9 store attivi** (Amazon.de e Amazon.fr esclusi) e una riga `TOTAL`, anche quando uno store non ha offerte persistite:

- `indexed_url_count`: numero di URL prodotto attivi indicizzati in `store_urls`. È un conteggio di URL candidati, non di offerte verificate; viene mantenuto separato soprattutto per Notino.
- `catalog_product_count`: numero di prodotti canonici validi caricati dal catalogo JSON.
- `catalog_variant_count`: numero di varianti canoniche valide caricate dal catalogo JSON.
- `offer_count`: numero di offerte persistite nel database. Il generatore combina `store_product_variants` e `store_products` come fallback, evitando di ricontare la stessa URL base; non somma ciecamente le tabelle.
- `valid_price_count` e `valid_price_pct`: prezzo numerico strettamente maggiore di zero e codice valuta di tre lettere maiuscole, sul totale offerte dello store.
- `valid_url_count` e `valid_url_pct`: URL assoluto HTTP/HTTPS con host.
- `valid_stock_count` e `valid_stock_pct`: disponibilità esplicita riconosciuta (`in_stock`, `out_of_stock`, `preorder`, `backorder`, `limited_availability`). Valori nulli o sconosciuti non sono validi.
- `ambiguous_match_count`: record che il matcher canonico in modalità conservativa classifica come `ambiguous`.
- `matched_count` e `unresolved_match_count`: contesto aggiuntivo per distinguere match risolti da record non associabili.
- `offer_source_table`: tabella SQLite utilizzata.

Le percentuali hanno come denominatore tutte le offerte conteggiate per quello store. Se uno store non ha offerte, la sua riga resta presente con conteggio 0 e percentuali 0: non vengono creati record offerta fittizi.

## Interpretazione e limiti

Questo è un **baseline tecnico del catalogo locale**, non una certificazione che il prezzo sia corretto sul sito del negozio. La validità URL verifica la struttura HTTP/HTTPS, non il successo del link o il mercato corretto. La validità prezzo controlla numero positivo e EUR, non confronta il prezzo con la pagina live. La disponibilità valida indica uno stato esplicito e riconosciuto, non una verifica in tempo reale.

Il conteggio ambiguo usa il matcher canonico conservativo già presente in `scenthunter_next_engine`; non applica fuzzy matching. I record non associati restano separati come `unresolved`.

## Dati necessari per produrre il CSV

Il file `backend/store_catalog.sqlite3` è un database runtime e non è incluso nel repository. Per questo motivo il CSV popolato va generato nell'ambiente che contiene il database effettivo. Non è corretto sostituire i dati mancanti con stime o conteggi ricavati dai soli file scraper.

## Perimetro e stato runtime verificato

Il report comprende Bplatz, Deloox, ParfumCity, ParfumZentrum, PerfumeMarket, Sabina, Orioudh, Easycosmetic e Notino. Amazon.de e Amazon.fr sono esclusi dal CSV.

Il controllo runtime del 1 novembre 2026 ha restituito per Notino 9.000 URL indicizzati ma 0 offerte persistite. Il vecchio endpoint runtime ha risposto HTTP 503 perché rifiuta di produrre il CSV quando uno store ha URL ma nessuna offerta. Il generatore aggiornato non applica più quel blocco: emette la riga Notino con `indexed_url_count=9000` e `offer_count=0`, senza trasformare gli URL in offerte.

I test automatici di regressione per Notino senza offerte, conteggio URL e esclusione Amazon sono passati su GitHub Actions. Il CSV runtime completo resta da acquisire dopo l'aggiornamento del servizio che espone l'endpoint: il workflow attuale interroga ancora la versione runtime precedente. Non è stato eseguito alcun deploy durante la Fase 0.
