//! JATS XML -> 'Paper' ingestion.
//!
//! Extracts title, abstract, sections/subsections and paragraphs, figures,
//! tables, citations, and front-matter metadata. Missing fields are left empty.

use roxmltree::{Document, Node, ParsingOptions};

use crate::model::{Body, Citation, Figure, Metadata, Paper, Paragraph, Section, Table};

/// Parse JATS XML into a 'Paper'. 'source' is the input file name.
pub fn parse(xml: &str, source: &str) -> Result<Paper, String> {
    // PMC downloads declare the JATS DTD.
    let options = ParsingOptions {
        allow_dtd: true,
        ..ParsingOptions::default()
    };
    let document = Document::parse_with_options(xml, options)
        .map_err(|error| format!("invalid XML: {error}"))?;

    // efetch wraps the article in a <pmc-articleset>, so the root element
    // is not always the <article> itself.
    let root_element = document.root_element();
    let root = if tag(root_element) == "article" {
        root_element
    } else {
        root_element
            .descendants()
            .find(|node| tag(*node) == "article")
            .ok_or("no <article> element found")?
    };

    let metadata = match root.descendants().find(|node| tag(*node) == "article-meta") {
        Some(article_meta) => parse_metadata(article_meta),
        None => Metadata::default(),
    };

    let mut body = Body::default();
    if let Some(body_node) = find_child(root, "body") {
        for child in body_node.children() {
            if tag(child) == "sec" {
                body.sections.push(parse_section(child));
            }
        }
    }

    // Figures and tables are not always inside <body>; PMC often collects
    // them in a <floats-group> at the end, so scan the whole article.
    for node in root.descendants() {
        match tag(node) {
            "fig" => body.figures.push(parse_figure(node)),
            "table-wrap" => body.tables.push(parse_table(node)),
            _ => {}
        }
    }

    body.citations = parse_citations(root);

    Ok(Paper {
        source: source.to_string(),
        metadata,
        body,
    })
}

/// Pull front-matter out of <article-meta> in a single pass.
fn parse_metadata(article_meta: Node) -> Metadata {
    let mut metadata = Metadata::default();

    for node in article_meta.descendants() {
        match tag(node) {
            "article-title" if metadata.title.is_none() => {
                metadata.title = Some(inner_text(node));
            }
            "year" if metadata.year.is_none() => {
                metadata.year = Some(inner_text(node));
            }
            "article-id" => match node.attribute("pub-id-type") {
                Some("doi") => metadata.doi = Some(inner_text(node)),
                Some("pmid") => metadata.pmid = Some(inner_text(node)),
                Some("pmc") | Some("pmcid") => metadata.pmcid = Some(inner_text(node)),
                _ => {}
            },
            "contrib" if node.attribute("contrib-type").unwrap_or("author") == "author" => {
                if let Some(name) = author_name(node) {
                    metadata.authors.push(name);
                }
            }
            _ => {}
        }
    }

    if let Some(abstract_node) = find_child(article_meta, "abstract") {
        let text = paragraph_text(abstract_node);
        if !text.is_empty() {
            metadata.abstract_text = Some(text);
        }
    }

    metadata
}

/// Build a display name from a <contrib>'s <name>.
fn author_name(contrib: Node) -> Option<String> {
    let name = find_child(contrib, "name")?;
    let given = find_child(name, "given-names").map(inner_text);
    let surname = find_child(name, "surname").map(inner_text);
    match (given, surname) {
        (Some(given), Some(surname)) => Some(format!("{given} {surname}")),
        (given, surname) => given.or(surname),
    }
}

/// Parse a <sec>, recursing into nested subsections.
fn parse_section(sec: Node) -> Section {
    let mut section = Section {
        id: sec.attribute("id").map(str::to_string),
        provenance: element_path(sec),
        ..Section::default()
    };

    for child in sec.children() {
        match tag(child) {
            "title" => section.title = Some(inner_text(child)),
            "p" => section.paragraphs.push(Paragraph {
                text: inner_text(child),
                citations: citation_ids(child),
                provenance: element_path(child),
            }),
            "sec" => section.subsections.push(parse_section(child)),
            _ => {}
        }
    }

    section
}

