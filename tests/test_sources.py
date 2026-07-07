from corvette_tracker.sources.autoscout24 import parse_autoscout24_search
from corvette_tracker.sources.kleinanzeigen import parse_kleinanzeigen_search


AUTOSCOUT_HTML = '''
<html><body>
<article data-testid="list-item" id="as24-123">
  <a href="/angebote/chevrolet-corvette-c6-z06-abc123">Chevrolet Corvette C6 Z06 LS7</a>
  <img src="https://img.example/as24.jpg" />
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
  <p class="aditem-main--middle--description">68.000 km EZ 05/2011 HU 06/2027</p>
  <div class="aditem-main--top--left">Hamburg</div>
</article>
</body></html>
'''


def test_parse_autoscout24_search_extracts_normalized_listings():
    listings = parse_autoscout24_search(AUTOSCOUT_HTML, "https://www.autoscout24.de/lst/chevrolet/corvette")

    assert len(listings) == 1
    listing = listings[0]
    assert listing.source == "AutoScout24"
    assert listing.source_listing_id == "as24-123"
    assert listing.price_eur == 59900
    assert listing.image_urls == ["https://img.example/as24.jpg"]
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
