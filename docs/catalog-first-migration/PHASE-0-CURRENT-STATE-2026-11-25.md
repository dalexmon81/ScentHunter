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


## 9. Second verification pass — 25/11/2026 (after initial report)

A fresh read-only query was executed after the first inventory. Counts have continued to change, so the earlier counts in section 3 are an earlier observation, not the latest value.

### Latest operational branch counts
Branch: `offer-first-postgres-cutover` (`br-red-night-ba3reqhp`), database `scenthunter_offerfirst`.

| Object | First pass | Second pass |
|---|---:|---:|
| brands | 65 | 65 |
| fragrances | 1,403 | 1,403 |
| variants | 556 | 556 |
| stores | 10 | 10 |
| offers | 167 | 167 |
| ingestion_runs | 62,500 | 62,538 |
| ingestion_raw | 60,089 | 60,126 |
| ingestion_queue_jobs | 187,062 | 187,062 |

The operational database is still receiving writes while this audit is in progress. This is why a point-in-time copy is required before any migration/cleanup work.

### Existing backup branches compared against operational branch

| Branch | offers | runs | raw | queue jobs |
|---|---:|---:|---:|---:|
| Operational `offer-first-postgres-cutover` | 167 | 62,538 | 60,126 | 187,062 |
| `phase0-verified-backup-2026-11-24-compute` | 163 | 50,128 | 48,100 | 173,039 |
| `phase0-restore-drill-2026-11-24` | 163 | 50,443 | 48,400 | 173,365 |
| `phase0-final-audit-backup-2026-11-24` | 163 | 50,291 | 48,257 | 173,202 |
| `scenthunter-release-restore-check-2026-11-24` | 167 | 54,326 | 52,125 | 178,305 |
| `restore-test-isolated-2026-11-24` | 167 | 54,325 | 52,125 | 178,255 |

All these child branches report `init_source=parent-data` and a parent timestamp on `offer-first-postgres-cutover`. They are point-in-time child branches, **not evidence of a snapshot restore drill**. In particular, the name `phase0-restore-drill-2026-11-24` must not be interpreted as proof that a snapshot restore was executed. The branch contents were inspected read-only; no restore was finalized and no operational branch was replaced.

### Snapshot policy
- The project currently has one manual snapshot: `scenthunter-phase0-before-cleanup-2026-11-24`.
- Its source is `production` (`br-dry-water-ban3a63s`), not the operational branch.
- Snapshot schedule for both `production` and `offer-first-postgres-cutover`: empty.
- The attempted snapshot of the non-root operational branch was rejected by Neon.
- The attempted new branch was rejected because the project is at its branch limit.

Therefore, the project has no verified current snapshot schedule or fresh backup of the operational branch as of this second pass.

### Frontend source mapping — verified statically
- `postgres_main.py` redirects `/` and `/frontend` to `/catalog-demo`.
- `app/api/catalog_search.py` serves `/catalog-demo` as inline HTML.
- The page calls `/api/catalog/search`.
- The same router exposes `/api/catalog/status`.
- This confirms the source-level route wiring, not the response currently served by Fly. Live production HTTP access remains unverified.

### Tooling constraints confirmed
- Available GitHub actions connector exposes workflow-run/artifact/log reads and rerun actions, but no `workflow_dispatch` action.
- Available Neon connector exposes branch/snapshot operations, but no logical database dump/export operation.
- No Fly.io connector was found in plugin discovery; the available hosting results did not include Fly.io.
- No command was issued that changes Fly, Neon data, production secrets, deployments, or workflows.

## 10. Updated exit decision

Fase 0 remains open. The new pass improves the data comparison and corrects the interpretation of the historical restore-test branches, but does not remove the two external blockers:
1. The Fly read-only diagnostic workflow must be run from GitHub Actions (or through an authorized Fly CLI session) to capture actual machine/volume/secret-name/runtime connection details.
2. A fresh logical or platform-supported backup of `br-red-night-ba3reqhp` must be produced and verified. Existing child branches are stale relative to the current operational counts; the sole manual snapshot belongs to the wrong branch.

No deletions, branch cleanup, workflow changes, deployments, imports, schema changes, or production writes were performed.


## 11. Third verification pass — 25/11/2026

### Neon branch-capacity check
A complete branch listing including recoverable/deleted branches returned exactly 10 active branches and no deleted branches:
- 1 default/root branch: `production`
- 1 operational branch: `offer-first-postgres-cutover`
- 8 child branches created on 24 November.

