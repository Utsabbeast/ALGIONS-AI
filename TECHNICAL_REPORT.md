# Technical Report — Cinema Hall Ticket Booking System

**Project:** Cinema Hall Ticket Booking System (BookMyShow Clone)  
**Role:** Full-Stack Web Development  
**Organization:** ALGIONS AI LABS PRIVATE LIMITED  
**Submission Package:** Architecture, Design Decisions & Evaluation Evidence  

---

## 1. Executive Summary & Problem Formulation

Cinema hall ticket booking platforms encounter extreme traffic spikes during blockbuster movie releases. The primary technical challenges include:
1. **Preventing Double-Booking (ACID Race Conditions):** Multiple concurrent users attempting to reserve the exact same seat within the same millisecond.
2. **Temporary Seat Holds (Lock TTL):** Providing users with a 10-minute lock during seat selection and checkout, guaranteeing the seats are not sold to others while automatically releasing them if the cart is abandoned.
3. **Contactless Single-Use Gate Entry:** Validating tickets at cinema auditorium doors, ensuring a ticket can only be scanned once.
4. **Inventory & Revenue Reconciliation:** Accurately reflecting booking conversions, holds, and cancellations in occupancy reports.

To solve this, CinemaBox is architected as a **modular monolith** employing **Polyglot Persistence**: combining an ACID relational database (Django ORM with SQLite/PostgreSQL) with a document-oriented NoSQL persistence layer (MongoDB / PyMongo).

---

## 2. High-Level Architecture & Key Design Decisions

```
[ Client Browser / Mobile Web ]
            │
            ▼ HTTP / REST
[ Gunicorn / WSGI Application Server (Render) ]
            │
            ├──────► [ Whitenoise Static File Compression ]
            │
            ▼
[ Django 5.1 Application Core (cinemabox) ]
  ├── cinema (Theatres, Screens, Seats, Movies, Showtimes, RBAC User)
  ├── bookings (SeatHold, Booking, Concurrency Safety, Gate Scanner)
  ├── nosql (PyMongo Client, Resilient Embedded Document Store)
  └── api (DRF REST Endpoints & Spectacular OpenAPI 3.0)
            │
      ┌─────┴─────────────────────────┐
      ▼                               ▼
[ Relational ORM ]             [ NoSQL Collections ]
• Transactions (`select_for_update`) • ticket_scans (Entry audit)
• Database Unique Constraints        • audit_events (Action stream)
• Foreign Key Cascades               • movie_reviews (Dynamic ratings)
                                      • seat_matrix_cache (Snapshots)
```

### Design Decision 1: Relational ACID Model for Seat Inventory & Bookings
- **Rationale:** Financial transactions, ticket numbers, and seat coordinates require strict relational consistency. We implement pessimistic locking via `select_for_update()` wrapped inside `transaction.atomic()`, paired with database-level `UniqueConstraint` on active holds.
- **Guarantee:** Under extreme concurrent load, two users can never secure the same seat. The losing request immediately receives HTTP 409 Conflict.

### Design Decision 2: NoSQL Layer for High-Throughput Audit Trails & Reviews
- **Rationale:** Cinema entry gates generate high-frequency read/write telemetry that does not require relational normalization. Gate entry scans, material business event streams, dynamic reviews, and seat matrix snapshots are stored as documents in NoSQL (`ticket_scans`, `audit_events`, `movie_reviews`).
- **Resilience:** The system features a dual-mode NoSQL manager: when `MONGODB_URI` is present (e.g. MongoDB Atlas), it connects natively; otherwise, it automatically utilizes a thread-safe embedded JSON document store. This ensures zero setup friction during review while retaining true NoSQL document structures.

### Design Decision 3: Single-Use Cryptographic QR Token
- **Rationale:** Rather than relying solely on predictable sequential booking IDs, each confirmed booking generates a unique cryptographic validation token (`TKT-<uuid>`), encoded into a base64 PNG QR image.
- **Gate Validation:** Staff scanners check the token against the database. The first scan marks `is_validated = True` with a timestamp and operator ID. Subsequent scans instantly flag the ticket as `ALREADY_USED`, preventing unauthorized re-entry.

