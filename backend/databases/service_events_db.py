"""
Service Events History Database
Tracks service starts, stops, and status changes.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from threading import Lock
import logging

logger = logging.getLogger(__name__)


class ServiceEventsDB:
    """Persistent storage for service lifecycle events."""
    
    _db_path = Path(__file__).parent.parent.parent / 'config' / 'service_events.db'
    _initialized = False
    _lock = Lock()
    _last_service_state = {}
    
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
                    CREATE TABLE IF NOT EXISTS service_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        time TEXT NOT NULL,
                        service_id TEXT,
                        service_type TEXT,
                        event TEXT,
                        node_id TEXT DEFAULT ''
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_service_time ON service_events(time)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_service_node ON service_events(node_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_service_type ON service_events(service_type)")
                conn.commit()
                conn.close()
                cls._initialized = True
                logger.info("ServiceEventsDB initialized")
            except Exception as e:
                logger.warning(f"ServiceEventsDB init failed: {e}")
    
    @classmethod
    def record_services_snapshot(cls, services_list, node_id=''):
        """Record events when services change state."""
        cls.init()
        
        now = datetime.now(timezone.utc).isoformat()
        current_state = {}
        
        for svc in services_list:
            svc_id = svc.get('id', '')
            svc_type = svc.get('type', 'unknown')
            is_active = svc.get('is_active', False)
            
            if svc_id:
                current_state[svc_id] = {
                    'type': svc_type,
                    'active': is_active,
                }
        
        events = []
        
        for svc_id, state in current_state.items():
            if svc_id not in cls._last_service_state:
                events.append({
                    'service_id': svc_id,
                    'service_type': state['type'],
                    'event': 'started' if state['active'] else 'registered',
                })
            elif cls._last_service_state[svc_id]['active'] != state['active']:
                events.append({
                    'service_id': svc_id,
                    'service_type': state['type'],
                    'event': 'activated' if state['active'] else 'deactivated',
                })
        
        for svc_id in cls._last_service_state:
            if svc_id not in current_state:
                events.append({
                    'service_id': svc_id,
                    'service_type': cls._last_service_state[svc_id]['type'],
                    'event': 'stopped',
                })
        
        if events:
            with cls._lock:
                try:
                    conn = cls._conn()
                    for event in events:
                        conn.execute("""
                            INSERT INTO service_events (time, service_id, service_type, event, node_id)
                            VALUES (?, ?, ?, ?, ?)
                        """, (now, event['service_id'], event['service_type'], event['event'], node_id))
                    conn.commit()
                    conn.close()
                    logger.info(f"ServiceEventsDB: recorded {len(events)} events")
                except Exception as e:
                    logger.warning(f"ServiceEventsDB record failed: {e}")
        
        cls._last_service_state = current_state
        return len(events)
    
    @classmethod
    def get_events(cls, limit=100, node_id=None, service_type=None):
        """Get recent service events."""
        cls.init()
        try:
            conn = cls._conn()
            
            conditions = []
            params = []
            
            if node_id:
                conditions.append("node_id = ?")
                params.append(node_id)
            
            if service_type:
                conditions.append("service_type = ?")
                params.append(service_type)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            rows = conn.execute(f"""
                SELECT * FROM service_events 
                WHERE {where_clause}
                ORDER BY time DESC 
                LIMIT ?
            """, params + [limit]).fetchall()
            
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"ServiceEventsDB get_events failed: {e}")
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
                        SUM(CASE WHEN event = 'started' THEN 1 ELSE 0 END) as starts,
                        SUM(CASE WHEN event = 'stopped' THEN 1 ELSE 0 END) as stops
                    FROM service_events 
                    WHERE (node_id = ? OR node_id = '')
                """, (node_id,)).fetchone()
            else:
                row = conn.execute("""
                    SELECT 
                        COUNT(*) as total,
                        MIN(time) as oldest,
                        MAX(time) as newest,
                        SUM(CASE WHEN event = 'started' THEN 1 ELSE 0 END) as starts,
                        SUM(CASE WHEN event = 'stopped' THEN 1 ELSE 0 END) as stops
                    FROM service_events
                """).fetchone()
            
            conn.close()
            
            if row:
                return {
                    'total': row['total'] or 0,
                    'oldest': row['oldest'][:10] if row['oldest'] else None,
                    'newest': row['newest'][:10] if row['newest'] else None,
                    'starts': row['starts'] or 0,
                    'stops': row['stops'] or 0,
                    'exists': True,
                }
        except Exception as e:
            logger.warning(f"ServiceEventsDB get_stats failed: {e}")
        
        return {'total': 0, 'oldest': None, 'newest': None, 'exists': False}
    
    @classmethod
    def delete_range(cls, node_id=None, keep_days=None, before_date=None):
        """Delete service events."""
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
            
            cursor = conn.execute(f"DELETE FROM service_events WHERE {where_clause}", params)
            deleted = cursor.rowcount
            
            if node_id:
                cursor.execute("SELECT COUNT(*) FROM service_events WHERE node_id = ?", (node_id,))
            else:
                cursor.execute("SELECT COUNT(*) FROM service_events")
            remaining = cursor.fetchone()[0]
            
            conn.commit()
            conn.close()
            
            return {'deleted': deleted, 'remaining': remaining}
        except Exception as e:
            logger.warning(f"ServiceEventsDB delete_range failed: {e}")
            return {'deleted': 0, 'remaining': 0, 'error': str(e)}