A further attempt to create a no-compute child branch directly from the operational branch was rejected with Neon error `branches limit exceeded`. No branch was deleted or modified. This confirms that a current Neon point-in-time child copy cannot be created through the available Neon connector without first freeing a branch slot; freeing a slot requires an explicit, dependency-informed decision and is not part of this audit.

### Workflow dispatch check
The GitHub connector was checked for a workflow-dispatch operation. It exposes workflow run, job, log and artifact reads, plus rerun operations, but no workflow dispatch/start action. The latest 100 workflow runs returned no run for the read-only Fly diagnostics workflow or the phase-0 live baseline workflow. No unrelated workflow was rerun.

The read-only Fly diagnostic workflow remains available for manual launch in GitHub Actions:
`.github/workflows/scenthunter-readonly-fly-diagnostics.yml`
It performs only status, machines, volumes, secret-name inventory and runtime DB configuration/file-presence checks.

### Current hard blockers (confirmed again)
1. Fly production state is not yet verified live because this session cannot dispatch the workflow and no Fly connector is installed.
2. A fresh operational Neon backup cannot be created through the available connector while the project branch limit is reached. Existing child branches are stale, and the existing manual snapshot is from the wrong root branch.
3. No branch deletion or replacement has been authorized or performed.

This pass made no changes to `main`, production, Neon data, Fly machines, deployments, secrets, or scheduled jobs.


## 12. Fourth verification pass — scraper and ingestion evidence (25/11/2026)

### Live operational database: per-store state
Fresh read-only queries against `offer-first-postgres-cutover` returned:

| Store | State | Active offers | Completed runs | Partial runs | Failed runs |
|---|---|---:|---:|---:|---:|
| Bplatz | active | 28 | 1,450 | 572 | 5 |
| Deloox.be | active | 0 | 14 | 1,380 | 0 |
| Easycosmetic.de | active | 0 | 42 | 4,712 | 4 |
| Notino.fr | active | 108 | 7,657 | 42,736 | 0 |
| Parfum-Zentrum.de | active | 7 | 371 | 1,588 | 5 |
| Sabina.es | active | 24 | 1,282 | 635 | 5 |
| Deloox.com / .es / .lu / .nl | inactive | 0 | 0 | 197 combined | 0 |

`last_successful_sync_at` is recent for active rows, but this is not proof of fresh offer publication. Latest per-store runs show:
- Bplatz: latest completed run discovered 8 products, created/updated 0 offers; preceding single-product runs are partial.
- Deloox.be: latest three runs completed but discovered 0 products and changed 0 offers.
- Easycosmetic.de: latest completed run discovered 100 products but created/updated 0 offers; preceding runs are partial.
- Notino.fr: latest runs are partial; each rejected a product for `incomplete_variant_identity`.
- Parfum-Zentrum.de: latest completed run updated 1 offer; an immediately preceding run rejected an offer because retailer currency evidence was not explicit.
- Sabina.es: latest completed runs updated 1 existing offer each; no new offers were created in those runs.

### Queue and ingestion health
Latest `ingestion_runs` status counts:
- completed: 10,817
- partial: 51,852
- failed: 19
- running: 34

Of the 34 running ingestion runs, 24 are older than 24 hours and 8 are older than 72 hours. Store breakdown: Notino 20 (13 older than 24h, 7 older than 72h), Deloox.be 5 (all older than 24h), Easycosmetic 5 (3 older than 24h, 1 older than 72h), Sabina 2 (both older than 24h), plus one each for inactive Deloox.com and Parfum-Zentrum.de.

Queue status counts:
- completed: 60,409
- failed: 51,421
- queued: 75,321
- running: 1

Queue stage counts:
- discover: 262 completed, 8 failed, 33 queued
- fetch: 49,852 completed, 50,934 failed, 75,115 queued, 1 running
- refresh: 10,301 completed, 479 failed, 167 queued

The largest failed-job class is 45,321 fetch jobs explicitly cancelled because the Deloox market was disabled (Belgian storefront only). Other major failed classes are missing connector registrations for inactive Deloox markets and product-not-found fetches. The queue is not healthy enough to declare the ingestion pipeline fully operational.

