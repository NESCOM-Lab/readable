#!/usr/bin/env python3
"""Fetch a paper as JATS XML, by whichever route that paper allows.

Not every paper in an evaluation set is deposited the same way. PMC serves
proper JATS only when the licence permits reuse, so a paper can have a PMCID
and still return front matter alone, and a paywalled one has no PMC record at
all. This fetches the best available source and writes JATS either way, so the
parser downstream sees one format.

Three routes, in descending order of fidelity:

  jats      EuropePMC's full text XML, used as published
  html      the PMC reading page, rebuilt into JATS
  abstract  the abstract alone, when that is all that is public

The route taken is recorded in the output, since a conversion is not the same
evidence as a deposit and the difference has to stay visible in the results.
"""

import argparse
import html
import json
import re
import urllib.parse
import urllib.request

EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
PMC_ARTICLE = "https://pmc.ncbi.nlm.nih.gov/articles"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read().decode("utf-8", errors="replace")


def strip_tags(fragment):
    text = re.sub(r"<[^>]+>", "", fragment)
    return html.unescape(text).replace("\xa0", " ").strip()


def fetch_jats(pmcid):
    """The published XML, when the licence lets PMC serve it."""
    try:
        text = get(f"{EUROPE_PMC}/{pmcid}/fullTextXML")
    except Exception:
        return None
    if "<body>" not in text:
        return None
    return text


def fetch_metadata(query):
    """Title, abstract and journal, which are public for every indexed paper."""
    url = f"{EUROPE_PMC}/search?query={urllib.parse.quote(query)}&resultType=core&format=json"
    results = json.loads(get(url))["resultList"]["result"]
    return results[0] if results else {}


def paragraphs_of(block):
    """The <p> text of one HTML section, skipping figures and captions.

    Those are collected separately by the parser, and inlining them here would
    run a caption onto the end of the sentence before it.
    """
    block = re.sub(r"<figure.*?</figure>", "", block, flags=re.S)
    block = re.sub(r"<figcaption.*?</figcaption>", "", block, flags=re.S)

    found = []
    for match in re.finditer(r"<p[^>]*>(.*?)</p>", block, re.S):
        text = strip_tags(match.group(1))
        if len(text) > 40:
            found.append(text)
    return found


def sections_from_html(page):
    """Rebuild the section tree from the PMC reading page.

    PMC keeps the original JATS section ids in the HTML, and nests them by
    name: 's0002-s2001' is a subsection of 's0002'. That naming is what makes
    the hierarchy recoverable, so it is used rather than the tag nesting.
    """
    found = {}
    order = []
    pattern = re.compile(r'<section[^>]*id="(s\d[^"]*)"[^>]*>(.*?)(?=<section[^>]*id="s\d|</article>)', re.S)

    for match in pattern.finditer(page):
        section_id = match.group(1)
        block = match.group(2)

        heading = re.search(r"<h[2-6][^>]*>(.*?)</h[2-6]>", block, re.S)
        title = strip_tags(heading.group(1)) if heading else ""
        body = paragraphs_of(block)
        if not title and not body:
            continue

        found[section_id] = {"id": section_id, "title": title, "paragraphs": body, "subsections": []}
        order.append(section_id)

    # 's0002-s2001' hangs under 's0002'. Anything whose parent is missing stays
    # at the top rather than being dropped.
    roots = []
    for section_id in order:
        parent = section_id.rsplit("-", 1)[0] if "-" in section_id else None
        if parent and parent in found:
            found[parent]["subsections"].append(found[section_id])
        else:
            roots.append(found[section_id])
    return roots


def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_sections(sections):
    out = []
    for section in sections:
        out.append(f'<sec id="{section["id"]}">')
        if section["title"]:
            out.append(f"<title>{escape(section['title'])}</title>")
        for paragraph in section["paragraphs"]:
            out.append(f"<p>{escape(paragraph)}</p>")
        out.extend(render_sections(section["subsections"]))
        out.append("</sec>")
    return out


def build_jats(meta, sections, pmcid, route):
    title = escape(meta.get("title", "").rstrip("."))
    journal = escape(meta.get("journalInfo", {}).get("journal", {}).get("title", ""))
    year = meta.get("pubYear", "")
    abstract = meta.get("abstractText", "")
    abstract = escape(strip_tags(abstract)) if abstract else ""

    authors = []
    for author in meta.get("authorList", {}).get("author", [])[:40]:
        surname = escape(author.get("lastName", ""))
        given = escape(author.get("firstName", ""))
        if surname:
            authors.append(f"<contrib contrib-type='author'><name><surname>{surname}</surname>"
                           f"<given-names>{given}</given-names></name></contrib>")

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<article xmlns:xlink="http://www.w3.org/1999/xlink" article-type="research-article">',
        "<front><journal-meta><journal-title-group>",
        f"<journal-title>{journal}</journal-title>",
        "</journal-title-group></journal-meta><article-meta>",
        f'<article-id pub-id-type="pmcid">{pmcid}</article-id>',
        f'<article-id pub-id-type="doi">{escape(meta.get("doi", ""))}</article-id>',
        f"<title-group><article-title>{title}</article-title></title-group>",
        f"<contrib-group>{''.join(authors)}</contrib-group>",
        f'<pub-date pub-type="epub"><year>{year}</year></pub-date>',
    ]
    if abstract:
        parts.append(f"<abstract><p>{abstract}</p></abstract>")
    parts.append(f"<custom-meta-group><custom-meta>"
                 f"<meta-name>source_format</meta-name><meta-value>{route}</meta-value>"
                 f"</custom-meta></custom-meta-group>")
    parts.append("</article-meta></front><body>")
    parts.extend(render_sections(sections))
    parts.append("</body></article>")
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pmcid", help="PMC id, when the paper has one")
    parser.add_argument("--doi", help="used to look the paper up when there is no PMCID")
    parser.add_argument("--out", required=True, help="where to write the JATS file")
    parser.add_argument("--name", help="short label recorded alongside the file")
    args = parser.parse_args()

    query = f'DOI:"{args.doi}"' if args.doi else f"PMCID:{args.pmcid}"
    meta = fetch_metadata(query)
    if not meta:
        raise SystemExit(f"nothing found for {query}")
    pmcid = args.pmcid or meta.get("pmcid") or "unknown"

    route = None
    xml = None

    if args.pmcid:
        xml = fetch_jats(args.pmcid)
        if xml:
            route = "jats"

    if xml is None and args.pmcid:
        try:
            page = get(f"{PMC_ARTICLE}/{args.pmcid}/")
            sections = sections_from_html(page)
            if sections:
                xml = build_jats(meta, sections, pmcid, "html")
                route = "html"
        except Exception as error:
            print(f"  html route failed: {error}")

    if xml is None:
        xml = build_jats(meta, [], pmcid, "abstract")
        route = "abstract"

    with open(args.out, "w") as handle:
        handle.write(xml)

    note = {"jats": "published XML",
            "html": "rebuilt from the PMC reading page",
            "abstract": "abstract only; no public full text"}[route]
    print(f"{args.name or pmcid}: {route} ({note}), {len(xml)} chars -> {args.out}")


if __name__ == "__main__":
    main()
