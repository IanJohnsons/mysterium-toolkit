"""
System Metrics History Database
Stores CPU, RAM, disk, and temperature snapshots.
"""

import sqlite3
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from threading import Lock
import logging

logger = logging.getLogger(__name__)


class SystemMetricsDB:
    """Persistent storage for system resource metrics."""
    
    _db_path = Path(__file__).parent.parent.parent / 'config' / 'system_metrics.db'
    _initialized = False
    _lock = Lock()
    
    @classmethod
    def _conn(cls):
        conn = sqlite3.connect(str(cls._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    
    @classmethod
    def init(cls):
        """Create table if it doesn't exist."""
        if cls._initialized:
            return
        cls._db_path.parent.mkdir(parents=True, exist_ok=True)
        with cls._lock:
            try:
                conn = cls._conn()
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS system_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        time TEXT NOT NULL,
                        cpu_pct REAL,
                        ram_pct REAL,
                        disk_pct REAL,
                        cpu_temp REAL,
                        load_avg_1 REAL,
                        load_avg_5 REAL,
                        load_avg_15 REAL,
                        node_id TEXT DEFAULT '',
                        tunnel_count INTEGER,
                        node_speed_mbps REAL,
                        sys_speed_mbps REAL,
                        latency_ms REAL,
                        ambient_temp REAL,
                        ram_temp REAL,
                        UNIQUE(time, node_id)
                    )
                """)
                # Migrate existing databases — add new columns if missing
                for col, coltype in [
                    ('tunnel_count',    'INTEGER'),
                    ('node_speed_mbps', 'REAL'),
                    ('sys_speed_mbps',  'REAL'),
                    ('latency_ms',      'REAL'),
                    ('ambient_temp',    'REAL'),
                    ('ram_temp',        'REAL'),
                ]:
                    try:
                        conn.execute(f"ALTER TABLE system_snapshots ADD COLUMN {col} {coltype}")
                    except Exception:
                        pass  # Column already exists
                conn.execute("CREATE INDEX IF NOT EXISTS idx_system_time ON system_snapshots(time)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_system_node ON system_snapshots(node_id)")
                conn.commit()
                conn.close()
                cls._initialized = True
                logger.info("SystemMetricsDB initialized")
            except Exception as e:
                logger.warning(f"SystemMetricsDB init failed: {e}")
    
    @classmethod
    def record(cls, resources_data, node_id='', performance_data=None):
        """Record a system metrics snapshot."""
        cls.init()
        
        now = datetime.now(timezone.utc).isoformat()
        
        load_avg_1 = load_avg_5 = load_avg_15 = None
        try:
            if hasattr(os, 'getloadavg'):
                load_avg_1, load_avg_5, load_avg_15 = os.getloadavg()
        except:
            pass

        # Extract extra temps from all_temps list
        ambient_temp = None
        ram_temp = None
        for t in (resources_data.get('all_temps') or []):
            lbl = t.get('label', '').lower()
            val = t.get('value')
            if val is None:
                continue
            if 'ambient' in lbl or 'board' in lbl or 'acpi' in lbl:
                ambient_temp = val
            elif lbl in ('ram', 'sodimm') or 'dimm' in lbl or 'mem' in lbl:
                ram_temp = val

        # Extract tunnel/speed/latency from performance_data
        tunnel_count    = None
        node_speed_mbps = None
        sys_speed_mbps  = None
        latency_ms      = None
        if performance_data:
            tunnel_count    = performance_data.get('tunnel_count')
            node_speed_mbps = performance_data.get('speed_total')
            sys_speed_mbps  = performance_data.get('sys_speed_total')
            latency_ms      = performance_data.get('latency_ms')
        
        with cls._lock:
            try:
                conn = cls._conn()
                conn.execute("""
                    INSERT OR REPLACE INTO system_snapshots 
                    (time, cpu_pct, ram_pct, disk_pct, cpu_temp,
                     load_avg_1, load_avg_5, load_avg_15, node_id,
                     tunnel_count, node_speed_mbps, sys_speed_mbps,
                     latency_ms, ambient_temp, ram_temp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    now,
                    resources_data.get('cpu'),
                    resources_data.get('ram'),
                    resources_data.get('disk'),
                    resources_data.get('cpu_temp'),
                    load_avg_1,
                    load_avg_5,
                    load_avg_15,
                    node_id,
                    tunnel_count,
                    node_speed_mbps,
                    sys_speed_mbps,
                    latency_ms,
                    ambient_temp,
                    ram_temp,
                ))
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                logger.warning(f"SystemMetricsDB record failed: {e}")
                return False
    
    @classmethod
    def get_history(cls, days_back=7, node_id=None):
        """Get system metrics history for charting."""
        cls.init()
        try:
            conn = cls._conn()
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
            
            if node_id:
                rows = conn.execute("""
                    SELECT * FROM system_snapshots 
                    WHERE time >= ? AND (node_id = ? OR node_id = '')
                    ORDER BY time ASC
                """, (cutoff, node_id)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM system_snapshots 
                    WHERE time >= ?
                    ORDER BY time ASC
                """, (cutoff,)).fetchall()
            
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"SystemMetricsDB get_history failed: {e}")
            return []
    
    @classmethod
    def get_stats(cls, node_id=None):
        """Get summary statistics."""
        cls.init()
        try:
            conn = cls._conn()
            
            if node_id:
                row = conn.execute("""
                    SELECT 
                        COUNT(*) as total,
                        MIN(time) as oldest,
                        MAX(time) as newest,
                        AVG(cpu_pct) as avg_cpu,
                        MAX(cpu_pct) as max_cpu,
                        AVG(ram_pct) as avg_ram,
                        MAX(ram_pct) as max_ram,
                        AVG(cpu_temp) as avg_temp,
                        MAX(cpu_temp) as max_temp
                    FROM system_snapshots 
                    WHERE (node_id = ? OR node_id = '')
                """, (node_id,)).fetchone()
            else:
                row = conn.execute("""
                    SELECT 
                        COUNT(*) as total,
                        MIN(time) as oldest,
                        MAX(time) as newest,
                        AVG(cpu_pct) as avg_cpu,
                        MAX(cpu_pct) as max_cpu,
                        AVG(ram_pct) as avg_ram,
                        MAX(ram_pct) as max_ram,
                        AVG(cpu_temp) as avg_temp,
                        MAX(cpu_temp) as max_temp
                    FROM system_snapshots
                """).fetchone()
            
            conn.close()
            
            if row:
                return {
                    'total': row['total'] or 0,
                    'oldest': row['oldest'][:10] if row['oldest'] else None,
                    'newest': row['newest'][:10] if row['newest'] else None,
                    'avg_cpu': round(row['avg_cpu'], 1) if row['avg_cpu'] else None,
                    'max_cpu': round(row['max_cpu'], 1) if row['max_cpu'] else None,
                    'avg_ram': round(row['avg_ram'], 1) if row['avg_ram'] else None,
                    'max_ram': round(row['max_ram'], 1) if row['max_ram'] else None,
                    'avg_temp': round(row['avg_temp'], 1) if row['avg_temp'] else None,
                    'max_temp': round(row['max_temp'], 1) if row['max_temp'] else None,
                    'exists': True,
                }
        except Exception as e:
            logger.warning(f"SystemMetricsDB get_stats failed: {e}")
        
        return {'total': 0, 'oldest': None, 'newest': None, 'exists': False}
    
    @classmethod
    def delete_range(cls, node_id=None, keep_days=None, before_date=None):
        """Delete system metrics snapshots."""
        cls.init()
        try:
            conn = cls._conn()
            
            conditions = []
            params = []
            
            if keep_days is not None:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
                conditions.append("time < ?")
                params.append(cutoff)
            elif before_date is not None:
                conditions.append("time < ?")
                params.append(before_date)
            
            if node_id:
                conditions.append("node_id = ?")
                params.append(node_id)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            cursor = conn.execute(f"DELETE FROM system_snapshots WHERE {where_clause}", params)
            deleted = cursor.rowcount
            
            if node_id:
                cursor.execute("SELECT COUNT(*) FROM system_snapshots WHERE node_id = ?", (node_id,))
            else:
                cursor.execute("SELECT COUNT(*) FROM system_snapshots")
            remaining = cursor.fetchone()[0]
            
            conn.commit()
            conn.close()
            
            return {'deleted': deleted, 'remaining': remaining}
        except Exception as e:
            logger.warning(f"SystemMetricsDB delete_range failed: {e}")
            return {'deleted': 0, 'remaining': 0, 'error': str(e)}