### Scraper package / test evidence
Nine scraper packages exist in source: Bplatz, Deloox, Easycosmetic, Notino, Orioudh, Parfumcity, Parfumzentrum, PerfumeMarket, Sabina.
- Five legacy retailers (Bplatz, Deloox BE, Easycosmetic, Parfumzentrum, Sabina) are routed through the generic legacy adapter. Regression tests exercise adapter behavior with fixtures/mocks; they are not end-to-end live retailer acceptance tests.
- Notino has the dedicated CJ/VIV feed parser/connector and fixture-based parser tests.
- Orioudh, Parfumcity and PerfumeMarket have scraper source files but no active store rows or active PostgreSQL connector adapters in this runtime.
- The latest PR #927 CI checks on branch `fix/notino-direct-postgres-runtime` (not merged to main) show the queue-contract suite passing, canonical Notino discovery regression passing, and isolated disposable-Neon API smoke passing. The same PR's direct Notino storefront live acceptance job failed: five product searches returned zero candidates; Notino endpoints returned HTTP 403 and the Jina reader returned HTTP 401. The separate parser-regression job passed its fixture tests and public fallback probe; its live direct-connector job is the failing job.
- The Bplatz live-offer pilot step in that parser workflow was skipped. No CI evidence here proves all nine scraper packages work against their live retailers.

### Fase 0 scraper verdict
No scraper can be labelled fully end-to-end verified based on current evidence:
- Evidence of active offers and recent successful updates: Bplatz, Notino CJ/VIV, Parfumzentrum, Sabina — but with material partial/rejection/backlog issues.
- Not currently producing offers: Deloox.be and Easycosmetic.de.
- Not enabled in the active PostgreSQL runtime: Orioudh, Parfumcity, PerfumeMarket and the four inactive Deloox international market rows.
- Notino direct storefront connector in PR #927: live acceptance failed; PR is not merged.

No job queue was purged, retried, re-enqueued, or edited. No stores were enabled/disabled, no scraper was changed, and no offers were modified.



## 13. Fifth verification pass — latest Neon branch and data comparison (25/11/2026)

### Fresh operational counts
A new read-only query against `offer-first-postgres-cutover` returned:
- offers: 167
- ingestion_runs: 63,250
- ingestion_raw: 60,830

The run/raw totals have continued to grow since the previous pass. Earlier counts in this report are timestamped observations and should not be mistaken for a frozen database state.

### Complete Neon branch inventory
The latest complete listing confirms exactly 10 active branches and no recoverable deleted branches:

| Branch | Parent | Created UTC | Logical size |
|---|---|---|---:|
| `scenthunter-release-restore-check-2026-11-24` | operational | 24 Nov 19:05 | 328.8 MB |
| `restore-test-isolated-2026-11-24` | operational | 24 Nov 18:19 | 328.8 MB |
| `phase0-final-snapshot-2026-11-24-1000` | operational | 24 Nov 09:10 | 319.3 MB |
| `phase0-restore-drill-2026-11-24` | operational | 24 Nov 06:54 | 317.3 MB |
| `phase0-final-audit-backup-2026-11-24` | operational | 24 Nov 06:33 | 316.9 MB |
| `phase0-verified-backup-2026-11-24-compute` | operational | 24 Nov 06:15 | 296.7 MB |
| `phase0-verified-backup-2026-11-24` | operational | 24 Nov 06:14 | 296.7 MB |
| `phase0-backup-2026-11-24` | operational | 24 Nov 05:32 | 296.2 MB |
| `offer-first-postgres-cutover` | production | 21 Nov 10:17 | 395.2 MB |
| `production` | none (default) | 04 Nov 09:24 | 35.8 MB |

All eight non-root child branches have the operational branch as their parent. The two most recent branches were queried read-only:
- `scenthunter-release-restore-check-2026-11-24`: 167 offers, 54,326 ingestion runs, 52,125 raw rows.
- `restore-test-isolated-2026-11-24`: 167 offers, 54,325 ingestion runs, 52,125 raw rows.

Compared with the operational branch's latest 63,250 runs and 60,830 raw rows, even these newest child branches are stale by 8,924/8,925 runs and 8,705 raw rows. They are not a current backup. The older branches are further behind; some no longer have an available compute endpoint for SQL verification. No branch was deleted, reset, or modified.

