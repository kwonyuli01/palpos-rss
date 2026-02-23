#!/usr/bin/env python3
"""
Palpos.disway.id RSS Feed Scraper - Pencarian "bansos"
=======================================================
Scrape hasil pencarian keyword "bansos" dari palpos.disway.id
dengan konten artikel lengkap (termasuk multi-page).

Dijalankan otomatis via GitHub Actions + publish ke GitHub Pages.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import time
import re
import os
import html
import hashlib

# ============================================================
# KONFIGURASI
# ============================================================

BASE_URL = "https://palpos.disway.id"

# URL pencarian keyword "bansos"
SEARCH_URL = "https://palpos.disway.id/search/kata/?c=bansos"

# Jumlah artikel maksimal yang di-scrape
MAX_ARTICLES = 30

# Nama dan deskripsi feed
FEED_TITLE = "Palpos.disway.id - Bansos"
FEED_DESCRIPTION = "RSS Feed hasil pencarian 'bansos' dari palpos.disway.id dengan konten artikel lengkap"
FEED_LINK = "https://palpos.disway.id"

# File output
OUTPUT_FILE = "docs/feed.xml"

# Delay antar request (detik)
REQUEST_DELAY = 2

# User Agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Timezone WIB
WIB = timezone(timedelta(hours=7))

# ============================================================
# KODE UTAMA
# ============================================================

session = requests.Session()
session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
})


def fetch_page(url, retries=3):
    """Fetch halaman web dengan retry."""
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            response.encoding = 'utf-8'
            return response.text
        except requests.RequestException as e:
            print(f"  [!] Gagal fetch {url} (percobaan {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(REQUEST_DELAY * 2)
    return None


def parse_search_page(url):
    """Parse halaman pencarian untuk mendapatkan daftar artikel."""
    print(f"\n[*] Scraping halaman pencarian: {url}")
    html_content = fetch_page(url)
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, 'lxml')
    articles = []

    # Cari semua link artikel dari h2.media-heading
    # Di halaman search, ada duplikat di sidebar - kita filter yang di area konten utama
    # Area konten utama: setelah <h2>Kata Pencarian "bansos"</h2>
    search_header = soup.find('h2', string=re.compile(r'Kata Pencarian'))
    
    if search_header:
        # Cari parent section dari header
        search_section = search_header.find_parent('div', class_='col-sm-8')
        if search_section:
            headings = search_section.select('h2.media-heading a')
        else:
            headings = soup.select('h2.media-heading a')
    else:
        headings = soup.select('h2.media-heading a')

    for link in headings:
        href = link.get('href', '')
        title = link.get_text(strip=True)

        if not href or not title:
            continue

        # Pastikan URL lengkap
        if href.startswith('/'):
            href = BASE_URL + href

        # Filter hanya link artikel (harus mengandung /read/)
        if '/read/' not in href:
            continue

        # Hindari duplikat
        if any(a['link'] == href for a in articles):
            continue

        articles.append({
            'title': title,
            'link': href,
        })

        if len(articles) >= MAX_ARTICLES:
            break

    print(f"  [+] Ditemukan {len(articles)} artikel")
    return articles


def parse_article_page(url):
    """Parse halaman artikel untuk mendapatkan konten lengkap."""
    print(f"  [>] Mengambil artikel: {url}")

    html_content = fetch_page(url)
    if not html_content:
        return None

    soup = BeautifulSoup(html_content, 'lxml')
    article_data = {}

    # === JUDUL ===
    h1 = soup.find('h1')
    article_data['title'] = h1.get_text(strip=True) if h1 else ''

    # === TANGGAL ===
    # Palpos menggunakan meta pubdate: "2026-02-23 17:18:45"
    pub_date_str = ''
    pubdate_meta = soup.find('meta', attrs={'name': 'pubdate'})
    if pubdate_meta:
        pub_date_str = pubdate_meta.get('content', '')

    if not pub_date_str:
        # Fallback: cari di dataLayer
        match = re.search(r'"published_date"\s*:\s*"([^"]+)"', html_content)
        if match:
            pub_date_str = match.group(1)

    if not pub_date_str:
        # Fallback: cari format "Senin 23-02-2026,17:18 WIB" di halaman
        for text in soup.find_all(string=re.compile(r'(Senin|Selasa|Rabu|Kamis|Jumat|Sabtu|Minggu)\s+\d{2}-\d{2}-\d{4}')):
            pub_date_str = text.strip()
            break

    article_data['pub_date'] = parse_date(pub_date_str)

    # === REPORTER & EDITOR ===
    reporter = ''
    editor = ''

    # Palpos: <div class="author" id="author">Reporter: <strong>Bambang</strong>
    author_div = soup.find('div', id='author')
    if author_div:
        bold = author_div.find('strong')
        if bold:
            reporter = bold.get_text(strip=True)

    editor_div = soup.find('div', id='editor')
    if editor_div:
        bold = editor_div.find('strong')
        if bold:
            editor = bold.get_text(strip=True)

    # Fallback: cari di semua elemen
    if not reporter:
        for tag in soup.find_all(['p', 'span', 'div']):
            text = tag.get_text()
            if 'Reporter:' in text or 'Penulis:' in text:
                bold = tag.find('b') or tag.find('strong')
                if bold:
                    reporter = bold.get_text(strip=True)
                    break

    article_data['reporter'] = reporter
    article_data['editor'] = editor

    # === GAMBAR UTAMA ===
    main_image = ''
    
    # Cari dari og:image meta tag (paling reliable)
    og_image = soup.find('meta', property='og:image')
    if og_image:
        main_image = og_image.get('content', '')
    
    if not main_image:
        # Fallback: cari gambar di konten artikel
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if 'palpos.disway.id/upload/' in src and 'logo' not in src and 'favicon' not in src:
                main_image = src
                break

    article_data['image'] = main_image

    # === CAPTION GAMBAR ===
    caption = ''
    caption_elem = soup.select_one('div.post.text-black-1 .bottom-15 small')
    if caption_elem:
        caption = caption_elem.get_text(strip=True)
    
    if not caption and main_image:
        # Fallback: cari small/figcaption dekat gambar
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if src and 'upload/' in src:
                small = img.find_next('small')
                if small and len(small.get_text(strip=True)) < 200:
                    caption = small.get_text(strip=True)
                    break

    article_data['caption'] = caption

    # === KONTEN ARTIKEL ===
    content_parts = []

    # Cari konten di dalam div.post.text-black-1
    post_div = soup.find('div', class_=lambda c: c and 'post' in c and 'text-black-1' in c)
    
    if post_div:
        # Ambil semua p dan h3/h4 di dalam post div
        for element in post_div.find_all(['p', 'h3', 'h4']):
            text = element.get_text(strip=True)
            
            if not text:
                continue

            # Skip metadata
            if any(skip in text for skip in [
                'Reporter:', 'Editor:', 'Penulis:', 'Cek Berita dan Artikel',
                'Google News', 'WhatsApp Channel', 'Sumber:'
            ]):
                continue

            # Skip BACA JUGA links
            if text.startswith('BACA JUGA:'):
                continue

            # Skip caption gambar
            if text == caption:
                continue

            # Skip paragraf yang hanya berisi <small> (caption/credit)
            if element.find('small') and not element.find('strong'):
                continue

            # Skip teks sangat pendek yang bukan konten
            if len(text) < 10:
                continue

            # Skip ads placeholder
            parent_classes = ' '.join(element.parent.get('class', []))
            if any(skip in parent_classes for skip in ['ads-slot', 'adsbygoogle']):
                continue

            if element.name in ['h3', 'h4']:
                content_parts.append(f"\n### {text}\n")
            else:
                clean_text = text.replace('\xa0', ' ').strip()
                if clean_text:
                    content_parts.append(clean_text)
    else:
        # Fallback: ambil semua paragraf
        found_content = False
        for p in soup.find_all('p'):
            text = p.get_text(strip=True)
            if not text:
                continue

            parent_classes = ' '.join(p.parent.get('class', []))
            if any(skip in parent_classes for skip in ['sidebar', 'footer', 'nav', 'menu', 'comment']):
                continue

            if any(skip in text for skip in [
                'Reporter:', 'Editor:', 'Penulis:', 'Cek Berita dan Artikel',
                'Google News', 'WhatsApp Channel', 'BACA JUGA:'
            ]):
                continue

            if len(text) < 20:
                continue

            # Deteksi awal konten
            if re.match(r'^(PALPOS\.CO|PALPOS\.ID)', text) or (not found_content and len(text) > 50):
                found_content = True

            if found_content:
                clean_text = text.replace('\xa0', ' ').strip()
                if clean_text:
                    content_parts.append(clean_text)

    article_data['content'] = '\n\n'.join(content_parts)

    # === MULTI-PAGE: Cek halaman lanjutan ===
    # Palpos: /read/710227/slug/15, /read/710227/slug/30
    next_pages = []
    pagination = soup.find('ul', class_='pagination')
    if pagination:
        for a in pagination.find_all('a'):
            href = a.get('href', '')
            page_num = a.get('data-ci-pagination-page', '')
            if href and page_num and page_num != '1' and 'rel' not in a.attrs:
                page_url = href if href.startswith('http') else BASE_URL + href
                if page_url not in next_pages and page_url != url:
                    next_pages.append(page_url)

    for page_url in next_pages[:5]:
        print(f"    [>] Halaman lanjutan: {page_url}")
        time.sleep(REQUEST_DELAY)
        page_content = fetch_additional_page(page_url)
        if page_content:
            article_data['content'] += '\n\n' + page_content

    # === TAG ===
    tags = []
    tag_section = soup.find('div', class_='news-tags')
    if tag_section:
        for tag_link in tag_section.select('a[href*="/listtag/"]'):
            tag_text = tag_link.get_text(strip=True).replace('#', '').strip()
            if tag_text:
                tags.append(tag_text)
    else:
        # Fallback
        for tag_link in soup.select('a[href*="/listtag/"]'):
            tag_text = tag_link.get_text(strip=True).replace('#', '').strip()
            if tag_text and tag_text not in tags:
                tags.append(tag_text)

    article_data['tags'] = tags

    # === KATEGORI ===
    category = ''
    breadcrumb = soup.find('ul', class_='breadcrumb')
    if breadcrumb:
        cat_links = breadcrumb.select('a[href*="/kategori/"]')
        for cl in cat_links:
            cat_text = cl.get_text(strip=True)
            if cat_text and cat_text not in ['Home', '']:
                category = cat_text
                break

    if not category:
        # Fallback: dari dataLayer
        match = re.search(r'"rubrik"\s*:\s*"([^"]+)"', html_content)
        if match:
            category = match.group(1)

    article_data['category'] = category

    return article_data


def fetch_additional_page(url):
    """Fetch halaman lanjutan dari artikel multi-page."""
    html_content = fetch_page(url)
    if not html_content:
        return ''

    soup = BeautifulSoup(html_content, 'lxml')
    content_parts = []

    # Cari konten di div.post
    post_div = soup.find('div', class_=lambda c: c and 'post' in c and 'text-black-1' in c)
    elements = post_div.find_all(['p', 'h3', 'h4']) if post_div else soup.find_all('p')

    for elem in elements:
        text = elem.get_text(strip=True)
        if not text or len(text) < 10:
            continue

        parent_classes = ' '.join(elem.parent.get('class', []))
        if any(skip in parent_classes for skip in ['sidebar', 'footer', 'nav', 'ads-slot']):
            continue

        if any(skip in text for skip in [
            'Reporter:', 'Editor:', 'Cek Berita', 'Google News',
            'WhatsApp Channel', 'BACA JUGA:', 'Sumber:'
        ]):
            continue

        if elem.name in ['h3', 'h4']:
            content_parts.append(f"\n### {text}\n")
        else:
            clean_text = text.replace('\xa0', ' ').strip()
            if clean_text:
                content_parts.append(clean_text)

    return '\n\n'.join(content_parts)


def parse_date(date_str):
    """Parse tanggal ke format RFC 822."""
    if not date_str:
        return datetime.now(WIB).strftime('%a, %d %b %Y %H:%M:%S +0700')

    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    # Format 1: "2026-02-23 17:18:45" (meta pubdate)
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', date_str)
    if match:
        year, month, day, hour, minute, sec = match.groups()
        try:
            dt = datetime(int(year), int(month), int(day), int(hour), int(minute), int(sec))
            return f"{days[dt.weekday()]}, {dt.day:02d} {months[dt.month-1]} {dt.year} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} +0700"
        except ValueError:
            pass

    # Format 2: "Senin 23-02-2026,17:18 WIB"
    match = re.search(r'(\d{2})-(\d{2})-(\d{4}),?\s*(\d{2}):(\d{2})', date_str)
    if match:
        day, month, year, hour, minute = match.groups()
        try:
            dt = datetime(int(year), int(month), int(day), int(hour), int(minute))
            return f"{days[dt.weekday()]}, {dt.day:02d} {months[dt.month-1]} {dt.year} {dt.hour:02d}:{dt.minute:02d}:00 +0700"
        except ValueError:
            pass

    return datetime.now(WIB).strftime('%a, %d %b %Y %H:%M:%S +0700')


def generate_rss(articles_data):
    """Generate file RSS XML dari data artikel."""
    print(f"\n[*] Generating RSS XML...")
    now = datetime.now(WIB).strftime('%a, %d %b %Y %H:%M:%S +0700')

    rss_items = []
    for article in articles_data:
        if not article:
            continue

        content_html = ''

        # Gambar utama
        if article.get('image'):
            content_html += f'<p><img src="{html.escape(article["image"])}" alt="{html.escape(article.get("title", ""))}" style="max-width:100%;" /></p>\n'

        # Caption
        if article.get('caption'):
            content_html += f'<p><em>{html.escape(article["caption"])}</em></p>\n'

        # Reporter/Editor
        if article.get('reporter'):
            content_html += f'<p><strong>Reporter:</strong> {html.escape(article["reporter"])}'
            if article.get('editor'):
                content_html += f' | <strong>Editor:</strong> {html.escape(article["editor"])}'
            content_html += '</p>\n'

        # Konten
        if article.get('content'):
            paragraphs = article['content'].split('\n\n')
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                if para.startswith('### '):
                    content_html += f'<h3>{html.escape(para[4:])}</h3>\n'
                else:
                    content_html += f'<p>{html.escape(para)}</p>\n'

        # Tags
        if article.get('tags'):
            tags_str = ', '.join(article['tags'])
            content_html += f'<p><strong>Tags:</strong> {html.escape(tags_str)}</p>\n'

        guid = article.get('link', hashlib.md5(article.get('title', '').encode()).hexdigest())

        rss_items.append({
            'title': article.get('title', 'Tanpa Judul'),
            'link': article.get('link', ''),
            'description': content_html,
            'pubDate': article.get('pub_date', now),
            'category': article.get('category', ''),
            'tags': article.get('tags', []),
            'guid': guid,
            'image': article.get('image', ''),
        })

    # Bangun XML
    rss_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>{html.escape(FEED_TITLE)}</title>
    <description>{html.escape(FEED_DESCRIPTION)}</description>
    <link>{html.escape(FEED_LINK)}</link>
    <language>id</language>
    <lastBuildDate>{now}</lastBuildDate>
    <generator>Palpos RSS Scraper (GitHub Actions)</generator>
'''

    for item in rss_items:
        rss_xml += f'''    <item>
      <title><![CDATA[{item['title']}]]></title>
      <link>{html.escape(item['link'])}</link>
      <guid isPermaLink="true">{html.escape(item['guid'])}</guid>
      <pubDate>{item['pubDate']}</pubDate>
'''
        if item['category']:
            rss_xml += f'      <category><![CDATA[{item["category"]}]]></category>\n'
        for tag in item.get('tags', []):
            rss_xml += f'      <category><![CDATA[{tag}]]></category>\n'
        if item['image']:
            rss_xml += f'      <media:content url="{html.escape(item["image"])}" medium="image" />\n'
        rss_xml += f'      <description><![CDATA[{item["description"]}]]></description>\n'
        rss_xml += f'      <content:encoded><![CDATA[{item["description"]}]]></content:encoded>\n'
        rss_xml += '    </item>\n'

    rss_xml += '''  </channel>
</rss>'''

    return rss_xml


def main():
    """Fungsi utama."""
    print("=" * 60)
    print("  Palpos.disway.id RSS Scraper - Bansos")
    print("=" * 60)
    print(f"  Feed Title : {FEED_TITLE}")
    print(f"  Output     : {OUTPUT_FILE}")
    print(f"  Max Artikel: {MAX_ARTICLES}")
    print(f"  Search URL : {SEARCH_URL}")
    print("=" * 60)

    # Buat folder docs/ jika belum ada
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    # Step 1: Scrape halaman pencarian
    articles = parse_search_page(SEARCH_URL)

    if not articles:
        print("\n[!] Tidak ada artikel ditemukan.")
        return

    # Hapus duplikat
    seen = set()
    unique_articles = []
    for article in articles:
        if article['link'] not in seen:
            seen.add(article['link'])
            unique_articles.append(article)

    print(f"\n[*] Total {len(unique_articles)} artikel unik")

    # Step 2: Fetch konten lengkap setiap artikel
    articles_data = []
    for i, article in enumerate(unique_articles):
        print(f"\n--- Artikel {i+1}/{len(unique_articles)} ---")
        article_data = parse_article_page(article['link'])

        if article_data:
            if not article_data.get('title'):
                article_data['title'] = article['title']
            article_data['link'] = article['link']
            articles_data.append(article_data)
        else:
            articles_data.append({
                'title': article['title'],
                'link': article['link'],
                'content': '(Konten tidak dapat diambil)',
                'pub_date': datetime.now(WIB).strftime('%a, %d %b %Y %H:%M:%S +0700'),
                'image': '', 'reporter': '', 'editor': '',
                'tags': [], 'category': '', 'caption': '',
            })

        time.sleep(REQUEST_DELAY)

    # Step 3: Generate & simpan RSS
    rss_xml = generate_rss(articles_data)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(rss_xml)

    print(f"\n{'=' * 60}")
    print(f"  SELESAI! File: {OUTPUT_FILE}")
    print(f"  Total artikel: {len(articles_data)}")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