### Design Decision 4: Tiered Seat Layout & Dynamic Pricing
- **Layout:** Screens are modeled as 2D coordinate matrices (Rows A through J, Columns 1 to 12) divided into categories:
  - **Silver** (₹150–₹160)
  - **Gold** (₹220–₹240)
  - **Platinum** (₹320–₹350)
  - **VIP Recliner** (₹450–₹480)
- The frontend dynamically calculates subtotal, per-seat convenience fees (₹20), and grand totals in real time.

---

## 3. Concurrency & State Machine Verification

```
  [ AVAILABLE SEAT ]
          │
          │ hold_seats() (Atomic Lock)
          ▼
   [ SEAT HOLD ] ──(10 Min Expired)──► [ EXPIRED / RELEASED ] ──► [ AVAILABLE ]
          │
          │ confirm_booking() (Simulated Payment)
          ▼
  [ CONFIRMED BOOKING ]
     • QR Token Generated
     • Unique Ref Issued
          │
          ├────────────────────────────────┬───────────────────────────────┐
          │                                │                               │
          │ validate_ticket_entry() (1st)  │ cancel_booking()              │ validate_ticket_entry() (2nd)
          ▼                                ▼                               ▼
   [ GATE VALIDATED ]             [ CANCELLED & REFUNDED ]         [ REJECTED: ALREADY USED ]
   (Audience Checked In)          (Seats Restored to Available)    (Security Incident Logged)
```

---

## 4. Verification Evidence (Acceptance Criteria)

All 12 automated unit and integration tests executed with 100% success:

1. **Available seat can be held and booked:** Verified by `test_01_available_seat_can_be_held_and_booked`. Seat hold created, status converted to `CONFIRMED`, unique booking reference and QR token generated.
2. **Concurrency conflict prevention:** Verified by `test_02_double_booking_concurrency_prevention`. Second user receives `SeatUnavailableError` (HTTP 409).
3. **Expired hold release:** Verified by `test_03_expired_holds_release_seat_and_confirmed_remain_booked`. Expired holds return to `AVAILABLE`; confirmed bookings remain `BOOKED`.
4. **Single-use ticket QR validation:** Verified by `test_04_single_use_ticket_qr_validation`. 1st scan approves entry; 2nd scan throws `TicketAlreadyUsedError` and logs to NoSQL.
5. **Occupancy & revenue reconciliation:** Verified by `test_05_occupancy_report_matches_bookings_and_cancellations`. Invariant equation: `Capacity = Confirmed + Holds + Available` holds exactly before and after cancellations.

---

## 5. 3–5 Minute Walkthrough Video Script

- **[0:00 - 0:45] Overview & Tech Stack:**
  Show home page (`/`), review top evaluation bar, demonstrate city switcher (Mumbai, Delhi-NCR, Bengaluru) and movie filters (genres, languages, search).
- **[0:45 - 1:45] Customer Journey (Discovery & Seat Reservation):**
  Click on "Dune: Part Two", select a theatre and showtime. Open interactive seat picker. Select 2 seats across tiers (Gold / Platinum). Demonstrate the 10-minute hold lock timer and live price calculation. Click "Lock Seats & Pay", simulate UPI checkout, and view the generated ticket with base64 QR code pass.
- **[1:45 - 2:30] Gate Scanner & Entry Validation (Staff Flow):**
  Switch to Gate Staff role using 1-click login. Open Gate Scanner (`/bookings/staff/gate-scanner/`). Scan the generated ticket QR token. Show **Entry Approved** screen. Immediately scan the same ticket a second time to demonstrate the **Already Used** security alert and live NoSQL audit log.
- **[2:30 - 3:15] Cancellation & Inventory Release:**
  Return to customer view, open "My Bookings". Click "Cancel Ticket". Observe the simulated refund policy calculation (e.g. ₹480 refund processed) and verify that the cancelled seats are instantly released back to available inventory.
- **[3:15 - 4:00] Admin Dashboard & NoSQL Diagnostics:**
  Sign in as Cinema Admin. Review the live Occupancy and Sales Dashboard. Demonstrate the mathematical reconciliation table and the NoSQL engine diagnostic card displaying live document counts.

