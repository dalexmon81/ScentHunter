# Esportazione SQLite legacy in sola lettura

Questo comando legge lo schema reale usato da `backend/catalog_engine.py` (`store_urls`, `store_products`, `store_product_variants`) senza importare il motore legacy, eseguire migrazioni o inviare richieste HTTP. Apre il database con SQLite `mode=ro` e `PRAGMA query_only=ON`.

```sh
PYTHONPATH=backend python -m scenthunter_next_engine.sqlite_export \
  --db /data/store_catalog.sqlite3 \
  --store deloox \
  --limit-per-table 50000 \
  --output /tmp/scenthunter-deloox-snapshot.json
```

Sostituire `--db` solo con il percorso effettivamente configurato nell'ambiente in cui viene eseguito il comando. Non usare `catalog_engine.db()`: quella funzione può creare o migrare tabelle. Il percorso di output deve essere diverso dal database. I limiti sono per tabella; `truncated: true` indica che occorre ripetere l'esportazione con un limite più alto.

Il file JSON risultante può essere fornito direttamente al confronto shadow:

```sh
PYTHONPATH=backend python -m scenthunter_next_engine.shadow_runner \
  --legacy /tmp/scenthunter-deloox-snapshot.json \
  --next /tmp/scenthunter-next-snapshot.json \
  --output /tmp/scenthunter-shadow-report.json
```

Il formato snapshot legacy è riconosciuto dal runner: usa le varianti persistite quando disponibili e i prodotti base per URL senza varianti. Per una comparazione reale serve comunque un export del nuovo motore con righe normalizzate compatibili. Questo pacchetto non legge autonomamente il filesystem Fly remoto e non esegue operazioni sul database live.


## Esportazione del nuovo motore

Dopo aver popolato il database separato del nuovo motore, esportarlo in sola lettura:

```sh
PYTHONPATH=backend python -m scenthunter_next_engine.next_sqlite_export \
  --db /data/scenthunter_next.sqlite3 \
  --store deloox \
  --output /tmp/scenthunter-next-snapshot.json
```

Il percorso indicato in `--db` deve essere quello reale del database separato del nuovo motore. L'esportatore rifiuta database che non contengono lo schema atteso (`products`, `variants`, `offers`). Confrontare i due snapshot con il comando documentato in `SHADOW_RUNNER.md`. Entrambi gli esportatori aprono il database sorgente in sola lettura.
