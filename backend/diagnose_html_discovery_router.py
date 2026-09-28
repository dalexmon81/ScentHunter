from fastapi import APIRouter, Query

router = APIRouter()

@router.get('/diagnose-html-discovery-trace')
def diagnose_html_discovery_trace_endpoint(
    store: str = Query('deloox'),
    q: str = Query('Liquid Brun'),
    max_pages: int = Query(120, ge=1, le=800),
    max_depth: int = Query(8, ge=0, le=8),
    max_events: int = Query(500, ge=50, le=2000),
):
    try:
        from catalog_engine import diagnose_html_discovery_trace
        return diagnose_html_discovery_trace(store=store, query=q, max_pages=max_pages,
                                             max_depth=max_depth, max_events=max_events)
    except Exception as exc:
        return {'ok': False, 'diagnostic': 'html-discovery-trace-read-only-v1',
                'error': f'{type(exc).__name__}: {exc}', 'store': store, 'query': q}
