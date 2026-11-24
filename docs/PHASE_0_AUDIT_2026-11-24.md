# Fase 0 — fotografia tecnica ScentHunter (24 novembre 2026)

**Stato: IN CORSO — nessuna cancellazione o modifica dei dati di produzione effettuata durante questa verifica.**

Questa fotografia separa ciò che è stato verificato da ciò che resta da dimostrare. Non costituisce ancora il via libera alla Fase 1.

## 1. Repository GitHub

Riferimento: repository `dalexmon81/ScentHunter`, branch `main`, commit `18bfe7f51144520c30e75214eff8e03c7a748adb`.

Inventario del tree GitHub:
- 390 voci complessive nel tree.
- 221 file Python.
- 55 workflow GitHub Actions.
- 90 file di test.
- Frontend legacy concentrato in `frontend/index.html` (917.721 byte).
- 25 file nella cartella `tools/diagnostics` e 2 script in `tools/debug`.

Componenti principali:
- Runtime PostgreSQL attuale: `backend/postgres_main.py`, `backend/app/`, `backend/app/workers/postgres_worker.py`.
- Componenti legacy ancora presenti: `backend/main.py`, `backend/catalog_engine.py`, `backend/product_matcher.py`, `backend/product_catalog.json`, `backend/family_registry.json`, `backend/offer_engine/` e `backend/scrapers/`.
- Il repository contiene quindi due generazioni di runtime. La presenza di un file non dimostra che sia usato in produzione.

## 2. Fly.io — produzione

App corretta: `scenthunter`, hostname `scenthunter.fly.dev`, regione primaria `ams`.

Configurazione versionata in `fly.toml`:
- Processo `app`: `uvicorn postgres_main:app`.
- Processo `worker`: `python -m app.workers.postgres_worker`.
- Coda: PostgreSQL.
- PostgreSQL obbligatorio; nessun fallback SQLite nel runtime canonico.
- Nessun mount di volume dichiarato in `fly.toml`.

Verifiche registrate:
- Il deploy del commit `58cc05c5d178c8ed0402f9ce1e4844afd69ead65` ha completato il deploy Fly, il seed del catalogo, i controlli di salute e la verifica della ricerca pubblica.
- La stessa esecuzione è terminata con esito complessivo negativo soltanto nel controllo successivo della coda discovery Deloox: il job giornaliero esistente era stato riutilizzato dal meccanismo idempotente e il controllo pretendeva erroneamente un job creato negli ultimi 10 minuti.
- Correzione del controllo: PR #908, merge `fdedba7de9e2826601f5e5a6f96467e20e5cd9fa`.
- Correzione del controllo read-only che attendeva un deploy anche per modifiche ai soli workflow: PR #909, merge `18bfe7f51144520c30e75214eff8e03c7a748adb`.
- L'audit read-only successivo ha confermato che la salute del catalogo PostgreSQL è `ready`. La ricerca di prova `Dior Sauvage` ha però restituito 0 prodotti e 0 offerte: il controllo è stato quindi reso più severo e deve usare una query di prova che abbia offerte pubblicabili.

Inventario Fly registrato il 24/11 alle 07:24, prima dell'ultimo deploy:
- 1 macchina app avviata.
- 1 macchina worker avviata.
- 1 macchina worker standby ferma.
- 3 volumi elencati, tutti senza macchina collegata.
Il deploy successivo ha aggiornato le tre macchine. È richiesta una nuova fotografia post-deploy per confermare lo stato corrente di macchine e volumi.

## 3. Neon — rami e database

Sono presenti più rami distinti. Non vanno trattati come se fossero un unico database.

| Ramo | Database | Brand | Profumi | Varianti | Negozi | Offerte | Storico prezzi | Raw |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `production` (default) | `neondb` | 73 | 3.579 | 853 | 0 | 0 | 0 | 0 |
| `offer-first-postgres-cutover` | `scenthunter_offerfirst` | 65 | 1.403 | 556 | 10 | 163 | 9.026 | 48.700 |
| `phase0-verified-backup-2026-11-24-compute` | `scenthunter_offerfirst` | 65 | 1.403 | 556 | 10 | 163 | 8.582 | 48.100 |
| `phase0-restore-drill-2026-11-24` | `scenthunter_offerfirst` | 65 | 1.403 | 556 | 10 | 163 | 8.882 | 48.400 |

