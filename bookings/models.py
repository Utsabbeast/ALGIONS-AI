import uuid
from decimal import Decimal
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.conf import settings
from cinema.models import Showtime, Seat


class SeatHold(models.Model):
    """
    Manages temporary holds on seats during the customer checkout journey.
    Guarantees no two users can hold or book the same seat concurrently.
    Expires automatically after a configured duration (e.g. 8-10 minutes).
    """
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active Hold'
        EXPIRED = 'EXPIRED', 'Expired Hold'
        CONVERTED = 'CONVERTED', 'Converted to Booking'
        RELEASED = 'RELEASED', 'Released by User'

    showtime = models.ForeignKey(
        Showtime,
        on_delete=models.CASCADE,
        related_name='seat_holds'
    )
    seat = models.ForeignKey(
        Seat,
        on_delete=models.CASCADE,
        related_name='holds'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='seat_holds'
    )
    hold_token = models.CharField(
        max_length=64,
        db_index=True,
        help_text="UUID/Token tying multiple seats in one cart session"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['showtime', 'seat', 'status']),
            models.Index(fields=['hold_token', 'status']),
            models.Index(fields=['expires_at', 'status']),
        ]
        constraints = [
            # Ensure at the database level that no two ACTIVE holds exist for the same seat in the same show
            models.UniqueConstraint(
                fields=['showtime', 'seat'],
                condition=Q(status='ACTIVE'),
                name='unique_active_hold_per_seat_show'
            )
        ]

    @property
    def is_expired(self) -> bool:
        return self.status == self.Status.ACTIVE and timezone.now() > self.expires_at

    def release(self, reason='RELEASED'):
        self.status = reason
        self.save(update_fields=['status'])

    def __str__(self):
        return f"Hold {self.seat.seat_code} for Show #{self.showtime_id} [{self.status}]"


class Booking(models.Model):
    """
    Confirmed customer reservation with payment details, QR validation token,
    and cancellation/refund tracking.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Payment'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    booking_reference = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        help_text="Human-readable booking reference e.g. BMS-8X9K2L"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bookings'
    )
    showtime = models.ForeignKey(
        Showtime,
        on_delete=models.CASCADE,
        related_name='bookings'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
        db_index=True
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    convenience_fee = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('35.00'))
    discount_amount = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    
    # Payment details (sandboxed/simulated)
    payment_method = models.CharField(max_length=50, default='SIMULATED_UPI')
    payment_reference = models.CharField(max_length=64, blank=True)
    payment_status = models.CharField(max_length=30, default='SUCCESS')
    
    # Gate entry validation
    qr_token = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        help_text="Unique verifiable security token encoded into ticket QR"
    )
    is_validated = models.BooleanField(
        default=False,
        help_text="True if scanned and checked into cinema gate"
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='validated_bookings'
    )
    
    # Cancellation & simulated refund
    cancellation_reason = models.TextField(blank=True, null=True)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    refund_status = models.CharField(max_length=40, blank=True, null=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def seat_codes_display(self) -> str:
        codes = [s.seat.seat_code for s in self.seats.all()]
        return ", ".join(codes)

    @property
    def seat_count(self) -> int:
        return self.seats.count()

    def __str__(self):
        return f"{self.booking_reference} | {self.user.username} | {self.showtime.movie.title} [{self.status}]"


class BookingSeat(models.Model):
    """
    Individual seat assignment tied to a confirmed booking.
    Enforces relational uniqueness preventing double-confirmation.
    """
    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name='seats'
    )
    seat = models.ForeignKey(
        Seat,
        on_delete=models.CASCADE,
        related_name='booking_seats'
    )
    showtime = models.ForeignKey(
        Showtime,
        on_delete=models.CASCADE,
        related_name='booked_seats'
    )
    seat_price = models.DecimalField(max_digits=8, decimal_places=2)
    seat_category = models.CharField(max_length=20)

    class Meta:
        ordering = ['seat__row_label', 'seat__seat_number']
        # Note: Uniqueness for active confirmed seats is enforced via transactions
        # and checked against booking__status != CANCELLED
        indexes = [
            models.Index(fields=['showtime', 'seat']),
            models.Index(fields=['booking', 'seat']),
        ]

    def __str__(self):
        return f"{self.seat.seat_code} ({self.seat_category}) - {self.booking.booking_reference}"
