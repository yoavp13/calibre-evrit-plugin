import json
import re
import time
import unicodedata
import uuid
from collections.abc import Iterable, Mapping
from queue import Empty, Queue
from threading import Event
from typing import Callable

import mechanize

from calibre.ebooks.BeautifulSoup import BeautifulSoup
from calibre.ebooks.metadata.book.base import Metadata
from calibre.ebooks.metadata.sources.base import Source
from calibre.utils.logging import Log


USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


def get_guest_cart_cookie() -> str:
    return f'iv_guest_cart={uuid.uuid4()}'


def levenshtein_distance(s1, s2):
    # Source: https://stackoverflow.com/a/32558749/61061.
    if len(s1) > len(s2):
        s1, s2 = s2, s1

    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2 + 1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
    return distances[-1]


def remove_control_characters(text: str) -> str:
    unicode_categories = {
        'C',  # Control
        'M',  # Mark
    }

    return ''.join(filter(lambda ch: unicodedata.category(ch)[0] not in unicode_categories, text))


def remove_optional_hebrew_characters(text: str) -> str:
    optional_characters = {'א', 'ה', 'ו', 'י', '"', "'"}
    return ''.join(filter(lambda ch: ch not in optional_characters, text))


def replace_symbols(text: str) -> str:
    unicode_categories = {
        'S',  # Symbol
    }
    text = ''.join(map(lambda ch: ' ' if unicodedata.category(ch)[0] in unicode_categories else ch, text))
    return ' '.join(text.split())


def replace_punctuation(text: str) -> str:
    unicode_categories = {
        'P',  # Punctuation
    }
    text = ''.join(map(lambda ch: ' ' if unicodedata.category(ch)[0] in unicode_categories else ch, text))
    return ' '.join(text.split())


def normalize(text: str) -> str:
    return replace_symbols(
        remove_control_characters(
            unicodedata.normalize('NFC', text)))


def normalize_for_match(text: str) -> str:
    return replace_punctuation(
        replace_symbols(
            remove_control_characters(
                unicodedata.normalize('NFC', text))))


def normalize_for_search(text: str) -> str:
    forbidden_characters = {'?'}
    return ''.join(filter(lambda ch: ch not in forbidden_characters, normalize(text)))


def aggressive_normalize(text: str) -> str:
    return remove_optional_hebrew_characters(normalize(text))


def author_match(left: str, right: str) -> bool:
    '''
    'לוסי מוד מונטגומרי'
    'ל. מ. מונטגומרי'
    'ל.מ. מונטגומרי'
    'ל"מ מונטגומרי'
    "ג'. ר. ר. טולקין", "ג'ון רונלד רעואל טולקין"
    'ש"י עגנון', 'שמואל יוסף עגנון'
    'ד"ר ליאת יקיר', 'ליאת יקיר'
    '''
    TITLES = ['ד"ר ', 'דוקטור ', 'פרופ. ', 'פרופסור ']
    for title in TITLES:
        left = left.removeprefix(title)
        right = right.removeprefix(title)

    left_parts = [part for part in re.split(r'[, ."]', left) if part]
    right_parts = [part for part in re.split(r'[, ."]', right) if part]

    if not left_parts or not right_parts:
        return False

    # Match last name
    if left_parts[-1] != right_parts[-1]:
        return False

    if all(any(lp.startswith(rp) for lp in left_parts[:-1]) for rp in right_parts[:-1]):
        return True

    if all(any(rp.startswith(lp) for lp in left_parts[:-1]) for rp in right_parts[:-1]):
        return True

    return False


def token_match(left: str, right: str) -> bool:
    if left == right:
        return True

    left_regex = r'^.*\b' + r'\b.*\b'.join(map(re.escape, left.split())) + r'\b.*$'
    if re.match(left_regex, right):
        return True

    right_regex = r'^.*\b' + r'\b.*\b'.join(map(re.escape, right.split())) + r'\b.*$'
    if re.match(right_regex, left):
        return True

    return False


def title_match(title: str, product_title: str,
                normalize_func: Callable[[str], str]) -> bool:
    title = normalize_func(title)
    product_title = normalize_func(product_title)

    if token_match(title, product_title):
        return True

    return False