### Backup decision
The branch inventory identifies historical candidates for a future cleanup decision, but it does not establish that any branch is safe to delete. Names such as `restore-test`, `final-snapshot`, and `verified-backup` are not proof of independent restore points or that their purpose is obsolete. No candidate is selected for deletion. The project remains at its 10-branch limit, so creating a current child backup remains blocked until the owner explicitly approves a specific branch for deletion or supplies another authorized backup method.


## 14. Sixth verification pass — candidate branch dependency assessment (25/11/2026)

This pass was specifically performed to avoid asking the project owner to choose a Neon branch without evidence.

### Compute endpoint and usage inventory

The project-wide endpoint listing shows a read-write compute endpoint for:
- `scenthunter-release-restore-check-2026-11-24`
- `restore-test-isolated-2026-11-24`
- `phase0-restore-drill-2026-11-24`
- `phase0-final-audit-backup-2026-11-24`
- `phase0-verified-backup-2026-11-24-compute`
- `production`
- `offer-first-postgres-cutover`

No compute endpoint is registered for:
- `phase0-final-snapshot-2026-11-24-1000`
- `phase0-verified-backup-2026-11-24`
- `phase0-backup-2026-11-24`

Branch metadata also shows:
- `phase0-final-snapshot-2026-11-24-1000`: 0 CPU seconds, 0 compute seconds, 0 active seconds, 0 bytes written and 0 data-transfer bytes since creation; no compute endpoint; no child branches; created 24 Nov 09:10 UTC.
- `phase0-verified-backup-2026-11-24`: 0 CPU/compute/active seconds and no endpoint, but it is explicitly named as a verified backup and is paired with the compute-enabled verified-backup clone. Existing repository documentation explicitly says not to delete either verified-backup branch.
- `phase0-backup-2026-11-24`: 0 CPU/compute/active seconds and no endpoint, but it is the earliest named backup clone and the GitHub audit records a separate Git snapshot branch relationship. It is not selected as a deletion candidate.
- The restore-drill branch has substantial recorded compute/active time and data transfer and has a successful isolated API read-only smoke test documented in `docs/PHASE_0_RESTORE_DRILL_AUDIT.md`. It must be preserved.
- `phase0-final-audit-backup`, `restore-test-isolated` and `scenthunter-release-restore-check` all have compute endpoints and recent endpoint activity timestamps; none is selected.

### GitHub dependency search

Repository-wide searches on the default branch for the exact name `phase0-final-snapshot-2026-11-24-1000` and its branch ID found no workflow, source, configuration, PR documentation or other code reference beyond the historical inventory table in `docs/PHASE_0_RESTORE_DRILL_AUDIT.md`. This search is evidence of no checked-in reference on `main`; it cannot prove that no person has a manually saved connection URL or external operational dependency.

### Recommended candidate — NOT deleted

**Lowest observed operational-dependency candidate:** `phase0-final-snapshot-2026-11-24-1000` (`br-frosty-leaf-ba2f6e47`).

Reasons:
1. It is a later point-in-time child clone of the operational branch, not the operational branch itself.
2. It has no Neon compute endpoint.
3. Neon reports zero CPU, compute, active time, writes and transfer since creation.
4. It has no child branches.
5. No checked-in code/workflow/PR reference to its exact name or ID was found.
6. Its name and audit entry indicate a historical clone, not the documented API restore-drill branch or the verified-backup pair.

Limitations:
- It remains a point-in-time clone containing historical data; absence of compute or Git references is not proof that nobody relies on it manually.
- Its contents could not be queried because it has no compute endpoint. It is therefore not certified as a valid or invalid restore point.
- It is not a platform snapshot object and must not be described as an independent backup.

**Decision:** This is the strongest candidate for owner-approved deletion to free one branch slot, but it has not been deleted. Deleting a Neon branch is destructive and disconnects its clients; explicit approval naming this exact branch is required. No other branch is recommended for deletion on the evidence currently available.


## 15. Owner-approved Neon branch removal — verified (25/11/2026)

The owner explicitly approved deletion of exactly:
- Name: `phase0-final-snapshot-2026-11-24-1000`
- Branch ID: `br-frosty-leaf-ba2f6e47`
- Project: `square-math-01119225`

Immediately before deletion, branch metadata was re-read and confirmed the exact name, operational parent `br-red-night-ba3reqhp`, and that it was neither the default nor primary branch. The Neon delete operation returned the target branch with state `storage_deleted`.

