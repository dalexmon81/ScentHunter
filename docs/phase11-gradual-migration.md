# Fase 11 — Migrazione graduale

## Scopo

Introdurre la nuova architettura in modo progressivo e reversibile, senza interrompere la ricerca legacy e senza spostare traffico finché i prerequisiti operativi non sono dimostrati.

**Branch:** `phase11/gradual-migration`  
**Base iniziale:** `main` al commit `54c90b2f9a031e0b4a671bf9acce34c45331ccba`  
**Ambiente target iniziale:** staging isolato.  
**Produzione:** nessun deploy, merge, modifica di secrets, migrazione o cambio traffico implicito in questa fase di preparazione.

## Stato di partenza verificato

- Il branch predefinito `main` punta al commit `54c90b2f9a031e0b4a671bf9acce34c45331ccba`.
- Le PR #343 (pipeline Redis/Celery) e #344 (configurazione staging worker) risultano aperte e in draft.
- La PR #343 documenta gate ancora aperti: seed Phase 2 con zero offerte importate, test end-to-end reale con PostgreSQL/Redis/Celery, attivazione operativa di migrazioni e worker e verifica isolata dei nove store.
- Di conseguenza, i livelli 5% / 20% / 50% / 100% sono **obiettivi futuri**, non percentuali autorizzate o già attive.
- Il commit Phase 10 indicato in precedenza (`7dcc67d...`) non è stato possibile verificare come ref accessibile durante la preparazione. Prima di usare le sue funzionalità come prerequisito, verificare il commit/branch corretto e la relativa CI.

## Regole di sicurezza non negoziabili

1. Il percorso legacy resta il percorso predefinito fino al completamento dei gate.
2. La nuova API viene inizialmente esercitata in shadow/read-only: può calcolare e registrare risultati ma non determina la risposta mostrata all'utente.
3. Nessun dual-write verso due database indipendenti. La raccolta può alimentare il catalogo nuovo; la lettura legacy resta indipendente.
4. Kill switch immediato: disabilitare il routing nuovo e tornare al 100% legacy senza deploy, se possibile tramite flag/configurazione già distribuita.
5. Non usare percentuali di traffico su endpoint che modificano stato o fanno refresh retailer. Il canary riguarda esclusivamente le richieste di lettura/search.
6. Non pubblicare offerte Phase 2 finché URL, prezzo, valuta, disponibilità, timestamp, stato store e match siano validati.
7. Nessun token, URL con credenziali, secret o dato personale nei log/metriche.
8. Non dichiarare rollback completato finché health check e confronto risultati confermano il ripristino.

## Gate 0 — Prerequisiti prima dello shadow

- [ ] Risolvere e sottoporre a review PR #343 e #344; non unirle solo per far avanzare la fase.
- [ ] Verificare ambiente staging isolato: PostgreSQL dedicato, Redis dedicato, worker/Beat dedicati, nessun volume o secret di produzione.
- [ ] Applicare migrazioni in staging e verificare che siano ripetibili e non distruttive.
- [ ] Seed canonico completato e conteggiati brands, fragrances, variants, stores.
- [ ] Importare o acquisire offerte reali per il pilot, senza inventare record; confermare che `offers_imported > 0`.
- [ ] Eseguire vertical slice Dior Sauvage EDP 100 ml su un solo connector/store già autorizzato e stabile.
- [ ] Dimostrare API → database → indice → frontend in staging con timestamp visibile.
- [ ] Dimostrare refresh Celery con task realmente consumato, aggiornamento persistito e nessuna chiamata retailer durante una normale search.
- [ ] Eseguire test di isolamento: un connector fallito/quarantinato non blocca gli altri.
- [ ] Verificare backup, restore testato e piano di rollback.

**Uscita Gate 0:** checklist completa, CI verde sui commit finali, report di smoke/E2E allegato alla PR. Fino ad allora resta vietato inviare traffico utente al nuovo percorso.

## Gate 1 — Shadow mode (0% traffico servito dalla nuova API)

- [ ] Inoltrare in parallelo una copia delle sole richieste GET/search alla nuova API, senza usarne la risposta.
- [ ] Applicare timeout rigidi e circuit breaker: la shadow non deve aumentare la latenza della risposta legacy.
- [ ] Campionare richieste e confrontare risultati per query normalizzata, variante, offerte pubblicate, prezzo minimo, disponibilità e store.
- [ ] Registrare discrepanze senza salvare query personali o dati sensibili.
- [ ] Eseguire almeno 24–72 ore di osservazione continua, includendo finestre di refresh.
- [ ] Produrre report per precisione dei match, copertura offerte, offerte stale, errori e latenza P50/P95.

