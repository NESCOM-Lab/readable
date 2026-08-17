//! Write a parsed 'Paper' out as a folder of files: metadata json, one
//! markdown file per top-level section, one json file per figure and table,
//! and all citations in a single json file.

use std::fs;
use std::path::Path;

use crate::model::{Paper, Section};

/// Write the whole workspace under 'out_dir', copying the source XML in
/// alongside it. Returns nothing; the caller prints the summary.
pub fn write(paper: &Paper, input: &Path, out_dir: &Path) -> Result<(), String> {
    let sections_dir = out_dir.join("sections");
    let figures_dir = out_dir.join("figures");
    let tables_dir = out_dir.join("tables");
    let citations_dir = out_dir.join("citations");

    for dir in [
        out_dir,
        &sections_dir,
        &figures_dir,
        &tables_dir,
        &citations_dir,
    ] {
        fs::create_dir_all(dir).map_err(|error| format!("could not create {}: {error}", dir.display()))?;
    }

    // Keep a copy of the source alongside the derived files.
    let xml_copy = out_dir.join("paper.jats.xml");
    fs::copy(input, &xml_copy)
        .map_err(|error| format!("could not copy source to {}: {error}", xml_copy.display()))?;

    write_json(&out_dir.join("metadata.json"), &paper.metadata)?;

    for (index, section) in paper.body.sections.iter().enumerate() {
        let name = format!("{}.md", section_file_stem(section, index + 1));
        let markdown = render_section(section, 1);
        let path = sections_dir.join(name);
        fs::write(&path, markdown)
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

    write_json(&citations_dir.join("citations.json"), &paper.body.citations)?;

    Ok(())
}

fn write_json<T: serde::Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let json = serde_json::to_string_pretty(value)
        .map_err(|error| format!("could not serialize {}: {error}", path.display()))?;
    fs::write(path, json).map_err(|error| format!("could not write {}: {error}", path.display()))
}

/// '<id>_<slugified title>', falling back to 'sec_<index>' when the section
/// has neither.
fn section_file_stem(section: &Section, index: usize) -> String {
    let id = section.id.as_deref().unwrap_or("");
    let title = section.title.as_deref().map(slugify).unwrap_or_default();

    match (id.is_empty(), title.is_empty()) {
        (false, false) => format!("{id}_{title}"),
        (false, true) => id.to_string(),
        (true, false) => title,
        (true, true) => format!("sec_{index}"),
    }
}

/// Lowercase, spaces to underscores, punctuation stripped.
fn slugify(title: &str) -> String {
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
fn render_section(section: &Section, level: usize) -> String {
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
    }

    for subsection in &section.subsections {
        markdown.push_str(&render_section(subsection, level + 1));
    }

    markdown
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