Post-operation verification:
- Neon branch inventory now contains 9 branches (one slot freed).
- The deleted branch name and ID are absent from the branch inventory.
- No compute endpoint remains attached to the deleted branch.
- The operational branch `offer-first-postgres-cutover` was not the deletion target.
- No other branch was deleted; no database tables, rows, workflows, Git branches, Fly machines, or secrets were changed by this action.

This deletion is complete. The remaining nine branches are retained pending further dependency analysis.


## 16. Operational Neon backup created and verified (25/11/2026)

After the owner-approved deletion freed one branch slot, a new point-in-time child clone was created from the live operational branch.

### Backup identity

- Project: `square-math-01119225`
- New backup branch: `phase0-operational-backup-2026-11-25`
- Branch ID: `br-lingering-sky-baehcw2s`
- Parent: `offer-first-postgres-cutover` (`br-red-night-ba3reqhp`)
- Parent LSN: `0/2F3F3EA8`
- Parent timestamp: `2026-11-25T17:44:24Z`
- Creation time: `2026-11-25T17:44:35Z`
- Neon state: `ready`
- Database inspected: `scenthunter_offerfirst`
- Alembic revision: `0007_catalog_identity`

### Data verification

Read-only count comparison was run against the operational parent and the new backup. All listed counts matched exactly at verification time:

| Object | Operational parent | New backup |
|---|---:|---:|
| Brands | 65 | 65 |
| Fragrances | 1,403 | 1,403 |
| Product variants | 556 | 556 |
| Stores | 10 | 10 |
| Active offers | 167 | 167 |
| Price history | 10,832 | 10,832 |
| Raw ingestion records | 62,151 | 62,151 |
| Ingestion runs | 64,601 | 64,601 |
| Match audit | 354 | 354 |
| Queue jobs | 188,915 | 188,915 |

Five referential-integrity checks on the backup returned zero:
- Offers without a canonical variant.
- Offers without a valid store.
- Price-history rows without an offer.
- Raw ingestion records without a valid store.
- Product variants without a fragrance.

The database tree includes the canonical application tables and indexes. The new branch is a point-in-time Neon copy-on-write clone of the operational database, not an independent logical export or off-platform backup.

### Protection and cost state

- Neon refused to mark the new branch as protected because the plan's protected-branch limit has been reached. No existing protected branch was changed.
- Its read-write compute endpoint was suspended after the verification queries. The data branch remains `ready`; its compute can be started if a future restore/read test requires it.
- The project is again at 10 active branches out of 10. Do not create another branch until a slot is deliberately freed or the plan limit changes.

### Result and remaining limitation

**Operational point-in-time clone: created and query-verified.** Parent LSN/time, schema revision, table counts and key references are recorded above.

**Independent backup: not yet achieved.** No logical `pg_dump` export or off-platform copy has been produced in this session. Do not describe this clone as protection against loss of the entire Neon project/account. The backup is also currently unprotected by Neon because of the plan limit.


## 17. Fly.io verification and independent-export capability check (25/11/2026)

### Fly production configuration re-read from main

The current `main` versions of `fly.toml` and `.github/workflows/fly.yml` were read directly from GitHub. They configure:
- Fly app `scenthunter`, primary region `ams`.
- Web process `uvicorn postgres_main:app` and worker process `python -m app.workers.postgres_worker`.
- PostgreSQL queue backend and mandatory PostgreSQL catalog runtime.
- Production deployment stages Notino CJ feed credentials and sets `SCENTHUNTER_ACTIVE_OFFER_REFRESH_ENABLED=1` before deploy.
- Deployment then runs Alembic, catalog/store seeding and verification, health/catalog API checks, public search checks, and a Bplatz refresh-queue check.

These are repository configuration facts only. They do not prove which machines are currently running, which secrets are present in Fly, or whether the deployed release matches `main`.

### Available read-only Fly workflow

`.github/workflows/scenthunter-readonly-fly-diagnostics.yml` is explicitly read-only. If manually dispatched, it checks:
- Fly app status, machines, volumes and secret names (not secret values).
- Runtime database backend/driver, database host/name and whether the database URL variables are configured.
- Presence of the two legacy SQLite paths.

It does not export the PostgreSQL database. Its current triggers are `workflow_dispatch` and a push to `main` changing `docs/PHASE_0_AUDIT_2026-11-24.md`; the current Phase 0 report is on a separate documentation branch and at a different path. The GitHub tools available in this session do not expose a workflow-dispatch action. The Fly.io plugin search returned no Fly.io integration. Therefore this workflow was not dispatched and no live Fly machine/volume/secret inventory is claimed.

