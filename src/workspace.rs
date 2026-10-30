//! Write a parsed paper as a folder of linked Markdown and JSON files.

use std::fs;
use std::path::Path;

use crate::model::{Citation, Paper, Section};

/// Write the whole workspace under 'out_dir', copying the source XML in
/// alongside it. Returns nothing; the caller prints the summary.
pub fn write(paper: &Paper, input: &Path, out_dir: &Path) -> Result<(), String> {
    let sections_dir = out_dir.join("sections");
    let references_dir = out_dir.join("references");
    let figures_dir = out_dir.join("figures");
    let tables_dir = out_dir.join("tables");

    for dir in [
        out_dir,
        &sections_dir,
        &references_dir,
        &figures_dir,
        &tables_dir,
    ] {
        fs::create_dir_all(dir).map_err(|error| format!("could not create {}: {error}", dir.display()))?;
    }

    // Keep a copy of the source alongside the derived files.
    let xml_copy = out_dir.join("paper.jats.xml");
    fs::copy(input, &xml_copy)
        .map_err(|error| format!("could not copy source to {}: {error}", xml_copy.display()))?;

    write_json(&out_dir.join("metadata.json"), &paper.metadata)?;
    write_json(&out_dir.join("paper.json"), paper)?;
    fs::write(out_dir.join("README.md"), render_readme(paper))
        .map_err(|error| format!("could not write README.md: {error}"))?;

    for (index, section) in paper.body.sections.iter().enumerate() {
        let name = format!("{}.md", section_file_stem(section, index + 1));
        let markdown = render_section(section, 1, &paper.body.citations);
        let path = sections_dir.join(name);
        fs::write(&path, markdown)
            .map_err(|error| format!("could not write {}: {error}", path.display()))?;
    }

    for (index, citation) in paper.body.citations.iter().enumerate() {
        let name = format!("{}.md", reference_file_stem(citation, index + 1));
        let path = references_dir.join(name);
        fs::write(&path, render_reference(citation, index + 1))
            .map_err(|error| format!("could not write {}: {error}", path.display()))?;
    }

    for (index, figure) in paper.body.figures.iter().enumerate() {
        let name = figure.id.clone().unwrap_or_else(|| format!("fig_{}", index + 1));
        write_json(&figures_dir.join(format!("{name}.json")), figure)?;
    }

    for (index, table) in paper.body.tables.iter().enumerate() {
        let name = table.id.clone().unwrap_or_else(|| format!("tab_{}", index + 1));
        write_json(&tables_dir.join(format!("{name}.json")), table)?;
    }

    Ok(())
}

fn write_json<T: serde::Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let json = serde_json::to_string_pretty(value)
        .map_err(|error| format!("could not serialize {}: {error}", path.display()))?;
    fs::write(path, json).map_err(|error| format!("could not write {}: {error}", path.display()))
}

/// '<id>_<slugified title>', falling back to 'sec_<index>' when the section
/// has neither.
pub(crate) fn section_file_stem(section: &Section, index: usize) -> String {
    let id = section.id.as_deref().map(slugify).unwrap_or_default();
    let title = section.title.as_deref().map(slugify).unwrap_or_default();

    match (id.is_empty(), title.is_empty()) {
        (false, false) => format!("{id}_{title}"),
        (false, true) => id.to_string(),
        (true, false) => title,
        (true, true) => format!("sec_{index}"),
    }
}

fn reference_file_stem(citation: &Citation, index: usize) -> String {
    citation
        .id
        .as_deref()
        .map(slugify)
        .filter(|id| !id.is_empty())
        .unwrap_or_else(|| format!("ref_{index}"))
}

/// Lowercase, spaces to underscores, punctuation stripped.
pub(crate) fn slugify(title: &str) -> String {
    let mut slug = String::new();
    for character in title.chars() {
        if character.is_alphanumeric() {
            slug.extend(character.to_lowercase());
        } else if character.is_whitespace() || character == '-' || character == '_' {
            // Collapse runs of separators into a single underscore.
            if !slug.ends_with('_') {
                slug.push('_');
            }
        }
    }
    slug.trim_matches('_').to_string()
}

/// Render a section and its subsections as markdown. 'level' is the heading
/// depth, so a top-level section gets '#' and its subsections get '##'.
fn render_section(section: &Section, level: usize, citations: &[Citation]) -> String {
    let mut markdown = String::new();

    if let Some(title) = &section.title {
        markdown.push_str(&"#".repeat(level));
        markdown.push(' ');
        markdown.push_str(title);
        markdown.push_str("\n\n");
    }

    for paragraph in &section.paragraphs {
        // Provenance goes in an HTML comment so it stays in the file but does
        // not show up when the markdown is rendered.
        markdown.push_str(&format!("<!-- {} -->\n", paragraph.provenance));
        markdown.push_str(&paragraph.text);
        markdown.push_str("\n\n");
        if !paragraph.citations.is_empty() {
            markdown.push_str("References: ");
            for (index, id) in paragraph.citations.iter().enumerate() {
                if index > 0 {
                    markdown.push_str(", ");
                }
                markdown.push_str(&reference_link(id, citations));
            }
            markdown.push_str("\n\n");
        }
    }

    for subsection in &section.subsections {
        markdown.push_str(&render_section(subsection, level + 1, citations));
    }

    markdown
}

