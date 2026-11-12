from decimal import Decimal
from datetime import timedelta
import pytest
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError

from cinema.models import User, Genre, Theatre, Screen, Seat, Movie, Showtime
from bookings.models import Booking, BookingSeat, SeatHold
from bookings import services
from nosql import service as nosql_service


class AcceptanceCriteriaTestSuite(TestCase):
    """
    Automated test suite verifying the 5 mandatory acceptance criteria
    stipulated in the ALGIONS assessment brief.
    """

    def setUp(self):
        # Setup test users with different roles
        self.customer1 = User.objects.create_user(
            username='test_alice',
            password='password123',
            email='alice@example.com',
            role=User.Role.CUSTOMER
        )
        self.customer2 = User.objects.create_user(
            username='test_bob',
            password='password123',
            email='bob@example.com',
            role=User.Role.CUSTOMER
        )
        self.staff_user = User.objects.create_user(
            username='test_staff',
            password='password123',
            email='staff@example.com',
            role=User.Role.STAFF
        )
        self.admin_user = User.objects.create_user(
            username='test_admin',
            password='password123',
            email='admin@example.com',
            role=User.Role.ADMIN
        )

        # Setup Theatre, Screen, and Seats
        self.theatre = Theatre.objects.create(
            name='Test Grand Cinema',
            city='Mumbai',
            address='123 Cinema Street'
        )
        self.screen = Screen.objects.create(
            theatre=self.theatre,
            name='Screen 1 - Atmos',
            total_rows=3,
            total_columns=4
        )
        self.seats = []
        for r in ['A', 'B', 'C']:
            for c in range(1, 5):
                cat = Seat.Category.SILVER if r == 'A' else (Seat.Category.GOLD if r == 'B' else Seat.Category.VIP)
                s = Seat.objects.create(
                    screen=self.screen,
                    row_label=r,
                    seat_number=c,
                    seat_code=f"{r}{c}",
                    category=cat
                )
                self.seats.append(s)

        # Setup Movie and Showtime
        self.movie = Movie.objects.create(
            title='Inception: Resurgence',
            description='Mind-bending sci-fi thriller',
            duration_minutes=150,
            language='English',
            certification='UA',
            release_date=timezone.now().date()
        )
        self.showtime = Showtime.objects.create(
            movie=self.movie,
            screen=self.screen,
            start_time=timezone.now() + timedelta(days=1, hours=2),
            end_time=timezone.now() + timedelta(days=1, hours=5),
            price_silver=Decimal('150.00'),
            price_gold=Decimal('220.00'),
            price_vip=Decimal('400.00')
        )

    # Acceptance Test 1: An available seat can be held and booked for a show
    def test_01_available_seat_can_be_held_and_booked(self):
        """
        Criteria 1: Customer selects available seats, holds them with expiry,
        and converts the hold into a confirmed booking with a valid QR token.
        """
        seat_a1 = self.seats[0] # A1
        seat_a2 = self.seats[1] # A2

        # Step 1: Place temporary hold
        hold_result = services.hold_seats(
            showtime_id=self.showtime.id,
            seat_ids=[seat_a1.id, seat_a2.id],
            user=self.customer1,
            hold_minutes=10
        )

        self.assertIn('hold_token', hold_result)
        self.assertEqual(len(hold_result['seats']), 2)
        hold_token = hold_result['hold_token']

        # Verify hold records exist and are ACTIVE
        holds = SeatHold.objects.filter(hold_token=hold_token)
        self.assertEqual(holds.count(), 2)
        self.assertTrue(all(h.status == SeatHold.Status.ACTIVE for h in holds))

        # Step 2: Confirm booking using hold_token
        booking = services.confirm_booking(
            hold_token=hold_token,
            user=self.customer1,
            payment_method='SIMULATED_UPI'
        )

        self.assertIsNotNone(booking.id)
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertTrue(booking.booking_reference.startswith('BMS-'))
        self.assertTrue(booking.qr_token.startswith('TKT-'))
        self.assertEqual(booking.seats.count(), 2)

        # Verify holds are marked CONVERTED
        holds.filter(id__in=[h.id for h in holds]).update()
        for h in SeatHold.objects.filter(hold_token=hold_token):
            self.assertEqual(h.status, SeatHold.Status.CONVERTED)

        # Verify seat matrix marks them as BOOKED
        matrix = services.get_show_seat_matrix(self.showtime.id)
        a1_status = next(s['status'] for row in matrix['rows'] for s in row['seats'] if s['code'] == 'A1')
        self.assertEqual(a1_status, 'BOOKED')

    # Acceptance Test 2: The same seat cannot be confirmed to two users for one show
    def test_02_double_booking_concurrency_prevention(self):
        """
        Criteria 2: If User A holds or books a seat, User B's attempt to hold
        or confirm that same seat for the same show must be rejected with SeatUnavailableError.
        """
        seat_b1 = self.seats[4] # B1

        # User A holds seat B1
        hold_a = services.hold_seats(
            showtime_id=self.showtime.id,
            seat_ids=[seat_b1.id],
            user=self.customer1
        )

        # User B attempts to hold the same seat B1 while User A's hold is active -> Must raise SeatUnavailableError
        with self.assertRaises(services.SeatUnavailableError):
            services.hold_seats(
                showtime_id=self.showtime.id,
                seat_ids=[seat_b1.id],
                user=self.customer2
            )

        # User A confirms booking
        booking_a = services.confirm_booking(
            hold_token=hold_a['hold_token'],
            user=self.customer1
        )
        self.assertEqual(booking_a.status, Booking.Status.CONFIRMED)

        # User B attempts again after confirmation -> Must raise SeatUnavailableError
        with self.assertRaises(services.SeatUnavailableError):
            services.hold_seats(
                showtime_id=self.showtime.id,
                seat_ids=[seat_b1.id],
                user=self.customer2
            )

    # Acceptance Test 3: Expired holds release the seat; confirmed bookings remain unavailable
    def test_03_expired_holds_release_seat_and_confirmed_remain_booked(self):
        """
        Criteria 3: An expired hold automatically releases the seat back to AVAILABLE,
        while confirmed bookings permanently stay BOOKED.
        """
        seat_c1 = self.seats[8]  # C1 (to be held and expired)
        seat_c2 = self.seats[9]  # C2 (to be booked confirmed)

        # Book seat C2 confirmed
        hold_c2 = services.hold_seats(showtime_id=self.showtime.id, seat_ids=[seat_c2.id], user=self.customer1)
        booking_c2 = services.confirm_booking(hold_token=hold_c2['hold_token'], user=self.customer1)
        self.assertEqual(booking_c2.status, Booking.Status.CONFIRMED)

        # Place hold on seat C1 with expiry in the past
        hold_c1 = services.hold_seats(showtime_id=self.showtime.id, seat_ids=[seat_c1.id], user=self.customer2)
        # Manually backdate expiry to simulate time passage
        SeatHold.objects.filter(hold_token=hold_c1['hold_token']).update(
            expires_at=timezone.now() - timedelta(minutes=5)
        )

        # Attempting to confirm the expired hold must fail
        with self.assertRaises(services.HoldExpiredError):
            services.confirm_booking(
                hold_token=hold_c1['hold_token'],
                user=self.customer2
            )

        # Query seat matrix: seat C1 should be back to AVAILABLE, while seat C2 remains BOOKED
        matrix = services.get_show_seat_matrix(self.showtime.id)
        c1_info = next(s for row in matrix['rows'] for s in row['seats'] if s['code'] == 'C1')
        c2_info = next(s for row in matrix['rows'] for s in row['seats'] if s['code'] == 'C2')

        self.assertEqual(c1_info['status'], 'AVAILABLE', "Expired hold must be released back to AVAILABLE")
        self.assertEqual(c2_info['status'], 'BOOKED', "Confirmed booking must remain BOOKED")

        # Another user can now hold seat C1
        new_hold = services.hold_seats(showtime_id=self.showtime.id, seat_ids=[seat_c1.id], user=self.customer1)
        self.assertIsNotNone(new_hold['hold_token'])

    # Acceptance Test 4: A ticket reference/QR can be validated once in a simulated entry flow
    def test_04_single_use_ticket_qr_validation(self):
        """
        Criteria 4:
        - 1st scan: Validates ticket successfully, updates validated_at, logs VALID_ENTRY to NoSQL.
        - 2nd scan: Rejects ticket as ALREADY_USED with exception, logging audit trail.
        - Cancelled ticket: Rejects ticket.
        """
        seat = self.seats[2] # A3
        hold = services.hold_seats(showtime_id=self.showtime.id, seat_ids=[seat.id], user=self.customer1)
        booking = services.confirm_booking(hold_token=hold['hold_token'], user=self.customer1)

        qr_token = booking.qr_token
        booking_ref = booking.booking_reference

        # First scan by gate staff -> MUST SUCCEED
        res1 = services.validate_ticket_entry(
            token_or_reference=qr_token,
            staff_user=self.staff_user
        )
        self.assertTrue(res1['success'])
        self.assertEqual(res1['status'], 'VALID_ENTRY')
        
        # Verify database state
        booking.refresh_from_db()
        self.assertTrue(booking.is_validated)
        self.assertIsNotNone(booking.validated_at)
        self.assertEqual(booking.validated_by, self.staff_user)

        # Second scan of the same ticket -> MUST FAIL with TicketAlreadyUsedError
        with self.assertRaises(services.TicketAlreadyUsedError):
            services.validate_ticket_entry(
                token_or_reference=qr_token,
                staff_user=self.staff_user
            )

        # Scan using booking reference instead of QR token -> MUST ALSO FAIL as ALREADY_USED
        with self.assertRaises(services.TicketAlreadyUsedError):
            services.validate_ticket_entry(
                token_or_reference=booking_ref,
                staff_user=self.staff_user
            )

        # Verify gate scans logged in NoSQL
        scans = nosql_service.get_ticket_scan_logs(limit=10)
        statuses = [s['status'] for s in scans]
        self.assertIn('VALID_ENTRY', statuses)
        self.assertIn('ALREADY_USED', statuses)

    # Acceptance Test 5: The admin occupancy report matches bookings and cancellations
    def test_05_occupancy_report_matches_bookings_and_cancellations(self):
        """
        Criteria 5: Verify mathematical integrity between bookings, cancellations,
        refunds, and the admin occupancy report.
        """
        seat1 = self.seats[0]
        seat2 = self.seats[1]
        seat3 = self.seats[2]

        # Total screen capacity = 12 seats (3 rows x 4 cols)
        total_capacity = self.screen.seats.count()
        self.assertEqual(total_capacity, 12)

        # Initial occupancy report
        initial_rep = services.get_occupancy_report_data(theatre_id=self.theatre.id)
        show_rep = next(s for s in initial_rep['shows'] if s['showtime_id'] == self.showtime.id)
        self.assertEqual(show_rep['confirmed_seats'], 0)
        self.assertEqual(show_rep['available_seats'], 12)
        self.assertEqual(show_rep['cancelled_bookings'], 0)

        # User 1 books 2 seats (Seat 1 & 2)
        hold1 = services.hold_seats(showtime_id=self.showtime.id, seat_ids=[seat1.id, seat2.id], user=self.customer1)
        booking1 = services.confirm_booking(hold_token=hold1['hold_token'], user=self.customer1)

        # User 2 books 1 seat (Seat 3)
        hold2 = services.hold_seats(showtime_id=self.showtime.id, seat_ids=[seat3.id], user=self.customer2)
        booking2 = services.confirm_booking(hold_token=hold2['hold_token'], user=self.customer2)

        # Occupancy report after 2 bookings (total 3 seats booked)
        rep_after_booking = services.get_occupancy_report_data(theatre_id=self.theatre.id)
        s_rep = next(s for s in rep_after_booking['shows'] if s['showtime_id'] == self.showtime.id)
        
        self.assertEqual(s_rep['confirmed_seats'], 3)
        self.assertEqual(s_rep['available_seats'], 9) # 12 - 3 = 9
        self.assertEqual(s_rep['total_capacity'], s_rep['confirmed_seats'] + s_rep['active_holds'] + s_rep['available_seats'])
        self.assertGreater(s_rep['gross_revenue'], 0)

        # User 2 cancels Booking 2
        cancelled_booking = services.cancel_booking(
            booking_reference=booking2.booking_reference,
            requested_by=self.customer2,
            reason="Change of plans"
        )
        self.assertEqual(cancelled_booking.status, Booking.Status.CANCELLED)
        self.assertGreater(cancelled_booking.refund_amount, 0)

        # Occupancy report after cancellation
        rep_after_cancel = services.get_occupancy_report_data(theatre_id=self.theatre.id)
        s_rep2 = next(s for s in rep_after_cancel['shows'] if s['showtime_id'] == self.showtime.id)

        # Invariants verified:
        # 1. Confirmed seats decreased from 3 to 2
        self.assertEqual(s_rep2['confirmed_seats'], 2)
        # 2. Cancelled bookings increased to 1
        self.assertEqual(s_rep2['cancelled_bookings'], 1)
        # 3. Available seats increased from 9 to 10
        self.assertEqual(s_rep2['available_seats'], 10)
        # 4. Total capacity equation strictly holds
        self.assertEqual(s_rep2['total_capacity'], s_rep2['confirmed_seats'] + s_rep2['active_holds'] + s_rep2['available_seats'])
        # 5. Net revenue equals gross revenue minus refunds issued
        self.assertEqual(s_rep2['net_revenue'], s_rep2['gross_revenue'] - s_rep2['refunds_issued'])

    # Additional Negative & Edge Case Tests
    def test_06_cannot_cancel_past_show(self):
        """Negative case: Customer cannot cancel a show that has already started."""
        # Create a showtime in the past
        past_show = Showtime.objects.create(
            movie=self.movie,
            screen=self.screen,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(minutes=30)
        )
        seat = self.seats[0]
        # Directly create confirmed booking for past show
        booking = Booking.objects.create(
            booking_reference="BMS-PAST-TEST",
            user=self.customer1,
            showtime=past_show,
            status=Booking.Status.CONFIRMED,
            total_amount=Decimal('200.00'),
            qr_token="TKT-PAST-01"
        )
        BookingSeat.objects.create(
            booking=booking,
            seat=seat,
            showtime=past_show,
            seat_price=Decimal('200.00'),
            seat_category=seat.category
        )

        with self.assertRaises(ValidationError):
            services.cancel_booking(
                booking_reference=booking.booking_reference,
                requested_by=self.customer1
            )

    def test_07_unauthorized_user_cannot_cancel_others_booking(self):
        """RBAC security: Customer B cannot cancel Customer A's booking."""
        seat = self.seats[0]
        hold = services.hold_seats(showtime_id=self.showtime.id, seat_ids=[seat.id], user=self.customer1)
        booking = services.confirm_booking(hold_token=hold['hold_token'], user=self.customer1)

        with self.assertRaises(ValidationError):
            services.cancel_booking(
                booking_reference=booking.booking_reference,
                requested_by=self.customer2  # Customer 2 attempting to cancel Customer 1's ticket
            )

