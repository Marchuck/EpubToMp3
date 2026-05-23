#!/usr/bin/env python3
"""Split an EPUB file into individual chapter .txt files."""

import glob
import os
import re
import sys

from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub


def find_epub(directory: str) -> str | None:
    """Find the first .epub file in the given directory."""
    epubs = glob.glob(os.path.join(directory, "*.epub"))
    return epubs[0] if epubs else None


def sanitize_filename(name: str) -> str:
    """Replace non-alphanumeric characters with underscores."""
    return re.sub(r"[^a-zA-Z0-9]", "_", name)


def extract_title(soup: BeautifulSoup, fallback: str) -> str:
    """Extract chapter title from HTML headings or title tag."""
    for tag in ("title", "h1", "h2", "h3"):
        el = soup.find(tag)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return fallback


def extract_text(soup: BeautifulSoup) -> str:
    """Extract readable text from the <body> tag."""
    body = soup.find("body")
    if body is None:
        return ""
    return body.get_text(separator="\n").strip()


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Accept optional CLI arg for epub path
    if len(sys.argv) > 1:
        epub_path = os.path.abspath(sys.argv[1])
        if not os.path.isfile(epub_path):
            print(f"File not found: {epub_path}")
            sys.exit(1)
    else:
        epub_path = find_epub(script_dir)
        if epub_path is None:
            print("No .epub file found in the current directory.")
            print("Usage: python epub_splitter.py [path/to/book.epub]")
            sys.exit(1)

    print(f"Reading: {epub_path}")
    book = epub.read_epub(epub_path)

    output_dir = os.path.join(script_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    chapter_num = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html_content = item.get_content().decode("utf-8", errors="replace")
        soup = BeautifulSoup(html_content, "html.parser")

        title = extract_title(soup, fallback=item.get_id())
        text = extract_text(soup)

        # Skip items with no meaningful content (nav, toc, blank pages)
        if len(text) < 50:
            continue

        chapter_num += 1

        # Replace sub-chapter markers: standalone number surrounded by blank lines
        # e.g. "\n\n1\n\n" becomes "\n\nPodrozdzial 1\n\n"
        text = re.sub(
            r'\n\n(\d{1,3})\n\n',
            lambda m: f'\n\nPodrozdzial {m.group(1)}\n\n',
            text,
        )

        safe_title = sanitize_filename(title)
        filename = f"ch_{chapter_num:03d}_{safe_title}.txt"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(text)

        print(f"  {filename} ({len(text)} chars)")

    if chapter_num == 0:
        print("No chapters with content found.")
    else:
        print(f"Done — {chapter_num} chapters written to {output_dir}")


if __name__ == "__main__":
    main()