def authors_match(authors: Iterable[str], product_authors: Iterable[str],
                  normalize_func: Callable[[str], str]) -> bool:
    authors = list(map(normalize_func, authors))
    product_authors = list(map(normalize_func, product_authors))

    if any(any(token_match(author, product_author)
               for product_author in product_authors)
           for author in authors):
        return True

    if any(any(author_match(author, product_author)
               for product_author in product_authors)
           for author in authors):
        return True

    return False


def partial_queries(query: str, min_length: int = 2) -> list[str]:
    queries: Iterable[str] = [query[i:j] for i in range(len(query)) for j in range(i + min_length, len(query) + 1)]
    queries = map(lambda s: s.strip(), queries)
    queries = filter(lambda s: len(s) >= min_length, queries)
    queries = set(queries)
    queries: list[str] = sorted(queries, key=len, reverse=True)

    return queries


def partial_spans(query: str,
                  normalize_func: Callable[[str], str],
                  min_length: int = 2) -> list[str]:
    queries = query.split()
    queries = map(lambda s: normalize_func(s), queries)
    queries = map(lambda s: s.strip(), queries)
    queries = list(queries)
    queries = [' '.join(queries[:i]) for i in range(min_length - 1, len(queries) + 1)]
    queries = list(queries)

    if len(queries) == 1 and queries[0] == query:
        return []

    return queries


def split_queries(query: str,
                  normalize_func: Callable[[str], str],
                  min_length: int = 2) -> list[str]:
    queries = re.split(r'[-:]', query)
    queries = map(lambda s: normalize_func(s), queries)
    queries = map(lambda s: s.strip(), queries)
    queries = filter(lambda s: len(s) >= min_length, queries)
    queries = list(queries)

    if len(queries) == 1 and queries[0] == query:
        return []

    return queries


__license__ = 'GPL v3'
__copyright__ = '2023, Hebrew Reader <hebrew.reader.calibre@gmail.com>; 2026, yoavp13'
__docformat__ = 'restructuredtext en'


