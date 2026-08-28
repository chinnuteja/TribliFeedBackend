"""
Source registry — the single source of truth for what TRIBLI ingests.

Every source declares WHICH scraper handles it and WHAT category it feeds.
Adding a source = adding a row here. No other file needs to change.

kind:
  rss          -> generic RSS/Atom feed
  jobposting   -> sitemap of URLs, each page carrying schema.org JobPosting
                  (JSON-LD or microdata)
  festivalapi  -> the Festival API REST client

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
         limit=60, credibility=3, max_age_days=60,
         note="12,099 job URLs using JobPosting microdata rather than JSON-LD."),

    # ---------- FESTIVALS ----------
    dict(id="festivalapi", name="Festival API", kind="festivalapi", category="festivals",
         credibility=5, refresh_min=10080,
         note="Official REST API over 14,076 festivals. Free tier — credits burn "
              "per search, and festival deadlines move monthly, so refresh weekly."),

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
    dict(name="CastYou", category="casting", status="untested",
         reason="Not probed yet."),
    dict(name="Modelz World", category="telugu", status="nofeed",
         reason="Intake is WhatsApp-only by design — no web endpoint exists."),
    dict(name="Gnapika Entertainments", category="telugu", status="nofeed",
         reason="Real auditions page but no feed. Needs page-diff monitoring."),
    dict(name="Instagram casting accounts", category="telugu", status="nofeed",
         reason="Instagram blocks apps from reading third-party accounts without that account's consent."),
    dict(name="Facebook casting groups", category="telugu", status="nofeed",
         reason="Facebook restricted third-party group reads in 2018."),
    dict(name="FilmFreeway", category="festivals", status="nofeed",
         reason="Sitemap holds only marketing pages; its webhooks are organizer-side only. Covered via Festival API instead."),
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
         reason="Annual application cycle, no feed. Calendar entry, not automation."),
    dict(name="Berlinale Talents", category="grants", status="nofeed",
         reason="Annual application window, no feed."),
    dict(name="Hubert Bals Fund", category="grants", status="nofeed",
         reason="Two funding rounds a year, no feed."),
    dict(name="Telangana / AP film policy", category="grants", status="nofeed",
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