### Existing backup workflow is not suitable for the current production database

The repository also contains `.github/workflows/scenthunter-postgres-precutover-backup.yml`. Inspection shows it snapshots a Fly volume and creates an SQLite online backup from `/data/catalog/catalog.sqlite3`, with assertions for old revision `0005_connector_quarantine` and old row counts. It is explicitly a pre-cutover workflow and does not run `pg_dump` or export the current Neon PostgreSQL database. It must not be treated as a current production PostgreSQL backup or run as a substitute.

`.github/workflows/scenthunter-production-db-inventory.yml` is also read-only. It inventories Fly topology, volume snapshots and SQLite file state; it does not back up the current Neon PostgreSQL database.

### Independent export result

The available Neon integration exposes SQL, branch, snapshot and storage operations, but no logical PostgreSQL export/`pg_dump` operation. A Neon child branch is not an off-platform copy. No independent PostgreSQL dump or off-platform export has been created.

### Phase 0 status after this pass

- Repository configuration re-read: complete.
- Suitable read-only Fly diagnostic workflow identified: complete.
- Live Fly verification: blocked pending a secure Fly.io execution path (or a successful run of the existing read-only GitHub workflow).
- Current production PostgreSQL logical export: blocked; no supported export path is available through the connected tools.
- No Fly machine, volume, secret, deployment, production database, workflow, or production code was changed.
- `main` remains untouched; this report update is documentation-only on `docs/phase0-current-audit-2026-11-25`.

**Phase 0 remains open. Do not start Phase 1 until live Fly state and an independent PostgreSQL backup are verified, or the owner explicitly accepts a documented exception to the backup requirement.**


## 18. Live Fly diagnostic rerun completed (25/11/2026, 18:59 UTC)