fn citation_ids(paragraph: Node) -> Vec<String> {
    let mut ids = Vec::new();

    for xref in paragraph.descendants() {
        if tag(xref) != "xref" || xref.attribute("ref-type") != Some("bibr") {
            continue;
        }
        if let Some(rid) = xref.attribute("rid") {
            for id in rid.split_whitespace() {
                if !ids.iter().any(|found| found == id) {
                    ids.push(id.to_string());
                }
            }
        }
    }

    ids
}

fn parse_figure(fig: Node) -> Figure {
    Figure {
        id: fig.attribute("id").map(str::to_string),
        label: find_child(fig, "label").map(inner_text),
        caption: find_child(fig, "caption").map(paragraph_text),
        provenance: element_path(fig),
    }
}

fn parse_table(table_wrap: Node) -> Table {
    Table {
        id: table_wrap.attribute("id").map(str::to_string),
        label: find_child(table_wrap, "label").map(inner_text),
        caption: find_child(table_wrap, "caption").map(paragraph_text),
        provenance: element_path(table_wrap),
    }
}

/// Collect <ref> entries from <back>/<ref-list>.
fn parse_citations(root: Node) -> Vec<Citation> {
    let mut citations = Vec::new();

    for ref_node in root.descendants() {
        if tag(ref_node) != "ref" {
            continue;
        }

        // The citation is usually wrapped in one of these; fall back to the ref itself.
        let citation = find_child(ref_node, "mixed-citation")
            .or_else(|| find_child(ref_node, "element-citation"))
            .unwrap_or(ref_node);

        let doi = ref_node
            .descendants()
            .find(|node| tag(*node) == "pub-id" && node.attribute("pub-id-type") == Some("doi"))
            .map(inner_text);

        // <mixed-citation> carries its own punctuation and spacing;
        // <element-citation> is pure markup with no whitespace between fields,
        // so its leaf text has to be rejoined with spaces.
        let text = if tag(citation) == "element-citation" {
            leaf_text(citation)
        } else {
            inner_text(citation)
        };

        citations.push(Citation {
            id: ref_node.attribute("id").map(str::to_string),
            text,
            doi,
            provenance: element_path(ref_node),
        });
    }

    citations
}

// --- tree helpers -----------------------------------------------------------

/// Tag name of an element (empty string for non-elements like text nodes).
fn tag<'input>(node: Node<'_, 'input>) -> &'input str {
    node.tag_name().name()
}

/// First direct child element with the given tag name.
fn find_child<'a, 'input>(node: Node<'a, 'input>, name: &str) -> Option<Node<'a, 'input>> {
    node.children().find(|child| tag(*child) == name)
}

