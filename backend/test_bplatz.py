from backend.scrapers.bplatz.scraper import search

queries = [
    "Dior Sauvage",
    "Rasasi Hawas",
    "Versace Eros",
    "Azzaro Wanted",
]

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