The existing workflow `.github/workflows/scenthunter-readonly-fly-diagnostics.yml` was rerun as GitHub Actions run [45353437876, attempt 2](https://github.com/dalexmon81/ScentHunter/actions/runs/45353437876). This is the same read-only workflow already present in the repository; no workflow file or production code was changed to run it.

### Current Fly inventory observed by the workflow

- Fly app: `scenthunter`; hostname `scenthunter.fly.dev`.
- App machine `2861625cd341d8`: `started`, process group `app`, region `ams`, release image `deployment-01M88E539J2KP1NQK35MVB0FFT`.
- Worker machine `78455def0d0368`: `started`, process group `worker`, region `ams`, same release image.
- Standby worker `784ee395a5d028`: `stopped`, marked by Fly as standby.
- All three machines report release version `2528`.
- Three encrypted Fly volumes were listed, all in `ams`, and none attached to a VM at the time of the check:
  - `vol_vwn91672oj9d1z9v`, `scenthunter_data`, 5 GB.
  - `vol_rkg3w2my7exjk864`, `scenthunter_data_recovery`, 2 GB.
  - `vol_491p1y217q8ln75r`, `scenthunter_data`, 1 GB.
- The workflow listed secret names only. It showed nine secrets as staged/not deployed, including the Notino CJ feed settings, active-offer-refresh flag and five retailer discovery-query settings. Secret values were not read or exposed.

### Runtime database and legacy-file check

The workflow connected read-only to the running worker and reported:

- `CANONICAL_BACKEND=postgresql`
- `CANONICAL_DRIVER=postgresql+psycopg`
- Database host: `ep-aged-thunder-ba5bz2vz.c-8.eu-central-1.aws.neon.tech`
- Database name: `scenthunter_offerfirst`
- `SCENTHUNTER_CATALOG_DATABASE_URL` configured: true.
- General `SCENTHUNTER_DATABASE_URL` configured: false.
- `SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL=1`.
- `/data/catalog/catalog.sqlite3` absent.
- `/data/store_catalog.sqlite3` absent.

This verifies the running worker's configured canonical database backend and the absence of those two specific SQLite paths. It does not prove that every legacy SQLite database, JSON file, or legacy code path has been removed from all machines or external storage.

### Diagnostic safety and result

The workflow completed successfully. It performed no deploy, restart, migration, import, secret update, or database write. The run and decoded job logs are available from the GitHub Actions link above.

The three unattached volumes have not been mounted, inspected, snapshotted, deleted, or modified. Their names alone do not establish that they contain usable backups. No claim is made that they are recoverable snapshots.

### Updated Phase 0 status

- Live Fly app/machine/volume inventory: **verified read-only**.
- Running worker's PostgreSQL backend and canonical database target: **verified read-only**.
- Two configured legacy SQLite paths: **absent on the inspected worker**.
- Full legacy-file inventory across every machine and volume: **not yet verified**.
- Independent logical PostgreSQL export outside Neon: **still not produced**.
- Current production frontend route/browser rendering: **not independently verified by this diagnostic**.
- No production resources or `main` branch were changed by this diagnostic.

**Phase 0 remains open.** The remaining critical blocker is a verified independent PostgreSQL backup/export. The unattached Fly volumes also need provenance/content verification before they can be classified as backups. Do not begin Phase 1 until these are resolved or the owner explicitly accepts a documented exception.


## 19. Neon snapshot and branch inventory rechecked (25/11/2026)

A fresh read-only inventory was performed after the Fly diagnostic.

### Snapshot inventory

The Neon project currently exposes one snapshot:

- Name: `scenthunter-phase0-before-cleanup-2026-11-24`
- ID: `snap-wandering-silence-bah0m86y`
- Created: `2026-11-24T05:31:44Z`
- Source branch ID: `br-dry-water-ban3a63s` (`production`, the Neon default branch)
- Manual snapshot; reported full size 35,782,656 bytes.

This snapshot is **not** sourced from the live operational branch `offer-first-postgres-cutover` (`br-red-night-ba3reqhp`). It must not be represented as a snapshot of the current operational database.

### Snapshot schedules

A fresh schedule read returned an empty schedule for both:
- Operational branch `offer-first-postgres-cutover` (`br-red-night-ba3reqhp`).
- Default branch `production` (`br-dry-water-ban3a63s`).

Thus no automatic snapshot schedule is currently configured for either branch.

### Branch capacity

The fresh branch inventory contains 10 branches, matching the project's 10-branch limit. The operational backup clone `phase0-operational-backup-2026-11-25` remains `ready`, unprotected, and a child of the operational branch. No branch was created, deleted, reset, or modified during this inventory.

### Consequence

There is still no verified independent export, and the only listed Neon snapshot belongs to the default `production` branch rather than the operational database. The child clone is the only newly verified point-in-time copy of the operational database, but it remains inside the same Neon project and is not protected. Phase 0 backup acceptance criteria therefore remain unmet.


## 20. Final blocker triage — backup workflow and frontend reachability (25/11/2026)

### Backup workflow suitability rechecked

The repository workflow directory was re-read. The only similarly named PostgreSQL backup workflow, `.github/workflows/scenthunter-postgres-precutover-backup.yml`, was inspected in full. It is a legacy pre-cutover routine that:
- snapshots Fly volume `vol_vwn91672oj9d1z9v`;
- attempts an SQLite online backup from `/data/catalog/catalog.sqlite3`;
- asserts old Alembic revision `0005_connector_quarantine` and old SQLite row counts.

The latest successful Fly worker diagnostic reports that `/data/catalog/catalog.sqlite3` is absent on the inspected production worker and that the active canonical backend is PostgreSQL. Therefore this old workflow is not a valid backup path for the current Neon database and was deliberately not run. Running it would not satisfy the independent PostgreSQL export requirement and could create misleading backup evidence.

The GitHub Actions artifact listing for diagnostic run `45353437876` returned no artifacts. Its decoded logs remain available through the run/job log endpoint.

### Frontend live reachability

A direct HTTPS probe of `/`, `/health`, `/api/catalog/status` and `/catalog-demo` could not resolve the Fly hostname from the available execution environment (DNS resolution failure). This is an environment/network limitation, not evidence that the production site is down or healthy. Live browser rendering and API response remain unverified.

### Phase 0 status

This pass rules out the legacy pre-cutover SQLite workflow as a safe substitute for a current PostgreSQL backup. It does not produce an independent database export or verify the frontend live. No workflow was dispatched, no deploy/restart was made, no production data or secrets were changed, and `main` remains untouched.

**Remaining hard blockers:** (1) an authorized execution path that can produce and verify a logical export of `scenthunter_offerfirst` outside the Neon project; (2) live frontend/API verification from a network that can resolve `scenthunter.fly.dev`. The Fly machine/worker inventory itself is now verified by the successful read-only diagnostic in section 18.
