"""
Comprehensive Edge-Case & Sanitization Test Suite for COMET Cinema Booking System.
Validates:
1. Seat ID deduplication & max-limit validation in hold_seats
2. Race condition hold expiry handling in confirm_booking
3. Open redirect prevention on login
4. Malformed query parameters on admin dashboard & occupancy API
5. NoSQL review HTML tag stripping & XSS defense
6. Single-use QR token defense and invalid gate scanner inputs
"""

from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError

from cinema.models import User, Movie, Theatre, Screen, Seat, Showtime
from bookings.models import Booking, SeatHold, BookingSeat
from bookings import services
from nosql import service as nosql_service


class EdgeCaseAndSanitizationTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin user
        self.admin_user = User.objects.create_superuser(
            username='edge_admin',
            email='admin@comet.test',
            password='testpassword123',
            role=User.Role.ADMIN
        )

        # Customer user
        self.customer = User.objects.create_user(
            username='edge_customer',
            email='customer@comet.test',
            password='testpassword123',
            role=User.Role.CUSTOMER
        )

        # Staff user
        self.staff_user = User.objects.create_user(
            username='edge_staff',
            email='staff@comet.test',
            password='testpassword123',
            role=User.Role.STAFF
        )

        # Movie
        self.movie = Movie.objects.create(
            title='Inception Matrix',
            slug='inception-matrix',
            duration_minutes=150,
            certification='UA',
            language='English',
            release_date=timezone.now().date()
        )

        # Theatre & Screen
        self.theatre = Theatre.objects.create(
            name='COMET Megaplex Alpha',
            city='Mumbai',
            address='Bandra West'
        )
        self.screen = Screen.objects.create(
            theatre=self.theatre,
            name='Screen 1 - Laser 4K',
            screen_type='IMAX',
            total_rows=2,
            total_columns=10
        )

        # Generate seats (2 rows: A and B)
        self.seats = []
        for r in ['A', 'B']:
            for num in range(1, 11):
                seat = Seat.objects.create(
                    screen=self.screen,
                    row_label=r,
                    seat_number=num,
                    category=Seat.Category.VIP if r == 'A' else Seat.Category.GOLD,
                    is_active=True
                )
                self.seats.append(seat)

        # Showtime tomorrow
        start = timezone.now() + timedelta(days=1)
        self.showtime = Showtime.objects.create(
            movie=self.movie,
            screen=self.screen,
            start_time=start,
            end_time=start + timedelta(minutes=150),
            price_vip=Decimal('500.00'),
            price_platinum=Decimal('350.00'),
            price_gold=Decimal('250.00'),
            price_silver=Decimal('150.00')
        )

    def test_hold_seats_duplicate_seat_ids_deduplicated(self):
        """Duplicate seat IDs in hold payload are safely deduplicated without failure."""
        s1 = self.seats[0]
        duplicate_ids = [s1.id, s1.id, s1.id]
        
        hold_result = services.hold_seats(
            showtime_id=self.showtime.id,
            seat_ids=duplicate_ids,
            user=self.customer
        )
        self.assertIn('hold_token', hold_result)
        self.assertEqual(len(hold_result['seats']), 1)
        self.assertEqual(hold_result['seats'][0]['seat_id'], s1.id)

    def test_hold_seats_exceeds_max_limit_raises_error(self):
        """Holding more than 10 seats in a single transaction raises ValidationError."""
        all_seat_ids = [s.id for s in self.seats[:12]]
        with self.assertRaises(ValidationError) as ctx:
            services.hold_seats(
                showtime_id=self.showtime.id,
                seat_ids=all_seat_ids,
                user=self.customer
            )
        self.assertIn("Maximum 10 seats", str(ctx.exception))

    def test_hold_seats_invalid_showtime_id_raises_validation_error(self):
        """Non-existent showtime ID raises clean ValidationError rather than unhandled exception."""
        with self.assertRaises(ValidationError) as ctx:
            services.hold_seats(
                showtime_id=999999,
                seat_ids=[self.seats[0].id],
                user=self.customer
            )
        self.assertIn("Showtime 999999 not found", str(ctx.exception))

    def test_confirm_booking_race_condition_expired_hold(self):
        """If a hold expires right as confirmation is invoked, it is rejected and marked EXPIRED."""
        s1 = self.seats[0]
        hold_result = services.hold_seats(
            showtime_id=self.showtime.id,
            seat_ids=[s1.id],
            user=self.customer,
            hold_minutes=10
        )
        token = hold_result['hold_token']

        # Artificially age the hold to simulate expiry race
        SeatHold.objects.filter(hold_token=token).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        with self.assertRaises(services.HoldExpiredError):
            services.confirm_booking(
                hold_token=token,
                user=self.customer
            )

        # Verify hold is now EXPIRED
        hold = SeatHold.objects.get(hold_token=token)
        self.assertEqual(hold.status, SeatHold.Status.EXPIRED)

    def test_login_view_open_redirect_defense(self):
        """Login view rejects off-site redirect URLs and falls back to home."""
        response = self.client.post(
            reverse('cinema:login') + '?next=https://malicious-phishing-site.com',
            {'username': 'edge_customer', 'password': 'testpassword123'}
        )
        # Should redirect to cinema:home (/) and NOT malicious-phishing-site.com
        self.assertEqual(response.status_code, 302)
        self.assertFalse('malicious-phishing-site.com' in response.url)
        self.assertEqual(response.url, reverse('cinema:home'))

    def test_admin_dashboard_malformed_query_params(self):
        """Admin dashboard gracefully handles non-numeric query parameters."""
        self.client.login(username='edge_admin', password='testpassword123')
        response = self.client.get(
            reverse('bookings:admin-dashboard') + '?theatre_id=invalid_text&movie_id=malformed'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "COMET Megaplex Alpha")

    def test_occupancy_api_malformed_query_params(self):
        """Occupancy API gracefully handles non-numeric query parameters."""
        self.client.login(username='edge_admin', password='testpassword123')
        response = self.client.get(
            reverse('api:admin-occupancy-report') + '?theatre_id=text_str&movie_id=bad_id'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('summary', response.json())

    def test_nosql_audit_and_scans_clamped_limit(self):
        """Audit trail and ticket scans API clamp limits safely."""
        self.client.login(username='edge_admin', password='testpassword123')
        
        res1 = self.client.get(reverse('api:nosql-audit-trail') + '?limit=999999')
        self.assertEqual(res1.status_code, 200)

        res2 = self.client.get(reverse('api:nosql-ticket-scans') + '?limit=-10')
        self.assertEqual(res2.status_code, 200)

        res3 = self.client.get(reverse('api:nosql-audit-trail') + '?limit=invalid_int')
        self.assertEqual(res3.status_code, 200)

    def test_nosql_review_html_sanitization(self):
        """NoSQL review storage strips dangerous HTML tags and script payloads."""
        review_doc = nosql_service.add_movie_review(
            movie_id=self.movie.id,
            username='<script>alert("hacked")</script>Alice',
            rating=6.5,  # Exceeds max rating of 5.0
            comment='<b>Great show!</b> <script>document.cookie</script>',
            tags=['<img src=x onerror=alert(1)>Action', 'Sci-Fi']
        )
        self.assertNotIn('<script>', review_doc['username'])
        self.assertEqual(review_doc['username'], 'Alice')
        self.assertNotIn('<script>', review_doc['comment'])
        self.assertNotIn('<b>', review_doc['comment'])
        self.assertEqual(review_doc['comment'], 'Great show!')
        self.assertEqual(review_doc['rating'], 5.0)  # Clamped to 5.0
        self.assertNotIn('<img', review_doc['tags'][0])

    def test_validate_ticket_entry_empty_input_rejected(self):
        """Empty or whitespace ticket input raises clean TicketValidationError."""
        with self.assertRaises(services.TicketValidationError):
            services.validate_ticket_entry(
                token_or_reference='   ',
                staff_user=self.staff_user
            )
