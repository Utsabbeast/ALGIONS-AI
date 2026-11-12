from django.urls import path
from bookings import views

app_name = 'bookings'

urlpatterns = [
    path('shows/<int:showtime_id>/seats/', views.seat_selection_view, name='seat-selection'),
    path('checkout/<str:hold_token>/', views.payment_checkout_view, name='checkout'),
    path('tickets/<str:reference>/', views.booking_confirmation_view, name='booking-confirmation'),
    path('my-bookings/', views.my_bookings_view, name='my-bookings'),
    path('bookings/<str:reference>/cancel/', views.cancel_booking_view, name='cancel-booking'),
    path('staff/gate-scanner/', views.gate_scanner_view, name='gate-scanner'),
    path('admin/dashboard/', views.admin_dashboard_view, name='admin-dashboard'),
]

