import json
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from cinema.models import User, Genre, Theatre, Screen, Seat, Movie, Showtime
from bookings.models import Booking, BookingSeat, SeatHold
from nosql import service as nosql_service


class ApiAndNoSQLTestSuite(TestCase):
    """
    Integration tests for DRF REST endpoints, RBAC permissions,
    and NoSQL document collections.
    """

    def setUp(self):
        self.client = APIClient()

        self.customer = User.objects.create_user(
            username='api_customer',
            password='password123',
            email='customer@example.com',
            role=User.Role.CUSTOMER
        )
        self.staff_user = User.objects.create_user(
            username='api_staff',
            password='password123',
            email='staff@example.com',
            role=User.Role.STAFF
        )
        self.admin_user = User.objects.create_user(
            username='api_admin',
            password='password123',
            email='admin@example.com',
            role=User.Role.ADMIN
        )

        self.theatre = Theatre.objects.create(name='PVR City Centre', city='Mumbai', address='Main Street')
        self.screen = Screen.objects.create(theatre=self.theatre, name='Screen 1', total_rows=2, total_columns=2)
        
        self.seats = []
        for r in ['A', 'B']:
            for c in [1, 2]:
                s = Seat.objects.create(
                    screen=self.screen,
                    row_label=r,
                    seat_number=c,
                    seat_code=f"{r}{c}",
                    category=Seat.Category.GOLD
                )
                self.seats.append(s)

        self.movie = Movie.objects.create(
            title='Avatar 3',
            description='Pandora adventures',
            duration_minutes=190,
            language='English',
            certification='UA',
            release_date=timezone.now().date()
        )
        self.showtime = Showtime.objects.create(
            movie=self.movie,
            screen=self.screen,
            start_time=timezone.now() + timedelta(days=2),
            end_time=timezone.now() + timedelta(days=2, hours=3),
            price_gold=Decimal('250.00')
        )

    def test_01_public_movies_api_with_filters(self):
        """Test GET /api/movies/ with filters."""
        res = self.client.get('/api/movies/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(res.data['results']), 1)

        # Search filter
        res_search = self.client.get('/api/movies/?search=Avatar')
        self.assertEqual(res_search.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_search.data['results']), 1)

    def test_02_showtime_seat_matrix_api(self):
        """Test GET /api/showtimes/{id}/seats/."""
        res = self.client.get(f'/api/showtimes/{self.showtime.id}/seats/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('showtime', res.data)
        self.assertIn('rows', res.data)
        self.assertIn('stats', res.data)
        self.assertEqual(res.data['stats']['total_seats'], 4)

    def test_03_seat_hold_and_confirm_api_workflow(self):
        """Test POST /api/bookings/hold/ and POST /api/bookings/confirm/."""
        # Hold seats via API
        hold_payload = {
            'showtime_id': self.showtime.id,
            'seat_ids': [self.seats[0].id]
        }
        res_hold = self.client.post('/api/bookings/hold/', hold_payload, format='json')
        self.assertEqual(res_hold.status_code, status.HTTP_201_CREATED)
        hold_token = res_hold.data['hold_token']

        # Confirm booking via API (authenticated as customer)
        self.client.force_authenticate(user=self.customer)
        confirm_payload = {
            'hold_token': hold_token,
            'payment_method': 'SIMULATED_UPI'
        }
        res_confirm = self.client.post('/api/bookings/confirm/', confirm_payload, format='json')
        self.assertEqual(res_confirm.status_code, status.HTTP_201_CREATED)
        self.assertIn('booking_reference', res_confirm.data)
        self.assertIn('qr_image_base64', res_confirm.data)
        booking_ref = res_confirm.data['booking_reference']
        qr_token = res_confirm.data['qr_token']

        # Gate scanner validation (Staff only)
        self.client.force_authenticate(user=self.staff_user)
        validate_payload = {'token_or_reference': qr_token}
        res_val = self.client.post('/api/staff/validate-ticket/', validate_payload, format='json')
        self.assertEqual(res_val.status_code, status.HTTP_200_OK)
        self.assertTrue(res_val.data['success'])

        # Second validation attempt -> Should fail as ALREADY_USED
        res_val2 = self.client.post('/api/staff/validate-ticket/', validate_payload, format='json')
        self.assertEqual(res_val2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res_val2.data['status'], 'ALREADY_USED')

    def test_04_admin_occupancy_report_rbac(self):
        """RBAC test: Customer cannot access admin report, but Admin can."""
        # Customer access -> Forbidden
        self.client.force_authenticate(user=self.customer)
        res_cust = self.client.get('/api/admin/reports/occupancy/')
        self.assertEqual(res_cust.status_code, status.HTTP_403_FORBIDDEN)

        # Admin access -> OK
        self.client.force_authenticate(user=self.admin_user)
        res_admin = self.client.get('/api/admin/reports/occupancy/')
        self.assertEqual(res_admin.status_code, status.HTTP_200_OK)
        self.assertIn('summary', res_admin.data)
        self.assertIn('shows', res_admin.data)

    def test_05_nosql_status_and_reviews(self):
        """Test NoSQL document collection diagnostics and reviews posting."""
        # Diagnostic status endpoint
        res = self.client.get('/api/nosql/status/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('engine', res.data)
        self.assertIn('collections', res.data)

        # Add customer review via API
        self.client.force_authenticate(user=self.customer)
        review_payload = {
            'rating': 9.2,
            'comment': 'Stunning visual fidelity on the big screen!',
            'tags': ['Visuals', 'Must Watch']
        }
        res_rev = self.client.post(f'/api/movies/{self.movie.id}/reviews/', review_payload, format='json')
        self.assertEqual(res_rev.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_rev.data['comment'], review_payload['comment'])

        # Verify review is stored in NoSQL
        stored_reviews = nosql_service.get_movie_reviews(self.movie.id)
        self.assertGreaterEqual(len(stored_reviews), 1)
        self.assertEqual(stored_reviews[0]['comment'], review_payload['comment'])

