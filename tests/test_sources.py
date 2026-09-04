from corvette_tracker.sources.autoscout24 import (
    normalize_autoscout24_image_url,
    parse_autoscout24_search,
)
from corvette_tracker.sources.autouncle import parse_autouncle_search
from corvette_tracker.sources.classic_trader import parse_classic_trader_search
from corvette_tracker.sources.kleinanzeigen import (
    fetch_kleinanzeigen,
    normalize_kleinanzeigen_image_url,
    parse_kleinanzeigen_detail_images,
    parse_kleinanzeigen_pagination_urls,
    parse_kleinanzeigen_search,
)

AUTOSCOUT_HTML = """
<html><body>
<article data-testid="list-item" id="as24-123">
  <a href="/angebote/chevrolet-corvette-c6-z06-abc123">Chevrolet Corvette C6 Z06 LS7</a>
  <img src="https://prod.pictures.autoscout24.net/listing-images/as24_abc.jpg/250x188.webp" />
  <p>59.900 €</p><p>72.000 km</p><p>05/2008</p><p>512 PS</p><p>München</p>
  <span>unfallfrei, HU 06/2027</span>
</article>
</body></html>
"""

KLEINANZEIGEN_HTML = """
<html><body>
<article class="aditem" data-adid="ka-77" data-href="/s-anzeige/corvette-c6-grand-sport/77-216-1234">
  <a href="/s-anzeige/corvette-c6-grand-sport/77-216-1234">12</a>
  <h2><a class="ellipsis" href="/s-anzeige/corvette-c6-grand-sport/77-216-1234">Chevrolet Corvette C6 Grand Sport LS3</a></h2>
  <img src="https://img.example/ka.jpg" />
  <p class="aditem-main--middle--price-shipping--price">54.900 €</p>
  <p class="aditem-main--middle--description">68.000 km EZ 05/2011 HU 06/2027 Getriebe Manuell</p>
  <div class="aditem-main--top--left">Hamburg</div>
</article>
</body></html>
"""

AUTOUNCLE_HTML = """\
<html><body>
<article>
  <div class="_AQ3hX">
    <div class="_v1SHB">
      <img src="https://autouncle-public.s3.eu-west-1.amazonaws.com/de/car_images/c6.webp" />
    </div>
  </div>
  <a class="_p9jqN" href="/de/d/222-c6-corvette">
    <h3>Gebraucht (2008) Chevrolet Corvette C6 LS3 437 PS | Seltenes Fahrzeug</h3>
    <ul>
      <li>Mär 2008</li>
      <li>68.000 km</li>
      <li>6.2L Benzin</li>
      <li>Coupé</li>
      <li>Schaltgetriebe</li>
      <li>437 PS (321 kW)</li>
    </ul>
  </a>
  <div class="_eMl_E">
    <div class="_i2QOc">54.900&nbsp;€</div>
  </div>
</article>
</body></html>
"""

CLASSIC_TRADER_HTML = """
<html><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"ItemList","itemListElement":[{"@type":"ListItem","item":{"@type":"Vehicle","name":"Chevrolet Corvette C6 Z06 LS7","url":"/de/automobile/inserat/chevrolet/corvette/c6-z06/2008/123","image":"https://cdn.classic-trader.com/I/images/640_480/c6.jpg","offers":{"price":"69900","priceCurrency":"EUR"},"description":"EZ 05/2008, 72.000 km, 512 PS, Schaltgetriebe"}}]}
</script>
</body></html>
"""


def test_parse_autouncle_search_extracts_normalized_c6_listings():
    listings = parse_autouncle_search(
        AUTOUNCLE_HTML, "https://www.autouncle.de/de/gebrauchtwagen/Chevrolet/Corvette?freetext=C6"
    )

    assert len(listings) == 1
    listing = listings[0]
    assert listing.source == "AutoUncle"
    assert listing.url == "https://www.autouncle.de/de/d/222-c6-corvette"
    assert listing.price_eur == 54900
    assert listing.mileage_km == 68000
    assert listing.engine == "LS3"
    assert listing.image_urls == [
        "https://autouncle-public.s3.eu-west-1.amazonaws.com/de/car_images/c6.webp"
    ]


