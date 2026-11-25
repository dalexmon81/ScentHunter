# FASE 0 — Fotografia aggiornata ScentHunter
**Data:** 25 novembre 2026  
**Repository:** `dalexmon81/ScentHunter`  
**Commit main fotografato:** `e771019db37f035261da543b47edc4750244aeaa`  
**Esito:** inventario GitHub e Neon aggiornato; Fase 0 **NON CHIUSA** per due blocchi esterni: fotografia runtime Fly non eseguita e backup Neon fresco non creabile con i limiti attuali.

## Regole applicate durante l'audit
- Nessun merge, deploy, restart, import o modifica ai secret.
- Nessuna scrittura SQL sui database operativi.
- Nessuna cancellazione di branch, file, workflow, record o volumi.
- Tutte le query Neon eseguite sono SELECT/catalog inspection.
- La branch Git di questo report parte dal commit fotografato; `main` non è stata modificata.

## 1. GitHub

| Elemento | Evidenza |
|---|---|
| `main` | `e771019db37f035261da543b47edc4750244aeaa` |
| Branch Git elencati | 78 |
| PR aperte | 16 |
| PR #927 Notino direct | Aperta, non integrata |
| Snapshot Git | `phase0-git-snapshot-2026-11-25`, confronto con `main`: identical, 0 commit ahead/behind |
| Branch di questo report | `docs/phase0-current-audit-2026-11-25` |

Il lavoro non è globalmente congelato: sono presenti 16 PR aperte e numerosi branch operativi. In questa sessione è stato rispettato il blocco: nessuna PR è stata integrata e nessun commit è stato inviato a `main`. La protezione e le regole di blocco lato repository/team non sono state modificate né verificate con un endpoint amministrativo dedicato.

## 2. Fly.io e frontend

### Configurazione versionata
`fly.toml` identifica:
- App: `scenthunter`, regione primaria `ams`.
- Processo HTTP: `uvicorn postgres_main:app`.
- Processo worker: `python -m app.workers.postgres_worker`.
- Coda: PostgreSQL.
- `SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL=1`.
- Cutoff coda: `SCENTHUNTER_QUEUE_MIN_CREATED_AT=2026-11-23T08:27:00Z`.
- Nessun volume mount dichiarato nel file `fly.toml`.

`fly.staging.toml` / `.github/workflows/fly-pilot.yml` sono un ambiente pilota separato: app `scenthunter-pilot-20261030`, SQLite e volume `/data`. Non vanno confusi con l'app di produzione.

### Dipendenze CJ ancora attive su main
Il workflow di produzione `.github/workflows/fly.yml`:
- richiede i secret GitHub CJ;
- prepara `NOTINO_CJ_FEED_URL`, username e password come Fly secrets staged;
- abilita `SCENTHUNTER_ACTIVE_OFFER_REFRESH_ENABLED=1`;
- esegue il deploy dell'app PostgreSQL.

Il workflow `.github/workflows/notino-cj-feed-import.yml` ha schedule giornaliero `17 5 * * *` e dispatch manuale. Il workflow `.github/workflows/notino-cj-production-feed-monitor.yml` ha schedule ogni 6 ore (`17 */6 * * *`). Pertanto CJ/VIV non è un residuo inattivo: è ancora una dipendenza operativa dichiarata su `main`. La PR #927 che propone di sostituire il runtime Notino con il connettore diretto non è stata integrata.

### Diagnostica Fly non eseguita
È presente `.github/workflows/scenthunter-readonly-fly-diagnostics.yml`, manuale, progettato per leggere:
- stato app, macchine e volumi;
- nomi dei secret (non i valori);
- backend/driver database, host e nome database;
- presenza dei due percorsi SQLite storici.

Il workflow non effettua deploy, restart, migrazioni, import, aggiornamenti secret o scritture DB. Non è stato possibile dispatcharlo da questa sessione: gli strumenti GitHub disponibili non espongono un'azione workflow-dispatch e non è disponibile un connettore Fly.io. I tentativi di aprire gli endpoint pubblici Fly tramite il canale web non hanno restituito una risposta leggibile. Quindi macchine, volumi, secret names e connessione DB effettivamente iniettata nella macchina Fly **non sono verificati in tempo reale**.

