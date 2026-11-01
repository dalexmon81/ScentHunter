# Fase 0 — Inventario iniziale ScentHunter

Data rilevazione: 2026-11-01
Branch di lavoro: `refactor/catalog-first-architecture`
Baseline di codice: branch creato da `main` prima delle modifiche della migrazione.

## Stato di sicurezza

- Il branch di lavoro è separato da `main`.
- Il contenuto originario di `main` è conservato nel commit antenato del branch.
- Le copie di sicurezza dei dati catalogo e del codice connector sono conservate in `backups/phase-0/2026-11-01/`.
- Nessuna modifica a `main`, nessun deploy, nessuna modifica a Fly/Railway.
- Il congelamento delle modifiche a `main` è una regola operativa del progetto; non è stata modificata la protezione GitHub del branch perché ciò richiederebbe una modifica amministrativa separata.

## Inventario backend osservato

| Percorso | Dimensione osservata | Ruolo |
|---|---:|---|
| `backend/main.py` | 222,684 byte | API e logica applicativa |
| `backend/catalog_engine.py` | 320,540 byte | Catalogo, ricerca e raccolta |
| `backend/product_matcher.py` | 139,481 byte | Matching prodotti |
| `backend/product_catalog.json` | 1,242,247 byte | Catalogo statico |
| `backend/family_registry.json` | 23,653 byte | Registro famiglie/alias |
| `backend/offer_engine/refresh_worker.py` | 6,814 byte | Refresh offerte |
| `backend/scrapers/` | 17 file sorgente | Codice store |

Le dimensioni sono quelle restituite dall'albero Git di `main`, non misure del filesystem di produzione.

## Store e connector presenti nel repository

| Store / famiglia | Percorso | Stato documentale |
|---|---|---|
| Amazon Creators API condivisa | `backend/scrapers/amazon_creators_api.py` | Codice presente; accesso/credenziali da verificare |
| Amazon DE | `backend/scrapers/amazon_de/scraper.py` | Codice presente; mercato DE da verificare |
| Amazon FR | `backend/scrapers/amazon_fr/scraper.py` | Codice presente; mercato FR da verificare |
| Bplatz | `backend/scrapers/bplatz/scraper.py` | Codice presente |
| Deloox | `backend/scrapers/deloox/scraper.py` | Codice presente; URL/mercato da verificare |
| Easycosmetic | `backend/scrapers/easycosmetic/scraper.py` | Codice presente |
| Notino | `backend/scrapers/notino/` | Scraper, feed affiliate e legacy public presenti |
| Orioudh | `backend/scrapers/orioudh/scraper.py` | Codice presente |
| ParfumCity | `backend/scrapers/parfumcity/scraper.py` | Codice presente |
| ParfumZentrum | `backend/scrapers/parfumzentrum/scraper.py` | Codice presente |
| PerfumeMarket | `backend/scrapers/perfumemarket/scraper.py` | Codice presente |
| Sabina | `backend/scrapers/sabina/scraper.py` | Codice presente |

**Attenzione:** presenza del codice non equivale a connector funzionante, accesso autorizzato, copertura prodotti o offerte verificate.

## Configurazioni e segreti

La fotografia Git conserva codice, workflow e configurazioni versionate. Non contiene né deve contenere segreti runtime. Token, password, chiavi API e variabili Fly/Railway non vengono copiati nei backup Git. La loro presenza e configurazione saranno censite solo come nomi/stato (configurato o mancante), senza leggere o esportare i valori segreti.

## Workflow e strumenti diagnostici rilevati

Sono presenti workflow GitHub Actions per parser regression, hydration, catalog discovery, shadow engine, recovery controllato e deploy Fly. Nel backend sono presenti numerosi file `diagnose_*.py`, `debug_*.py` e `recover_*.py`; in Fase 1 saranno inventariati e spostati, non cancellati alla cieca.

## Baseline quantitativa — stato

Non vengono dichiarati numeri di prodotti/offerte/match senza eseguire un conteggio riproducibile sul contenuto integrale dei dati. Il file catalogo supera 1 MB e il connettore GitHub non ha restituito il suo contenuto integrale durante la prima lettura. La baseline numerica resta quindi **da generare con uno script eseguito sul repository completo**; non sarà sostituita da stime.

Metriche richieste:
- prodotti e varianti catalogate;
- offerte totali e offerte per store;
- percentuale prezzi validi;
- percentuale URL validi;
- percentuale disponibilità esplicita;
- match ambigui.

## Regole di lavoro

1. Nessun commit diretto su `main` per il backend coinvolto nella migrazione.
2. Nessuna modifica o deploy in produzione durante le fasi di costruzione.
3. Ogni fase termina con evidenze, test e criteri di accettazione.
4. I vecchi percorsi restano intatti finché il nuovo sistema non supera il confronto parallelo.