def test_parse_classic_trader_search_extracts_json_ld_listings():
    listings = parse_classic_trader_search(
        CLASSIC_TRADER_HTML,
        "https://www.classic-trader.com/de/automobile/suche/chevrolet/corvette/c6",
    )

    assert len(listings) == 1
    listing = listings[0]
    assert listing.source == "Classic Trader"
    assert (
        listing.url
        == "https://www.classic-trader.com/de/automobile/inserat/chevrolet/corvette/c6-z06/2008/123"
    )
    assert listing.price_eur == 69900
    assert listing.mileage_km == 72000
    assert listing.engine == "LS7"
    assert listing.image_urls == ["https://cdn.classic-trader.com/I/images/640_480/c6.jpg"]


def test_parse_autoscout24_search_extracts_normalized_listings():
    listings = parse_autoscout24_search(
        AUTOSCOUT_HTML, "https://www.autoscout24.de/lst/chevrolet/corvette"
    )

    assert len(listings) == 1
    listing = listings[0]
    assert listing.source == "AutoScout24"
    assert listing.source_listing_id == "as24-123"
    assert listing.price_eur == 59900
    assert listing.image_urls == [
        "https://prod.pictures.autoscout24.net/listing-images/as24_abc.jpg/1920x1080.webp"
    ]
    assert listing.engine == "LS7"


def test_parse_autoscout24_next_data_without_anchor_href():
    html = """
    <html><body><script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"listings":[{"id":"next-1","url":"/angebote/chevrolet-corvette-c6-benzin-schwarz-next-1","price":{"priceRaw":41900,"priceFormatted":"€ 41.900"},"images":["https://img.example/as24-next.webp"],"location":{"zip":"80809","city":"München"},"seller":{"type":"P"},"vehicle":{"make":"Chevrolet","model":"Corvette","modelVersionInput":"C6"},"vehicleDetails":[{"data":"03/2010"},{"data":"61.000 km"},{"data":"297 kW (404 PS)"}] }]}}}
    </script></body></html>
    """

    listings = parse_autoscout24_search(html, "https://www.autoscout24.de/lst/chevrolet/corvette")

    assert len(listings) == 1
    assert listings[0].source_listing_id == "next-1"
    assert (
        listings[0].url
        == "https://www.autoscout24.de/angebote/chevrolet-corvette-c6-benzin-schwarz-next-1"
    )
    assert listings[0].title == "Chevrolet Corvette C6"
    assert listings[0].price_eur == 41900
    assert listings[0].mileage_km == 61000
    assert listings[0].image_urls == ["https://img.example/as24-next.webp"]


def test_parse_autoscout24_detail_next_data_uses_listing_details_fields():
    html = """
    <html><body><script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"listingDetails":{"id":"e7fbd6c4-e19f-4a64-9b89-c8bd28ba3111","url":"/angebote/corvette-c6-coupe-automatik-benzin-cat_ma16380mo19140-e7fbd6c4-e19f-4a64-9b89-c8bd28ba3111","price":{"priceRaw":39900,"priceFormatted":"€ 39.900"},"images":["https://prod.pictures.autoscout24.net/listing-images/e7fbd6c4.jpg/250x188.webp"],"location":{"zip":"48143","city":"Münster"},"vehicle":{"make":"Chevrolet","model":"Corvette","modelVersionInput":"C6 Coupe Automatik","mileageInKmRaw":82000,"firstRegistrationDate":"2006-06-01","powerInHp":404,"gearbox":"Automatic","bodyType":"Coupe"},"vehicleDetails":[{"label":"Getriebe","data":"Automatik"},{"label":"Karosserieform","data":"Coupé"},{"label":"Leistung","data":"297 kW (404 PS)"},{"label":"Kilometerstand","data":"82.000 km"}]}}}}
    </script></body></html>
    """

    listings = parse_autoscout24_search(
        html,
        "https://www.autoscout24.de/angebote/corvette-c6-coupe-automatik-benzin-cat_ma16380mo19140-e7fbd6c4-e19f-4a64-9b89-c8bd28ba3111",
    )

    assert len(listings) == 1
    listing = listings[0]
    assert listing.source_listing_id == "e7fbd6c4-e19f-4a64-9b89-c8bd28ba3111"
    assert listing.transmission == "automatic"
    assert listing.engine is None
    assert listing.probable_engine == "LS2"
    assert listing.trim == "Base"
    assert listing.body_style == "Targa"
    assert listing.price_eur == 39900
    assert listing.mileage_km == 82000
    assert listing.image_urls == [
        "https://prod.pictures.autoscout24.net/listing-images/e7fbd6c4.jpg/1920x1080.webp"
    ]


