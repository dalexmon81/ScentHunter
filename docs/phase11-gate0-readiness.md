# Gate 0 — readiness audit (2026-11-05)

## Decision

**STATUS: BLOCKED — do not start shadow traffic or the 5% canary.**

The selected pilot remains **Bplatz — French Avenue Liquid Brun Eau de Parfum 100 ml**. Notino is now a documented alternative affiliate-feed path, but its application is still pending and it is not yet an active pilot.

This audit distinguishes CI fixtures, staging infrastructure, retailer authorization, affiliate-program approval, and live offer evidence. Passing one category does not imply another.

## Current verified evidence

### Phase 5 staging infrastructure

The isolated Fly.io staging deployment [run 42085586218](https://github.com/dalexmon81/ScentHunter/actions/runs/42085586218) completed successfully. All 20 job steps passed, including isolated ingestion/connector tests, Fly token scope verification and staging secret application, worker deploy with one app worker and zero Beat machines, worker startup and broker connection, read-only database/store safety audit, Alembic migrations, canonical brand-alias normalization, canonical catalog seed without activating a retailer, non-root worker verification, Celery broker ping, and queued-task smoke execution.

The seeded staging catalog contains **60 brands, 1,389 fragrances, and 512 variants**. It reports **stores=0, offers=0, invalid_active_offers=0**. The deployment includes the bounded manual-only Bplatz task from merged PR #360.

This proves staging deployment and smoke execution. It does not prove retailer authorization, a live offer, offer refresh, price history, or end-to-end catalog-first search.

### Bplatz bounded pilot implementation

PR [#360](https://github.com/dalexmon81/ScentHunter/pull/360) added a manual-only task for the exact Bplatz Liquid Brun EDP 100 ml product page. It is restricted to the approved product path, records source evidence against an ingestion run, and passes data through the existing validation/matching/promotion pipeline. It requires an explicit authorization reference.

The offline fixture tests passed in workflow [42073836383](https://github.com/dalexmon81/ScentHunter/actions/runs/42073836383), with 39 tests passing. The task is deployed to staging but **has not been invoked**. The authorization-reference field is a safeguard, not proof that permission exists.

### Bplatz permission request

Bplatz's official [Terms and Conditions](https://en.bplatz.de/pages/purchase-clauses) and [Privacy Policy](https://en.bplatz.de/pages/Data-protection) were reviewed. They do not expressly authorize automated collection or scraping. robots.txt could not be retrieved, so no allow/disallow conclusion is recorded.

A permission request was sent to **orders@bplatz.de** on 2026-11-05. It asks for an approved API/feed/affiliate feed or written permission for a limited one-product test, restricted to product URL, price/currency, and availability. **No reply or authorization has been received yet.** No live Bplatz request has been made.

Do not invoke the task until a permitted access method is confirmed and the authorization reference records the actual approval.

### Notino.fr affiliate program — application pending

The user supplied a screenshot from the CJ publisher account showing advertiser **4912189 — NOTINO.fr**, category **Fragrance**, under the filter **Status: Pending Applications**. The advertiser row is therefore present in the user's pending applications.

The screenshot also shows serviceable area **FRANCE**, supported currency **EUR**, and the program's displayed commission information (default 4–6%; other rates vary by partner type/content). This is evidence of a pending application only — **not approval, active advertiser status, feed entitlement, or permission to scrape Notino's website**.

CJ/VIVnetworks previously confirmed by email that a Notino.fr XML product feed is available to approved publishers and includes product names, EAN/GTIN, direct URLs, current prices, currency, availability, and images, with daily updates. CJ also stated that publisher approval by Notino is required and that Notino makes the final partner decision. The user's CJ network account welcome email confirms network-account activation, not approval to the Notino.fr program.

Next action: wait for the NOTINO.fr application to change from **Pending Applications** to an active/approved status, or for a direct decision from the program. After approval, inspect the program terms and feed access instructions in CJ, confirm the feed's permitted use and technical format, then implement a dedicated feed connector. Until then, do not attempt to fetch the feed or treat Notino as an authorized source.

### Latest retailer parser verification — 2026-11-05

Deloox parser hardening commit `136d381ca44057a2cd0774cc5a4cc6c3764a4720` passed all three relevant CI workflows:
- Backend Parser Regression: [42108328640](https://github.com/dalexmon81/ScentHunter/actions/runs/42108328640)
- Hydration Regression: [42108328805](https://github.com/dalexmon81/ScentHunter/actions/runs/42108328805)
- Next Engine Shadow Integration: [42108328702](https://github.com/dalexmon81/ScentHunter/actions/runs/42108328702)

The fix reads an explicit price from the selected Schema.org `priceSpecification` when `Offer.price` is absent. This is parser/fixture validation only. Deloox's earlier HTTP 403 remains an access blocker; no further live request was made.

The latest Gmail check found no new Bplatz permission response and no Notino advertiser approval/feed entitlement. The CJ network welcome email is not advertiser approval. Therefore these results do not change any Gate 0 authorization or real-offer requirements.

## Public-site publisher-readiness audit — 2026-11-06

### Public URL supplied by owner
`https://scenthunter.fly.dev` is the current Fly.io application URL supplied by the owner. No custom domain is currently configured/known.

### Live availability check
A direct page fetch of the Fly URL could not be completed in this audit (browser cache miss / fetch unavailable). Therefore HTTP status, rendered content, mobile behavior, robots/indexing, TLS, and live navigation are **not verified**. Do not report the live site as down or healthy based on this failed inspection.

### Repository source inspection
Inspected `frontend/index.html` on `phase11/gradual-migration` (916 KB). The source contains:
- Italian-language ScentHunter branding and perfume price-comparison positioning.
- Search UI, offer section, fragrance categories and wishlist/comparison interface.
- Retailer outbound links rendered from offer URLs.

The inspected HTML source did not expose a clear public navigation/footer link or page route for:
- About / operator identity;
- Contact details;
- Privacy policy;
- Terms of use;
- Affiliate disclosure / how the service earns money;
- Comparison methodology, offer freshness, and correction/reporting process.

This is a source-level observation of the inspected single-page frontend file, not a definitive claim that no such routes exist elsewhere in the deployed app. A repository-wide route/server audit and live browser verification remain required.

### Operator status — owner confirmation, 2026-11-06
The owner has explicitly confirmed that **he is the individual behind ScentHunter and that no company has been incorporated or otherwise established for the project yet**. This is the currently verified operator arrangement; do not describe ScentHunter as a SARL, company, or other legal entity.

This confirmation does **not**, by itself, establish whether the activity is legally a private non-professional project or a commercial/professional activity, nor whether a business permit, registration, VAT status, or other formalities are required. That classification must be checked against the actual activity, revenue model, and operational facts before launch or further affiliate monetization.

### Luxembourg legal-notice and privacy implications
The Luxembourg Law of 14 August 2000 on electronic commerce, Article 5, requires an information-society service provider to make certain identification details easily, directly, and permanently accessible to recipients and competent authorities. The statutory list includes the provider's name, geographical address of establishment, and contact details enabling rapid and direct communication, including an email address. Registration, VAT and activity-authorization details are included **where applicable**. The legal text does not make up a company identity where no company exists.

Accordingly, the public-site remediation must:
1. Identify the real operator in the correct capacity; do not invent a company name, legal form, RCS number, VAT number, or business permit.
2. Establish, with Luxembourg professional/legal advice if needed, which geographical address is legally appropriate to publish for this individual's actual establishment. Do not publish a home address in the repository or this audit; do not substitute a mailbox or registered-office service unless it is legally valid for the actual situation.
3. Publish a working direct contact channel, including an email address controlled by the operator. No address has been supplied or verified for publication.
4. Add registration/VAT/authorization details only if they apply and have been obtained.
5. Publish a privacy notice identifying the actual data controller and explaining real processing purposes, legal bases, recipients/processors, retention, user rights, and contact route. Do not copy a generic policy that describes data practices the site does not actually have.
6. Audit cookies and third-party trackers. CNPD guidance requires prior consent for non-essential cookies/trackers; strictly necessary technologies are treated differently. The live site's actual scripts and network behavior still need inspection.
7. Clearly identify affiliate/commercial communications and disclose the commercial relationship where links or placements may generate commission. Do not claim commissions never affect ranking unless that is demonstrably true in the implemented ranking logic.

Official references reviewed:
- [Luxembourg Law of 14 August 2000 on electronic commerce, consolidated text (Article 5 and commercial communications provisions)](https://legilux.public.lu/eli/etat/leg/loi/2000/08/14/n8)
- [Luxembourg Directorate for Consumer Protection — company identity and legal notices on websites](https://mpc.gouvernement.lu/en/le-ministere/protjur/pro-pc.html)
- [CNPD — cookies and other trackers guidance](https://cnpd.public.lu/fr/dossiers-thematiques/cookies0/cookies.html)
- [CNPD — information to provide to data subjects](https://cnpd.public.lu/en/particuliers/vos-droits/droit-a-information.html)

These sources support the information requirements above; they do not replace advice on the legal classification of this particular activity.

### Priority remediation before advertiser reapplication
1. Verify the deployed URL from a normal browser, including a logged-out session and mobile viewport.
2. Complete the Luxembourg legal classification of the activity and confirm whether any business permit, registration, or tax steps are required before monetized operation.
3. Confirm the operator's legally appropriate geographical address and a working contact email. Keep private address details out of source control until publication is intentionally approved.
4. Add clear, accurate public links for About, Contact, Privacy, Terms, Affiliate Disclosure, and How comparison works; ensure each page is actually served and linked in the visible footer/navigation.
5. Explain the service accurately: fragrance-only comparison, exact variant matching (concentration/size/packaging), retailer source, price/currency, stock status, last checked time, shipping/coupon limitations, and how users report errors. Never claim coverage or freshness not measured by the backend.
6. Verify consent/cookie behavior and privacy text against the actual data collected and processors.
7. Ensure there are genuine product/category pages and traceable current offers before presenting the site as an operational price-comparison service. Do not fabricate products, retailers, prices, stock, reviews, or timestamps.

### Scope
No frontend files were changed, no DNS/custom domain was purchased or configured, no new affiliate application was submitted, and no retailer was activated. This is an audit and prioritized remediation plan only. Gate 0 remains BLOCKED; shadow/canary remain 0%.

## Awin advertiser application outcomes — verified from Gmail, 2026-11-06

A Gmail search of messages from `no-reply@awin.com` found two advertiser rejection notices dated 2026-08-06 for publisher ScentHunter (PID 3021971):

| Advertiser | Advertiser ID | Recorded rejection reason |
|---|---:|---|
| Fragrance Click UK | 124166 | “Site does not complement advertiser brand” |
| Perfume Click | 6561 | “URL is irrelevant to advertiser brand” |

The same search found the Awin network publisher-account activation email dated 2026-08-05. That account activation is separate from advertiser-program acceptance.

**Scope limitation:** the mailbox search found these two rejection notices; it does not establish that every Awin advertiser application was rejected. The user recalls further applications but no other rejection notices were found in this search. Do not describe all Awin programmes as rejected without additional evidence.

**Interpretation:** both recorded reasons concern perceived site/URL relevance, not API tokens or feed configuration. This suggests improving the public-facing publisher presentation before submitting more applications: clearly explain ScentHunter as a perfume-only search and price-comparison service; show usable perfume category/product pages and genuine, traceable offers; make operator/contact, privacy, terms, affiliate disclosure, data freshness and comparison methodology easy to find. These are recommended readiness checks, not confirmed causes of all advertiser decisions.

Do not reapply to the same advertisers yet. First audit the live public site against those criteria and document the actual pages and current state. No changes to public website or new advertiser applications have been made as part of this audit.

## Additional affiliate-feed route: Awin (research only)

A new research shortlist is documented in [phase11-affiliate-feed-alternatives.md](phase11-affiliate-feed-alternatives.md). Public merchant profiles indicate:
- Perfume Market UK (Awin merchant 124168): daily automated product feed advertised.
- Perfumetrader DE (Awin merchant 11672): product data advertised.
- The Fragrance Shop (Rakuten merchant 43488): automated daily feed advertised.

These public descriptions do not prove publisher acceptance, feed entitlement, price-comparison permission, required fields, or shipping coverage for ScentHunter's target countries. No application result or feed download has been verified. Do not implement a live downloader or activate any of these merchants until the publisher account shows access and the program terms permit the intended use.

## Offline quality evidence

- PR #347 adds the Bplatz offline fixture validation matrix.
- PR #343 workflow [41967935150](https://github.com/dalexmon81/ScentHunter/actions/runs/41967935150) passed Bplatz fixture parsing, Celery discovery, raw artifact SHA-256, and artifact-to-ingestion-run linkage.
- PR #343 workflow [41968439231](https://github.com/dalexmon81/ScentHunter/actions/runs/41968439231) passed timeout retry/quarantine isolation, wrong-size rejection (50 ml versus canonical 100 ml), and ambiguous duplicate-GTIN review without automatic matching.
- Latest PR #345 CI checks passed: backend parser [42074248195](https://github.com/dalexmon81/ScentHunter/actions/runs/42074248195), Next Engine Shadow Integration [42074248249](https://github.com/dalexmon81/ScentHunter/actions/runs/42074248249), and Hydration Regression [42074248330](https://github.com/dalexmon81/ScentHunter/actions/runs/42074248330).

These are offline fixture/stub or CI checks. They are not evidence of a current retailer offer or live authorized ingestion.

## Gate 0 checklist

| Requirement | Status |
|---|---|
| Disposable PostgreSQL/Redis/Celery CI integration | PASS — synthetic CI only |
| Bplatz Liquid Brun historical fixture and validation matrix | PASS — historical/offline only |
| Bplatz artifact linkage and negative-path tests | PASS — fixture/stub CI only |
| Bounded manual Bplatz task implemented | PASS — merged and deployed to staging; not invoked |
| Isolated staging deploy, migrations, canonical seed | PASS — run 42085586218 |
| Staging worker non-root, Celery ping and queued smoke task | PASS — run 42085586218 |
| Bplatz automated access permission/method | BLOCKED — email sent; awaiting reply |
| Notino.fr CJ publisher application | PENDING — screenshot confirms Pending Applications |
| Notino.fr affiliate-feed entitlement | BLOCKED — requires advertiser approval and feed terms review |
| Retailer activated in staging | NOT RUN — stores=0 |
| Real offer persisted through Phase 5 PostgreSQL | NOT RUN — offers=0 |
| Real Celery price/stock refresh and price history | NOT RUN |
| Catalog search proven to avoid synchronous retailer requests | NOT RUN |
| Rollback/readiness proof for live traffic | NOT COMPLETE |
| Shadow/canary traffic | BLOCKED — 0% |

## Required next steps

1. Await Bplatz's response. If it confirms an approved API/feed or grants written permission, record the exact scope and approval reference before any live request.
2. Monitor the NOTINO.fr application in CJ. Once approved, inspect the program terms and obtain the official feed access instructions; confirm permitted use before connecting it.
3. In parallel, evaluate alternative retailers that provide a documented API, product feed, or affiliate feed with terms permitting the intended use. Do not assume that an affiliate account alone authorizes scraping or feed reuse.
4. For the first retailer with a confirmed permitted method, configure it explicitly in isolated staging and run a narrowly bounded pilot. Keep the Bplatz task dormant unless Bplatz approval arrives.
5. Verify one genuine offer is persisted, validated, refreshed by Celery, represented in price history, and returned by catalog-first search without a synchronous retailer request.
6. Complete rollback, monitoring, and readiness checks before considering shadow traffic. Start with shadow only after Gate 0 approval; consider 5% canary only after shadow evidence is acceptable.

Do not create a synthetic published offer, scrape around a block, activate a retailer without a permitted access method, or enable shadow/canary traffic while the gate is blocked.

**Gate 0 remains BLOCKED; shadow/canary remain 0%.**


### Follow-up legal classification research — Luxembourg official guidance, 2026-11-06

This section records an official-source review prompted by the owner's confirmation that ScentHunter is currently operated by an individual and no company has been formed.

**Important distinction: no company does not mean no business formalities.** Guichet.lu describes a sole proprietorship as an activity carried out by a natural person in their own name; no separate legal entity needs to be incorporated. Depending on the actual activity, however, the individual may still need the relevant business permit, registrations and social-security affiliation. A sole proprietor trading as a merchant may also have RCS registration obligations. See [Sole proprietorship (self-employed persons)](https://guichet.public.lu/en/entreprises/creation-developpement/forme-juridique/entreprise-individuelle-societe-personnes/entreprise-individuelle.html).

Guichet.lu states that, as a general rule, an economic activity carried out habitually is subject to prior establishment authorisation, including commercial activities and certain services, whether performed independently or through a company. The precise classification of this particular perfume-comparison/affiliate activity has **not** been determined by the administration. See [Initial application for an establishment permit](https://guichet.public.lu/en/entreprises/creation-developpement/autorisation-etablissement/autorisation-honorabilite/autorisation-etablissement.html) and [Commercial activities and services](https://guichet.public.lu/en/entreprises/creation-developpement/autorisation-etablissement/commerce/commerce.html).

**Preliminary application to ScentHunter (not a legal ruling):**
- The project is operated by an individual; incorporation of a SARL is not automatically a prerequisite to operating in one's own name.
- If the site regularly promotes retailers and earns affiliate commissions, that recurring revenue-generating activity may be treated as an economic/commercial service. The fact that consumers do not pay ScentHunter directly does not by itself settle the classification.
- Do not assume that a hobby/personal-project label, low revenue, or a free-to-use website creates an exemption. Ask the competent Ministry of the Economy / House of Entrepreneurship to classify the exact activity and confirm whether an establishment permit is required before activating affiliate monetisation.
- If the activity is carried on as a sole proprietorship and requires an establishment permit, Guichet.lu describes subsequent steps including CCSS self-employed affiliation and VAT registration. CCSS says self-employed persons must affiliate within 8 days after starting their activity; where a specific authorisation is required, it must be held before starting the professional activity.
- The Luxembourg VAT small-business exemption threshold is EUR 50,000 annual turnover excluding VAT (with a 10% tolerance under the stated conditions). This is a VAT regime threshold, **not** a blanket exemption from business permits, income tax, social-security obligations, or all VAT identification/filing duties. Cross-border EU services can create additional VAT questions. See [VAT registration](https://guichet.public.lu/en/entreprises/creation-developpement/obligations-fiscales-sociales/impots/inscription-tva.html), [SME VAT exemption scheme](https://pfi.public.lu/fr/professionnel/tva/sme.html), and [CCSS affiliation](https://ccss.public.lu/en/independants/commencer-arreter-activite/affilier.html).

**Recommended next action — obtain a written classification before monetisation:**
Contact the House of Entrepreneurship / Ministry of the Economy and describe the actual model accurately: an individual resident/established in Luxembourg operating an online perfume price-comparison website; no consumer charge; retailer outbound links; potential affiliate commissions from approved partner programmes; no sale or possession of perfumes; no employees (unless this changes). Ask:
1. Does this exact activity require an autorisation d'établissement, and under which activity category?
2. Can it be carried on as an entreprise individuelle in the operator's own name, and what RCS registration is required?
3. What establishment/address conditions apply to a home-based online activity?
4. When must CCSS self-employed affiliation begin?
5. How should affiliate commissions from EU and non-EU networks be treated for Luxembourg VAT, including the small-business exemption and cross-border services?
6. Which details must appear in the site's legal notice before the first affiliate link/commission?

Do not start or represent the activity as formally compliant based solely on this preliminary desk review. Do not apply for an arbitrary permit category or publish private address details until the competent authority has confirmed the applicable requirements.

**Official source links reviewed (6 November 2026):**
- [Guichet.lu — Sole proprietorship](https://guichet.public.lu/en/entreprises/creation-developpement/forme-juridique/entreprise-individuelle-societe-personnes/entreprise-individuelle.html)
- [Guichet.lu — Commercial activities and services](https://guichet.public.lu/en/entreprises/creation-developpement/autorisation-etablissement/commerce/commerce.html)
- [Guichet.lu — Establishment permit](https://guichet.public.lu/en/entreprises/creation-developpement/autorisation-etablissement/autorisation-honorabilite/autorisation-etablissement.html)
- [CCSS — Self-employed affiliation](https://ccss.public.lu/en/independants/commencer-arreter-activite/affilier.html)
- [Guichet.lu — VAT registration](https://guichet.public.lu/en/entreprises/creation-developpement/obligations-fiscales-sociales/impots/inscription-tva.html)
- [AED — Small-business VAT exemption scheme](https://pfi.public.lu/fr/professionnel/tva/sme.html)

The review is informational and does not replace a written administrative decision or advice from a Luxembourg accountant/legal professional.
