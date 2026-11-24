#!/usr/bin/env python3

import time
from datetime import timedelta

import HTMLParser
import urlparse
from tornado import gen, httpclient, ioloop, queues

base_url = "http://www.tornadoweb.org/en/stable/"
concurrency = 10


@gen.coroutine
def get_links_from_url(url):
    """Download the page at `url` and parse it for links.

    Returned links have had the fragment after `#` removed, and have been made
    absolute so, e.g. the URL 'gen.html#tornado.gen.coroutine' becomes
    'http://www.tornadoweb.org/en/stable/gen.html'.
    """
    try:
        response = yield httpclient.AsyncHTTPClient().fetch(url)
        print(f"fetched {url}")
        urls = [
            urlparse.urljoin(url, remove_fragment(new_url))
            for new_url in get_links(response.body)
        ]
    except Exception as e:
        print(f"Exception: {e} {url}")
        raise gen.Return([])

    raise gen.Return(urls)


def remove_fragment(url):
    scheme, netloc, url, params, query, fragment = urlparse.urlparse(url)
    return urlparse.urlunparse((scheme, netloc, url, params, query, ""))


def get_links(html):
    class URLSeeker(HTMLParser.HTMLParser):
        def __init__(self):
            HTMLParser.HTMLParser.__init__(self)
            self.urls = []

        def handle_starttag(self, tag, attrs):
            href = dict(attrs).get("href")
            if href and tag == "a":
                self.urls.append(href)

    url_seeker = URLSeeker()
    url_seeker.feed(html)
    return url_seeker.urls


@gen.coroutine
def main():
    q = queues.Queue()
    start = time.time()
    fetching, fetched = set(), set()

    @gen.coroutine
    def fetch_url():
        current_url = yield q.get()
        try:
            if current_url in fetching:
                return

            print(f"fetching {current_url}")
            fetching.add(current_url)
            urls = yield get_links_from_url(current_url)
            fetched.add(current_url)

            for new_url in urls:
                # Only follow links beneath the base URL
                if new_url.startswith(base_url):
                    yield q.put(new_url)

        finally:
            q.task_done()

    @gen.coroutine
    def worker():
        while True:
            yield fetch_url()

    q.put(base_url)

    # Start workers, then wait for the work queue to be empty.
    for _ in range(concurrency):
        worker()
    yield q.join(timeout=timedelta(seconds=300))
    assert fetching == fetched
    print(f"Done in {int(time.time() - start)} seconds, fetched {len(fetched)} URLs.")


if __name__ == "__main__":
    import logging

    logging.basicConfig()
    io_loop = ioloop.IOLoop.current()
    io_loop.run_sync(main)
