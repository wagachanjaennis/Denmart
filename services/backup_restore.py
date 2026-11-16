import json
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.sql.sqltypes import JSON, Date, DateTime, Numeric

from extensions import db


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return {"__type__": "datetime", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"__type__": "decimal", "value": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__type__": "bytes", "value": bytes(value).hex()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    return value


def _restore_value(column, value):
    if isinstance(value, dict) and "__type__" in value:
        t = value.get("__type__")
        raw = value.get("value")
        if t == "datetime":
            return datetime.fromisoformat(raw)
        if t == "decimal":
            return Decimal(raw)
        if t == "bytes":
            return bytes.fromhex(raw)
    if value is None:
        return None
    typ = column.type
    if isinstance(typ, JSON):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return value
        return value
    if isinstance(typ, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(typ, Date) and isinstance(value, str):
        return date.fromisoformat(value)
    if isinstance(typ, Numeric) and isinstance(value, str):
        return Decimal(value)
    if getattr(typ, "python_type", None) is bool and isinstance(value, (int, str)):
        return str(value).lower() in {"1", "true", "yes", "on"}
    return value



def _usable_image_reference(value):
    """Accept safe remote/data URLs or local static files that really exist."""
    import re
    from urllib.parse import unquote

    raw = str(value or "").strip()
    if raw.startswith(("https://", "http://")):
        return True
    if re.match(r"^data:image/[a-zA-Z0-9.+-]+;base64,", raw):
        return True
    if not raw.startswith("/static/") or ".." in raw.split("?", 1)[0].split("/"):
        return False
    root = Path(__file__).resolve().parents[1] / "static"
    candidate = (root / unquote(raw.split("?", 1)[0]).removeprefix("/static/")).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return False
    return candidate.is_file() and candidate.stat().st_size > 0


def _capture_existing_product_images():
    """Keep live image references before a full database restore replaces rows."""
    try:
        from models import Product, ProductImage
        products = Product.query.all()
        images = {}
        for product in products:
            candidates = []
            if _usable_image_reference(product.image_url):
                candidates.append(str(product.image_url).strip())
            for image in ProductImage.query.filter_by(product_id=product.id).order_by(
                ProductImage.is_primary.desc(), ProductImage.sort_order.asc()
            ).all():
                if _usable_image_reference(image.image_url):
                    candidates.append(str(image.image_url).strip())
            chosen = next((url for url in candidates if url), "")
            if not chosen:
                continue
            record = {
                "barcode": str(product.barcode or "").strip(),
                "name": " ".join(str(product.name or "").split()).casefold(),
                "brand": " ".join(str(product.brand or "").split()).casefold(),
                "url": chosen,
            }
            if record["barcode"]:
                images.setdefault(("barcode", record["barcode"]), record)
            if record["name"]:
                images.setdefault(("name", record["name"], record["brand"]), record)
        return images
    except Exception:
        # Image preservation must never make an otherwise valid backup impossible.
        return {}


def _reconcile_restored_product_images(previous_images):
    """Preserve matching photos across restores and synchronize the primary image table."""
    previous_images = previous_images or {}
    from models import Product, ProductImage
    import uuid

    changed = False
    for product in Product.query.all():
        current = str(product.image_url or "").strip()
        rows = ProductImage.query.filter_by(product_id=product.id).order_by(
            ProductImage.is_primary.desc(), ProductImage.sort_order.asc()
        ).all()
        if not _usable_image_reference(current):
            # A backup may store the only valid image reference in product_images.
            current = next((str(image.image_url or "").strip() for image in rows
                            if _usable_image_reference(image.image_url)), "")
            if current:
                product.image_url = current
                changed = True
            else:
                barcode = str(product.barcode or "").strip()
                name = " ".join(str(product.name or "").split()).casefold()
                brand = " ".join(str(product.brand or "").split()).casefold()
                previous = previous_images.get(("barcode", barcode)) if barcode else None
                if not previous and name:
                    previous = previous_images.get(("name", name, brand))
                if previous and _usable_image_reference(previous.get("url")):
                    current = previous["url"]
                    product.image_url = current
                    changed = True

        # Keep the legacy product_images table in step with products.image_url.
        if _usable_image_reference(current):
            if not rows:
                db.session.add(ProductImage(
                    id=str(uuid.uuid4()), product_id=product.id,
                    image_url=current, thumbnail_url=current,
                    alt_text=product.name, source_type="RESTORE_PRESERVED",
                    license_info="Image reference preserved during database restore.",
                    sort_order=0, is_primary=True,
                ))
                changed = True
            elif not _usable_image_reference(rows[0].image_url):
                rows[0].image_url = current
                rows[0].thumbnail_url = current
                rows[0].is_primary = True
                changed = True
    if changed:
        db.session.commit()

def export_database_json():
    """Export every application table and row as a portable JSON snapshot."""
    tables = {}
    for table in db.metadata.sorted_tables:
        rows = db.session.execute(table.select()).mappings().all()
        tables[table.name] = [{k: _jsonable(v) for k, v in row.items()} for row in rows]
    return {
        "format": "denmart-database-v2",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "dialect": db.engine.url.get_backend_name(),
        "table_counts": {name: len(rows) for name, rows in tables.items()},
        "tables": tables,
    }


def _ensure_restore_schema():
    """Create missing tables and apply only the additive columns needed by this build."""
    db.create_all()
    # Existing Render/Postgres databases are not altered by create_all(). These
    # two migrations add nullable/defaulted columns and never rewrite existing rows.
    from bootstrap import _ensure_payment_columns, _ensure_storefront_order_column
    _ensure_payment_columns()
    _ensure_storefront_order_column()

    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    missing_tables = [table.name for table in db.metadata.sorted_tables
                      if not inspector.has_table(table.name)]
    if missing_tables:
        raise ValueError("The target database is missing application tables: " + ", ".join(missing_tables[:8]))

    missing_columns = []
    for table in db.metadata.sorted_tables:
        current = {column["name"] for column in inspector.get_columns(table.name)}
        absent = [column.name for column in table.columns if column.name not in current]
        if absent:
            missing_columns.append(f"{table.name}: {', '.join(absent)}")
    if missing_columns:
        raise ValueError("The target database schema is older than this application: " + "; ".join(missing_columns[:8]))


def _validate_restore_counts(tables_data, table_counts=None):
    """Reject truncated or inconsistent backup payloads before touching live data."""
    if not isinstance(tables_data, dict):
        raise ValueError("Backup table data is missing or invalid.")
    counts = table_counts if isinstance(table_counts, dict) else None
    if counts is not None:
        for name, rows in tables_data.items():
            if not isinstance(rows, list):
                raise ValueError(f"Backup table {name} is not a row list.")
            expected = counts.get(name)
            if expected is not None and int(expected) != len(rows):
                raise ValueError(f"Backup is incomplete for {name}: expected {expected} rows, found {len(rows)}.")


def restore_database_json(payload):
    """Restore a complete Denmart JSON snapshot without silently dropping data."""
    if not isinstance(payload, dict) or payload.get("format") not in {"denmart-database-v2", "real-mart-json-v1"}:
        raise ValueError("Unsupported backup format. Choose a Denmart JSON backup.")
    tables_data = payload.get("tables") or {}
    _validate_restore_counts(tables_data, payload.get("table_counts"))

    _ensure_restore_schema()
    known = {t.name: t for t in db.metadata.sorted_tables}
    missing = [name for name in known if name not in tables_data]
    if missing:
        raise ValueError("Backup is incomplete; missing application tables: " + ", ".join(missing[:8]))
    unknown = [name for name in tables_data if name not in known]
    if unknown:
        raise ValueError("Backup contains unsupported tables: " + ", ".join(unknown[:8]))

    # Preflight every column before the destructive transaction starts. Older
    # snapshots may omit only columns that are nullable or have a DB/model default.
    for table_name, rows in tables_data.items():
        table = known[table_name]
        columns = {column.name: column for column in table.columns}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"Backup contains an invalid row in {table_name}.")
            unknown_columns = set(row) - set(columns)
            if unknown_columns:
                raise ValueError(f"Backup contains unsupported columns in {table_name}: " + ", ".join(sorted(unknown_columns)[:5]))
        supplied = set().union(*(set(row) for row in rows)) if rows else set()
        required_missing = ([column.name for column in table.columns
                             if column.name not in supplied and not column.nullable
                             and not column.primary_key and column.default is None
                             and column.server_default is None] if rows else [])
        if required_missing:
            raise ValueError(f"Backup omits required fields in {table_name}: " + ", ".join(required_missing[:8]))

    previous_images = _capture_existing_product_images()
    db.session.rollback()
    dialect = db.engine.url.get_backend_name()
    if dialect == "sqlite":
        db.session.execute(text("PRAGMA foreign_keys=OFF"))
    elif dialect == "postgresql":
        names = ", ".join('"' + t.name.replace('"', '""') + '"' for t in db.metadata.sorted_tables)
        if names:
            db.session.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))

    try:
        if dialect != "postgresql":
            for table in reversed(db.metadata.sorted_tables):
                db.session.execute(table.delete())
        for table in db.metadata.sorted_tables:
            rows = tables_data.get(table.name, [])
            if not rows:
                continue
            columns = {c.name: c for c in table.columns}
            cleaned = [{k: _restore_value(columns[k], v) for k, v in raw.items()} for raw in rows]
            db.session.execute(table.insert(), cleaned)

        # Verify the restored row totals inside the same transaction, before commit.
        from sqlalchemy import func, select
        for table in db.metadata.sorted_tables:
            expected = len(tables_data.get(table.name, []))
            actual = db.session.execute(select(func.count()).select_from(table)).scalar_one()
            if actual != expected:
                raise ValueError(f"Restore verification failed for {table.name}: expected {expected}, found {actual}.")
        db.session.commit()
        _reconcile_restored_product_images(previous_images)
    except Exception:
        db.session.rollback()
        raise
    finally:
        if dialect == "sqlite":
            db.session.execute(text("PRAGMA foreign_keys=ON"))
            db.session.commit()



