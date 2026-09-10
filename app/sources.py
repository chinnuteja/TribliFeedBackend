"""
Source registry — the single source of truth for what TRIBLI ingests.

Every source declares WHICH scraper handles it and WHAT category it feeds.
Adding a source = adding a row here. No other file needs to change.

kind:
  rss              -> generic RSS/Atom feed (articles)
  rss_opportunity  -> job RSS, scored like JobPosting
  rss_festival     -> editorial call-for-entry RSS
  jobposting       -> sitemap of URLs, each page carrying schema.org JobPosting
  festivalapi      -> the Festival API REST client
  official_call    -> curated permalink + deadline; redirect card only


Optional per-source fields:
  refresh_min    minutes before this source is worth re-running (default:
                 INGEST_INTERVAL_MIN). A paid or slow-moving source sets this
                 higher so a frequent pipeline schedule doesn't re-hit it.
  max_age_days   ignore sitemap entries whose <lastmod> is older than this.
"""

# Sources that are live and pulling.
SOURCES = [
    # ---------- OPPORTUNITIES (schema.org JobPosting) ----------
    dict(id="aiocine", name="AIO Cine", kind="jobposting", category="casting",
         sitemap="https://aiocine.com/jobs-{ym}.xml", sitemap_dynamic=True,
         limit=80, credibility=5,
         note="Verifies production houses before they can post. Cleanest structured data of the three."),
    dict(id="castkro", name="Castkro", kind="jobposting", category="casting",
         sitemap="https://www.castkro.com/sitemaps/jobs_sitemap.xml",
         limit=80, credibility=3, max_age_days=60,
         note="449 listings. Some adult-content posts need filtering."),
    dict(id="dazzlerr", name="Dazzlerr", kind="jobposting", category="casting",
         sitemap="https://www.dazzlerr.com/jobs-sitemap.xml",
         sitemap_browser_ua=True,
         limit=60, credibility=3, max_age_days=60,
         note="12,099 job URLs using JobPosting microdata rather than JSON-LD."),
    dict(id="avjobs", name="Animation and VFX Jobs", kind="rss_opportunity",
         category="casting",
         url="https://animationandvfxjobs.com/feed/",
         credibility=4, limit=15,
         note="Hourly WordPress RSS of studio HR posts. Hyderabad/Mumbai VFX "
              "walk-ins included. Non-job explainers in the same feed are dropped. "
              "Probed 2026-08-31: robots User-agent * Disallow empty (allow all); "
              "/feed/ is RSS 2.0, hourly, 7 entries including Hanu Studios roto "
              "and a SmartRoto explainer that must fail the job gate."),

    # ---------- FESTIVALS ----------
    dict(id="festivalapi", name="Festival API", kind="festivalapi", category="festivals",
         credibility=5, refresh_min=10080,
         note="Official REST API over 14,076 festivals. Free tier — credits burn "
              "per search, and festival deadlines move monthly, so refresh weekly. "
              "India / short / documentary / closing-soon first; FilmFreeway is "
              "an outbound submit URL, never scraped."),
    dict(id="asianfilmfestivals", name="Asian Film Festivals", kind="rss_festival",
         category="festivals",
         url="https://asianfilmfestivals.com/category/call-for-entry/feed/",
         credibility=4, refresh_min=1440,
         note="CFE-only category RSS, not the mixed news feed. IFFK / IFFI / "
              "IDSFFK / PIFF often skip FilmFreeway. Probed 2026-09-03: 10 CFE "
              "items, currently 2027 international shorts; South calls appear "
              "when that publisher posts them."),
    dict(id="iffk2026", name="IFFK Call for Entry 2026", kind="official_call",
         category="festivals", credibility=5, refresh_min=1440, publisher="IFFK",
         call=dict(
             title="31st International Film Festival of Kerala — Call for Entry",
             permalink="https://vp.eventival.com/idsffk/31iffk",
             deadline="2026-09-10",
             publisher="IFFK / Kerala Chalachitra Academy",
             location="Thiruvananthapuram",
             region_tier="south",
             fee="Free entry",
             description="Feature films over 70 minutes. India premiere. Submit on "
                         "Eventival (account required to upload). Festival 11–18 Dec 2026.",
             opened_at="2026-08-12",
         ),
         note="Redirect-only. Official apply portal, not a scrape of Eventival. "
              "Visitor page is public; film upload needs an Eventival login — same "
              "class as FilmFreeway submit, not a hidden dashboard. "
              "iffk.in/submit 404s. Probed 2026-09-03: HTTP 200 HTML; robots Allow."),

    # ---------- CRAFT & TECH ----------
    dict(id="cined", name="CineD", kind="rss", category="tech",
         url="https://www.cined.com/feed/", credibility=5),
    dict(id="newsshooter", name="Newsshooter", kind="rss", category="tech",
         url="https://www.newsshooter.com/feed/", credibility=5),
    dict(id="pvc", name="ProVideo Coalition", kind="rss", category="tech",
         url="https://www.provideocoalition.com/feed/", credibility=5),
    dict(id="nofilmschool", name="No Film School", kind="rss", category="tech",
         url="https://nofilmschool.com/rss.xml", credibility=4),
    dict(id="beforesafters", name="befores & afters", kind="rss", category="tech",
         url="https://beforesandafters.com/feed", credibility=5),
    dict(id="filmmakermag", name="Filmmaker Magazine", kind="rss", category="tech",
         url="https://filmmakermagazine.com/feed/", credibility=5),
    dict(id="moviemaker", name="MovieMaker", kind="rss", category="tech",
         url="https://www.moviemaker.com/feed/", credibility=4),
    dict(id="wrapbook", name="Wrapbook", kind="rss", category="tech",
         url="https://www.wrapbook.com/blog/rss.xml", credibility=4),
    dict(id="premiumbeat", name="PremiumBeat", kind="rss", category="tech",
         url="https://www.premiumbeat.com/blog/feed/", credibility=4),
    dict(id="indiewire", name="IndieWire", kind="rss", category="tech",
         url="https://www.indiewire.com/feed/", credibility=4),
    dict(id="studiobinder", name="StudioBinder", kind="rss", category="tech",
         url="https://www.studiobinder.com/blog/feed/", credibility=4,
         note="Requires a browser User-Agent — returns 403 without one."),
    # --- new in this build ---
    dict(id="ymcinema", name="Y.M.Cinema", kind="rss", category="tech",
         url="https://ymcinema.com/feed/", credibility=4,
         note="Camera and cinema technology news. Added after live verification."),
    dict(id="frameio", name="Frame.io Insider", kind="rss", category="tech",
         url="https://blog.frame.io/feed/", credibility=5,
         note="Post-production workflow and craft. Deep archive."),
    dict(id="redshark", name="RedShark News", kind="rss", category="tech",
         url="https://www.redsharknews.com/rss.xml", credibility=4,
         note="Production technology and industry analysis."),
    dict(id="fdtimes", name="Film & Digital Times", kind="rss", category="tech",
         url="https://www.fdtimes.com/feed/", credibility=5,
         note="Authoritative on lenses and camera systems."),

    # ---------- AI IN FILM ----------
    dict(id="curiousrefuge", name="Curious Refuge", kind="rss", category="ai",
         url="https://curiousrefuge.com/blog?format=rss", credibility=5,
         note="Feed only works at /blog?format=rss — the /feed path 404s."),
    dict(id="delirio", name="Delirio / Karloff", kind="rss", category="ai",
         url="https://delirio.ai/blogs/karloff.atom", credibility=3),

    # ---------- INDUSTRY / TRADE ----------
    dict(id="ormax", name="Ormax Media", kind="rss", category="trade",
         url="https://www.ormaxmedia.com/feed/", credibility=5,
         note="Best business-signal source — commissioning and supply-trend data."),
    dict(id="variety", name="Variety", kind="rss", category="trade",
         url="https://variety.com/feed/", credibility=5),
    dict(id="animationxpress", name="Animation Xpress", kind="rss", category="trade",
         url="https://www.animationxpress.com/feed/", credibility=4,
         note="Indian animation, VFX and AVGC industry. Added after live verification."),

    # ---------- LEARN ----------
    dict(id="srfti", name="SRFTI", kind="rss", category="education",
         url="https://www.srfti.ac.in/feed", credibility=5,
         note="WARNING: this feed has carried script-injection test posts. Sanitising is mandatory."),
    dict(id="whistlingwoods", name="Whistling Woods", kind="rss", category="education",
         url="https://www.whistlingwoods.net/feed", credibility=4),

    # ---------- GRANTS & LABS ----------
    dict(id="sundance", name="Sundance Institute", kind="rss", category="grants",
         url="https://www.sundance.org/feed/", credibility=5,
         note="Labs, fellowships and grants. Added after live verification. "
              "Now 403s from this network on both attempts of the retry."),
    dict(id="filmindependent", name="Film Independent", kind="rss", category="grants",
         url="https://www.filmindependent.org/feed/", credibility=5,
         note="Grants, fellowships and labs — Project Involve, Fast Track, "
              "Fiscal Sponsorship. Probed 2026-08-28 with the project UA: "
              "HTTP 200, application/rss+xml; charset=UTF-8, 133416 bytes, "
              "10 entries, robots.txt allows."),
    dict(id="gotham", name="The Gotham", kind="rss", category="grants",
         url="https://thegotham.org/feed/", credibility=5,
         note="Lab and fellowship calls — Gotham Week, Rotterdam Lab Fellowship. "
              "Probed 2026-08-28 with the project UA: HTTP 200, "
              "application/rss+xml; charset=UTF-8, 31963 bytes, 20 entries, "
              "robots.txt allows."),
    dict(id="hbf_europe_mincopro", name="Hubert Bals HBF+Europe Minority Co-production",
         kind="official_call", category="grants",
         credibility=5, refresh_min=10080, publisher="Hubert Bals Fund",
         call=dict(
             title="HBF+Europe Minority Co-production Support 2026",
             permalink="https://iffr.com/en/hubert-bals-fund/funding-schemes/hbfeurope-minority-co-production-support",
             deadline="2026-09-22",
             publisher="Hubert Bals Fund / IFFR",
             location="International (India eligible)",
             region_tier="india",
             fee="Up to €60,000",
             description="India-eligible as the non-European producer. A European "
                         "MEDIA co-producer files the application. Opens 8 Sep 2026.",
             opened_at="2026-09-08",
         ),
         note="Redirect-only. Scheme page, not the HBF deadlines hub. Applicant is "
              "the European co-producer; Indian filmmakers need that partner. "
              "Payal Kapadia’s All We Imagine As Light is an HBF+Europe title. "
              "Probed 2026-09-03: HTTP 200 HTML, deadline 22 Sep 2026 17:00 CEST."),
    dict(id="alteff", name="ALT EFF Film Fund", kind="official_call", category="grants",
         credibility=5, refresh_min=10080, publisher="ALT EFF",
         call=dict(
             title="ALT EFF Film Fund 2026 — DocEdge window",
             permalink="https://www.alteff.in/film-fund",
             deadline="2026-12-10",
             publisher="ALT EFF / Rohini Nilekani Philanthropies",
             location="India",
             description="Environmental documentary fund. DocEdge Kolkata window "
                         "opens 1 Nov 2026. Apply on the official page.",
             opened_at="2026-11-01",
         ),
         note="Redirect-only. Curated official permalink, not a scrape of the body. "
              "Green Stories 2026 window already closed — not carded. "
              "Publisher page lists DocEdge close as both 1 Dec and 10 Dec 2026; "
              "card uses the later Submission Dates bound (2026-12-10). "
              "Probed 2026-08-31: HTTP 200 HTML at /film-fund; robots Allow "
              "(Squarespace Disallow is /config /search /account, not this path)."),
]

