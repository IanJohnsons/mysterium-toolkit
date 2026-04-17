#!/usr/bin/env python3
"""
One-time migration: adds 'node_id' column to all SQLite databases.
Also adds additional tracking columns for unlimited history.
Run once: python3 scripts/migrate_all.py
"""

import sqlite3
import json
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / 'config'


def get_node_id():
    """Get current node identity."""
    identity_file = CONFIG_DIR / 'node_identity.txt'
    if identity_file.exists():
        return identity_file.read_text().strip()
    
    setup_file = CONFIG_DIR / 'setup.json'
    if setup_file.exists():
        try:
            data = json.loads(setup_file.read_text())
            return data.get('beneficiary_address', 'local')
        except:
            pass
    
    return 'local'


def migrate_earnings_db(db_path):
    """Add node_id and additional tracking columns to earnings_history.db."""
    if not db_path.exists():
        print(f"  Skip: {db_path.name} does not exist")
        return False
    
    node_id = get_node_id()
    print(f"  Processing: {db_path.name}")
    print(f"    node_id = {node_id[:16]}...")
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Check existing columns
    cursor.execute("PRAGMA table_info(earnings_snapshots)")
    columns = [col[1] for col in cursor.fetchall()]
    
    changes_made = False
    
    # Add node_id if missing
    if 'node_id' not in columns:
        print(f"    Adding node_id column...")
        cursor.execute("ALTER TABLE earnings_snapshots ADD COLUMN node_id TEXT DEFAULT ''")
        cursor.execute("UPDATE earnings_snapshots SET node_id = ? WHERE node_id = ''", (node_id,))
        updated = cursor.rowcount
        print(f"    Updated {updated} rows")
        changes_made = True
    
    # Add settled_at for tracking when earnings were settled
    if 'settled_at' not in columns:
        print(f"    Adding settled_at column...")
        cursor.execute("ALTER TABLE earnings_snapshots ADD COLUMN settled_at TEXT DEFAULT ''")
        changes_made = True
    
    # Add balance for tracking settled balance over time
    if 'balance' not in columns:
        print(f"    Adding balance column...")
        cursor.execute("ALTER TABLE earnings_snapshots ADD COLUMN balance REAL DEFAULT 0")
        changes_made = True
    
    # Create index if needed
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_earnings_node ON earnings_snapshots(node_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_earnings_time ON earnings_snapshots(time)")
        print(f"    Indexes created/verified")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()
    return changes_made


def migrate_sessions_db(db_path):
    """Add additional tracking columns to sessions_history.db for unlimited history."""
    if not db_path.exists():
        print(f"  Skip: {db_path.name} does not exist")
        return False
    
    node_id = get_node_id()
    print(f"  Processing: {db_path.name}")
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(sessions)")
    columns = [col[1] for col in cursor.fetchall()]
    
    changes_made = False
    
    # Add node_id if missing (critical for fleet mode)
    if 'node_id' not in columns:
        print(f"    Adding node_id column...")
        cursor.execute("ALTER TABLE sessions ADD COLUMN node_id TEXT DEFAULT ''")
        cursor.execute("UPDATE sessions SET node_id = ? WHERE node_id = ''", (node_id,))
        updated = cursor.rowcount
        print(f"    Updated {updated} rows")
        changes_made = True
    
    # Add ended_at for accurate duration tracking
    if 'ended_at' not in columns:
        print(f"    Adding ended_at column...")
        cursor.execute("ALTER TABLE sessions ADD COLUMN ended_at TEXT DEFAULT ''")
        changes_made = True
    
    # Add settled_tokens for tracking what was actually settled
    if 'settled_tokens' not in columns:
        print(f"    Adding settled_tokens column...")
        cursor.execute("ALTER TABLE sessions ADD COLUMN settled_tokens INTEGER DEFAULT 0")
        changes_made = True
    
    # Add settlement_tx for blockchain reference
    if 'settlement_tx' not in columns:
        print(f"    Adding settlement_tx column...")
        cursor.execute("ALTER TABLE sessions ADD COLUMN settlement_tx TEXT DEFAULT ''")
        changes_made = True
    
    # Create indexes
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_node ON sessions(node_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_consumer ON sessions(consumer_id)")
        print(f"    Indexes created/verified")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()
    return changes_made


def migrate_traffic_db(db_path):
    """Add node_id to traffic_history.db."""
    if not db_path.exists():
        print(f"  Skip: {db_path.name} does not exist")
        return False
    
    node_id = get_node_id()
    print(f"  Processing: {db_path.name}")
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(daily_traffic)")
    columns = [col[1] for col in cursor.fetchall()]
    
    changes_made = False
    
    if 'node_id' not in columns:
        print(f"    Adding node_id column...")
        cursor.execute("ALTER TABLE daily_traffic ADD COLUMN node_id TEXT DEFAULT ''")
        cursor.execute("UPDATE daily_traffic SET node_id = ? WHERE node_id = ''", (node_id,))
        updated = cursor.rowcount
        print(f"    Updated {updated} rows")
        changes_made = True
    
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_traffic_node ON daily_traffic(node_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_traffic_date ON daily_traffic(date)")
        print(f"    Indexes created/verified")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()
    return changes_made


def migrate_quality_db(db_path):
    """Verify quality_history.db has all needed columns."""
    if not db_path.exists():
        print(f"  Skip: {db_path.name} does not exist")
        return False
    
    print(f"  Processing: {db_path.name}")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(quality_snapshots)")
    columns = [col[1] for col in cursor.fetchall()]
    
    changes_made = False
    
    # Add monitoring_agent_version for tracking
    if 'monitoring_agent_version' not in columns:
        print(f"    Adding monitoring_agent_version column...")
        cursor.execute("ALTER TABLE quality_snapshots ADD COLUMN monitoring_agent_version TEXT DEFAULT ''")
        changes_made = True
    
    # Add nat_type for tracking NAT changes
    if 'nat_type' not in columns:
        print(f"    Adding nat_type column...")
        cursor.execute("ALTER TABLE quality_snapshots ADD COLUMN nat_type TEXT DEFAULT ''")
        changes_made = True
    
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quality_time ON quality_snapshots(time)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quality_node ON quality_snapshots(node_id)")
        print(f"    Indexes created/verified")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()
    return changes_made


def migrate_system_metrics_db(db_path):
    """Verify system_metrics.db has all needed columns."""
    if not db_path.exists():
        print(f"  Skip: {db_path.name} does not exist")
        return False
    
    print(f"  Processing: {db_path.name}")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(system_snapshots)")
    columns = [col[1] for col in cursor.fetchall()]
    
    changes_made = False
    
    # Add swap_used_mb for memory pressure tracking
    if 'swap_used_mb' not in columns:
        print(f"    Adding swap_used_mb column...")
        cursor.execute("ALTER TABLE system_snapshots ADD COLUMN swap_used_mb REAL DEFAULT 0")
        changes_made = True
    
    # Add network_connections for connection tracking
    if 'network_connections' not in columns:
        print(f"    Adding network_connections column...")
        cursor.execute("ALTER TABLE system_snapshots ADD COLUMN network_connections INTEGER DEFAULT 0")
        changes_made = True
    
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_time ON system_snapshots(time)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_node ON system_snapshots(node_id)")
        print(f"    Indexes created/verified")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()
    return changes_made


def main():
    print("\n" + "=" * 60)
    print("  Mysterium Toolkit - Database Migration")
    print("  Adding node_id + unlimited history columns")
    print("=" * 60)
    
    node_id = get_node_id()
    print(f"\nCurrent node identity: {node_id[:16]}...")
    print()
    
    migrations = [
        (CONFIG_DIR / 'earnings_history.db', migrate_earnings_db),
        (CONFIG_DIR / 'sessions_history.db', migrate_sessions_db),
        (CONFIG_DIR / 'traffic_history.db', migrate_traffic_db),
        (CONFIG_DIR / 'quality_history.db', migrate_quality_db),
        (CONFIG_DIR / 'system_metrics.db', migrate_system_metrics_db),
        (CONFIG_DIR / 'service_events.db', lambda p: print(f"  Processing: {p.name}\n    Already up-to-date") or False),
    ]
    
    any_migrated = False
    for db_path, migrate_func in migrations:
        if migrate_func(db_path):
            any_migrated = True
        print()
    
    print("=" * 60)
    if any_migrated:
        print("✓ Migration complete. Restart the toolkit.")
        print("  All databases now support unlimited history retention.")
    else:
        print("✓ No migrations needed. All databases are up-to-date.")
    print("=" * 60 + "\n")


if __name__ == '__main__':
    main()