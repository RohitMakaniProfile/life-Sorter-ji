#!/usr/bin/env python3
"""
Production Database Migration Script
Applies all pending migrations to the production database
"""

import asyncio
import sys
from pathlib import Path

import asyncpg

# Production database URL (using postgres superuser for schema modifications)
PROD_DATABASE_URL = "postgresql://postgres:pgadminikshan23@35.200.170.233:5432/ikshan-prod"

# Migration files in order
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
MIGRATION_FILES = [
    "add_scraped_pages.sql",
    "add_scraped_page_ids_to_onboarding.sql",
    "add_crawl_logs.sql",
    "add_token_usage_columns.sql",
]


async def run_migration(conn: asyncpg.Connection, sql_file: Path) -> None:
    """Run a single migration file."""
    print(f"\n{'='*60}")
    print(f"Running migration: {sql_file.name}")
    print(f"{'='*60}")

    sql = sql_file.read_text()

    try:
        # Execute the migration
        await conn.execute(sql)
        print(f"✅ SUCCESS: {sql_file.name} applied successfully")
    except Exception as e:
        print(f"❌ ERROR in {sql_file.name}: {e}")
        raise


async def main():
    """Main migration runner."""
    print("=" * 60)
    print("PRODUCTION DATABASE MIGRATION")
    print("=" * 60)
    print(f"\nTarget Database: ikshan-prod @ 35.200.170.233:5432")
    print(f"Migrations Directory: {MIGRATIONS_DIR}")
    print(f"\nMigrations to apply ({len(MIGRATION_FILES)}):")
    for i, mig in enumerate(MIGRATION_FILES, 1):
        print(f"  {i}. {mig}")

    # Confirm before proceeding
    print("\n⚠️  WARNING: This will modify the PRODUCTION database!")
    response = input("\nDo you want to proceed? (yes/no): ").strip().lower()

    if response != "yes":
        print("\n❌ Migration cancelled by user")
        return 1

    # Connect to production database
    print("\n📡 Connecting to production database...")
    try:
        conn = await asyncpg.connect(PROD_DATABASE_URL)
        print("✅ Connected successfully")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return 1

    try:
        # Run each migration
        for migration_file_name in MIGRATION_FILES:
            migration_path = MIGRATIONS_DIR / migration_file_name

            if not migration_path.exists():
                print(f"⚠️  WARNING: Migration file not found: {migration_file_name}")
                continue

            await run_migration(conn, migration_path)

        print("\n" + "=" * 60)
        print("✅ ALL MIGRATIONS COMPLETED SUCCESSFULLY")
        print("=" * 60)

        return 0

    except Exception as e:
        print("\n" + "=" * 60)
        print(f"❌ MIGRATION FAILED: {e}")
        print("=" * 60)
        return 1

    finally:
        await conn.close()
        print("\n📡 Database connection closed")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

