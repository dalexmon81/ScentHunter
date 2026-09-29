from fastapi import APIRouter, Query
import heapq
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

router = APIRouter()


@router.get('/diagnose-deloox-catalog-trace')
def diagnose_deloox_catalog_trace(
    q: str = Query('Hawas'),
    max_pages: int = Query(30, ge=1, le=100),
    max_depth: int = Query(8, ge=0, le=10),
):
    """READ-ONLY trace of where proven Deloox product URLs disappear.

    This is deliberately separate from production catalog discovery. It does
    not write SQLite, enqueue hydration, call ProductMatcher, run /search or
    perform a resync. It first obtains the real Deloox scraper candidates for
    the query, then walks the same catalog URL-admission/priority logic as
    the deployed catalog engine while recording exactly where each proven
    target URL is (or is not) encountered.
    """
    started = time.monotonic()
    query = str(q or '').strip() or 'Hawas'
    out = {
        'diagnostic': 'deloox-catalog-trace-read-only-v1',
        'ok': False,
        'store': 'deloox',
        'query': query,
        'writes': False,
        'resync': False,
        'production_search_called': False,
        'product_matcher_called': False,
        'parameters': {'max_pages': int(max_pages), 'max_depth': int(max_depth)},
    }

    try:
        import catalog_engine
        from scrapers.deloox import scraper
        import requests

        product_classifier = getattr(catalog_engine, '_html_product_url', None)
        listing_classifier = getattr(catalog_engine, '_html_listing_url', None)
        priority_fn = getattr(catalog_engine, '_html_discovery_priority', None)
        fetch_fn = getattr(catalog_engine, '_fetch_html_page', None)
        discover_fn = getattr(scraper, '_discover', None)

        required = {
            '_html_product_url': product_classifier,
            '_html_listing_url': listing_classifier,
            '_html_discovery_priority': priority_fn,
            '_fetch_html_page': fetch_fn,
            'scraper._discover': discover_fn,
        }
        missing = [name for name, fn in required.items() if not callable(fn)]
        if missing:
            out['error'] = 'required_functions_unavailable'
            out['missing'] = missing
            return out

        session = requests.Session()
        session.headers.update(getattr(scraper, 'HEADERS', {}))
        try:
            proven_candidates = list(discover_fn(session, query) or [])
        finally:
            session.close()

        targets = []
        for url in proven_candidates[:80]:
            absolute = str(url or '').split('#', 1)[0]
            if absolute and absolute not in targets:
                targets.append(absolute)

        out['scraper_candidate_count'] = len(proven_candidates)
        out['scraper_candidates'] = proven_candidates[:100]
        out['target_urls'] = targets[:20]
        out['target_count'] = len(targets)

        seeds_map = getattr(catalog_engine, 'HTML_DISCOVERY_SEEDS', {})
        seeds = list((seeds_map.get('deloox') or ()))
        out['configured_seeds'] = seeds

        target_norm = {u.split('#', 1)[0]: u for u in targets}
        target_ids = set()
        for url in targets:
            match = re.search(r'/(?:product|produit|producto|prodotto)/(\d+)(?:/|$)', url, re.I)
            if match:
                target_ids.add(match.group(1))
        out['target_ids'] = sorted(target_ids)

        queue = []
        queued = set()
        visited = set()
        sequence = 0
        events = []
        target_state = {
            url: {
                'classifier': product_classifier('deloox', url, url),
                'queued': False,
                'visited': False,
                'found_in_page': None,
                'found_in_attribute': None,
                'found_in_raw_html': None,
                'source_page': None,
                'source_depth': None,
            }
            for url in targets
        }

        def normalize(value, base):
            if not value:
                return None
            return urllib.parse.urljoin(base, str(value)).split('#', 1)[0]

        def mark_target(raw_url, source_page, depth, channel):
            absolute = normalize(raw_url, source_page)
            if not absolute:
                return None
            canonical = target_norm.get(absolute)
            if canonical is not None:
                state = target_state[canonical]
                key = f'{channel}'
                if state.get(key) is None:
                    state[key] = {'source_page': source_page, 'depth': depth}
                if state['source_page'] is None:
                    state['source_page'] = source_page
                    state['source_depth'] = depth
                return canonical
            # Also match by known product id after redirects/encoding changes.
            m = re.search(r'/(?:product|produit|producto|prodotto)/(\d+)(?:/|$)', absolute, re.I)
            if m and m.group(1) in target_ids:
                for candidate in targets:
                    if m.group(1) in candidate:
                        state = target_state[candidate]
                        key = f'{channel}'
                        if state.get(key) is None:
                            state[key] = {'source_page': source_page, 'depth': depth, 'url_seen': absolute}
                        if state['source_page'] is None:
                            state['source_page'] = source_page
                            state['source_depth'] = depth
                        return candidate
            return None

        def add(url, depth, source=''):
            nonlocal sequence
            if not url or depth > max_depth:
                return
            key = url.split('#', 1)[0]
            if key in queued or key in visited:
                return
            p = urllib.parse.urlparse(key)
            if p.netloc.lower() != 'www.deloox.be' or p.scheme not in ('http', 'https'):
                return
            product = product_classifier('deloox', key, key)
            if product:
                canonical = mark_target(product, source or key, depth, 'found_in_queue')
                if canonical:
                    target_state[canonical]['queued'] = True
                return
            listing = listing_classifier('deloox', key, key, source)
            if not listing:
                return
            sequence += 1
            priority = priority_fn('deloox', key, depth, source)
            heapq.heappush(queue, (priority, sequence, key, depth, source))
            queued.add(key)
            for target in targets:
                if target_state[target]['queued'] is False and target == key:
                    target_state[target]['queued'] = True

        for seed in seeds:
            add(seed, 0, 'configured_seed')

        while queue and len(visited) < int(max_pages):
            batch = []
            while queue and len(batch) < 12 and len(visited) + len(batch) < int(max_pages):
                _priority, _seq, url, depth, source = heapq.heappop(queue)
                if url in visited:
                    continue
                visited.add(url)
                batch.append((url, depth, source))

            if not batch:
                continue

            with ThreadPoolExecutor(max_workers=min(12, len(batch))) as pool:
                futures = {
                    pool.submit(fetch_fn, 'deloox', url): (url, depth, source)
                    for url, depth, source in batch
                }
                for future in as_completed(futures):
                    requested, depth, source = futures[future]
                    page_event = {
                        'url': requested,
                        'depth': depth,
                        'source': source,
                        'status': None,
                        'bytes': 0,
                        'product_links': 0,
                        'listing_links': 0,
                        'target_hits': [],
                    }
                    try:
                        _requested, final, data, error = future.result()
                    except Exception as exc:
                        page_event['status'] = f'{type(exc).__name__}:{exc}'
                        events.append(page_event)
                        continue

                    if error:
                        page_event['status'] = error
                        events.append(page_event)
                        continue

                    page_event['status'] = 'OK'
                    page_event['bytes'] = len(data or b'')
                    base = final or requested
                    soup = BeautifulSoup(data, 'html.parser')

                    for a in soup.find_all('a', href=True):
                        raw = a.get('href')
                        absolute = normalize(raw, base)
                        target = mark_target(raw, requested, depth, 'found_in_page')
                        if target:
                            page_event['target_hits'].append({'target': target, 'channel': 'anchor', 'raw': raw})
                        product = product_classifier('deloox', raw, base)
                        if product:
                            page_event['product_links'] += 1
                            if target is None:
                                target = mark_target(product, requested, depth, 'found_in_page')
                                if target:
                                    page_event['target_hits'].append({'target': target, 'channel': 'product_classifier', 'raw': raw})
                            continue
                        listing = listing_classifier('deloox', raw, base, a.get_text(' ', strip=True))
                        if listing:
                            page_event['listing_links'] += 1
                            add(listing, depth + 1, requested)

                    for node in soup.find_all(True):
                        label = node.get_text(' ', strip=True)[:300]
                        for attr in (
                            'value', 'data-value', 'data-filter-url', 'data-option-url',
                            'data-redirect-url', 'data-url', 'data-href', 'data-link',
                            'data-next-url', 'data-next', 'data-load-more-url',
                            'data-pagination-url',
                        ):
                            raw = node.get(attr)
                            if not raw:
                                continue
                            target = mark_target(raw, requested, depth, 'found_in_attribute')
                            if target:
                                page_event['target_hits'].append({'target': target, 'channel': attr, 'raw': str(raw)[:500]})
                            product = product_classifier('deloox', raw, base)
                            if product:
                                continue
                            listing = listing_classifier('deloox', raw, base, label)
                            if listing:
                                add(listing, depth + 1, requested)

                    try:
                        raw_html = data.decode('utf-8', 'ignore').replace('\\/', '/')
                        for match in re.finditer(
                            r"https?://[^\"'\s<>\\]+|/(?:[A-Za-z0-9._~-]+/){1,}[^\"'\s<>\\]+",
                            raw_html,
                            re.I,
                        ):
                            raw = match.group(0)
                            target = mark_target(raw, requested, depth, 'found_in_raw_html')
                            if target:
                                page_event['target_hits'].append({'target': target, 'channel': 'raw_html', 'raw': raw[:500]})
                            absolute = normalize(raw, base)
                            product = product_classifier('deloox', absolute, base)
                            if product:
                                continue
                            listing = listing_classifier('deloox', absolute, base, 'embedded_navigation')
                            if listing:
                                add(listing, depth + 1, requested)
                    except Exception as exc:
                        page_event['raw_scan_error'] = f'{type(exc).__name__}:{exc}'

                    for node in soup.find_all(['a', 'link'], href=True):
                        rel = ' '.join(node.get('rel') or []).lower()
                        href = node.get('href')
                        if 'next' in rel or re.search(r'(?:page|pagina|offset|start|p)=', urllib.parse.urlparse(href or '').query, re.I):
                            listing = listing_classifier('deloox', href, base, 'pagination')
                            if listing:
                                add(listing, depth + 1, requested)

                    events.append(page_event)

            if all(state.get('source_page') is not None for state in target_state.values()):
                break

        out['visited'] = len(visited)
        out['queue_remaining'] = len(queue)
        out['listing_urls_seen'] = len(queued)
        out['events'] = events[:100]
        out['target_state'] = target_state
        out['target_urls_found_anywhere'] = [u for u, s in target_state.items() if s.get('source_page')]
        out['targets_found_count'] = len(out['target_urls_found_anywhere'])
        out['diagnosis'] = (
            'TARGET_URL_FOUND_IN_DISCOVERY_SURFACE'
            if out['targets_found_count'] else
            'TARGET_URL_NOT_SEEN_BEFORE_CRAWL_LIMIT'
        )
        out['ok'] = True
        return out
    except Exception as exc:
        out['error'] = f'{type(exc).__name__}:{exc}'
        return out
    finally:
        out['elapsed_sec'] = round(time.monotonic() - started, 3)
