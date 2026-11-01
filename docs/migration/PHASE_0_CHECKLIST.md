# Fase 0 — Checklist di preparazione e sicurezza

- [x] Creato branch di lungo periodo `refactor/catalog-first-architecture` da `main`.
- [x] Inventario iniziale di moduli backend e store presenti nel repository.
- [x] Copia versionata dei dati catalogo e delle sorgenti connector in `backups/phase-0/2026-11-01/`.
- [x] Documentati limiti e trattamento delle credenziali runtime.
- [x] Baseline quantitativa: generatore CSV implementato; perimetro fissato a 9 store attivi (Amazon.de e Amazon.fr esclusi dal report); Notino compare anche con zero offerte verificate e conta separatamente gli URL indicizzati.
- [x] Test di regressione del generatore: verifica 9 store, esclusione Amazon e conteggio URL Notino senza inventare offerte; GitHub Actions superata.
- [ ] Evidenza runtime finale: CSV completo da scaricare dall'ambiente con DB SQLite aggiornato al codice del branch. L'endpoint attualmente interrogato da Actions restituisce HTTP 503 perché è ancora in esecuzione la vecchia logica runtime che blocca la baseline se Notino ha URL indicizzati ma zero offerte persistite.
- [x] Matrice statica dei connector completata per 11 store, con endpoint, campi, varianti, stock e limiti noti.
- [ ] Verificare configurazione effettiva delle credenziali e dei servizi esterni senza esporre segreti.
- [ ] Eseguire test live controllati per verificare URL finali, mercati, prezzi, varianti e disponibilità per ciascuno store.

## Criterio di uscita

La Fase 0 è pronta per il passaggio alla Fase 1 quando:
1. backup, branch e inventario sono conservati;
2. il report quantitativo è generabile, i test automatici passano e il CSV runtime completo è allegato all'evidenza di runtime;
3. gli store sono documentati distinguendo audit statico da verifica live;
4. le credenziali vengono verificate solo come presenti/assenti, senza divulgarne i valori;
5. l'assenza di test live o database runtime è dichiarata e non sostituita con stime.

Gli ultimi due controlli sono verifiche operative da eseguire nell'ambiente di deploy; non autorizzano modifiche a `main` né un deploy durante la Fase 0.
