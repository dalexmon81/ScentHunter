from backend.scrapers.bplatz.scraper import search

queries = [
    "Rasasi Hawas",
    "Armaf Club de Nuit",
    "Riiffs",
]

print("TEST BPLATZ ARABI - VERSIONE NUOVA")

for query in queries:
    print("\n" + "=" * 60)
    print("QUERY:", query)
    try:
        results = search(query)
        print("RISULTATI:", len(results))
        for item in results:
            print(item)
    except Exception as e:
        print("ERRORE:", type(e).__name__, str(e))