class Evrit(Source):
    name = 'Evrit'
    description = 'Get metadata and covers from Evrit. Maintained at https://github.com/yoavp13/calibre-evrit-plugin'
    capabilities = frozenset(['identify', 'cover'])
    author = 'Hebrew Reader (maintained by yoavp13)'
    version = (2, 0, 1)
    can_get_multiple_covers = False
    touched_fields = frozenset(
        ['title', 'authors', 'tags', 'publisher', 'comments',
         'pubdate', 'rating', 'series', 'identifier:evrit', 'languages'])
    supports_gzip_transfer_encoding = True
    cached_cover_url_is_reliable = True
    has_html_comments = True

    @property
    def guest_cart_cookie(self) -> str:
        if not hasattr(self, '_guest_cart_cookie') or not self._guest_cart_cookie:
            self._guest_cart_cookie = get_guest_cart_cookie()
        return self._guest_cart_cookie

    def get_book_url(self, identifiers: Mapping[str, str]) \
            -> tuple[str, str, str] | None:
        evrit_id = identifiers.get('evrit', None)
        if evrit_id:
            url = f'https://www.e-vrit.co.il/product/{evrit_id}'
            return 'evrit', str(evrit_id), url
        return None

    def get_book_url_name(self, idtype: str, idval: str, url: str) -> str:
        return 'עברית'

    def identify(self, log: Log, result_queue: Queue, abort: Event,
                 title: str = None, authors: Iterable[str] = None,
                 identifiers: Mapping[str, str] = None, timeout: int = 15) -> None:
        end_time = time.time() + timeout
        if identifiers is None:
            identifiers = {}

        # Evrit id exists, read detail page directly
        evrit_id = identifiers.get('evrit', None)
        evrit_ids_with_relevance = dict()
        if evrit_id:
            evrit_ids_with_relevance[str(evrit_id)] = 0
        else:
            evrit_ids_with_relevance = self.search_for_evrit_id(log, title, authors, abort, timeout)

        if not evrit_ids_with_relevance:
            log.info('No matching books found on Evrit.')
            return

        best_relevance = min(evrit_ids_with_relevance.values())
        ids_with_best_relevance = [k for k in evrit_ids_with_relevance
                                   if evrit_ids_with_relevance[k] == best_relevance]
        for eid in ids_with_best_relevance:
            remaining_timeout = max(int(end_time - time.time()), 1)
            if abort.is_set() or remaining_timeout <= 0:
                break
            self.retrieve_evrit_detail(log, eid, best_relevance, result_queue, abort, remaining_timeout)

    def search_for_evrit_id(self, log: Log, title: str, authors: Iterable[str],
                            abort: Event, timeout: int) -> dict[str, int]:
        end_time = time.time() + timeout
        authors = [normalize(author) for author in authors] if authors else []
        queries: list[str] = [normalize_for_search(title)]
        queries += split_queries(title, normalize_for_search)
        queries += partial_spans(title, normalize_for_search)
        queries += partial_queries(normalize_for_search(title))
        seen_queries = set()
        evrit_ids_with_relevance = dict()

        for query in queries:
            if not query or query in seen_queries:
                continue
            seen_queries.add(query)

            remaining_timeout = max(int(end_time - time.time()), 1)
            if abort.is_set() or remaining_timeout <= 0:
                break

            product_values = self.get_product_values_from_search(log, query, remaining_timeout)

            for normalize_func in [normalize, normalize_for_match, aggressive_normalize]:
                for product_title, product_authors, product_id in product_values:
                    relevance = levenshtein_distance(title, product_title)
                    author_matched = True
                    if authors and product_authors:
                        author_matched = authors_match(authors, product_authors, normalize_func)

                    if (relevance < 3 or title_match(title, product_title, normalize_func)) and author_matched:
                        if product_id in evrit_ids_with_relevance:
                            relevance = min(evrit_ids_with_relevance[product_id], relevance)
                        evrit_ids_with_relevance[product_id] = relevance

            if evrit_ids_with_relevance:
                log.info('Found candidate Evrit IDs:', evrit_ids_with_relevance)
                return evrit_ids_with_relevance

        return evrit_ids_with_relevance

    def get_product_values_from_search(self, log: Log, query: str, timeout: int) \
            -> list[tuple[str, list[str], str]]:
        url = 'https://www.e-vrit.co.il/api/search'
        payload = json.dumps({'q': query}).encode('utf-8')
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json, text/plain, */*',
            'Origin': 'https://www.e-vrit.co.il',
            'Referer': 'https://www.e-vrit.co.il/',
            'User-Agent': USER_AGENT,
            'Cookie': self.guest_cart_cookie
        }

        try:
            req = mechanize.Request(url, data=payload, headers=headers)
            response = self.browser.open_novisit(req, timeout=timeout)
            raw = response.read()
            if isinstance(raw, bytes):
                raw = raw.decode('utf-8', errors='replace')
            data = json.loads(raw)
        except Exception as e:
            log.warning(f'Evrit search query failed for "{query}": {e}')
            return []

        products = data.get('results', {}).get('product', {}).get('r', [])
        product_values = []
        for item in products:
            pd = item.get('pd', {})
            product_id = str(pd.get('productId', '')).strip()
            product_title = pd.get('title', '').strip()
            author_str = pd.get('author', '').strip()
            if not product_id or not product_title:
                continue

            product_authors = [a.strip() for a in author_str.split(',') if a.strip()] if author_str else []
            product_values.append((product_title, product_authors, product_id))

            # Pre-cache high-res cover URL
            img = pd.get('img')
            if img:
                clean_img = img.replace('/image_', '/') if '/image_' in img else img
                cover_url = f'https://images.e-vrit.co.il/cdn-cgi/image/width=1200,format=auto,quality=85/{clean_img.lstrip("/")}'
                self.cache_identifier_to_cover_url(product_id, cover_url)

        return product_values

    def retrieve_evrit_detail(self, log: Log, evrit_id: str, relevance: int,
                              result_queue: Queue, abort: Event, timeout: int) -> None:
        if abort.is_set():
            return

        product_url = f'https://www.e-vrit.co.il/product/{evrit_id}'
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Referer': 'https://www.e-vrit.co.il/'
        }

        # 1. Fetch main product page for Schema.org JSON-LD and high-res og:image
        html = ''
        try:
            req = mechanize.Request(product_url, headers=headers)
            resp = self.browser.open_novisit(req, timeout=timeout)
            raw = resp.read()
            html = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
        except Exception as e:
            log.warning(f'Failed to fetch product page for Evrit ID {evrit_id}: {e}')

        book_ld = {}
        if html:
            ld_matches = re.findall(r'<script[^>]*type=[\'"]application/ld\+json[\'"][^>]*>(.*?)</script>', html, re.DOTALL)
            for ld in ld_matches:
                try:
                    obj = json.loads(ld)
                    if isinstance(obj, dict) and obj.get('@type') == 'Book':
                        book_ld = obj
                        break
                except Exception:
                    pass

        # 2. Fetch extra product details (rich description, tags, pubdate, series)
        extra_data = {}
        try:
            extra_url = f'https://www.e-vrit.co.il/api/product/extra/{evrit_id}'
            extra_headers = {
                'User-Agent': USER_AGENT,
                'Accept': 'application/json, text/plain, */*',
                'Referer': product_url,
                'Cookie': self.guest_cart_cookie
            }
            extra_req = mechanize.Request(extra_url, headers=extra_headers)
            extra_resp = self.browser.open_novisit(extra_req, timeout=timeout)
            raw_extra = extra_resp.read()
            extra_text = raw_extra.decode('utf-8', errors='replace') if isinstance(raw_extra, bytes) else raw_extra
            extra_data = json.loads(extra_text)
            log.info(f'Fetched extra details for Evrit ID {evrit_id}, PublishYear: {extra_data.get("PublishYear")}')
        except Exception as e:
            log.warning(f'Could not fetch extra product details for {evrit_id}: {e}')

        # Determine Title & Authors
        title = None
        if book_ld.get('name'):
            title = remove_control_characters(book_ld['name'].strip())

        authors = []
        if book_ld.get('author'):
            for author_obj in book_ld['author']:
                if isinstance(author_obj, dict) and author_obj.get('name'):
                    authors.append(remove_control_characters(author_obj['name'].strip()))
                elif isinstance(author_obj, str):
                    authors.append(remove_control_characters(author_obj.strip()))

        # Fallback to page title if JSON-LD wasn't present
        if not title and html:
            m = re.search(r'<title>(.*?)</title>', html)
            if m:
                raw_title = m.group(1).split('|')[0].split('-')[0].strip()
                title = remove_control_characters(raw_title)

        if not title:
            log.warning(f'No title found for Evrit ID {evrit_id}')
            return

        mi = Metadata(title, authors)
        mi.identifiers = {'evrit': str(evrit_id)}
        mi.languages = ['Hebrew']

        # Publisher
        publishers = []
        if book_ld.get('publisher'):
            for pub in book_ld['publisher']:
                if isinstance(pub, dict) and pub.get('name'):
                    publishers.append(pub['name'].strip())
                elif isinstance(pub, str):
                    publishers.append(pub.strip())
        if publishers:
            mi.publisher = ', '.join(publishers)

        # Rating
        agg_rating = book_ld.get('aggregateRating', {})
        if isinstance(agg_rating, dict) and agg_rating.get('ratingValue'):
            try:
                mi.rating = float(agg_rating['ratingValue'])
            except (ValueError, TypeError):
                mi.rating = None

        # Tags / Genre / Content Groups
        tags = []
        if book_ld.get('genre'):
            tags.append(book_ld['genre'].strip())
        if extra_data.get('ContentGroupList'):
            for group in extra_data['ContentGroupList']:
                if isinstance(group, dict) and group.get('Name'):
                    tags.append(group['Name'].strip())
        if tags:
            seen_tags = set()
            mi.tags = [t for t in tags if not (t in seen_tags or seen_tags.add(t))]

        # Comments / Description
        if extra_data.get('LongDescription'):
            mi.comments = extra_data['LongDescription'].strip()
        elif book_ld.get('description'):
            mi.comments = book_ld['description'].strip()

        # Pubdate
        pub_year = extra_data.get('PublishYear') or extra_data.get('PublishDate')
        pub_month = extra_data.get('PublishMonth') or 1
        if pub_year:
            try:
                from calibre.utils.date import parse_date, utcnow
                year_num = int(str(pub_year).strip()[:4])
                month_num = int(pub_month) if pub_month else 1
                default = utcnow().replace(day=15)
                mi.pubdate = parse_date(f'{year_num:04d}-{month_num:02d}', assume_utc=True, default=default)
                log.info(f'Parsed pubdate for Evrit ID {evrit_id}: {mi.pubdate}')
            except Exception as e:
                log.warning(f'Failed to parse publication date: year={pub_year}, month={pub_month}: {e}')

        # Series
        if extra_data.get('RelatedSeries'):
            try:
                series_info = extra_data['RelatedSeries']
                if isinstance(series_info, list) and len(series_info) > 0:
                    mi.series = series_info[0].get('ItemName')
            except Exception:
                pass

        # High-res Cover Image
        cover_url = None
        if html:
            og_match = re.search(r'<meta\s+property=[\'"]og:image[\'"]\s+content=[\'"]([^\'"]+)[\'"]', html)
            if og_match:
                cover_url = og_match.group(1).strip()
        if not cover_url and book_ld.get('image'):
            img_raw = book_ld['image']
            cover_url = re.sub(r'width=\d+', 'width=1200', img_raw)

        if cover_url:
            mi.has_evrit_cover = cover_url
            self.cache_identifier_to_cover_url(str(evrit_id), cover_url)

        mi.source_relevance = relevance
        log.info(f'Identified Evrit book: {title} by {authors} (ID: {evrit_id})')
        result_queue.put(mi)

    def download_cover(self, log: Log, result_queue: Queue,
                       abort: Event, title: str = None,
                       authors: Iterable[str] = None,
                       identifiers: Mapping[str, str] = None,
                       timeout: int = 30,
                       get_best_cover: bool = False) -> None:
        if identifiers is None:
            identifiers = {}
        cached_url = self.get_cached_cover_url(identifiers)
        if cached_url is None:
            log.info('No cached cover found, running identify')
            rq = Queue()
            self.identify(log, rq, abort, title=title,
                          authors=authors, identifiers=identifiers)
            if abort.is_set():
                return
            results = []
            while True:
                try:
                    results.append(rq.get_nowait())
                except Empty:
                    break
            results.sort(
                key=self.identify_results_keygen(
                    title=title, authors=authors, identifiers=identifiers)
            )
            for mi in results:
                cached_url = self.get_cached_cover_url(mi.identifiers)
                if cached_url is not None:
                    break
        if cached_url is None:
            log.info('No cover found')
            return

        if abort.is_set():
            return

        log('Downloading cover from:', cached_url)
        self.download_image(cached_url, timeout, log, result_queue)

    def get_cached_cover_url(self, identifiers: Mapping[str, str] = None) -> str:
        if identifiers is None:
            identifiers = {}
        url = None
        evrit_id = identifiers.get('evrit', None)
        if evrit_id is not None:
            url = self.cached_identifier_to_cover_url(str(evrit_id))
        return url