def test_parse_autoscout24_detail_uses_webpage_when_url_missing():
    """Detail pages sometimes omit ``url`` — the canonical URL lives in
    ``webPage``.  Without the fallback the parser keeps the stale base URL."""
    html = """
    <html><body><script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"listingDetails":{"id":"e65b455d-a2cc-4bb9-adbd-77189c0a0dc4","webPage":"https://www.autoscout24.de/angebote/corvette-zr1-benzin-gelb-cat_ma16380gr202936-e65b455d-a2cc-4bb9-adbd-77189c0a0dc4","price":{"priceRaw":119980,"priceFormatted":"€ 119.980"},"images":[],"location":{"zip":"8301","city":"Kainbach bei Graz"},"vehicle":{"make":"Chevrolet","model":"Corvette","modelVersionInput":"ZR1","mileageInKmRaw":39801,"firstRegistrationDate":"2010-06-01"}}}}}
    </script></body></html>
    """
    stale_base = "https://www.autoscout24.de/angebote/corvette-zr1-exp-e-109-480-benzin-gelb-cat_ma16380mo19143-e65b455d-a2cc-4bb9-adbd-77189c0a0dc4"

    listings = parse_autoscout24_search(html, stale_base)

    assert len(listings) == 1
    assert listings[0].url == (
        "https://www.autoscout24.de/angebote/corvette-zr1-benzin-gelb-cat_ma16380gr202936-e65b455d-a2cc-4bb9-adbd-77189c0a0dc4"
    )
    assert listings[0].price_eur == 119980


def test_normalize_autoscout24_image_url_prefers_large_webp_variant():
    url = "https://prod.pictures.autoscout24.net/listing-images/abc.jpg/250x188.webp"

    assert (
        normalize_autoscout24_image_url(url)
        == "https://prod.pictures.autoscout24.net/listing-images/abc.jpg/1920x1080.webp"
    )


def test_parse_autouncle_search_uses_listing_scoped_images_not_global_page_images():
    html = """
    <html><body>
    <img src="https://www.autouncle.de/assets/autouncle-logo.webp" />
    <article>
      <div class="_AQ3hX">
        <div class="_v1SHB">
          <img src="https://images.autouncle.com/de/car_images/medium_real-2007-corvette.webp" />
        </div>
      </div>
      <a class="_p9jqN" href="/de/d/217293039-gebraucht-2007-chevrolet-corvette-lt-404-ps">
        <h3>Gebraucht 2007 Chevrolet Corvette C6 LT 404 PS</h3>
        <ul><li>58.000 km</li></ul>
      </a>
      <div class="_eMl_E">
        <div class="_i2QOc">39.900&nbsp;€</div>
      </div>
    </article>
    <article>
      <div class="_AQ3hX">
        <div class="_v1SHB">
          <img src="https://images.autouncle.com/de/car_images/medium_real-2008-corvette.webp" />
        </div>
      </div>
      <a class="_p9jqN" href="/de/d/148078450-gebraucht-2008-chevrolet-corvette">
        <h3>Gebraucht 2008 Chevrolet Corvette C6 404 PS</h3>
        <ul><li>68.000 km</li></ul>
      </a>
      <div class="_eMl_E">
        <div class="_i2QOc">42.900&nbsp;€</div>
      </div>
    </article>
    </body></html>
    """

    listings = parse_autouncle_search(
        html, "https://www.autouncle.de/de/gebrauchtwagen/Chevrolet/Corvette?freetext=C6"
    )

    assert [listing.source_listing_id for listing in listings] == [
        "217293039-gebraucht-2007-chevrolet-corvette-lt-404-ps",
        "148078450-gebraucht-2008-chevrolet-corvette",
    ]
    assert listings[0].image_urls == [
        "https://images.autouncle.com/de/car_images/medium_real-2007-corvette.webp"
    ]
    assert listings[1].image_urls == [
        "https://images.autouncle.com/de/car_images/medium_real-2008-corvette.webp"
    ]


