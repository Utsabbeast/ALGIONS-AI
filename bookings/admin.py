from django.contrib import admin
from bookings.models import SeatHold, Booking, BookingSeat


class BookingSeatInline(admin.TabularInline):
    model = BookingSeat
    extra = 0
    readonly_fields = ['seat', 'showtime', 'seat_price', 'seat_category']


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = [
        'booking_reference', 'user', 'showtime', 'status',
        'total_amount', 'payment_status', 'is_validated', 'created_at'
    ]
    list_filter = ['status', 'payment_status', 'is_validated', 'created_at']
    search_fields = ['booking_reference', 'user__username', 'user__email', 'qr_token']
    readonly_fields = ['booking_reference', 'qr_token', 'created_at', 'updated_at']
    inlines = [BookingSeatInline]


@admin.register(SeatHold)
class SeatHoldAdmin(admin.ModelAdmin):
    list_display = ['seat', 'showtime', 'user', 'hold_token', 'status', 'expires_at', 'created_at']
    list_filter = ['status', 'showtime', 'created_at']
    search_fields = ['hold_token', 'seat__seat_code']