def _sqlite_value(column, value):
    # SQLite's SQLAlchemy Date/DateTime bind processors expect Python date/datetime
    # objects and will serialize them correctly for the target database.
    if isinstance(column.type, (DateTime, Date)) and isinstance(value, (datetime, date)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(column.type, JSON) and value is not None:
        return _jsonable(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    return value


def _stream_table_rows(connection, table, batch_size=2000):
    result = connection.execution_options(stream_results=True).execute(table.select()).mappings()
    while True:
        batch = result.fetchmany(batch_size)
        if not batch:
            break
        yield batch


def _write_backup_manifest(connection, counts, source_dialect):
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS __denmart_backup_manifest ("
        "id INTEGER PRIMARY KEY, format TEXT NOT NULL, exported_at TEXT NOT NULL, "
        "source_dialect TEXT NOT NULL, table_counts TEXT NOT NULL)"
    )
    manifest = json.dumps(counts, ensure_ascii=False, separators=(",", ":"))
    connection.exec_driver_sql(
        "INSERT INTO __denmart_backup_manifest "
        "(format, exported_at, source_dialect, table_counts) VALUES (?, ?, ?, ?)",
        ("denmart-sqlite-v3", datetime.now(timezone.utc).isoformat(), source_dialect, manifest),
    )


def create_sqlite_snapshot(path: str | Path, batch_size: int = 2000):
    """Create and verify a complete SQLite snapshot of every application table."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    source_engine = db.engine
    target_engine = create_engine(f"sqlite:///{path}", future=True)
    counts = {}
    try:
        db.metadata.create_all(target_engine)
        source_conn = db.session.connection()
        for table in db.metadata.sorted_tables:
            columns = {c.name: c for c in table.columns}
            written = 0
            with target_engine.begin() as target:
                for rows in _stream_table_rows(source_conn, table, batch_size=batch_size):
                    cleaned = [{k: _sqlite_value(columns[k], v) for k, v in row.items()} for row in rows]
                    if cleaned:
                        target.execute(table.insert(), cleaned)
                        written += len(cleaned)
            counts[table.name] = written

        with target_engine.begin() as target:
            _write_backup_manifest(target, counts, source_engine.url.get_backend_name())

        with sqlite3.connect(str(path)) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError("SQLite integrity check failed while creating the backup.")
            fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_errors:
                raise ValueError("SQLite foreign-key verification failed while creating the backup.")
            for table_name, expected in counts.items():
                quoted = table_name.replace('"', '""')
                actual = conn.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0]
                if actual != expected:
                    raise ValueError(f"SQLite backup verification failed for {table_name}.")
    finally:
        target_engine.dispose()


def inspect_sqlite_tables(path: str | Path):
    with sqlite3.connect(str(path)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE '__denmart_%' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]


def restore_sqlite_snapshot(path: str | Path, batch_size: int = 2000):
    """Restore a verified SQLite snapshot into the configured Denmart database.

    This supports snapshots made before additive columns (for example
    store_products.storefront_sort_order) were introduced. Source and target
    columns are intersected explicitly; only genuinely required missing fields
    are rejected, and row counts are verified before the transaction commits.
    """
    from sqlalchemy import MetaData, Table, func, inspect, select

    path = Path(path)
    if not path.exists() or not path.is_file():
        raise ValueError("SQLite backup file not found.")

    with sqlite3.connect(str(path)) as raw:
        integrity = raw.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("The SQLite backup failed its integrity check and was not restored.")
        fk_errors = raw.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise ValueError("The SQLite backup contains foreign-key errors and was not restored.")

    _ensure_restore_schema()
    source = create_engine(f"sqlite:///{path}")
    try:
        available = set(inspect_sqlite_tables(path))
        known = {t.name: t for t in db.metadata.sorted_tables}
        if "businesses" not in available:
            raise ValueError("This is not a Denmart database snapshot.")
        missing_tables = [name for name in known if name not in available]
        if missing_tables:
            raise ValueError(
                "SQLite backup is incomplete; missing tables: " + ", ".join(missing_tables[:8])
                + (" …" if len(missing_tables) > 8 else "")
            )
        unknown = available - set(known)
        if unknown:
            raise ValueError(
                "SQLite backup contains unsupported tables: " + ", ".join(sorted(unknown)[:8])
            )

        source_metadata = MetaData()
        source_metadata.reflect(bind=source, only=sorted(available))
        source_tables = {name: source_metadata.tables[name] for name in available}
        source_counts = {}
        insert_columns = {}
        with source.connect() as preflight_conn:
            for table_name, target_table in known.items():
                source_table = source_tables[table_name]
                source_column_names = set(source_table.c.keys())
                target_column_map = {column.name: column for column in target_table.columns}
                common = [column.name for column in target_table.columns if column.name in source_column_names]
                source_row_count = preflight_conn.execute(select(func.count()).select_from(source_table)).scalar_one()
                required_missing = ([column.name for column in target_table.columns
                                     if column.name not in source_column_names and not column.nullable
                                     and not column.primary_key and column.default is None
                                     and column.server_default is None] if source_row_count else [])
                if required_missing:
                    raise ValueError(
                        f"SQLite backup omits required fields in {table_name}: "
                        + ", ".join(required_missing[:8])
                    )
                insert_columns[table_name] = (common, target_column_map)

        previous_images = _capture_existing_product_images()
        db.session.rollback()
        dialect = db.engine.url.get_backend_name()
        if dialect == "sqlite":
            db.session.execute(text("PRAGMA foreign_keys=OFF"))
        elif dialect == "postgresql":
            names = ", ".join('"' + t.name.replace('"', '""') + '"' for t in db.metadata.sorted_tables)
            if names:
                db.session.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))

        try:
            if dialect != "postgresql":
                for table in reversed(db.metadata.sorted_tables):
                    db.session.execute(table.delete())

            target_conn = db.session.connection()
            with source.connect() as source_conn:
                for target_table in db.metadata.sorted_tables:
                    table_name = target_table.name
                    source_table = source_tables[table_name]
                    common, target_column_map = insert_columns[table_name]
                    count = source_conn.execute(select(func.count()).select_from(source_table)).scalar_one()
                    source_counts[table_name] = int(count)
                    if not common or not count:
                        continue
                    statement = select(*(source_table.c[name] for name in common))
                    result = source_conn.execution_options(stream_results=True).execute(statement).mappings()
                    while True:
                        rows = result.fetchmany(batch_size)
                        if not rows:
                            break
                        cleaned = [
                            {name: _restore_value(target_column_map[name], row[name]) for name in common}
                            for row in rows
                        ]
                        target_conn.execute(target_table.insert(), cleaned)

            # Verify every imported table before committing. A failure rolls back
            # the truncate/delete and all inserts as one transaction.
            for table in db.metadata.sorted_tables:
                expected = source_counts.get(table.name, 0)
                actual = db.session.execute(select(func.count()).select_from(table)).scalar_one()
                if actual != expected:
                    raise ValueError(
                        f"SQLite restore verification failed for {table.name}: expected {expected}, found {actual}."
                    )
            db.session.commit()
            _reconcile_restored_product_images(previous_images)
        except Exception:
            db.session.rollback()
            raise
        finally:
            if dialect == "sqlite":
                db.session.execute(text("PRAGMA foreign_keys=ON"))
                db.session.commit()
    finally:
        source.dispose()

