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

Una riga per store e una riga `TOTAL`:

- `catalog_product_count`: numero di prodotti canonici validi caricati dal catalogo JSON.
- `offer_count`: numero di record offerta nel database, preferendo `store_product_variants`; se vuota o assente usa `store_products`. Le due tabelle non vengono sommate, per evitare duplicati a livello URL.
- `valid_price_count` e `valid_price_pct`: prezzo numerico strettamente maggiore di zero e valuta EUR, sul totale offerte dello store.
- `valid_url_count` e `valid_url_pct`: URL assoluto HTTP/HTTPS con host.
- `valid_stock_count` e `valid_stock_pct`: disponibilità esplicita riconosciuta (`in_stock`, `out_of_stock`, `preorder`, `backorder`, `limited_availability`). Valori nulli o sconosciuti non sono validi.
- `ambiguous_match_count`: record che il matcher canonico in modalità conservativa classifica come `ambiguous`.
- `matched_count` e `unresolved_match_count`: contesto aggiuntivo per distinguere match risolti da record non associabili.
- `offer_source_table`: tabella SQLite utilizzata.

Le percentuali hanno come denominatore tutte le offerte conteggiate per quello store. Se uno store non ha record, non viene inventata una riga con percentuali: compare solo se ha offerte nel database.

## Interpretazione e limiti

Questo è un **baseline tecnico del catalogo locale**, non una certificazione che il prezzo sia corretto sul sito del negozio. La validità URL verifica la struttura HTTP/HTTPS, non il successo del link o il mercato corretto. La validità prezzo controlla numero positivo e EUR, non confronta il prezzo con la pagina live. La disponibilità valida indica uno stato esplicito e riconosciuto, non una verifica in tempo reale.

Il conteggio ambiguo usa il matcher canonico conservativo già presente in `scenthunter_next_engine`; non applica fuzzy matching. I record non associati restano separati come `unresolved`.

## Dati necessari per produrre il CSV

Il file `backend/store_catalog.sqlite3` è un database runtime e non è incluso nel repository. Per questo motivo il CSV popolato va generato nell'ambiente che contiene il database effettivo. Non è corretto sostituire i dati mancanti con stime o conteggi ricavati dai soli file scraper.
