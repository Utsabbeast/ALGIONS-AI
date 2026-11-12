from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from api import views

app_name = 'api'

urlpatterns = [
    # OpenAPI Schema & Documentation
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='api:schema'), name='swagger-ui'),
    path('redoc/', SpectacularRedocView.as_view(url_name='api:schema'), name='redoc'),

    # Movies & Theatres
    path('movies/', views.MovieListAPIView.as_view(), name='movie-list'),
    path('movies/<int:pk>/', views.MovieDetailAPIView.as_view(), name='movie-detail'),
    path('movies/<int:movie_id>/reviews/', views.MovieReviewCreateAPIView.as_view(), name='movie-add-review'),
    path('theatres/', views.TheatreListAPIView.as_view(), name='theatre-list'),
    path('showtimes/', views.ShowtimeListAPIView.as_view(), name='showtime-list'),

    # Real-time Seat Layout & Reservation Workflow
    path('showtimes/<int:showtime_id>/seats/', views.ShowtimeSeatMatrixAPIView.as_view(), name='showtime-seats'),
    path('bookings/hold/', views.SeatHoldAPIView.as_view(), name='seat-hold'),
    path('bookings/release/', views.SeatReleaseAPIView.as_view(), name='seat-release'),
    path('bookings/confirm/', views.BookingConfirmAPIView.as_view(), name='booking-confirm'),
    path('bookings/my-bookings/', views.UserBookingsListAPIView.as_view(), name='my-bookings'),
    path('bookings/<str:reference>/', views.BookingDetailAPIView.as_view(), name='booking-detail'),
    path('bookings/<str:reference>/cancel/', views.BookingCancelAPIView.as_view(), name='booking-cancel'),

    # Staff Gate Scanner & Ticket Validation
    path('staff/validate-ticket/', views.TicketValidateAPIView.as_view(), name='staff-validate-ticket'),

    # Admin Operations & Analytics
    path('admin/reports/occupancy/', views.OccupancyReportAPIView.as_view(), name='admin-occupancy-report'),

    # NoSQL Diagnostic & Audit Endpoints
    path('nosql/status/', views.NoSQLStatusAPIView.as_view(), name='nosql-status'),
    path('nosql/audit-trail/', views.NoSQLAuditTrailAPIView.as_view(), name='nosql-audit-trail'),
    path('nosql/ticket-scans/', views.NoSQLTicketScansAPIView.as_view(), name='nosql-ticket-scans'),
]

