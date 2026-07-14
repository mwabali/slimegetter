from datetime import UTC
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from app.agents.annie.models import NewsArticle


class GoogleNewsRssSearch:
    """Free headline search. It returns sources; it never treats headlines as verified facts."""
    def search_gold_news(self, limit: int = 10) -> tuple[NewsArticle, ...]:
        query = urlencode({"q": "(gold OR XAUUSD OR bullion) (Fed OR inflation OR dollar OR geopolitics)", "hl": "en-US", "gl": "US", "ceid": "US:en"})
        request = Request(f"https://news.google.com/rss/search?{query}", headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=10) as response: root = ElementTree.fromstring(response.read())
        articles: list[NewsArticle] = []
        for item in root.findall("./channel/item")[:limit]:
            raw_date = item.findtext("pubDate")
            try: published = parsedate_to_datetime(raw_date).astimezone(UTC) if raw_date else None
            except (TypeError, ValueError): published = None
            source = item.find("source")
            articles.append(NewsArticle(title=item.findtext("title", "Untitled"), url=item.findtext("link", ""), publisher=source.text if source is not None else None, published_at=published))
        return tuple(articles)