def test_normalize_autoscout24_image_url_leaves_non_autoscout_urls_alone():
    url = "https://img.example/as24-next.webp"

    assert normalize_autoscout24_image_url(url) == url


def test_parse_kleinanzeigen_search_extracts_normalized_listings():
    listings = parse_kleinanzeigen_search(
        KLEINANZEIGEN_HTML, "https://www.kleinanzeigen.de/s-autos/chevrolet-corvette-c6/k0c216"
    )

    assert len(listings) == 1
    listing = listings[0]
    assert listing.source == "Kleinanzeigen"
    assert listing.source_listing_id == "ka-77"
    assert listing.title == "Chevrolet Corvette C6 Grand Sport LS3"
    assert listing.price_eur == 54900
    assert listing.location_raw == "Hamburg"
    assert listing.image_urls == ["https://img.example/ka.jpg"]
    assert listing.transmission == "manual"


def test_parse_kleinanzeigen_search_handles_zo6_and_zr1_trim_variants():
    html = """
    <html><body>
    <article class="aditem" data-adid="zo6-1" data-href="/s-anzeige/corvette-c6-zo6/1-216-1">
      <h2><a href="/s-anzeige/corvette-c6-zo6/1-216-1">Chevrolet Corvette C6 ZO6 LS7</a></h2>
      <img src="https://img.example/zo6.jpg" />
      <p class="aditem-main--middle--price-shipping--price">59.900 €</p>
      <p class="aditem-main--middle--description">Z06, 513 PS, Manuell, Coupé</p>
      <div class="aditem-main--top--left">Stuttgart</div>
    </article>
    <article class="aditem" data-adid="zr1-1" data-href="/s-anzeige/corvette-c6-zr-1/2-216-1">
      <h2><a href="/s-anzeige/corvette-c6-zr-1/2-216-1">Corvette C6 ZR 1 LS9 Kompressor</a></h2>
      <img src="https://img.example/zr1.jpg" />
      <p class="aditem-main--middle--price-shipping--price">109.900 €</p>
      <p class="aditem-main--middle--description">22.000 km, Kompressor, 647 PS</p>
      <div class="aditem-main--top--left">Hamburg</div>
    </article>
    </body></html>
    """

    listings = parse_kleinanzeigen_search(
        html, "https://www.kleinanzeigen.de/s-autos/corvette-c6/k0c216"
    )

    assert len(listings) == 2
    assert listings[0].trim == "Z06"
    assert listings[1].trim == "ZR1"


def test_parse_kleinanzeigen_search_extracts_links_when_article_tree_is_unusable():
    html = """
    <html><body>
      <div class="result-list">
        <h2 class="text-module-begin"><a class="ellipsis" href="/s-anzeige/corvette-c6-ls2-targa-manual/3454859454-216-8088">Corvette C6 LS2 Targa Manual</a></h2>
        <p class="aditem-main--middle--price-shipping--price">37.500 €</p>
        <p>82.000 km EZ 03/2006 Getriebe Manuell Köln</p>
        <h2 class="text-module-begin"><a class="ellipsis" href="/s-anzeige/corvette-c6-ls3-coupe/3426217519-216-16235">Corvette C6 6.2 V8 Coupe LS3 Autom.</a></h2>
        <p class="aditem-main--middle--price-shipping--price">44.900 €</p>
        <p>61.000 km EZ 04/2008 Automatik Hamburg</p>
        <h2 class="text-module-begin"><a class="ellipsis" href="/s-anzeige/suche-eine-corvette-c6/3447740769-216-6241">Suche eine Corvette c6</a></h2>
        <p>VB</p>
      </div>
    </body></html>
    """

    listings = parse_kleinanzeigen_search(
        html, "https://www.kleinanzeigen.de/s-autos/sortierung:neuste/corvette-c6/k0c216"
    )

    assert [listing.source_listing_id for listing in listings] == ["3454859454", "3426217519"]
    assert [listing.title for listing in listings] == [
        "Corvette C6 LS2 Targa Manual",
        "Corvette C6 6.2 V8 Coupe LS3 Autom.",
    ]
    assert listings[0].price_eur == 37500
    assert listings[0].transmission == "manual"
    assert listings[1].transmission == "automatic"