Il ramo Neon predefinito `production` che è stato ispezionato non contiene righe in `stores` o `offers`. Il ramo `offer-first-postgres-cutover` contiene invece il catalogo operativo. La verifica Fly ha confermato PostgreSQL e catalogo pronto, ma l'hostname/database esatti della connessione Fly devono essere riportati nella fotografia post-deploy: non si deve dedurre il ramo soltanto dal nome.

I rami di backup e restore drill esistono e risultano `ready`. I conteggi di storico, raw e coda sono diversi perché gli snapshot sono stati creati in momenti differenti; non si dichiara uguaglianza completa dei dati senza un confronto dedicato.

## 4. Negozi — differenza tra obiettivo e realtà

Il documento `docs/PHASE_0_BASELINE_SCOPE.md` richiede nove negozi:
`bplatz`, `deloox`, `easycosmetic`, `notino`, `orioudh`, `parfumcity`, `parfumzentrum`, `perfumemarket`, `sabina`.

Nel registro del ramo operativo risultano invece:
- **6 attivi:** Bplatz, Deloox.be, Easycosmetic.de, Notino.fr, Parfum-Zentrum.de, Sabina.
- **4 inattivi:** Deloox International, Deloox Spain, Deloox Luxembourg, Deloox Netherlands.
- **3 negozi richiesti ma assenti dal registro:** Orioudh, Parfumcity, Perfumemarket.

Non si deve modificare il requisito da nove a sei per far passare il controllo: la differenza va risolta e approvata esplicitamente.

Per Notino, il gate rigoroso di freschezza non ha trovato offerte eleggibili nella fotografia esaminata. Le offerte presenti avevano timestamp sorgente troppo vecchi. Non si devono aggiornare artificialmente i timestamp per superare il gate.

## 5. Blocco reale della baseline Fase 0

Il workflow `Phase 0 - live retailer baseline (read-only)` è fallito il 24/11 alle 07:35 con:

`Baseline start returned HTTP 404`

La causa è architetturale:
- Gli endpoint `/admin/phase0/baseline/...` sono definiti nel vecchio `backend/main.py`.
- Fly avvia `backend/postgres_main.py`, che non include quegli endpoint.
- Il vecchio `backend/phase0_baseline_worker.py` usa una coda SQLite in `/data/phase0/phase0_jobs.sqlite3`.
- Il processo worker Fly attuale è `app.workers.postgres_worker`, non il vecchio worker Phase 0.
- La fotografia Fly precedente mostrava i volumi senza VM collegata; `fly.toml` non dichiara un mount per quel vecchio archivio.

**Conclusione:** non basta rilanciare il workflow e non è corretto riattivare il vecchio worker SQLite. La baseline deve essere adattata al runtime PostgreSQL oppure realizzata come report read-only direttamente sul catalogo PostgreSQL. Prima va chiarito il perimetro corretto dei nove negozi.

## 6. Frontend

Il file `frontend/index.html` è un singolo file di circa 918 KB. Il runtime attuale `postgres_main.py` reindirizza `/` e `/frontend` a `/catalog-demo`. Il frontend legacy va quindi considerato distinto dall'interfaccia servita dal runtime PostgreSQL, finché non viene verificato il contrario.

## 7. Cosa manca per dichiarare conclusa la Fase 0

1. Completare la fotografia post-deploy Fly di macchine, volumi e connessione Neon (solo hostname e nome database; mai credenziali).
2. Identificare formalmente il ramo Neon usato da Fly e spiegare perché il ramo default `production` è privo di offerte.
3. Risolvere la differenza tra i nove negozi richiesti e i sei attivi più tre assenti.
4. Sostituire la baseline SQLite non più collegata al runtime con una verifica PostgreSQL read-only, senza scrivere dati o riattivare il vecchio worker.
5. Verificare ogni scraper/connector e le sue dipendenze prima di classificarlo come riutilizzabile, da modificare o da ritirare.
6. Completare il confronto logico dei backup e del restore drill.
7. Consegnare l'inventario finale con evidenze e criteri di accettazione.

**Regola di sicurezza:** nessun componente legacy viene cancellato e nessun volume/database viene eliminato finché dipendenze, uso effettivo e possibilità di ripristino non sono stati verificati.