/// All descendant text joined and whitespace-normalized; flattens inline
/// markup (italic, xref, ...) into plain text.
fn inner_text(node: Node) -> String {
    let mut text = String::new();
    for descendant in node.descendants() {
        if descendant.is_text() {
            if let Some(chunk) = descendant.text() {
                text.push_str(chunk);
            }
        }
    }
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Text of every innermost element, joined with spaces. Used for
/// <element-citation>, where the markup carries the structure and there is
/// no literal whitespace between fields like surname and given-names.
fn leaf_text(node: Node) -> String {
    let mut parts = Vec::new();
    for descendant in node.descendants() {
        if !descendant.is_element() {
            continue;
        }
        if descendant.children().any(|child| child.is_element()) {
            continue;
        }
        let text = inner_text(descendant);
        if !text.is_empty() {
            parts.push(text);
        }
    }
    parts.join(" ")
}

/// Join every <p> inside a node (abstract, caption) into one string,
/// falling back to the node's own text when there are no paragraphs.
fn paragraph_text(node: Node) -> String {
    let parts: Vec<String> = node
        .descendants()
        .filter(|descendant| tag(*descendant) == "p")
        .map(inner_text)
        .filter(|text| !text.is_empty())
        .collect();

    if parts.is_empty() {
        inner_text(node)
    } else {
        parts.join(" ")
    }
}

/// Simple provenance path like 'article/body/sec[1]/p[2]'. Indices are 1-based
/// and count preceding siblings with the same tag.
fn element_path(node: Node) -> String {
    let mut segments = Vec::new();
    let mut current = Some(node);

    while let Some(element) = current {
        if !element.is_element() {
            break;
        }
        let mut index = 1;
        let mut sibling = element.prev_sibling_element();
        while let Some(previous) = sibling {
            if tag(previous) == tag(element) {
                index += 1;
            }
            sibling = previous.prev_sibling_element();
        }
        segments.push(format!("{}[{}]", tag(element), index));
        current = element.parent();
    }

    segments.reverse();
    segments.join("/")
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = include_str!("../tests/fixtures/sample_jats.xml");

    #[test]
    fn parses_sample_and_produces_valid_json() {
        let paper = parse(SAMPLE, "sample_jats.xml").expect("fixture should parse");

        // Metadata basics.
        let metadata = &paper.metadata;
        assert_eq!(
            metadata.title.as_deref(),
            Some("Hippocampal Theta Oscillations During Spatial Navigation")
        );
        assert_eq!(metadata.doi.as_deref(), Some("10.1000/neuro.2026.001"));
        assert_eq!(metadata.pmcid.as_deref(), Some("PMC7654321"));
        assert_eq!(metadata.pmid.as_deref(), Some("31234567"));
        assert_eq!(metadata.year.as_deref(), Some("2026"));
        assert_eq!(metadata.authors, vec!["Elena Ramirez", "David A. Okonkwo"]);
        assert!(
            metadata
                .abstract_text
                .as_deref()
                .unwrap_or("")
                .contains("freely moving mice")
        );

        // Sections, subsections, and paragraphs.
        let body = &paper.body;
        assert_eq!(body.sections.len(), 2);
        let intro = &body.sections[0];
        assert_eq!(intro.id.as_deref(), Some("intro"));
        assert_eq!(intro.title.as_deref(), Some("Introduction"));
        assert_eq!(intro.paragraphs.len(), 2);
        assert_eq!(intro.paragraphs[0].citations, vec!["ref1", "ref2"]);
        assert!(intro.paragraphs[1].citations.is_empty());
        assert_eq!(intro.subsections.len(), 1);
        assert_eq!(intro.subsections[0].title.as_deref(), Some("Background"));

        // Provenance is recorded as an element path.
        assert_eq!(intro.provenance, "article[1]/body[1]/sec[1]");

        // Figures and tables with captions.
        assert_eq!(body.figures.len(), 1);
        assert_eq!(body.figures[0].label.as_deref(), Some("Figure 1"));
        assert!(
            body.figures[0]
                .caption
                .as_deref()
                .unwrap_or("")
                .contains("theta-filtered LFP")
        );
        assert_eq!(body.tables.len(), 1);
        assert_eq!(body.tables[0].label.as_deref(), Some("Table 1"));

        // Citations, including a DOI pulled from a pub-id.
        assert_eq!(body.citations.len(), 2);
        assert_eq!(body.citations[0].id.as_deref(), Some("ref1"));
        assert_eq!(body.citations[0].doi.as_deref(), Some("10.1000/okeefe.1978"));

        // The whole thing serializes to valid JSON.
        let json = serde_json::to_string_pretty(&paper).expect("should serialize");
        let reparsed: serde_json::Value =
            serde_json::from_str(&json).expect("output should be valid JSON");
        assert_eq!(reparsed["metadata"]["doi"], "10.1000/neuro.2026.001");
    }
}
