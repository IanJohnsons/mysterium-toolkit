"""
Centralized Data Management for all persistent storage.
Unified interface for delete, export, stats, and node_id management.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import logging
import sys

sys.path.insert(0, str(Path(__file__).parent))

try:
    from databases.quality_db import QualityDB
except ImportError:
    QualityDB = None

try:
    from databases.system_metrics_db import SystemMetricsDB
except ImportError:
    SystemMetricsDB = None

try:
    from databases.service_events_db import ServiceEventsDB
except ImportError:
    ServiceEventsDB = None

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent.parent / 'config'


class DataManager:
    """Unified data management for all storage backends."""

    @staticmethod
    def _connect(db_path) -> sqlite3.Connection:
        """Open a SQLite connection with proper timeout settings.

        WAL mode is set where possible — silently skipped on read-only databases.
        busy_timeout is a session setting and never requires write access.
        """
        conn = sqlite3.connect(str(db_path), timeout=10)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        try:
            conn.execute("PRAGMA busy_timeout=10000")
        except Exception:
            pass
        return conn

    @staticmethod
    def _get_node_id() -> str:
        """Get current node identity.

        Priority:
        1. config/node_identity.txt  — written by the slow-tier collector from the live API
        2. sessions_history.db       — most recent provider_id stored in sessions
        3. Return '' (empty)         — never returns 'local' or a beneficiary address,
                                       because those would cause delete WHERE node_id='local'
                                       which silently deletes 0 rows.
        """
        identity_file = CONFIG_DIR / 'node_identity.txt'
        if identity_file.exists():
            val = identity_file.read_text().strip()
            if val and val.lower().startswith('0x') and len(val) > 10:
                return val

        # Fallback: read from sessions DB — most recent provider_id written by the collector
        try:
            db_path = CONFIG_DIR / 'sessions_history.db'
            if db_path.exists():
                conn = DataManager._connect(db_path)
                row = conn.execute(
                    "SELECT provider_id FROM sessions "
                    "WHERE provider_id != '' AND provider_id IS NOT NULL "
                    "ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                conn.close()
                if row and row[0] and row[0].lower().startswith('0x') and len(row[0]) > 10:
                    return row[0]
        except Exception:
            pass

        return ''
    
    @staticmethod
    def get_all_stats(node_id: Optional[str] = None) -> Dict[str, Any]:
        """Return consolidated stats from ALL databases."""
        if node_id is None:
            node_id = DataManager._get_node_id()
        
        stats = {
            'node_id': node_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'databases': {}
        }
        
        stats['databases']['earnings'] = DataManager._get_earnings_stats(node_id)
        stats['databases']['traffic'] = DataManager._get_traffic_stats(node_id)
        stats['databases']['sessions'] = DataManager._get_sessions_stats(node_id)
        
        if QualityDB:
            stats['databases']['quality'] = QualityDB.get_stats(node_id)
        else:
            stats['databases']['quality'] = {'exists': False, 'total': 0}
        
        if SystemMetricsDB:
            stats['databases']['system'] = SystemMetricsDB.get_stats(node_id)
        else:
            stats['databases']['system'] = {'exists': False, 'total': 0}
        
        if ServiceEventsDB:
            stats['databases']['services'] = ServiceEventsDB.get_stats(node_id)
        else:
            stats['databases']['services'] = {'exists': False, 'total': 0}
        
        stats['databases']['uptime'] = DataManager._get_uptime_stats()
        
        total_records = sum(
            db.get('total', 0) 
            for db in stats['databases'].values() 
            if isinstance(db, dict)
        )
        stats['total_records'] = total_records
        
        return stats
    
    @staticmethod
    def _get_earnings_stats(node_id: str) -> Dict[str, Any]:
        db_path = CONFIG_DIR / 'earnings_history.db'
        if not db_path.exists():
            return {'total': 0, 'oldest': None, 'newest': None, 'exists': False}
        
        conn = DataManager._connect(db_path)
        conn.row_factory = sqlite3.Row
        
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(earnings_snapshots)")
        columns = [col[1] for col in cursor.fetchall()]
        has_node_id = 'node_id' in columns
        
        if has_node_id and node_id:
            row = conn.execute(
                "SELECT COUNT(*) as total, MIN(time) as oldest, MAX(time) as newest "
                "FROM earnings_snapshots WHERE node_id = ?",
                (node_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as total, MIN(time) as oldest, MAX(time) as newest "
                "FROM earnings_snapshots"
            ).fetchone()
        
        conn.close()
        
        return {
            'total': row['total'] if row else 0,
            'oldest': row['oldest'][:10] if row and row['oldest'] else None,
            'newest': row['newest'][:10] if row and row['newest'] else None,
            'exists': True,
        }
    
    @staticmethod
    def _get_traffic_stats(node_id: str) -> Dict[str, Any]:
        db_path = CONFIG_DIR / 'traffic_history.db'
        if not db_path.exists():
            return {'total': 0, 'oldest': None, 'newest': None, 'exists': False}
        
        conn = DataManager._connect(db_path)
        conn.row_factory = sqlite3.Row
        
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(daily_traffic)")
        columns = [col[1] for col in cursor.fetchall()]
        has_node_id = 'node_id' in columns
        
        if has_node_id and node_id:
            row = conn.execute(
                "SELECT COUNT(*) as total, MIN(date) as oldest, MAX(date) as newest "
                "FROM daily_traffic WHERE node_id = ?",
                (node_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as total, MIN(date) as oldest, MAX(date) as newest "
                "FROM daily_traffic"
            ).fetchone()
        
        conn.close()
        
        return {
            'total': row['total'] if row else 0,
            'oldest': row['oldest'] if row and row['oldest'] else None,
            'newest': row['newest'] if row and row['newest'] else None,
            'exists': True,
        }
    
    @staticmethod
    def _get_sessions_stats(node_id: str) -> Dict[str, Any]:
        db_path = CONFIG_DIR / 'sessions_history.db'
        if not db_path.exists():
            return {'total': 0, 'oldest': None, 'newest': None, 'exists': False}
        
        conn = DataManager._connect(db_path)
        conn.row_factory = sqlite3.Row
        
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(sessions)")
        columns = [col[1] for col in cursor.fetchall()]
        has_node_id = 'node_id' in columns
        has_provider_id = 'provider_id' in columns
        
        if has_node_id and node_id:
            where_clause = "WHERE node_id = ?"
            params = (node_id,)
        elif has_provider_id and node_id:
            where_clause = "WHERE provider_id = ?"
            params = (node_id,)
        else:
            where_clause = ""
            params = ()
        
        row = conn.execute(
            f"SELECT COUNT(*) as total, MIN(started_at) as oldest, MAX(started_at) as newest "
            f"FROM sessions {where_clause}",
            params
        ).fetchone()
        
        conn.close()
        
        return {
            'total': row['total'] if row else 0,
            'oldest': row['oldest'][:10] if row and row['oldest'] else None,
            'newest': row['newest'][:10] if row and row['newest'] else None,
            'exists': True,
        }
    
    @staticmethod
    def _get_uptime_stats() -> Dict[str, Any]:
        uptime_file = CONFIG_DIR / 'uptime_log.json'
        if not uptime_file.exists():
            return {'total': 0, 'exists': False}
        
        try:
            data = json.loads(uptime_file.read_text())
            if isinstance(data, list) and data:
                return {
                    'total': len(data),
                    'oldest': datetime.fromtimestamp(data[0]).isoformat() if data else None,
                    'newest': datetime.fromtimestamp(data[-1]).isoformat() if data else None,
                    'exists': True,
                }
        except:
            pass
        
        return {'total': 0, 'exists': False}
    
    @staticmethod
    def delete_range(
        data_type: str,
        node_id: Optional[str] = None,
        keep_days: Optional[int] = None,
        before_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delete data of specified type."""
        if node_id is None:
            node_id = DataManager._get_node_id()
        
        results = {}
        
        if data_type in ('earnings', 'all'):
            results['earnings'] = DataManager._delete_earnings(node_id, keep_days, before_date)
        
        if data_type in ('traffic', 'all'):
            results['traffic'] = DataManager._delete_traffic(node_id, keep_days, before_date)
        
        if data_type in ('sessions', 'all'):
            results['sessions'] = DataManager._delete_sessions(node_id, keep_days, before_date)
        
        if data_type in ('quality', 'all') and QualityDB:
            results['quality'] = QualityDB.delete_range(node_id, keep_days, before_date)
        
        if data_type in ('system', 'all') and SystemMetricsDB:
            results['system'] = SystemMetricsDB.delete_range(node_id, keep_days, before_date)
        
        if data_type in ('services', 'all') and ServiceEventsDB:
            results['services'] = ServiceEventsDB.delete_range(node_id, keep_days, before_date)
        
        if data_type in ('uptime', 'all'):
            results['uptime'] = DataManager._delete_uptime(keep_days, before_date)
        
        return {
            'success': True,
            'data_type': data_type,
            'node_id': node_id,
            'results': results,
        }
    
    @staticmethod
    def _delete_earnings(node_id: str, keep_days: Optional[int], before_date: Optional[str]) -> Dict[str, Any]:
        db_path = CONFIG_DIR / 'earnings_history.db'
        if not db_path.exists():
            return {'deleted': 0, 'remaining': 0, 'error': 'Database does not exist'}
        
        conn = DataManager._connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(earnings_snapshots)")
        columns = [col[1] for col in cursor.fetchall()]
        has_node_id = 'node_id' in columns
        
        conditions = []
        params = []
        
        if keep_days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
            conditions.append("time < ?")
            params.append(cutoff)
        elif before_date is not None:
            conditions.append("time < ?")
            params.append(before_date)
        
        _valid_id = node_id and node_id.lower().startswith('0x') and len(node_id) > 10
        if has_node_id and _valid_id:
            conditions.append("node_id = ?")
            params.append(node_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        cursor.execute(f"DELETE FROM earnings_snapshots WHERE {where_clause}", params)
        deleted = cursor.rowcount

        if has_node_id and _valid_id:
            cursor.execute("SELECT COUNT(*) FROM earnings_snapshots WHERE node_id = ?", (node_id,))
        else:
            cursor.execute("SELECT COUNT(*) FROM earnings_snapshots")
        remaining = cursor.fetchone()[0]
        
        conn.commit()
        conn.close()
        
        return {'deleted': deleted, 'remaining': remaining}
    
    @staticmethod
    def _delete_traffic(node_id: str, keep_days: Optional[int], before_date: Optional[str]) -> Dict[str, Any]:
        db_path = CONFIG_DIR / 'traffic_history.db'
        if not db_path.exists():
            return {'deleted': 0, 'remaining': 0, 'error': 'Database does not exist'}
        
        conn = DataManager._connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(daily_traffic)")
        columns = [col[1] for col in cursor.fetchall()]
        has_node_id = 'node_id' in columns
        
        conditions = []
        params = []
        
        if keep_days is not None:
            cutoff = (datetime.now() - timedelta(days=keep_days)).strftime('%Y-%m-%d')
            conditions.append("date < ?")
            params.append(cutoff)
        elif before_date is not None:
            conditions.append("date < ?")
            params.append(before_date)
        
        _valid_id = node_id and node_id.lower().startswith('0x') and len(node_id) > 10
        if has_node_id and _valid_id:
            conditions.append("node_id = ?")
            params.append(node_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        cursor.execute(f"DELETE FROM daily_traffic WHERE {where_clause}", params)
        deleted = cursor.rowcount

        if has_node_id and _valid_id:
            cursor.execute("SELECT COUNT(*) FROM daily_traffic WHERE node_id = ?", (node_id,))
        else:
            cursor.execute("SELECT COUNT(*) FROM daily_traffic")
        remaining = cursor.fetchone()[0]
        
        conn.commit()
        conn.close()
        
        return {'deleted': deleted, 'remaining': remaining}
    
    @staticmethod
    def _delete_sessions(node_id: str, keep_days: Optional[int], before_date: Optional[str]) -> Dict[str, Any]:
        db_path = CONFIG_DIR / 'sessions_history.db'
        if not db_path.exists():
            return {'deleted': 0, 'remaining': 0, 'error': 'Database does not exist'}
        
        conn = DataManager._connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(sessions)")
        columns = [col[1] for col in cursor.fetchall()]
        has_node_id = 'node_id' in columns
        has_provider_id = 'provider_id' in columns
        
        conditions = []
        params = []
        
        if keep_days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
            conditions.append("started_at < ?")
            params.append(cutoff)
        elif before_date is not None:
            conditions.append("started_at < ?")
            params.append(before_date)
        
        _valid_id = node_id and node_id.lower().startswith('0x') and len(node_id) > 10
        if has_node_id and _valid_id:
            conditions.append("node_id = ?")
            params.append(node_id)
        elif has_provider_id and _valid_id:
            conditions.append("provider_id = ?")
            params.append(node_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        cursor.execute(f"DELETE FROM sessions WHERE {where_clause}", params)
        deleted = cursor.rowcount

        if has_node_id and _valid_id:
            cursor.execute("SELECT COUNT(*) FROM sessions WHERE node_id = ?", (node_id,))
        elif has_provider_id and _valid_id:
            cursor.execute("SELECT COUNT(*) FROM sessions WHERE provider_id = ?", (node_id,))
        else:
            cursor.execute("SELECT COUNT(*) FROM sessions")
        remaining = cursor.fetchone()[0]
        
        conn.commit()
        conn.close()
        
        return {'deleted': deleted, 'remaining': remaining}
    
    @staticmethod
    def _delete_uptime(keep_days: Optional[int], before_date: Optional[str]) -> Dict[str, Any]:
        uptime_file = CONFIG_DIR / 'uptime_log.json'
        identity_file = CONFIG_DIR / 'node_identity.txt'
        
        if not uptime_file.exists():
            return {'deleted': 0}
        
        try:
            data = json.loads(uptime_file.read_text())
            
            if keep_days is not None or before_date is not None:
                if keep_days is not None:
                    cutoff_ts = (datetime.now() - timedelta(days=keep_days)).timestamp()
                else:
                    cutoff_ts = datetime.fromisoformat(before_date).timestamp()
                
                new_data = [t for t in data if t >= cutoff_ts]
                deleted = len(data) - len(new_data)
                uptime_file.write_text(json.dumps(new_data))
            else:
                uptime_file.unlink()
                if identity_file.exists():
                    identity_file.unlink()
                deleted = len(data)
            
            return {'deleted': deleted}
        except:
            return {'deleted': 0, 'error': 'Failed to process uptime log'}