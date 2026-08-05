from backend.scrapers.bplatz.scraper import search

for query in ("Rasasi Hawas", "Armaf Club de Nuit", "Riiffs"):
    print("\n" + "=" * 60)
    print("QUERY:", query)
    results = search(query)
    print("RISULTATI:", len(results))
    for item in results:
        print(item)