### Frontend
- `backend/postgres_main.py` include `catalog_search_router` e `phase0_baseline_router`.
- `/` e `/frontend` reindirizzano a `/catalog-demo`.
- `/catalog-demo` è servito dal router `backend/app/api/catalog_search.py` e chiama `/api/catalog/search`.
- `frontend/index.html` è presente nel repository, ma non è il target del redirect configurato nel runtime versionato. Non va dichiarato come frontend effettivamente servito senza la verifica Fly live.

## 3. Neon: progetto, branch e database

Progetto Neon: `Scenthunter` (`square-math-01119225`), regione `aws-eu-central-1`.

Il progetto ha 10 branch elencati e il tentativo di crearne un undicesimo è stato rifiutato con `branches limit exceeded`.

| Branch | Ruolo |
|---|---|
| `production` (`br-dry-water-ban3a63s`) | Branch predefinito; database `neondb`, non è il database operativo catalogo |
| `offer-first-postgres-cutover` (`br-red-night-ba3reqhp`) | Branch operativo esaminato; database `scenthunter_offerfirst` |
| `phase0-verified-backup-2026-11-24-compute` (`br-odd-heart-bale2lvj`) | Copia verificabile figlia del branch operativo, creata il 24/11 alle 06:15 UTC |
| `phase0-restore-drill-2026-11-24` | Branch di restore drill |
| Altri branch | Snapshot/audit/recovery storici; non cancellati |

### Conteggi attuali — branch operativo, database `scenthunter_offerfirst`
Query di sola lettura del 25/11:

| Oggetto | Record |
|---|---:|
| brands | 65 |
| fragrances | 1.403 |
| product_variants | 556 |
| stores | 10 |
| offers attive | 167 |
| ingestion_runs | 62.500 |
| ingestion_raw | 60.089 |

Distribuzione delle offerte attive:
- Bplatz: 28
- Notino.fr: 108
- Parfumzentrum.de: 7
- Sabina.es: 24
- Deloox.be: 0
- Easycosmetic.de: 0

### Stato negozi
Sei store risultano attivi: Bplatz, Deloox.be, Easycosmetic.de, Notino.fr, Parfumzentrum.de e Sabina.es. Quattro store Deloox internazionali (`deloox-com`, `deloox-es`, `deloox-lu`, `deloox-nl`) risultano inattivi.

Gli store attivi hanno `last_successful_sync_at` recente (25/11), ma questo non equivale a copertura di offerte valide: Deloox.be ed Easycosmetic.de hanno zero offerte attive. Notino ha 108 offerte attive, ma le catture delle offerte presenti vanno dal 23/11 al 24/11, mentre l'ultimo sync registrato è del 25/11. Occorre distinguere run riuscito, dato acquisito e offerta pubblicabile.

### Coda e run
- Job queued: 75.427.
- Job queued creati prima del cutoff Fly 23/11 08:27 UTC: 73.763.
- Job queued creati dopo il cutoff: 1.664.
- Job running: 2.
- Ingestion run running: 35; 25 più vecchi di 24 ore e 8 più vecchi di 72 ore.
- Ingestion run partial: 51.632.
- Ingestion run completed: 10.814.
- Ingestion run failed: 19.

I record non sono stati modificati. Il cutoff configurato esclude la maggior parte del backlog storico; la ragione e la strategia di riconciliazione sono da trattare in un'attività successiva, non da correggere durante l'inventario.

### Backup Neon: limite non risolto
La branch `phase0-verified-backup-2026-11-24-compute` è pronta e interrogabile, ma è una copia al 24/11 06:14:48 UTC. Conteggi allora: 65 brands, 1.403 fragrances, 556 variants, 10 stores, 163 offers, 50.128 ingestion runs, 48.100 ingestion_raw e 173.039 queue jobs.

La snapshot manuale esistente `scenthunter-phase0-before-cleanup-2026-11-24` ha come sorgente il branch predefinito `production`, non il branch operativo. Il tentativo di creare una snapshot dal branch operativo è stato rifiutato: `not allowed to snapshot non-root branch`. Il tentativo di creare una nuova branch backup è stato rifiutato: `branches limit exceeded`.

**Conclusione:** esiste una copia storica verificabile, ma non è stato possibile creare una copia aggiornata al 25/11. Non è stato cancellato alcun branch per liberare spazio: sarebbe contrario alla regola di mappare le dipendenze prima delle eliminazioni.

## 4. Mappa dei sistemi e dipendenze