def test_parse_kleinanzeigen_search_ignores_image_badge_and_uses_modern_h3_title():
    html = """
    <html><body>
      <article class="flex justify-between" data-adid="3503006324"
          data-href="/s-anzeige/corvette-c6-6-0-v8-coup-autom-/3503006324-216-8561">
        <a href="/s-anzeige/corvette-c6-6-0-v8-coup-autom-/3503006324-216-8561">
          <div><img src="https://img.example/c6.jpg"><div>9</div></div>
        </a>
        <div><h3 class="text-title3"><a name="3503006324"
          href="/s-anzeige/corvette-c6-6-0-v8-coup-autom-/3503006324-216-8561">
          Corvette C6 6.0 V8 Coupé Autom. -</a></h3>
          <p>Chevrolet Corvette C6 | 2005 | Automatik</p>
          <p>22.999 € 140.000 km</p>
        </div>
      </article>
    </body></html>
    """

    listings = parse_kleinanzeigen_search(html)

    assert len(listings) == 1
    assert listings[0].title == "Corvette C6 6.0 V8 Coupé Autom. -"
    assert not listings[0].title.isdigit()


def test_parse_kleinanzeigen_search_uses_json_ld_title_when_heading_is_missing():
    html = """
    <html><body>
      <article data-adid="ka-json-title" data-href="/s-anzeige/corvette-c6/123-216-1">
        <a href="/s-anzeige/corvette-c6/123-216-1"><span>3</span></a>
        <script type="application/ld+json">
          {"title":"Chevrolet Corvette C6 LS3 Schalter","description":"58.000 km"}
        </script>
        <p>Corvette C6 LS3 58.000 km 39.900 €</p>
      </article>
    </body></html>
    """

    listings = parse_kleinanzeigen_search(html)

    assert len(listings) == 1
    assert listings[0].title == "Chevrolet Corvette C6 LS3 Schalter"


def test_parse_kleinanzeigen_search_marks_missing_title_without_importing_badge_number(caplog):
    html = """
    <html><body>
      <article data-adid="ka-missing-title" data-href="/s-anzeige/corvette-c6/123-216-1">
        <a href="/s-anzeige/corvette-c6/123-216-1"><span>3</span></a>
        <p>Corvette C6 58.000 km 39.900 €</p>
      </article>
    </body></html>
    """

    listings = parse_kleinanzeigen_search(html)

    assert len(listings) == 1
    assert listings[0].title == "Kleinanzeigen-Angebot ka-missing-title ohne Titel"
    assert any("Titelquelle nicht verfügbar" in note for note in listings[0].inference_notes)
    assert "no usable title" in caplog.text


def test_parse_kleinanzeigen_search_skips_search_requests_from_json_ld_title():
    html = """
    <html><body>
      <article data-adid="ka-search-request" data-href="/s-anzeige/suche-corvette-c6/123-216-1">
        <a href="/s-anzeige/suche-corvette-c6/123-216-1"><span>3</span></a>
        <script type="application/ld+json">
          {"title":"SUCHE CORVETTE C6 CABRIO","description":"Bitte Angebote senden"}
        </script>
        <p>Gesuch Corvette C6, bis 20.000 €</p>
      </article>
    </body></html>
    """

    assert parse_kleinanzeigen_search(html) == []