def identifier_test(key: str, value: str) -> Callable[[Metadata], bool]:
    from calibre import prints

    def fn(mi: Metadata) -> bool:
        identifier = mi.get_identifiers().get(key, None)
        if identifier == value:
            return True
        prints(f'Identifier test failed. Expected: \'{key}:{value}\' found {mi.get_identifiers()}')
        return False

    return fn


def test() -> None:
    from calibre.ebooks.metadata.sources.test import (
        test_identify_plugin, title_test, authors_test
    )

    test_identify_plugin(
        Evrit.name, [
            ({  # Identify by identifier.
                 'identifiers': {'evrit': '3785'},
             }, [title_test('חפצים חדים', exact=True),
                 authors_test(['גיליאן פלין']),
                 ]),
            ({  # Identify by title & author.
                 'title': 'מובי דיק',
                 'authors': ['הרמן מלוויל']
             }, [identifier_test('evrit', '373'),
                 title_test('מובי דיק', exact=True),
                 authors_test(['הרמן מלוויל'])]),
            ({  # Identify by title only.
                 'title': 'בעל זבוב',
             }, [identifier_test('evrit', '9986'),
                 title_test('בעל זבוב', exact=True),
                 authors_test(['ויליאם גולדינג'])]),
        ], fail_missing_meta=False
    )


if __name__ == '__main__':
    test()
