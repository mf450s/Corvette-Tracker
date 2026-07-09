from corvette_tracker.sources.autouncle import parse_autouncle_search
from corvette_tracker.sources.autoscout24 import normalize_autoscout24_image_url, parse_autoscout24_search
from corvette_tracker.sources.classic_trader import parse_classic_trader_search
from corvette_tracker.sources.kleinanzeigen import (
    fetch_kleinanzeigen,
    normalize_kleinanzeigen_image_url,
    parse_kleinanzeigen_detail_images,
    parse_kleinanzeigen_search,
)


AUTOSCOUT_HTML = '''
<html><body>
<article data-testid="list-item" id="as24-123">
  <a href="/angebote/chevrolet-corvette-c6-z06-abc123">Chevrolet Corvette C6 Z06 LS7</a>
  <img src="https://prod.pictures.autoscout24.net/listing-images/as24_abc.jpg/250x188.webp" />
  <p>59.900 €</p><p>72.000 km</p><p>05/2008</p><p>512 PS</p><p>München</p>
  <span>unfallfrei, HU 06/2027</span>
</article>
</body></html>
'''

KLEINANZEIGEN_HTML = '''
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
'''

AUTOUNCLE_HTML = '''
<html><body>
<a href="/de/d/222-c6-corvette">
  Gebraucht (2008) Chevrolet Corvette C6 LS3 437 PS | Seltenes Fahrzeug
  Mär 2008 68.000 km 6.2L Benzin Coupé Schaltgetriebe 437 PS (321 kW)
  Details 54.900 € München
</a>
<img src="https://autouncle-public.s3.eu-west-1.amazonaws.com/de/car_images/c6.webp" />
</body></html>
'''

CLASSIC_TRADER_HTML = '''
<html><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"ItemList","itemListElement":[{"@type":"ListItem","item":{"@type":"Vehicle","name":"Chevrolet Corvette C6 Z06 LS7","url":"/de/automobile/inserat/chevrolet/corvette/c6-z06/2008/123","image":"https://cdn.classic-trader.com/I/images/640_480/c6.jpg","offers":{"price":"69900","priceCurrency":"EUR"},"description":"EZ 05/2008, 72.000 km, 512 PS, Schaltgetriebe"}}]}
</script>
</body></html>
'''


def test_parse_autouncle_search_extracts_normalized_c6_listings():
    listings = parse_autouncle_search(AUTOUNCLE_HTML, "https://www.autouncle.de/de/gebrauchtwagen/Chevrolet/Corvette?freetext=C6")

    assert len(listings) == 1
    listing = listings[0]
    assert listing.source == "AutoUncle"
    assert listing.url == "https://www.autouncle.de/de/d/222-c6-corvette"
    assert listing.price_eur == 54900
    assert listing.mileage_km == 68000
    assert listing.engine == "LS3"
    assert listing.image_urls == ["https://autouncle-public.s3.eu-west-1.amazonaws.com/de/car_images/c6.webp"]


def test_parse_classic_trader_search_extracts_json_ld_listings():
    listings = parse_classic_trader_search(CLASSIC_TRADER_HTML, "https://www.classic-trader.com/de/automobile/suche/chevrolet/corvette/c6")

    assert len(listings) == 1
    listing = listings[0]
    assert listing.source == "Classic Trader"
    assert listing.url == "https://www.classic-trader.com/de/automobile/inserat/chevrolet/corvette/c6-z06/2008/123"
    assert listing.price_eur == 69900
    assert listing.mileage_km == 72000
    assert listing.engine == "LS7"
    assert listing.image_urls == ["https://cdn.classic-trader.com/I/images/640_480/c6.jpg"]


def test_parse_autoscout24_search_extracts_normalized_listings():
    listings = parse_autoscout24_search(AUTOSCOUT_HTML, "https://www.autoscout24.de/lst/chevrolet/corvette")

    assert len(listings) == 1
    listing = listings[0]
    assert listing.source == "AutoScout24"
    assert listing.source_listing_id == "as24-123"
    assert listing.price_eur == 59900
    assert listing.image_urls == ["https://prod.pictures.autoscout24.net/listing-images/as24_abc.jpg/1920x1080.webp"]
    assert listing.engine == "LS7"