def test_fetch_kleinanzeigen_uses_metadata_title_and_data_attribute_facts(monkeypatch):
    search_html = """
    <html><body>
      <article class="aditem" data-adid="ka-meta-detail"
          data-href="/s-anzeige/corvette-c6-meta/123-216-1">
        <a href="/s-anzeige/corvette-c6-meta/123-216-1"><span>9</span></a>
        <p>Corvette C6 44.900 €</p>
      </article>
    </body></html>
    """
    detail_html = """
    <html><head><meta property="og:title" content="Chevrolet Corvette C6 LS3" /></head><body>
      <meta itemprop="price" content="44900" />
      <div data-label="Kilometerstand" data-value="62.000 km"></div>
      <div data-detail-label="Leistung" data-detail-value="437 PS"></div>
      <p id="viewad-description-text">Scheckheft gepflegt</p>
    </body></html>
    """

    def fake_fetch_html(url):
        return detail_html if "/s-anzeige/" in url else search_html

    monkeypatch.setattr("corvette_tracker.sources.kleinanzeigen.fetch_html", fake_fetch_html)

    listings = fetch_kleinanzeigen("https://www.kleinanzeigen.de/s-autos/corvette-c6/k0c216")

    assert len(listings) == 1
    assert listings[0].title == "Chevrolet Corvette C6 LS3"
    assert listings[0].mileage_km == 62000
    assert listings[0].power_hp == 437


def test_fetch_kleinanzeigen_merges_detail_title_description_and_fields(monkeypatch):
    search_html = """
    <html><body>
      <article class="aditem" data-adid="ka-detail-title"
          data-href="/s-anzeige/corvette-c6/123-216-1">
        <a href="/s-anzeige/corvette-c6/123-216-1">10</a>
        <p>Corvette C6 46.000 km 44.900 €</p>
      </article>
    </body></html>
    """
    detail_html = """
    <html><body>
      <h1 id="viewad-title">Corvette C6 Grand Sport LS3</h1>
      <h2 id="viewad-price">44.900 €</h2>
      <div id="viewad-details"><ul>
        <li class="addetailslist--detail">Marke<span>Corvette</span></li>
        <li class="addetailslist--detail">Modell<span>C6</span></li>
        <li class="addetailslist--detail">Kilometerstand<span>46.000 km</span></li>
        <li class="addetailslist--detail">Erstzulassung<span>Mai 2009</span></li>
        <li class="addetailslist--detail">Leistung<span>437 PS</span></li>
        <li class="addetailslist--detail">Getriebe<span>Manuell</span></li>
        <li class="addetailslist--detail">Fahrzeugtyp<span>Coupé</span></li>
        <li class="addetailslist--detail">Anzahl Vorbesitzer<span>2</span></li>
      </ul></div>
      <div id="viewad-configuration"><ul class="checktaglist">
        <li class="checktag">Sitzheizung</li><li class="checktag">Bose</li>
      </ul></div>
      <p id="viewad-description-text">Baujahr 2009, Scheckheft gepflegt, Rechnungen vorhanden.</p>
    </body></html>
    """

    def fake_fetch_html(url):
        return detail_html if "/s-anzeige/" in url else search_html

    monkeypatch.setattr("corvette_tracker.sources.kleinanzeigen.fetch_html", fake_fetch_html)

    listings = fetch_kleinanzeigen("https://www.kleinanzeigen.de/s-autos/corvette-c6/k0c216")

    assert len(listings) == 1
    listing = listings[0]
    assert listing.title == "Corvette C6 Grand Sport LS3"
    assert listing.description_text == "Baujahr 2009, Scheckheft gepflegt, Rechnungen vorhanden."
    assert listing.model_year == 2009
    assert listing.owners_count == 2
    assert listing.service_history is True
    assert listing.heated_seats is True
    assert listing.bose_audio is True


def test_fetch_kleinanzeigen_fills_missing_transmission_from_detail_page(monkeypatch):
    search_html = KLEINANZEIGEN_HTML.replace(" Getriebe Manuell", "")
    detail_html = """
    <html><body>
      <dl>
        <dt>Getriebe</dt><dd>Manuell</dd>
      </dl>
      <img src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/detail?rule=$_2.AUTO" />
    </body></html>
    """

    def fake_fetch_html(url):
        if "/s-anzeige/" in url:
            return detail_html
        return search_html

    monkeypatch.setattr("corvette_tracker.sources.kleinanzeigen.fetch_html", fake_fetch_html)

    listings = fetch_kleinanzeigen(
        "https://www.kleinanzeigen.de/s-autos/chevrolet-corvette-c6/k0c216"
    )

    assert len(listings) == 1
    assert listings[0].transmission == "manual"
    assert listings[0].image_urls == [
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/detail?rule=$_59.AUTO"
    ]


