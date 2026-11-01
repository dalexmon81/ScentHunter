# Fase 0 — Checklist di preparazione e sicurezza

- [x] Creato branch di lungo periodo `refactor/catalog-first-architecture` da `main`.
- [x] Inventario iniziale di moduli backend e store presenti nel repository.
- [x] Copia versionata dei dati catalogo e delle sorgenti connector in `backups/phase-0/2026-11-01/`.
- [x] Documentati limiti e trattamento delle credenziali runtime.
- [x] Baseline quantitativa: generatore CSV implementato e documentato; CSV popolato da eseguire nell'ambiente runtime che contiene il DB SQLite.
- [x] Matrice statica dei connector completata per 11 store, con endpoint, campi, varianti, stock e limiti noti.
- [ ] Verificare configurazione effettiva delle credenziali e dei servizi esterni senza esporre segreti.
- [ ] Eseguire test live controllati per verificare URL finali, mercati, prezzi, varianti e disponibilità per ciascuno store.

## Criterio di uscita

La Fase 0 è pronta per il passaggio alla Fase 1 quando:
1. backup, branch e inventario sono conservati;
2. il report quantitativo è generabile e il CSV popolato è allegato all'evidenza di runtime;
3. gli store sono documentati distinguendo audit statico da verifica live;
4. le credenziali vengono verificate solo come presenti/assenti, senza divulgarne i valori;
5. l'assenza di test live o database runtime è dichiarata e non sostituita con stime.

Gli ultimi due controlli sono verifiche operative da eseguire nell'ambiente di deploy; non autorizzano modifiche a `main` né un deploy durante la Fase 0.
