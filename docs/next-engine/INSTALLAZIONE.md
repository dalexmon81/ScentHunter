# ScentHunter — istruzioni d'installazione (fase isolata)

## Stato attuale

Il package è isolato e i test offline passano. **Non è ancora collegato al catalogo pubblico e non è pronto per l'attivazione in produzione.** Questa consegna non sostituisce `backend/main.py`, `backend/catalog_engine.py`, gli scraper attuali o il database esistente.

## Importante se stai usando iPhone

Non devi estrarre l'archivio dall'iPhone né modificare file esistenti dal telefono. L'archivio è una consegna del codice, non un aggiornamento già installato. Conserva il collegamento; non caricare file singoli a caso e non attivare variabili di produzione.

## Struttura del pacchetto

- `backend/scenthunter_next_engine/` — codice nuovo da aggiungere al repository;
- `tests/` — test offline;
- `README.md` — panoramica;
- `TEST_RESULTS.txt` — test eseguiti e limiti della verifica.

## Se lavori da un ambiente di sviluppo

1. Estrai l'archivio nella cartella di lavoro.
2. Copia **l'intera cartella** `backend/scenthunter_next_engine/` nel repository, mantenendo la sottocartella `adapters/`.
3. Non sovrascrivere `backend/main.py`, `backend/catalog_engine.py`, il database o gli scraper attuali.
4. Dalla radice della cartella estratta esegui `PYTHONPATH=backend python -m unittest discover -s tests -v`.
5. Non aggiungere ancora il mount API in `main.py` e non impostare `SCENTHUNTER_NEXT_ENABLED=1`.

## Condizioni prima dell'integrazione

Prima di collegare l'API al backend servono ancora:

1. test su HTML Deloox reale raccolto in modo consentito;
2. verifica che il package sia compatibile con le dipendenze e l'import path del backend attuale;
3. database SQLite nuovo e separato dal catalogo esistente;
4. confronto shadow fra offerte vecchie e nuove;
5. verifica di URL, identità prodotto/variante, prezzi e valute;
6. piano di rollback.

Non cancellare il catalogo e non resettare le code esistenti.