fn reference_link(id: &str, citations: &[Citation]) -> String {
    match citations
        .iter()
        .enumerate()
        .find(|(_, citation)| citation.id.as_deref() == Some(id))
    {
        Some((index, citation)) => format!(
            "[{id}](../references/{}.md)",
            reference_file_stem(citation, index + 1)
        ),
        None => format!("`{id}`"),
    }
}

fn render_reference(citation: &Citation, index: usize) -> String {
    let title = citation
        .id
        .clone()
        .unwrap_or_else(|| format!("Reference {index}"));
    let mut markdown = format!("# {title}\n\n{}\n\n", citation.text);

    if let Some(doi) = &citation.doi {
        markdown.push_str(&format!("DOI: {doi}\n\n"));
    }
    markdown.push_str(&format!("Source: `{}`\n", citation.provenance));
    markdown
}

fn render_readme(paper: &Paper) -> String {
    let title = paper.metadata.title.as_deref().unwrap_or("Untitled paper");
    let mut markdown = format!("# {title}\n\n");

    if !paper.metadata.authors.is_empty() {
        markdown.push_str(&format!("Authors: {}\n\n", paper.metadata.authors.join(", ")));
    }
    if let Some(year) = &paper.metadata.year {
        markdown.push_str(&format!("Year: {year}\n\n"));
    }
    if let Some(doi) = &paper.metadata.doi {
        markdown.push_str(&format!("DOI: {doi}\n\n"));
    }
    if let Some(pmcid) = &paper.metadata.pmcid {
        markdown.push_str(&format!("PMCID: {pmcid}\n\n"));
    }
    if let Some(pmid) = &paper.metadata.pmid {
        markdown.push_str(&format!("PMID: {pmid}\n\n"));
    }
    if let Some(abstract_text) = &paper.metadata.abstract_text {
        markdown.push_str("## Abstract\n\n");
        markdown.push_str(abstract_text);
        markdown.push_str("\n\n");
    }

    markdown.push_str("## Sections\n\n");
    for (index, section) in paper.body.sections.iter().enumerate() {
        let name = section.title.as_deref().unwrap_or("Untitled section");
        let path = section_file_stem(section, index + 1);
        markdown.push_str(&format!("- [{name}](sections/{path}.md)\n"));
        render_subsections(&mut markdown, &section.subsections, 1);
    }

    markdown.push_str("\n## Files\n\n");
    markdown.push_str("- `paper.json`: complete parsed paper\n");
    markdown.push_str("- `metadata.json`: paper metadata\n");
    markdown.push_str("- `references/`: bibliography entries\n");
    markdown.push_str("- `figures/`: figure metadata\n");
    markdown.push_str("- `tables/`: table metadata\n");
    markdown.push_str("- `paper.jats.xml`: original source\n");
    markdown
}

fn render_subsections(markdown: &mut String, sections: &[Section], depth: usize) {
    for section in sections {
        let title = section.title.as_deref().unwrap_or("Untitled section");
        markdown.push_str(&format!("{}- {title}\n", "  ".repeat(depth)));
        render_subsections(markdown, &section.subsections, depth + 1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = include_str!("../tests/fixtures/sample_jats.xml");

    #[test]
    fn slugifies_titles() {
        assert_eq!(slugify("Introduction"), "introduction");
        assert_eq!(slugify("Methods & Materials"), "methods_materials");
        assert_eq!(slugify("Results: part 2"), "results_part_2");
    }

    #[test]
    fn falls_back_when_section_has_no_id_or_title() {
        let section = Section::default();
        assert_eq!(section_file_stem(&section, 3), "sec_3");
    }

    #[test]
    fn writes_linked_workspace() {
        let root = std::env::temp_dir().join(format!("pgraph-workspace-{}", std::process::id()));
        let input = root.join("sample.xml");
        let output = root.join("paper");

        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        fs::write(&input, SAMPLE).unwrap();

        let paper = crate::jats::parse(SAMPLE, "sample.xml").unwrap();
        write(&paper, &input, &output).unwrap();

        assert!(output.join("README.md").is_file());
        assert!(output.join("paper.json").is_file());
        assert!(output.join("paper.jats.xml").is_file());
        assert!(output.join("references/ref1.md").is_file());

        let readme = fs::read_to_string(output.join("README.md")).unwrap();
        assert!(readme.contains("[Introduction](sections/intro_introduction.md)"));

        let section = fs::read_to_string(output.join("sections/intro_introduction.md")).unwrap();
        assert!(section.contains(
            "References: [ref1](../references/ref1.md), [ref2](../references/ref2.md)"
        ));

        let paper_json = fs::read_to_string(output.join("paper.json")).unwrap();
        let paper_json: serde_json::Value = serde_json::from_str(&paper_json).unwrap();
        assert_eq!(
            paper_json["body"]["sections"][0]["paragraphs"][0]["citations"][0],
            "ref1"
        );

        fs::remove_dir_all(root).unwrap();
    }
}