def test_parse_autoscout24_next_data_without_anchor_href():
    html = '''
    <html><body><script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"listings":[{"id":"next-1","url":"/angebote/chevrolet-corvette-c6-benzin-schwarz-next-1","price":{"priceRaw":41900,"priceFormatted":"€ 41.900"},"images":["https://img.example/as24-next.webp"],"location":{"zip":"80809","city":"München"},"seller":{"type":"P"},"vehicle":{"make":"Chevrolet","model":"Corvette","modelVersionInput":"C6"},"vehicleDetails":[{"data":"03/2010"},{"data":"61.000 km"},{"data":"297 kW (404 PS)"}] }]}}}
    </script></body></html>
    '''

    listings = parse_autoscout24_search(html, "https://www.autoscout24.de/lst/chevrolet/corvette")

    assert len(listings) == 1
    assert listings[0].source_listing_id == "next-1"
    assert listings[0].url == "https://www.autoscout24.de/angebote/chevrolet-corvette-c6-benzin-schwarz-next-1"
    assert listings[0].title == "Chevrolet Corvette C6"
    assert listings[0].price_eur == 41900
    assert listings[0].mileage_km == 61000
    assert listings[0].image_urls == ["https://img.example/as24-next.webp"]


def test_parse_autoscout24_detail_next_data_uses_listing_details_fields():
    html = '''
    <html><body><script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"listingDetails":{"id":"e7fbd6c4-e19f-4a64-9b89-c8bd28ba3111","url":"/angebote/corvette-c6-coupe-automatik-benzin-cat_ma16380mo19140-e7fbd6c4-e19f-4a64-9b89-c8bd28ba3111","price":{"priceRaw":39900,"priceFormatted":"€ 39.900"},"images":["https://prod.pictures.autoscout24.net/listing-images/e7fbd6c4.jpg/250x188.webp"],"location":{"zip":"48143","city":"Münster"},"vehicle":{"make":"Chevrolet","model":"Corvette","modelVersionInput":"C6 Coupe Automatik","mileageInKmRaw":82000,"firstRegistrationDate":"2006-06-01","powerInHp":404,"gearbox":"Automatic","bodyType":"Coupe"},"vehicleDetails":[{"label":"Getriebe","data":"Automatik"},{"label":"Karosserieform","data":"Coupé"},{"label":"Leistung","data":"297 kW (404 PS)"},{"label":"Kilometerstand","data":"82.000 km"}]}}}}
    </script></body></html>
    '''

    listings = parse_autoscout24_search(html, "https://www.autoscout24.de/angebote/corvette-c6-coupe-automatik-benzin-cat_ma16380mo19140-e7fbd6c4-e19f-4a64-9b89-c8bd28ba3111")

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
    assert listing.image_urls == ["https://prod.pictures.autoscout24.net/listing-images/e7fbd6c4.jpg/1920x1080.webp"]


def test_normalize_autoscout24_image_url_prefers_large_webp_variant():
    url = "https://prod.pictures.autoscout24.net/listing-images/abc.jpg/250x188.webp"

    assert normalize_autoscout24_image_url(url) == "https://prod.pictures.autoscout24.net/listing-images/abc.jpg/1920x1080.webp"