### Runtime canonico da preservare
- `backend/postgres_main.py`
- `backend/app/api/catalog_search.py`
- `backend/app/api/phase0_baseline.py` (endpoint read-only autenticato `/admin/phase0/postgres-baseline`)
- `backend/app/search/catalog.py`
- `backend/app/models/`, migrazioni Alembic e repository PostgreSQL
- `backend/app/connectors/base.py`
- `backend/app/workers/postgres_worker.py`
- `backend/app/workers/legacy_runtime.py`
- `backend/app/offers/`, `app/matching/`, `app/pricing/`, `app/repositories/`

### Componenti legacy ancora dipendenti
- `backend/main.py`: vecchio runtime FastAPI, route `/search-start`, ricerca e refresh legacy, numerosi router diagnostici.
- `backend/catalog_engine.py`: catalogo/ricerca/discovery legacy, SQLite e funzioni importate da script, diagnostica, Next Engine e feed Notino.
- `backend/product_matcher.py`: matching legacy ancora usato dal vecchio runtime e dai test.
- `backend/product_catalog.json`: identità catalogo usata da fallback Notino, Next Engine, seed/backfill e test.
- `backend/family_registry.json`: alias/famiglie usati da legacy matcher, catalog family coverage e test.
- `backend/scrapers/notino/affiliate_feed.py`: parser XML CJ/VIV; importa anche helper DB/URL legacy da `catalog_engine`.
- `backend/app/connectors/notino_feed.py` e `backend/app/workers/notino_runtime.py`: percorso Notino operativo corrente basato su CJ/VIV; il runtime usa ancora `product_catalog.json` come fallback matcher.
- `backend/app/search/catalog.py`: mantiene validazione dei link affiliati CJ e lettura del timestamp sorgente XML.
- `backend/offer_engine/refresh_worker.py`: worker separato con supporto SQLite; disabilitato per default se `SCENTHUNTER_OFFER_ENGINE_REFRESH_WORKER_ENABLED` non è `1`; non è il processo worker dichiarato in `fly.toml`.
- `backend/phase0_baseline_worker.py` e `backend/scenthunter_next_engine/phase0_baseline_jobs.py`: vecchia coda SQLite `/data/phase0/phase0_jobs.sqlite3`, legge catalogo JSON e SQLite retailer DB e produce CSV; non è il worker di produzione dichiarato in `fly.toml`.
- Script di ingestione, bootstrap, seed, backfill, audit, diagnostica e test che importano i moduli legacy.

Nessuno di questi elementi è autorizzato alla cancellazione in Fase 0.

## 5. CJ, Notino Feed, XML, CSV e import

### CJ/VIV e XML
Il feed CJ/VIV è tuttora parte del percorso Notino su `main`:
- URL feed Notino.fr configurato nel workflow di deploy;
- credenziali richieste tramite GitHub Actions secrets e staged su Fly;
- import schedulato giornalmente;
- parser autenticato ZIP/XML in `affiliate_feed.py`;
- normalizzazione di prodotti/offerte, raw XML, click URL CJ e destinazione Notino;
- connector e worker Notino PostgreSQL;
- monitor ogni sei ore e workflow diagnostici.

Il workflow di deploy `fly.yml` e l'import schedulato contraddicono l'idea che CJ sia già stato rimosso. La PR #927 propone la sostituzione, ma non è integrata. La prova live della nuova discovery diretta è fallita: Notino ha restituito 403 alle richieste dirette e il reader alternativo 401; per le cinque query del test non sono stati scoperti prodotti. Non si deve dichiarare completata la sostituzione.

### CSV
Non è stato trovato un feed CSV di retailer che alimenti il catalogo canonico. Il CSV è usato come output di report/baseline:
- `backend/scenthunter_next_engine/baseline_report.py` legge `product_catalog.json` e SQLite in modalità read-only e scrive `phase-0-retailer-baseline.csv`.
- Il vecchio worker `phase0_baseline_jobs.py` scrive CSV su `/data/phase0/baseline`.
- `.github/workflows/phase-0-smoke-test.yml` tenta ancora i vecchi endpoint `/admin/phase0/health`, `/smoke/start`, `/smoke/status`, `/smoke/download`; questi non corrispondono all'endpoint PostgreSQL attuale.

