use std::path::PathBuf;
use std::process;

use clap::{Parser, Subcommand};

mod jats;
mod model;
mod workspace;

/// convert jats xml paper into a IR
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
}

fn main() {
    let cli = Cli::parse();

    let result = match &cli.command {
        Command::Parse { input, out } => run_parse(input, out.as_deref()),
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