def test_parse_autouncle_search_uses_listing_scoped_images_not_global_page_images():
    html = '''
    <html><body>
    <img src="https://www.autouncle.de/assets/autouncle-logo.webp" />
    <a href="/de/d/217293039-gebraucht-2007-chevrolet-corvette-lt-404-ps">
      <img src="https://images.autouncle.com/de/car_images/medium_real-2007-corvette.webp" />
      Gebraucht 2007 Chevrolet Corvette C6 LT 404 PS 58.000 km 39.900 €
    </a>
    <a href="/de/d/148078450-gebraucht-2008-chevrolet-corvette">
      <img src="https://images.autouncle.com/de/car_images/medium_real-2008-corvette.webp" />
      Gebraucht 2008 Chevrolet Corvette C6 404 PS 68.000 km 42.900 €
    </a>
    </body></html>
    '''

    listings = parse_autouncle_search(html, "https://www.autouncle.de/de/gebrauchtwagen/Chevrolet/Corvette?freetext=C6")

    assert [listing.source_listing_id for listing in listings] == [
        "217293039-gebraucht-2007-chevrolet-corvette-lt-404-ps",
        "148078450-gebraucht-2008-chevrolet-corvette",
    ]
    assert listings[0].image_urls == ["https://images.autouncle.com/de/car_images/medium_real-2007-corvette.webp"]
    assert listings[1].image_urls == ["https://images.autouncle.com/de/car_images/medium_real-2008-corvette.webp"]


def test_normalize_autoscout24_image_url_leaves_non_autoscout_urls_alone():
    url = "https://img.example/as24-next.webp"

    assert normalize_autoscout24_image_url(url) == url


def test_parse_kleinanzeigen_search_extracts_normalized_listings():
    listings = parse_kleinanzeigen_search(KLEINANZEIGEN_HTML, "https://www.kleinanzeigen.de/s-autos/chevrolet-corvette-c6/k0c216")

    assert len(listings) == 1
    listing = listings[0]
    assert listing.source == "Kleinanzeigen"
    assert listing.source_listing_id == "ka-77"
    assert listing.title == "Chevrolet Corvette C6 Grand Sport LS3"
    assert listing.price_eur == 54900
    assert listing.location_raw == "Hamburg"
    assert listing.image_urls == ["https://img.example/ka.jpg"]
    assert listing.transmission == "manual"


def test_fetch_kleinanzeigen_fills_missing_transmission_from_detail_page(monkeypatch):
    search_html = KLEINANZEIGEN_HTML.replace(" Getriebe Manuell", "")
    detail_html = '''
    <html><body>
      <dl>
        <dt>Getriebe</dt><dd>Manuell</dd>
      </dl>
      <img src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/detail?rule=$_2.AUTO" />
    </body></html>
    '''

    def fake_fetch_html(url):
        if "/s-anzeige/" in url:
            return detail_html
        return search_html

    monkeypatch.setattr("corvette_tracker.sources.kleinanzeigen.fetch_html", fake_fetch_html)

    listings = fetch_kleinanzeigen("https://www.kleinanzeigen.de/s-autos/chevrolet-corvette-c6/k0c216")

    assert len(listings) == 1
    assert listings[0].transmission == "manual"
    assert listings[0].image_urls == [
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/detail?rule=$_59.AUTO"
    ]


def test_normalize_kleinanzeigen_image_url_prefers_detail_gallery_variant():
    url = "https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/abc?rule=$_2.AUTO"

    assert normalize_kleinanzeigen_image_url(url) == "https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/abc?rule=$_59.AUTO"


def test_parse_kleinanzeigen_detail_images_extracts_multiple_unique_gallery_images():
    html = '''
    <html><body>
      <img src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/first?rule=$_59.AUTO" />
      <script type="application/ld+json">
        {"@type":"ImageObject","contentUrl":"https://img.kleinanzeigen.de/api/v1/prod-ads/images/96/second?rule=$_2.AUTO"}
      </script>
      <script>gallery.push('https://img.kleinanzeigen.de/api/v1/prod-ads/images/9b/third?rule=$_57.AUTO');</script>
      <img src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/first?rule=$_2.AUTO" />
    </body></html>
    '''

    assert parse_kleinanzeigen_detail_images(html, "https://www.kleinanzeigen.de/s-anzeige/x") == [
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/82/first?rule=$_59.AUTO",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/96/second?rule=$_59.AUTO",
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/9b/third?rule=$_59.AUTO",
    ]