def test_fetch_kleinanzeigen_prefers_detail_facts_over_snippet_noise(monkeypatch):
    search_html = """
    <html><body>
      <article class="aditem" data-adid="3445036633" data-href="/s-anzeige/corvette-c6-grand-sport-60-jahre-edition/3445036633-216-2394">
        <h2><a href="/s-anzeige/corvette-c6-grand-sport-60-jahre-edition/3445036633-216-2394">Corvette c6 Grand Sport 60 Jahre Edition</a></h2>
        <p class="aditem-main--middle--description">Vor 2 Jahren Bremse komplett gewechselt und Batterie ca 5000 km gefahren in der Zeit.</p>
        <p class="aditem-main--middle--price-shipping--price">VB</p>
        <p>46.000 km EZ 11/2012</p>
      </article>
    </body></html>
    """
    detail_html = """
    <html><body>
      <h1>Corvette c6 Grand Sport 60 Jahre Edition</h1>
      <h2 id="viewad-price">VB</h2>
      <li class="addetailslist--detail"><span>Marke</span><span>Corvette</span></li>
      <li class="addetailslist--detail"><span>Modell</span><span>C6</span></li>
      <li class="addetailslist--detail"><span>Kilometerstand</span><span>46.000 km</span></li>
      <li class="addetailslist--detail"><span>Erstzulassung</span><span>November 2012</span></li>
      <li class="addetailslist--detail"><span>Getriebe</span><span>Automatik</span></li>
    </body></html>
    """

    def fake_fetch_html(url):
        if "/s-anzeige/" in url:
            return detail_html
        return search_html

    monkeypatch.setattr("corvette_tracker.sources.kleinanzeigen.fetch_html", fake_fetch_html)

    listing = fetch_kleinanzeigen(
        "https://www.kleinanzeigen.de/s-autos/sortierung:neuste/corvette-c6/k0c216"
    )[0]

    assert listing.price_eur is None
    assert listing.price_label == "VB"
    assert listing.mileage_km == 46000
    assert listing.transmission == "automatic"


def test_fetch_kleinanzeigen_extracts_price_mileage_and_power_from_detail_facts(monkeypatch):
    search_html = """
    <html><body>
      <article class="aditem" data-adid="3406308683" data-href="/s-anzeige/corvette-c6-cabrio-bj-2009/3406308683-216-3512">
        <h2><a href="/s-anzeige/corvette-c6-cabrio-bj-2009/3406308683-216-3512">Corvette C6 Cabrio Bj.2009</a></h2>
        <p class="aditem-main--middle--description">Erstzulassung 08.2010, in unserem Besitz seit 09.2011 Km-Stand 123.000, TÜV 09.2027</p>
        <p class="aditem-main--middle--price-shipping--price">35.000 € VB</p>
        <p>123.000 km EZ 08/2010</p>
      </article>
    </body></html>
    """
    detail_html = """
    <html><body>
      <h1>Corvette C6 Cabrio Bj.2009</h1>
      <h2 id="viewad-price">35.000 € VB</h2>
      <li class="addetailslist--detail"><span>Marke</span><span>Corvette</span></li>
      <li class="addetailslist--detail"><span>Modell</span><span>C6</span></li>
      <li class="addetailslist--detail"><span>Kilometerstand</span><span>123.000 km</span></li>
      <li class="addetailslist--detail"><span>Leistung</span><span>436 PS</span></li>
      <li class="addetailslist--detail"><span>Getriebe</span><span>Automatik</span></li>
      <li class="addetailslist--detail"><span>Fahrzeugtyp</span><span>Cabrio</span></li>
    </body></html>
    """

    def fake_fetch_html(url):
        if "/s-anzeige/" in url:
            return detail_html
        return search_html

    monkeypatch.setattr("corvette_tracker.sources.kleinanzeigen.fetch_html", fake_fetch_html)

    listing = fetch_kleinanzeigen(
        "https://www.kleinanzeigen.de/s-autos/sortierung:neuste/corvette-c6/k0c216"
    )[0]

    assert listing.price_eur == 35000
    assert listing.price_label == "VB"
    assert listing.mileage_km == 123000
    assert listing.power_hp == 436
    assert listing.probable_engine == "LS3"
    assert listing.transmission == "automatic"
    assert listing.body_style == "Cabrio"


