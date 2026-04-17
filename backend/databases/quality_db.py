"""
Node Quality History Database
Stores daily snapshots from Mysterium Discovery API.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from threading import Lock
import logging

logger = logging.getLogger(__name__)


class QualityDB:
    """Persistent storage for node quality metrics from Discovery API."""
    
    _db_path = Path(__file__).parent.parent.parent / 'config' / 'quality_history.db'
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
                    CREATE TABLE IF NOT EXISTS quality_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        time TEXT NOT NULL,
                        quality_score REAL,
                        latency_ms REAL,
                        bandwidth_mbps REAL,
                        uptime_24h_net REAL,
                        packet_loss_net REAL,
                        monitoring_failed INTEGER DEFAULT 0,
                        node_id TEXT DEFAULT '',
                        wallet_address TEXT DEFAULT '',
                        nat_type TEXT DEFAULT '',
                        UNIQUE(time, node_id)
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_quality_time ON quality_snapshots(time)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_quality_node ON quality_snapshots(node_id)")
                conn.commit()
                conn.close()
                cls._initialized = True
                logger.info("QualityDB initialized")
            except Exception as e:
                logger.warning(f"QualityDB init failed: {e}")
    
    @classmethod
    def record(cls, quality_data, node_id='', wallet_address='', nat_type=''):
        """Record a quality snapshot."""
        cls.init()
        if not quality_data or not quality_data.get('available'):
            return False
        
        now = datetime.now(timezone.utc).isoformat()
        
        with cls._lock:
            try:
                conn = cls._conn()
                conn.execute("""
                    INSERT OR REPLACE INTO quality_snapshots 
                    (time, quality_score, latency_ms, bandwidth_mbps, uptime_24h_net, 
                     packet_loss_net, monitoring_failed, node_id, wallet_address, nat_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    now,
                    quality_data.get('quality_score'),
                    quality_data.get('latency_ms'),
                    quality_data.get('bandwidth_mbps'),
                    quality_data.get('uptime_24h_net'),
                    quality_data.get('packet_loss_net'),
                    1 if quality_data.get('monitoring_failed') else 0,
                    node_id,
                    wallet_address,
                    nat_type or '',
                ))
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                logger.warning(f"QualityDB record failed: {e}")
                return False
    
    @classmethod
    def get_history(cls, days_back=30, node_id=None):
        """Get quality history for charting."""
        cls.init()
        try:
            conn = cls._conn()
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
            
            if node_id:
                rows = conn.execute("""
                    SELECT * FROM quality_snapshots 
                    WHERE time >= ? AND node_id = ?
                    ORDER BY time ASC
                """, (cutoff, node_id)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM quality_snapshots 
                    WHERE time >= ?
                    ORDER BY time ASC
                """, (cutoff,)).fetchall()
            
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"QualityDB get_history failed: {e}")
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
                        AVG(quality_score) as avg_quality,
                        AVG(latency_ms) as avg_latency,
                        AVG(bandwidth_mbps) as avg_bandwidth
                    FROM quality_snapshots 
                    WHERE node_id = ?
                """, (node_id,)).fetchone()
            else:
                row = conn.execute("""
                    SELECT 
                        COUNT(*) as total,
                        MIN(time) as oldest,
                        MAX(time) as newest,
                        AVG(quality_score) as avg_quality,
                        AVG(latency_ms) as avg_latency,
                        AVG(bandwidth_mbps) as avg_bandwidth
                    FROM quality_snapshots
                """).fetchone()
            
            conn.close()
            
            if row:
                return {
                    'total': row['total'] or 0,
                    'oldest': row['oldest'][:10] if row['oldest'] else None,
                    'newest': row['newest'][:10] if row['newest'] else None,
                    'avg_quality': round(row['avg_quality'], 2) if row['avg_quality'] else None,
                    'avg_latency': round(row['avg_latency'], 1) if row['avg_latency'] else None,
                    'avg_bandwidth': round(row['avg_bandwidth'], 1) if row['avg_bandwidth'] else None,
                    'exists': True,
                }
        except Exception as e:
            logger.warning(f"QualityDB get_stats failed: {e}")
        
        return {'total': 0, 'oldest': None, 'newest': None, 'exists': False}
    
    @classmethod
    def delete_range(cls, node_id=None, keep_days=None, before_date=None):
        """Delete quality snapshots."""
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
            
            cursor = conn.execute(f"DELETE FROM quality_snapshots WHERE {where_clause}", params)
            deleted = cursor.rowcount
            
            if node_id:
                cursor.execute("SELECT COUNT(*) FROM quality_snapshots WHERE node_id = ?", (node_id,))
            else:
                cursor.execute("SELECT COUNT(*) FROM quality_snapshots")
            remaining = cursor.fetchone()[0]
            
            conn.commit()
            conn.close()
            
            return {'deleted': deleted, 'remaining': remaining}
        except Exception as e:
            logger.warning(f"QualityDB delete_range failed: {e}")
            return {'deleted': 0, 'remaining': 0, 'error': str(e)}