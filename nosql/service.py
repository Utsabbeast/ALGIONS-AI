"""
NoSQL Persistence & Document Store Service Layer for CinemaBox.
Provides dual-mode operation:
1. Native MongoDB via PyMongo when MONGODB_URI is provided.
2. Resilient thread-safe JSON Document Store fallback when running locally or without MongoDB.

Key Collections:
- ticket_scans: Real-time gate entry validation events and security audit trail.
- audit_events: Material business action logs (reservations, cancellations, refunds, schedule changes).
- movie_reviews: Dynamic schema for unstructured user ratings, tags, and reviews.
- seat_matrix_cache: High-speed snapshot of real-time seat inventory.
"""

import os
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from django.conf import settings

logger = logging.getLogger(__name__)

DATA_DIR = getattr(settings, 'BASE_DIR', Path('.')) / 'nosql_data'
DATA_DIR.mkdir(exist_ok=True)


class JSONDocumentCollection:
    """
    Thread-safe embedded document collection matching PyMongo's collection API.
    Used when a remote MongoDB instance is not configured.
    """
    def __init__(self, collection_name: str, file_path: Path):
        self.name = collection_name
        self.file_path = file_path
        self._lock = threading.Lock()
        if not self.file_path.exists():
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def _read_all(self) -> List[Dict[str, Any]]:
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    def _write_all(self, docs: List[Dict[str, Any]]):
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(docs, f, default=str, indent=2)

    def insert_one(self, doc: Dict[str, Any]):
        with self._lock:
            docs = self._read_all()
            if '_id' not in doc:
                import uuid
                doc['_id'] = str(uuid.uuid4())
            if 'created_at' not in doc:
                doc['created_at'] = datetime.utcnow().isoformat()
            docs.append(doc)
            self._write_all(docs)
            return type('InsertResult', (), {'inserted_id': doc['_id']})()

    def find(self, query: Optional[Dict[str, Any]] = None, sort_field: str = 'created_at', reverse: bool = True, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            docs = self._read_all()
            if query:
                filtered = []
                for d in docs:
                    match = True
                    for k, v in query.items():
                        if d.get(k) != v:
                            match = False
                            break
                    if match:
                        filtered.append(d)
                docs = filtered
            
            # Sort
            if sort_field:
                docs.sort(key=lambda x: str(x.get(sort_field, '')), reverse=reverse)
            
            if limit:
                docs = docs[:limit]
            return docs

    def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        results = self.find(query=query, limit=1)
        return results[0] if results else None

    def update_one(self, query: Dict[str, Any], update: Dict[str, Any]):
        with self._lock:
            docs = self._read_all()
            updated = False
            for d in docs:
                match = True
                for k, v in query.items():
                    if d.get(k) != v:
                        match = False
                        break
                if match:
                    if '$set' in update:
                        d.update(update['$set'])
                    else:
                        d.update(update)
                    updated = True
                    break
            if updated:
                self._write_all(docs)
            return type('UpdateResult', (), {'modified_count': 1 if updated else 0})()

    def count_documents(self, query: Optional[Dict[str, Any]] = None) -> int:
        return len(self.find(query=query))

    def delete_many(self, query: Dict[str, Any]) -> int:
        with self._lock:
            docs = self._read_all()
            retained = []
            deleted = 0
            for d in docs:
                match = True
                for k, v in query.items():
                    if d.get(k) != v:
                        match = False
                        break
                if match:
                    deleted += 1
                else:
                    retained.append(d)
            self._write_all(retained)
            return deleted


class NoSQLManager:
    """
    Singleton manager providing access to MongoDB or the local document store.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(NoSQLManager, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        self.uri = getattr(settings, 'MONGODB_URI', '')
        self.db_name = getattr(settings, 'MONGODB_NAME', 'cinemabox_nosql')
        self.is_mongodb_connected = False
        self.client = None
        self.db = None
        self._collections: Dict[str, Any] = {}

        if self.uri:
            try:
                from pymongo import MongoClient
                self.client = MongoClient(self.uri, serverSelectionTimeoutMS=2000)
                # Verify connection with ping
                self.client.admin.command('ping')
                self.db = self.client[self.db_name]
                self.is_mongodb_connected = True
                logger.info("Connected successfully to MongoDB NoSQL database.")
            except Exception as e:
                logger.warning(f"Could not connect to MongoDB URI ({e}). Falling back to Embedded NoSQL Document Store.")
                self.is_mongodb_connected = False
        else:
            logger.info("No MONGODB_URI configured. Using Embedded Resilient NoSQL Document Store.")

    def get_collection(self, name: str):
        if self.is_mongodb_connected and self.db is not None:
            return self.db[name]
        
        if name not in self._collections:
            file_path = DATA_DIR / f"{name}.json"
            self._collections[name] = JSONDocumentCollection(name, file_path)
        return self._collections[name]

    @property
    def ticket_scans(self):
        return self.get_collection('ticket_scans')

    @property
    def audit_events(self):
        return self.get_collection('audit_events')

    @property
    def movie_reviews(self):
        return self.get_collection('movie_reviews')

    @property
    def seat_matrix_cache(self):
        return self.get_collection('seat_matrix_cache')


# Global NoSQL instance
nosql = NoSQLManager()


# Material Audit Logging Helper
def log_audit_event(event_type: str, actor: str, entity_type: str, entity_id: str, details: Dict[str, Any]):
    """
    Records an immutable audit document for material operations:
    - SEAT_HOLD
    - SEAT_RELEASE
    - BOOKING_CONFIRMED
    - BOOKING_CANCELLED
    - SIMULATED_REFUND
    - TICKET_SCAN
    - SCHEDULE_CHANGE
    """
    doc = {
        'event_type': event_type,
        'actor': actor,
        'entity_type': entity_type,
        'entity_id': str(entity_id),
        'details': details,
        'timestamp': datetime.utcnow().isoformat()
    }
    try:
        nosql.audit_events.insert_one(doc)
    except Exception as e:
        logger.error(f"Failed to record audit event: {e}")


# Gate Entry Scan Logging Helper
def log_ticket_scan(booking_reference: str, qr_token: str, status: str, staff_username: str, message: str, metadata: Optional[Dict[str, Any]] = None):
    """
    Records gate scanner validation attempts (VALID, ALREADY_USED, REJECTED).
    Provides non-repudiation audit trail for cinema entry gates.
    """
    doc = {
        'booking_reference': booking_reference,
        'qr_token': qr_token,
        'status': status,
        'staff_username': staff_username,
        'message': message,
        'metadata': metadata or {},
        'timestamp': datetime.utcnow().isoformat()
    }
    try:
        nosql.ticket_scans.insert_one(doc)
    except Exception as e:
        logger.error(f"Failed to record ticket scan: {e}")


# Movie Reviews NoSQL Helpers
def add_movie_review(movie_id: int, username: str, rating: float, comment: str, tags: Optional[List[str]] = None, verified_booking: bool = False):
    """
    Stores unstructured customer review documents with strict input sanitization.
    Strips script tags and inner contents, removes HTML markup, and bounds ratings.
    """
    import re
    from django.utils.html import strip_tags

    def _sanitize(val: str) -> str:
        if not val:
            return ""
        # Strip script and style blocks completely
        val = re.sub(r'(?is)<(script|style).*?>.*?(</\1>)', '', str(val))
        return strip_tags(val).strip()

    clean_username = _sanitize(username)[:50] or 'Anonymous Guest'
    clean_comment = _sanitize(comment)[:1000]
    
    try:
        clean_rating = max(1.0, min(5.0, round(float(rating), 1)))
    except (ValueError, TypeError):
        clean_rating = 5.0

    clean_tags = []
    if tags:
        for t in tags:
            tag_str = _sanitize(t)[:30]
            if tag_str and tag_str not in clean_tags:
                clean_tags.append(tag_str)

    doc = {
        'movie_id': int(movie_id),
        'username': clean_username,
        'rating': clean_rating,
        'comment': clean_comment,
        'tags': clean_tags[:8],
        'verified_booking': bool(verified_booking),
        'created_at': datetime.utcnow().isoformat(),
        'likes_count': 0
    }
    nosql.movie_reviews.insert_one(doc)
    return doc


def get_movie_reviews(movie_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    return nosql.movie_reviews.find({'movie_id': movie_id}, sort_field='created_at', reverse=True, limit=limit)


def get_audit_trail(limit: int = 50) -> List[Dict[str, Any]]:
    return nosql.audit_events.find({}, sort_field='timestamp', reverse=True, limit=limit)


def get_ticket_scan_logs(limit: int = 50) -> List[Dict[str, Any]]:
    return nosql.ticket_scans.find({}, sort_field='timestamp', reverse=True, limit=limit)


def get_nosql_status() -> Dict[str, Any]:
    """
    Returns diagnostic information about the active NoSQL engine.
    """
    is_mongo = nosql.is_mongodb_connected
    engine_name = "MongoDB (Native Atlas/Server)" if is_mongo else "Embedded JSON Document Store"
    counts = {
        'ticket_scans': nosql.ticket_scans.count_documents(),
        'audit_events': nosql.audit_events.count_documents(),
        'movie_reviews': nosql.movie_reviews.count_documents(),
        'seat_matrix_cache': nosql.seat_matrix_cache.count_documents(),
    }
    return {
        'engine': engine_name,
        'is_mongodb_connected': is_mongo,
        'database_name': nosql.db_name,
        'collections': counts,
    }