def test_fetch_kleinanzeigen_follows_pagination_and_dedupes(monkeypatch):
    first_page = """
    <html><body>
      <article class="aditem" data-adid="ka-1"><h2><a href="/s-anzeige/corvette-c6-one/1-216-1">Corvette C6 One</a></h2><p class="aditem-main--middle--price-shipping--price">30.000 €</p></article>
      <article class="aditem" data-adid="ka-dup"><h2><a href="/s-anzeige/corvette-c6-dup/2-216-1">Corvette C6 Duplicate</a></h2><p class="aditem-main--middle--price-shipping--price">31.000 €</p></article>
      <a href="/s-autos/sortierung:neuste/seite:2/corvette-c6/k0c216">2</a>
    </body></html>
    """
    second_page = """
    <html><body>
      <article class="aditem" data-adid="ka-dup"><h2><a href="/s-anzeige/corvette-c6-dup/2-216-1">Corvette C6 Duplicate</a></h2><p class="aditem-main--middle--price-shipping--price">31.000 €</p></article>
      <article class="aditem" data-adid="ka-3"><h2><a href="/s-anzeige/corvette-c6-three/3-216-1">Corvette C6 Three</a></h2><p class="aditem-main--middle--price-shipping--price">32.000 €</p></article>
    </body></html>
    """

    def fake_fetch_html(url):
        if "/s-anzeige/" in url:
            return "<html><body></body></html>"
        if "seite:2" in url:
            return second_page
        return first_page

    monkeypatch.setattr("corvette_tracker.sources.kleinanzeigen.fetch_html", fake_fetch_html)

    listings = fetch_kleinanzeigen(
        "https://www.kleinanzeigen.de/s-autos/sortierung:neuste/corvette-c6/k0c216"
    )

    assert [listing.source_listing_id for listing in listings] == ["ka-1", "ka-dup", "ka-3"]


def test_parse_kleinanzeigen_pagination_urls_accepts_link_rel_next():
    html = '<html><head><link rel="next" href="/s-autos/sortierung:neuste/seite:2/corvette-c6/k0c216"/></head></html>'

    assert parse_kleinanzeigen_pagination_urls(
        html, "https://www.kleinanzeigen.de/s-autos/sortierung:neuste/corvette-c6/k0c216"
    ) == ["https://www.kleinanzeigen.de/s-autos/sortierung:neuste/seite:2/corvette-c6/k0c216"]


def test_normalize_kleinanzeigen_image_url_prefers_detail_gallery_variant():
    url = "https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/abc?rule=$_2.AUTO"

    assert (
        normalize_kleinanzeigen_image_url(url)
        == "https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/abc?rule=$_59.AUTO"
    )


def test_parse_kleinanzeigen_detail_images_extracts_multiple_unique_gallery_images():
    html = """
    <html><body>
      <img src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/first?rule=$_59.AUTO" />
      <script type="application/ld+json">
        {"@type":"ImageObject","contentUrl":"https://img.kleinanzeigen.de/api/v1/prod-ads/images/96/second?rule=$_2.AUTO"}
      </script>
      <script>gallery.push('https://img.kleinanzeigen.de/api/v1/prod-ads/images/9b/third?rule=$_57.AUTO');</script>
      <img src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/first?rule=$_2.AUTO" />
    </body></html>
    """

    assert parse_kleinanzeigen_detail_images(html, "https://www.kleinanzeigen.de/s-anzeige/x") == [
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/first?rule=$_59.AUTO",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/96/second?rule=$_59.AUTO",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/9b/third?rule=$_59.AUTO",
    ]
