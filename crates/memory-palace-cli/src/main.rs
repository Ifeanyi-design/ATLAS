use anyhow::{Context, Result, bail};
use clap::{Parser, Subcommand};
use memory_palace_daemon::serve;
use memory_palace_sqlite::Storage;
use std::env;
use std::path::{Path, PathBuf};

#[derive(Parser)]
#[command(
    name = "memory-palace",
    version,
    about = "Local-first persistent memory for Hermes Agent"
)]
struct Cli {
    /// Override the Memory Palace data directory.
    #[arg(long, global = true)]
    home: Option<PathBuf>,
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Initialize the local SQLite database and runtime directories.
    Init,
    /// Run the local Unix-socket daemon.
    Serve,
    /// Verify paths and required SQLite capabilities.
    Doctor,
    /// Show local database record counts.
    Status,
    /// Search active decisions in one project.
    Search {
        query: String,
        #[arg(long)]
        project: Option<String>,
        #[arg(long, default_value_t = 10)]
        limit: usize,
    },
}

#[derive(Debug)]
struct Paths {
    home: PathBuf,
    database: PathBuf,
    socket: PathBuf,
    logs: PathBuf,
}

impl Paths {
    fn discover(override_home: Option<PathBuf>) -> Result<Self> {
        let home = if let Some(path) = override_home {
            path
        } else if let Some(path) = env::var_os("MEMORY_PALACE_HOME") {
            PathBuf::from(path)
        } else if let Some(path) = env::var_os("HERMES_HOME") {
            PathBuf::from(path).join("memory-palace")
        } else if let Some(path) = env::var_os("XDG_DATA_HOME") {
            PathBuf::from(path).join("hermes/memory-palace")
        } else if let Some(path) = env::var_os("HOME") {
            PathBuf::from(path).join(".local/share/hermes/memory-palace")
        } else {
            bail!("set HERMES_HOME or MEMORY_PALACE_HOME to choose a data directory")
        };
        Ok(Self {
            database: home.join("memory-palace.sqlite3"),
            socket: home.join("run/memory-palace.sock"),
            logs: home.join("log"),
            home,
        })
    }

    fn initialize_dirs(&self) -> Result<()> {
        std::fs::create_dir_all(&self.logs)?;
        if let Some(parent) = self.socket.parent() {
            std::fs::create_dir_all(parent)?;
        }
        Ok(())
    }
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let paths = Paths::discover(cli.home)?;
    match cli.command {
        Command::Init => {
            paths.initialize_dirs()?;
            let storage = Storage::open(&paths.database)?;
            let journal = storage.configure_wal()?;
            println!(
                "initialized {} (journal_mode={journal})",
                paths.database.display()
            );
        }
        Command::Serve => {
            paths.initialize_dirs()?;
            let storage = Storage::open(&paths.database)?;
            storage.configure_wal()?;
            println!("memory-palace listening on {}", paths.socket.display());
            serve(storage, &paths.socket)?;
        }
        Command::Doctor => {
            paths.initialize_dirs()?;
            let storage = Storage::open(&paths.database)?;
            let journal = storage.configure_wal()?;
            let report = storage.doctor()?;
            println!("home: {}", paths.home.display());
            println!("database: {}", paths.database.display());
            println!("socket: {}", paths.socket.display());
            println!("SQLite: {}", report.sqlite_version);
            println!("journal_mode: {journal}");
            println!("foreign_keys: {}", pass(report.foreign_keys));
            println!("FTS5: {}", pass(report.fts5));
            println!("schema migration: {}", report.migration_version);
            if !report.foreign_keys || !report.fts5 || report.migration_version < 1 {
                bail!("required SQLite capabilities are unavailable");
            }
        }
        Command::Status => {
            let storage = Storage::open(&paths.database)
                .with_context(|| format!("open {}", paths.database.display()))?;
            let status = storage.status()?;
            println!("database: {}", paths.database.display());
            println!("projects: {}", status.projects);
            println!("decisions: {}", status.decisions);
            println!("turns: {}", status.turns);
            println!("tool events: {}", status.tool_events);
            println!("checkpoints: {}", status.checkpoints);
        }
        Command::Search {
            query,
            project,
            limit,
        } => {
            let storage = Storage::open(&paths.database)?;
            let project_name = project.unwrap_or_else(resolve_project_name);
            let project = storage.resolve_project(&project_name)?;
            let hits = storage.search_decisions(&project.id, &query, limit)?;
            println!("{}", serde_json::to_string_pretty(&hits)?);
        }
    }
    Ok(())
}

fn pass(value: bool) -> &'static str {
    if value { "ok" } else { "missing" }
}

fn resolve_project_name() -> String {
    if let Ok(project) = env::var("MEMORY_PALACE_PROJECT")
        && !project.trim().is_empty()
    {
        return project;
    }
    let current = env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    repository_root(&current)
        .or(Some(current.as_path()))
        .and_then(Path::file_name)
        .and_then(|name| name.to_str())
        .unwrap_or("default")
        .to_owned()
}

fn repository_root(start: &Path) -> Option<&Path> {
    start.ancestors().find(|path| path.join(".git").exists())
}
