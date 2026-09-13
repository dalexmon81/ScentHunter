def diagnose(query):
    """
    Diagnostic endpoint for Deloox.
    Does NOT call search().
    Tests DNS, Bing discovery and direct Deloox endpoints separately.
    """
    started = time.perf_counter()
    query = clean(query)

    report = {
        "diagnostic": True,
        "diagnostic_version": "deloox-root-cause-2026-09-13-v1",
        "query": query,
        "elapsed_s": 0,
        "dns": {},
        "bing": {},
        "direct": [],
        "conclusion": {},
    }

    # DNS
    try:
        import socket
        addresses = sorted({
            item[4][0]
            for item in socket.getaddrinfo(
                "www.deloox.nl",
                443,
                type=socket.SOCK_STREAM
            )
            if item[4]
        })
        report["dns"] = {
            "ok": True,
            "addresses": addresses,
        }
    except Exception as exc:
        report["dns"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    session = requests.Session()

    # ---------------------------------------------------------
    # BING
    # ---------------------------------------------------------
    bing_started = time.perf_counter()
    bing_url = (
        "https://www.bing.com/search?q="
        + quote_plus(f'site:deloox.nl/product "{query}"')
    )

    try:
        r = session.get(
            bing_url,
            headers=HEADERS,
            timeout=(3.0, 10.0),
            allow_redirects=True,
        )

        soup = BeautifulSoup(r.text, "html.parser")

        candidates = []

        for block in soup.select("li.b_algo, div.b_algo"):
            a = block.select_one("h2 a, h3 a") or block.find(
                "a",
                href=True
            )

            if not a:
                continue

            href = clean(a.get("href", ""))

            m = re.search(
                r"https?://(?:www\.)?deloox\.nl/product/\d+/[^&<>\"']+",
                href,
                re.I,
            )

            if not m:
                m2 = re.search(
                    r"[?&](?:q|url)=([^&]+)",
                    href,
                    re.I,
                )
                if m2:
                    href = requests.utils.unquote(m2.group(1))

                m = re.search(
                    r"https?://(?:www\.)?deloox\.nl/product/\d+/[^&<>\"']+",
                    href,
                    re.I,
                )

            if not m:
                continue

            product = product_url(m.group(0))

            if not product:
                continue

            context = clean(
                block.get_text(" ", strip=True)
            )

            candidates.append({
                "url": product,
                "title": clean(a.get_text(" ", strip=True)),
                "context": context[:1000],
            })

        report["bing"] = {
            "url": bing_url,
            "status": r.status_code,
            "elapsed_s": round(
                time.perf_counter() - bing_started,
                3,
            ),
            "html_length": len(r.content),
            "title": clean(soup.title.get_text())
            if soup.title else "",
            "candidate_count": len(candidates),
            "candidates": candidates[:10],
        }

    except Exception as exc:
        report["bing"] = {
            "url": bing_url,
            "status": None,
            "elapsed_s": round(
                time.perf_counter() - bing_started,
                3,
            ),
            "error": f"{type(exc).__name__}: {exc}",
            "candidate_count": 0,
            "candidates": [],
        }

    # ---------------------------------------------------------
    # DIRECT DELOOX ENDPOINTS
    # ---------------------------------------------------------
    encoded = quote_plus(query)

    endpoints = [
        (
            "search_nl",
            f"https://www.deloox.nl/zoeken?query={encoded}",
        ),
        (
            "search_en",
            f"https://www.deloox.nl/en/search?query={encoded}",
        ),
        (
            "category_parfum",
            "https://www.deloox.nl/categorie/1103659/parfum.html",
        ),
    ]

    if norm(query) == "liquid brun":
        endpoints.append(
            (
                "category_liquid_brun",
                "https://www.deloox.nl/categorie/1122039/liquid-brun.html",
            )
        )

    for label, url in endpoints:
        item_started = time.perf_counter()

        item = {
            "label": label,
            "url": url,
            "status": None,
            "elapsed_s": 0,
            "html_length": 0,
            "final_url": "",
            "title": "",
            "product_link_count": 0,
            "candidate_count": 0,
            "candidates": [],
            "error": None,
        }

        try:
            r = session.get(
                url,
                headers=HEADERS,
                timeout=(3.0, 8.0),
                allow_redirects=True,
            )

            item["status"] = r.status_code
            item["final_url"] = r.url
            item["html_length"] = len(r.content)

            soup = BeautifulSoup(r.text, "html.parser")

            item["title"] = (
                clean(soup.title.get_text())
                if soup.title else ""
            )

            product_links = []

            for a in soup.find_all("a", href=True):
                u = product_url(a.get("href"))

                if u:
                    product_links.append(u)

            item["product_link_count"] = len(
                set(product_links)
            )

            contexts = _candidate_contexts(
                r.text,
                query,
            )

            item["candidate_count"] = len(contexts)

            for u, (score, context) in contexts[:10]:
                item["candidates"].append({
                    "url": u,
                    "score": score,
                    "context": context[:1000],
                })

        except Exception as exc:
            item["error"] = (
                f"{type(exc).__name__}: {exc}"
            )

        item["elapsed_s"] = round(
            time.perf_counter() - item_started,
            3,
        )

        report["direct"].append(item)

    # ---------------------------------------------------------
    # CONCLUSION
    # ---------------------------------------------------------
    bing_candidates = report["bing"].get(
        "candidate_count",
        0,
    )

    direct_candidates = sum(
        int(x.get("candidate_count") or 0)
        for x in report["direct"]
    )

    direct_200 = sum(
        1
        for x in report["direct"]
        if x.get("status") == 200
    )

    direct_errors = [
        x
        for x in report["direct"]
        if x.get("error")
    ]

    direct_statuses = [
        {
            "label": x["label"],
            "status": x["status"],
            "elapsed_s": x["elapsed_s"],
        }
        for x in report["direct"]
    ]

    if bing_candidates > 0:
        code = "BING_DISCOVERY_WORKS"

        cause = (
            "Bing returns first-party Deloox product URLs. "
            "The failure, if any, is therefore after discovery."
        )

    elif direct_candidates > 0:
        code = "DIRECT_DISCOVERY_WORKS"

        cause = (
            "Bing returns no usable Deloox candidates, "
            "but direct Deloox pages expose product candidates."
        )

    elif direct_200 > 0:
        code = "DELOOX_REACHABLE_BUT_PARSER_SEES_NO_PRODUCTS"

        cause = (
            "Render can reach Deloox with HTTP 200, "
            "but the current HTML does not expose usable "
            "product candidates."
        )

    elif direct_errors:
        code = "DELOOX_REQUEST_ERRORS"

        cause = (
            "One or more direct Deloox requests failed at "
            "the network/request level."
        )

    else:
        code = "DELOOX_BLOCKED_OR_UNREACHABLE"

        cause = (
            "Neither Bing nor the direct Deloox endpoints "
            "produced usable product candidates."
        )

    report["conclusion"] = {
        "code": code,
        "cause": cause,
        "evidence": {
            "bing_candidate_count": bing_candidates,
            "direct_200_pages": direct_200,
            "direct_candidate_count": direct_candidates,
            "direct_statuses": direct_statuses,
        },
    }

    report["elapsed_s"] = round(
        time.perf_counter() - started,
        3,
    )

    return report