**Uscita Gate 1:** nessun errore critico; nessuna offerta invalida pubblicata; nessun aumento misurabile della latenza legacy; differenze spiegate e accettate.

## Gate 2 — Canary 5%

- [ ] Abilitare il 5% delle sole richieste GET/search tramite feature flag server-side.
- [ ] Assegnare il bucket in modo deterministico (es. hash di sessione anonima o request key) per evitare oscillazioni.
- [ ] Escludere admin, refresh, ingestion, checkout/affiliate tracking e tutti gli endpoint mutanti.
- [ ] Osservare per almeno 24 ore e confrontare legacy vs nuovo.
- [ ] Kill switch automatico e manuale attivi.

Soglie iniziali consigliate, da rendere configurabili e calibrare sui dati reali:
- error rate nuovo percorso < 1%;
- P95 nuova API non oltre il 20% rispetto al baseline e comunque entro SLO applicativo;
- nessun aumento di offerte con dati invalidi;
- nessun crash loop o saturazione DB/Redis;
- precisione matching sopra la soglia approvata per il pilot.

## Gate 3 — 20%

Passare al 20% soltanto dopo approvazione del report 5%, almeno 24 ore stabili e nessun incidente P1/P2. Ripetere le stesse misure e verificare carico DB, Redis, worker e search index.

## Gate 4 — 50%

Passare al 50% dopo almeno 24–48 ore stabili al 20%. Verificare distribuzione del traffico, coerenza cache, errori per store e differenze di copertura per paese/valuta.

## Gate 5 — 100%

Passare al 100% solo dopo almeno 48 ore stabili al 50%, approvazione esplicita e piano di rollback ancora testato. Mantenere il percorso legacy disponibile per una finestra concordata; rimuoverlo in una fase separata dopo il periodo di stabilizzazione.

## Contratto di confronto

Per ogni richiesta campionata registrare:
- request/correlation ID anonimo;
- timestamp e versione API;
- query normalizzata e variante selezionata, con dati minimizzati;
- percorso usato (legacy/new);
- numero risultati e offerte valide;
- lista di identificatori prodotto/offerta non sensibili;
- differenza prezzo/disponibilità solo se entrambi i percorsi forniscono dati comparabili;
- latenza, timeout, error class.

Non registrare token, cookie, email, indirizzi IP grezzi o URL contenenti parametri segreti.

## Metriche e dashboard di rollout

- traffico legacy/new per minuto e percentuale effettiva;
- error rate, timeout e fallback;
- latenza P50/P95/P99;
- risultati zero e prodotti senza offerte;
- match automatici/ambigui e precisione campionata;
- offerte valide, stale e rifiutate;
- età dei prezzi e completezza stock;
- errori connector e store in quarantena;
- saturazione PostgreSQL, pool connessioni, Redis, queue lag e worker health.

## Rollback

Attivare rollback se una soglia critica viene superata, si pubblica un'offerta non verificabile, la nuova API restituisce dati incoerenti, o si verifica un incidente di disponibilità.

Procedura:
1. Portare feature flag a 0% (100% legacy).
2. Verificare health check e latenza legacy.
3. Congelare il nuovo percorso in sola lettura; non cancellare dati o migrazioni.
4. Conservare log/metriche sanitizzati e identificare la causa.
5. Riattivare solo dopo fix, CI, smoke test e nuova approvazione.

Non eseguire downgrade distruttivi del database durante un rollback del traffico.

## Registro decisioni

| Data | Step | Percentuale | Esito | Approvazione | Note |
|---|---|---:|---|---|---|
| Da compilare | Shadow | 0% | Non avviato | — | Gate 0 aperto |
| Da compilare | Canary | 5% | Non avviato | — | Non autorizzato |
| Da compilare | Ramp | 20% | Non avviato | — | — |
| Da compilare | Ramp | 50% | Non avviato | — | — |
| Da compilare | Cutover | 100% | Non avviato | — | — |

## Definition of Done — Fase 11

- [ ] Gate 0–5 completati con prove riproducibili.
- [ ] Confronti di qualità e performance archiviati.
- [ ] Feature flag e kill switch verificati.
- [ ] Rollback esercitato con successo.
- [ ] Nessun incidente critico aperto.
- [ ] 100% GET/search servito dal nuovo catalogo per la finestra di stabilizzazione approvata.
- [ ] Il vecchio percorso non viene rimosso automaticamente: la sua dismissione richiede una PR separata.