### Baseline PostgreSQL
È presente una nuova API read-only autenticata: `/admin/phase0/postgres-baseline`, implementata in `backend/app/api/phase0_baseline.py` e inclusa in `postgres_main.py`. Il workflow `phase-0-live-baseline.yml` usa questo endpoint e genera report JSON/Markdown. Il vecchio smoke CSV e il worker SQLite vanno mantenuti separati e non vanno confusi con questa API.

## 6. Scraper: copertura presente e stato reale

Sono presenti nove pacchetti scraper:
1. Bplatz
2. Deloox
3. Easycosmetic
4. Notino
5. Orioudh
6. Parfumcity
7. Parfumzentrum
8. PerfumeMarket
9. Sabina

Wiring PostgreSQL:
- Adapter generico: Bplatz, Deloox, Easycosmetic, Parfumzentrum, Sabina.
- Notino: runtime dedicato CJ/VIV.
- Orioudh, Parfumcity e PerfumeMarket: codice presente, ma nessun adapter PostgreSQL/store row attivo rilevato.

Evidenza runtime DB:
- Bplatz, Deloox.be, Easycosmetic.de, Notino.fr, Parfumzentrum.de e Sabina.es hanno sync riusciti registrati il 25/11.
- Offerte attive: 28, 0, 0, 108, 7, 24 rispettivamente.
- Numerosi run sono `partial`; i 35 run `running` e la coda arretrata impediscono di considerare il sistema pulito.
- Il test live Notino diretto è fallito.
- Le verifiche CI/parser/contract dimostrano che alcune funzioni sono testate, non che tutti e nove gli scraper superino oggi discovery, fetch, parsing, prezzo, stock, matching e pubblicazione live.

**Classificazione onesta:** nessuno scraper viene marcato “funzionante end-to-end” sulla sola base della presenza del codice o di un run registrato. La verifica live per retailer resta un gate separato e va eseguita uno alla volta.

## 7. Classificazione finale

| Categoria | Componenti |
|---|---|
| Riutilizzare | Runtime PostgreSQL, schema/migrazioni, modelli, API catalogo, canonical matching/persistence, queue worker, contratto connector, parser retailer già chiamati dagli adapter |
| Modificare/isolare dopo Fase 0 | `main.py`, `catalog_engine.py`, `product_matcher.py`, fallback JSON, Notino CJ/XML e helper SQLite, baseline SQLite/CSV, vecchio refresh worker, vecchi workflow |
| Preservare come input/compatibilità | `product_catalog.json`, `family_registry.json`, raw XML/feed, store URL mappings, legacy ID maps, script diagnostici, test, storico queue/run/price e workflow storici |
| Cancellare ora | **Niente** |

## 8. Gate di uscita Fase 0

| Requisito | Stato |
|---|---|
| Fotografia GitHub | Completata |
| Mappa dipendenze legacy | Completata come mappa statica; import dinamici e chiamate runtime non ancora esaustivi |
| Riferimenti CJ/XML/CSV/import | Completata su main |
| Inventario Neon read-only | Completato |
| Copia Git verificata | Completata |
| Backup Neon fresco del branch operativo | Bloccato da limite branch e divieto snapshot non-root; esiste solo copia storica del 24/11 |
| Fotografia live Fly (macchine, volumi, secret names, DB host/name) | Bloccata: workflow manuale disponibile ma non dispatchabile da questa sessione |
| Frontend realmente servito in produzione | Configurazione versionata identificata; verifica runtime Fly ancora necessaria |
| Prova live di tutti gli scraper | Non completata; nessuna falsa attestazione |
| Cancellazioni | Nessuna |

### Cosa serve per chiudere Fase 0
1. Eseguire manualmente `ScentHunter 2.0 read-only Fly diagnostics` da GitHub Actions e conservare il log/artifact.
2. Risolvere il limite Neon senza cancellare branch non mappati: liberare uno slot solo dopo un audit dipendenze/restore approvato, oppure ottenere un metodo backup logico esterno autorizzato.
3. Confrontare il backup storico con il branch operativo e completare un restore drill verificato.
4. Verificare il frontend live e la connessione effettiva Fly→Neon.
5. Eseguire la matrice live scraper in modo controllato, un retailer per volta.

**Decisione:** Fase 0 resta aperta. Non iniziare Fase 1, non rimuovere CJ, non modificare workflow, non fare cleanup e non avviare il refactoring finché i gate sopra non sono chiusi e documentati.
