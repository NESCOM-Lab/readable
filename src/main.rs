use std::path::PathBuf;
use std::process;

use clap::{Parser, Subcommand};

mod jats;
mod model;
mod query;
mod units;
mod workspace;

/// Convert a JATS XML paper into a workspace.
#[derive(Parser)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Parse a JATS XML file into a workspace folder.
    Parse {
        /// Input JATS XML file for a single paper.
        input: PathBuf,
        /// Output directory (defaults to ./<pmcid>/).
        #[arg(short, long)]
        out: Option<PathBuf>,
    },
    /// Query a parsed paper (a workspace folder or a JATS XML file).
    Query {
        #[command(subcommand)]
        query: query::Query,
    },
    /// Write the retrieval units for a parsed paper as JSON.
    Index {
        /// Workspace directory, or a JATS XML file.
        path: PathBuf,
        /// Output file (defaults to <workspace>/units.json).
        #[arg(short, long)]
        out: Option<PathBuf>,
    },
}

fn main() {
    let cli = Cli::parse();

    let result = match &cli.command {
        Command::Parse { input, out } => run_parse(input, out.as_deref()),
        Command::Query { query } => query::run(query),
        Command::Index { path, out } => run_index(path, out.as_deref()),
    };

    if let Err(message) = result {
        eprintln!("error: {message}");
        process::exit(1);
    }
}

fn run_parse(input: &std::path::Path, out: Option<&std::path::Path>) -> Result<(), String> {
    let xml = std::fs::read_to_string(input)
        .map_err(|error| format!("could not read {}: {error}", input.display()))?;

    let source = input
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| input.display().to_string());

    let paper = jats::parse(&xml, &source)?;

    // Name the folder after the PMCID when present, otherwise reuse the
    // input file's stem.
    let out_dir = match out {
        Some(path) => path.to_path_buf(),
        None => {
            let name = paper.metadata.pmcid.clone().unwrap_or_else(|| {
                input
                    .file_stem()
                    .map(|stem| stem.to_string_lossy().into_owned())
                    .unwrap_or_else(|| "paper".to_string())
            });
            PathBuf::from(name)
        }
    };

    workspace::write(&paper, input, &out_dir)?;

    println!(
        "wrote {} sections, {} figures, {} tables, {} citations to {}/",
        paper.body.sections.len(),
        paper.body.figures.len(),
        paper.body.tables.len(),
        paper.body.citations.len(),
        out_dir.display(),
    );
    Ok(())
}

fn run_index(path: &std::path::Path, out: Option<&std::path::Path>) -> Result<(), String> {
    let paper = query::load(path)?;
    let units = units::build(&paper);

    let out_path = match out {
        Some(given) => given.to_path_buf(),
        None if path.is_dir() => path.join("units.json"),
        None => PathBuf::from("units.json"),
    };

    let json = serde_json::to_string_pretty(&units)
        .map_err(|error| format!("could not serialize units: {error}"))?;
    std::fs::write(&out_path, json)
        .map_err(|error| format!("could not write {}: {error}", out_path.display()))?;

    println!("wrote {} units to {}", units.len(), out_path.display());
    Ok(())
}