# Sources checked and NOT ingesting, with the tested reason.
# Surfaced through the API so the UI can explain every gap honestly.
NOT_INGESTING = [
    dict(name="Talentrack", category="casting", status="nofeed",
         reason="Sitemap contains zero job URLs — they pivoted to a brand-services agency model."),
    dict(name="Castingkart", category="casting", status="blocked",
         reason="Site now shows an AI-platform signup waitlist instead of live listings."),
    dict(name="Backstage India", category="casting", status="untested",
         reason="Not probed yet."),
    dict(name="CastYou", category="casting", status="rejected",
         acquisition="rejected",
         reason="Public HTML and robots Allow, but listings are third-party dumps "
                "the publisher itself disclaims as unauthenticated, mixed with SEO "
                "'child artist in {city}' indexes. Quality gate, not a legal wall."),
    dict(name="Talent Katta", category="casting", status="rejected",
         acquisition="rejected",
         reason="Claims huge call volume; treated as an unvetted dump until a "
                "JobPosting sitemap or authenticated CD feed is proven."),
    dict(name="Screen Entry", category="casting", status="untested",
         acquisition="watch",
         reason="Telugu Hyderabad marketplace. Apply is behind sign-in; no public "
                "per-post permalink found. A homepage link is not a post."),
    dict(name="reelOn", category="casting", status="nofeed",
         acquisition="watch",
         reason="robots.txt allows share-preview bots but Disallow /f/feeds/ and "
                "/alljobs did not render jobs logged-out. Watching for a public "
                "/job/{id} URL."),
    dict(name="Kinosphere", category="casting", status="nofeed",
         acquisition="watch",
         reason="App + agency hybrid. No public job permalink found."),
    dict(name="Naanu", category="casting", status="nofeed",
         acquisition="watch",
         reason="Kannada casting app. No public job sitemap."),
    dict(name="StarKast", category="casting", status="nofeed",
         acquisition="watch",
         reason="South-four-industries marketing site. Featured auditions are not "
                "stable permalinks."),
    dict(name="Cine Talent India", category="casting", status="untested",
         acquisition="watch",
         reason="Launch-stage 2026–27. No public listings yet."),
    dict(name="Starzoned", category="casting", status="nofeed",
         acquisition="watch",
         reason="AI-match app. No public board."),
    dict(name="Modelz World", category="telugu", status="nofeed",
         reason="Intake is WhatsApp-only by design — no web endpoint exists. "
                "Cover those posts via the share-to-TRIBLI path, not a scraper."),
    dict(name="Gnapika Entertainments", category="telugu", status="nofeed",
         reason="Real auditions page but no feed. Needs page-diff monitoring."),
    dict(name="Instagram casting accounts", category="telugu", status="nofeed",
         reason="Instagram blocks apps from reading third-party accounts without that account's consent."),
    dict(name="Facebook casting groups", category="telugu", status="nofeed",
         reason="Facebook restricted third-party group reads in 2018."),
    dict(name="FilmFreeway", category="festivals", status="nofeed",
         acquisition="rejected",
         reason="ToS forbid robots/extraction and republishing Site Content. "
                "Cloudflare bot-check on festival pages. Covered as an outbound "
                "submit URL via Festival API — never scraped."),
    dict(name="ITVS", category="grants", status="nofeed",
         reason="Feed is HTTP 200 application/rss+xml but holds one placeholder "
                "post ('Hello world!'). Same failure mode as StudioBinder."),
    dict(name="Creative Capital", category="grants", status="nofeed",
         reason="HTTP 200 application/rss+xml but zero entries."),
    dict(name="IDA (International Documentary Association)", category="grants", status="blocked",
         reason="HTTP 403 to both the project UA and a browser UA."),
    dict(name="Doc Society / Firelight / Chicken & Egg / Catapult / Tribeca",
         category="grants", status="nofeed",
         reason="All five return HTTP 404 at /feed — no feed published."),
    dict(name="Screen Australia", category="grants", status="nofeed",
         reason="HTTP 200 but serves text/html, not a feed."),
    dict(name="SFFILM", category="grants", status="untested",
         reason="Feed works (HTTP 200, application/rss+xml, 12 entries) but the "
                "newest post is three months old. Held back as a spare."),
    dict(name="NYFA", category="grants", status="untested",
         reason="Feed works (HTTP 200, application/rss+xml, 10 entries) and is "
                "current, but it is arts-wide rather than film. Spare."),
    dict(name="NFDC WAVES Film Bazaar", category="grants", status="nofeed",
         acquisition="watch",
         reason="Annual application cycle, no feed. Will become an official_call "
                "redirect when a current permalink + deadline is verified."),
    dict(name="Berlinale Talents", category="grants", status="nofeed",
         acquisition="watch",
         reason="Annual application window, no feed."),
    dict(name="Hubert Bals Fund (other schemes)", category="grants", status="nofeed",
         acquisition="watch",
         reason="HBF+Europe Minority Co-production 2026 is an official_call. "
                "Development Support closed 2 Apr; post-production closed 22 Jun. "
                "Card the next dated scheme page when it opens."),
    dict(name="IDFA Bertha Fund", category="grants", status="nofeed",
         acquisition="watch",
         reason="Asia-eligible doc fund. Hub page, not a dated open call."),
    dict(name="Asian Cinema Fund", category="grants", status="nofeed",
         acquisition="watch",
         reason="Busan AND fund. Annual; waiting on a current call permalink."),
    dict(name="World Cinema Fund", category="grants", status="nofeed",
         acquisition="watch",
         reason="Berlinale production fund. Annual window, no feed."),
    dict(name="Doha Film Institute", category="grants", status="nofeed",
         acquisition="watch",
         reason="International grants programme. No public RSS."),
    dict(name="India Foundation for the Arts", category="grants", status="nofeed",
         acquisition="watch",
         reason="Arts Practice moving-image grants. Programme page, not a dated call."),
    dict(name="PSBT", category="grants", status="nofeed",
         acquisition="watch",
         reason="Currently not inviting proposals. Email list when they reopen."),
    dict(name="Green Stories / DocEdge", category="grants", status="nofeed",
         acquisition="watch",
         reason="Green Stories 2026 window closed 15 Jul. DocEdge opens 1 Nov — "
                "covered via the ALT EFF official_call permalink."),
    dict(name="KSFDC / TFDC / Karnataka Chalanachitra / Telangana Cinema 2047",
         category="grants", status="nofeed",
         acquisition="watch",
         reason="State film bodies publish PDFs and GOs, not feeds. Card a window "
                "only when an official permalink and deadline exist."),
    dict(name="Telangana / AP film policy", category="grants", status="nofeed",
         acquisition="watch",
         reason="Government portal, updates irregularly, no feed."),
    dict(name="American Cinematographer", category="tech", status="blocked",
         reason="Anti-bot protection blocks the feed even with a browser User-Agent."),
    dict(name="ARRI / RED / Blackmagic / Sony / Aputure", category="tech", status="nofeed",
         reason="Checked all five manufacturers — none publish a feed."),
    dict(name="Videomaker", category="tech", status="blocked",
         reason="Returns HTTP 403 to automated requests."),
    dict(name="Motion Array", category="tech", status="blocked",
         reason="Returns HTTP 403 to automated requests."),
    dict(name="Broadcast AI Media News", category="ai", status="blocked",
         reason="Paywalled and bot-protected (HTTP 405)."),
    dict(name="PJ's Newsletter", category="ai", status="nofeed",
         reason="Email newsletter with no public feed — needs inbox ingestion."),
    dict(name="Screen Daily", category="trade", status="blocked",
         reason="Hard paywall, quote-based pricing. Variety covers the same ground free."),
    dict(name="Film Companion", category="trade", status="blocked",
         reason="Feed endpoint responds but returned zero articles. Under investigation."),
    dict(name="Moneycontrol / ETBrandEquity / Exchange4Media", category="trade", status="blocked",
         reason="All three return HTTP 403 to automated requests."),
    dict(name="Bollywood Hungama", category="trade", status="rejected",
         reason="Feed works, but content is box-office and star gossip — deliberately excluded by editorial policy."),
    dict(name="FTII", category="education", status="blocked",
         reason="/feed returns HTTP 200 but serves HTML, not a real feed."),
    dict(name="Annapurna College (ACFM)", category="education", status="untested",
         reason="Hyderabad school, most locally relevant. Next in line to probe."),
    dict(name="Ramoji / RAFT", category="education", status="nofeed",
         reason="No feed at the standard address."),
    dict(name="MasterClass", category="education", status="blocked",
         reason="Blocks automated visits at the root domain."),
    dict(name="Raindance", category="education", status="blocked",
         reason="Anti-bot protection returns HTTP 202."),
    dict(name="ScreenCraft", category="education", status="untested",
         reason="Confirmed active elsewhere, but DNS failed from the build network."),
    dict(name="MAA", category="unions", status="nofeed",
         reason="Site works but publishes no feed."),
    dict(name="Telugu Film Chamber (TFCC)", category="unions", status="nofeed",
         reason="Publishes government orders as PDFs. No feed."),
    dict(name="Kerala Film Chamber", category="unions", status="nofeed",
         reason="No feed. Runs an Internal Complaints Committee for workplace abuse."),
    dict(name="FEFSI", category="unions", status="blocked",
         reason="HTTP 503 on repeated checks — likely a genuine outage."),
    dict(name="SIFCC", category="unions", status="untested",
         reason="DNS failed from the build network."),
    dict(name="ProjectCasting", category="aggregator", status="rejected",
         reason="Feed works, but content is US celebrity gossip — excluded by editorial policy."),
    dict(name="StaffMeUp", category="aggregator", status="nofeed",
         reason="Sitemap exposes only blog posts, no job listings."),
    dict(name="ProductionHUB", category="aggregator", status="blocked",
         reason="HTTP 403 at the root domain."),
    dict(name="Mandy", category="aggregator", status="blocked",
         reason="HTTP 403 at the root domain."),
    dict(name="Backstage.com", category="aggregator", status="blocked",
         reason="HTTP 403 at the root domain."),
    dict(name="Feedspot", category="aggregator", status="nofeed",
         reason="A directory for finding sources by hand, not a feed to read from."),
]

CATEGORIES = [
    dict(id="casting",    label="Opportunities",   icon="●"),
    dict(id="telugu",     label="Telugu & South",  icon="◈"),
    dict(id="festivals",  label="Festivals",       icon="◐"),
    dict(id="tech",       label="Craft & Tech",    icon="▲"),
    dict(id="ai",         label="AI in Film",      icon="◇"),
    dict(id="trade",      label="Industry",        icon="■"),
    dict(id="education",  label="Learn",           icon="✦"),
    dict(id="grants",     label="Grants & Labs",   icon="◑"),
    dict(id="unions",     label="Unions",          icon="◒"),
    dict(id="aggregator", label="Aggregators",     icon="◆"),
]
