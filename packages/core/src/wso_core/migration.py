"""Select an Alembic connection target without an implicit online database."""


def migration_database_url(
    explicit_url: str | None, environment_url: str | None, *, offline: bool
) -> str:
    url = explicit_url or environment_url
    if url:
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("migrations require postgresql+psycopg")
        return url
    if offline:
        return "postgresql+psycopg:///offline-sql-only"
    raise RuntimeError(
        "WSO_MIGRATION_DATABASE_URL or an explicit Alembic URL is required"
    )
