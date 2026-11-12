"""
Core Business Services for CinemaBox.
Implements ACID-compliant transactions, concurrency control, temporary seat holds,
QR code generation, gate validation, cancellation/refunds, and NoSQL audit logging.
"""

import uuid
import base64
import io
from decimal import Decimal
from datetime import timedelta
from typing import List, Dict, Any, Optional

from django.db import transaction
from django.db.models import Q, Sum, Count
from django.utils import timezone
from django.core.exceptions import ValidationError

import qrcode

from cinema.models import Showtime, Seat, User
from bookings.models import SeatHold, Booking, BookingSeat
from nosql.service import log_audit_event, log_ticket_scan, nosql


class SeatUnavailableError(Exception):
    """Raised when one or more requested seats are held or booked."""
    pass


class HoldExpiredError(Exception):
    """Raised when attempting to confirm a booking with an expired seat hold."""
    pass


class TicketValidationError(Exception):
    """Raised when a ticket cannot be validated at the entry gate."""
    pass


class TicketAlreadyUsedError(TicketValidationError):
    """Raised when a ticket has already been scanned and checked in."""
    pass


def release_expired_holds(showtime_id: Optional[int] = None) -> int:
    """
    Evaluates and releases expired temporary holds.
    Called before availability queries and booking attempts.
    """
    now = timezone.now()
    qs = SeatHold.objects.filter(status=SeatHold.Status.ACTIVE, expires_at__lt=now)
    if showtime_id:
        qs = qs.filter(showtime_id=showtime_id)

    expired_count = 0
    expired_holds = list(qs.select_related('seat', 'showtime'))
    for hold in expired_holds:
        hold.status = SeatHold.Status.EXPIRED
        hold.save(update_fields=['status'])
        expired_count += 1
        log_audit_event(
            event_type='SEAT_HOLD_EXPIRED',
            actor='system_reaper',
            entity_type='SeatHold',
            entity_id=str(hold.id),
            details={
                'showtime_id': hold.showtime_id,
                'seat_code': hold.seat.seat_code,
                'hold_token': hold.hold_token
            }
        )
    return expired_count


def hold_seats(
    showtime_id: int,
    seat_ids: List[int],
    user: Optional[User] = None,
    hold_minutes: int = 10,
    existing_hold_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Atomically places a temporary hold on the requested seats for a showtime.
    Guarantees no two users can hold or book the same seat simultaneously.
    """
    if not seat_ids:
        raise ValidationError("At least one seat must be selected.")

    # Always flush expired holds first
    release_expired_holds(showtime_id)

    with transaction.atomic():
        showtime = Showtime.objects.select_related('screen', 'movie').get(id=showtime_id)
        if showtime.is_past:
            raise ValidationError("Cannot reserve seats for a past showtime.")

        # Lock the requested seats for this screen to prevent race conditions
        seats = list(
            Seat.objects.select_for_update()
            .filter(id__in=seat_ids, screen=showtime.screen, is_active=True)
        )
        if len(seats) != len(seat_ids):
            raise ValidationError("One or more selected seats are invalid for this screen.")

        # Check for existing active holds
        active_holds_conflict = SeatHold.objects.filter(
            showtime=showtime,
            seat_id__in=seat_ids,
            status=SeatHold.Status.ACTIVE
        )
        if existing_hold_token:
            # Allow renewing or modifying user's own current hold
            active_holds_conflict = active_holds_conflict.exclude(hold_token=existing_hold_token)

        if active_holds_conflict.exists():
            conflicting_codes = list(active_holds_conflict.values_list('seat__seat_code', flat=True))
            raise SeatUnavailableError(
                f"Seat(s) {', '.join(conflicting_codes)} are currently held by another customer. Please choose different seats."
            )

        # Check for confirmed bookings
        booked_conflict = BookingSeat.objects.filter(
            showtime=showtime,
            seat_id__in=seat_ids,
            booking__status=Booking.Status.CONFIRMED
        )
        if booked_conflict.exists():
            conflicting_codes = list(booked_conflict.values_list('seat__seat_code', flat=True))
            raise SeatUnavailableError(
                f"Seat(s) {', '.join(conflicting_codes)} are already booked. Please choose different seats."
            )

        # Generate hold token or reuse existing
        hold_token = existing_hold_token or str(uuid.uuid4())
        expires_at = timezone.now() + timedelta(minutes=hold_minutes)

        created_holds = []
        price_breakdown = []
        total_seat_price = Decimal('0.00')

        for seat in seats:
            price = showtime.get_seat_price(seat.category)
            total_seat_price += price
            price_breakdown.append({
                'seat_id': seat.id,
                'seat_code': seat.seat_code,
                'category': seat.category,
                'price': float(price)
            })

            hold = SeatHold.objects.create(
                showtime=showtime,
                seat=seat,
                user=user if (user and user.is_authenticated) else None,
                hold_token=hold_token,
                status=SeatHold.Status.ACTIVE,
                expires_at=expires_at
            )
            created_holds.append(hold)

        # Convenience fee calculation (e.g. ₹20 per ticket)
        convenience_fee = Decimal('20.00') * len(seats)
        grand_total = total_seat_price + convenience_fee

        # Log audit trail to NoSQL
        log_audit_event(
            event_type='SEAT_HOLD_CREATED',
            actor=user.username if (user and user.is_authenticated) else 'anonymous_guest',
            entity_type='SeatHold',
            entity_id=hold_token,
            details={
                'showtime_id': showtime_id,
                'movie': showtime.movie.title,
                'seats': [s.seat_code for s in seats],
                'expires_at': expires_at.isoformat(),
                'grand_total': float(grand_total)
            }
        )

        return {
            'hold_token': hold_token,
            'showtime_id': showtime_id,
            'expires_at': expires_at,
            'seats': price_breakdown,
            'seat_subtotal': float(total_seat_price),
            'convenience_fee': float(convenience_fee),
            'grand_total': float(grand_total),
            'currency': 'INR'
        }


def release_hold(hold_token: str, user: Optional[User] = None) -> int:
    """
    Releases all active holds associated with a hold token.
    """
    with transaction.atomic():
        holds = SeatHold.objects.filter(hold_token=hold_token, status=SeatHold.Status.ACTIVE)
        count = holds.count()
        if count > 0:
            holds.update(status=SeatHold.Status.RELEASED)
            log_audit_event(
                event_type='SEAT_HOLD_RELEASED',
                actor=user.username if (user and user.is_authenticated) else 'anonymous_guest',
                entity_type='SeatHold',
                entity_id=hold_token,
                details={'released_count': count}
            )
        return count


def generate_qr_code_base64(data_payload: str) -> str:
    """
    Generates a base64-encoded PNG image of the QR code for ticket display.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(data_payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#111827", back_color="#FFFFFF")
    
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return f"data:image/png;base64,{encoded}"


def confirm_booking(
    hold_token: str,
    user: User,
    payment_method: str = 'SIMULATED_UPI',
    payment_details: Optional[Dict[str, Any]] = None
) -> Booking:
    """
    Converts an active seat hold into a confirmed booking.
    Ensures payment simulation, unique booking reference, QR token generation,
    and relational seat allocation.
    """
    # Flush expired holds first
    release_expired_holds()

    with transaction.atomic():
        active_holds = list(
            SeatHold.objects.select_for_update()
            .filter(hold_token=hold_token, status=SeatHold.Status.ACTIVE)
            .select_related('seat', 'showtime', 'showtime__movie', 'showtime__screen', 'showtime__screen__theatre')
        )

        if not active_holds:
            raise HoldExpiredError(
                "Your reservation hold has expired or is invalid. Please select your seats again."
            )

        showtime = active_holds[0].showtime
        seats = [h.seat for h in active_holds]

        # Double check no seat is already confirmed booked
        already_booked = BookingSeat.objects.filter(
            showtime=showtime,
            seat__in=seats,
            booking__status=Booking.Status.CONFIRMED
        )
        if already_booked.exists():
            conflicts = list(already_booked.values_list('seat__seat_code', flat=True))
            raise SeatUnavailableError(
                f"Seat(s) {', '.join(conflicts)} have already been confirmed by another booking."
            )

        # Calculate pricing
        subtotal = Decimal('0.00')
        for s in seats:
            subtotal += showtime.get_seat_price(s.category)

        convenience_fee = Decimal('20.00') * len(seats)
        total_amount = subtotal + convenience_fee

        # Generate unique booking reference and secure QR verification token
        date_str = timezone.now().strftime('%Y%m%d')
        random_suffix = uuid.uuid4().hex[:6].upper()
        booking_reference = f"BMS-{date_str}-{random_suffix}"
        
        qr_token = f"TKT-{uuid.uuid4().hex}"
        simulated_pay_ref = f"PAY-UPI-{uuid.uuid4().hex[:10].upper()}"

        # Create Booking
        booking = Booking.objects.create(
            booking_reference=booking_reference,
            user=user,
            showtime=showtime,
            status=Booking.Status.CONFIRMED,
            total_amount=total_amount,
            convenience_fee=convenience_fee,
            discount_amount=Decimal('0.00'),
            payment_method=payment_method,
            payment_reference=simulated_pay_ref,
            payment_status='COMPLETED',
            qr_token=qr_token,
            is_validated=False
        )

        # Create BookingSeat rows
        for s in seats:
            price = showtime.get_seat_price(s.category)
            BookingSeat.objects.create(
                booking=booking,
                seat=s,
                showtime=showtime,
                seat_price=price,
                seat_category=s.category
            )

        # Mark all holds as CONVERTED
        for hold in active_holds:
            hold.status = SeatHold.Status.CONVERTED
            hold.save(update_fields=['status'])

        # Record material business audit in NoSQL
        log_audit_event(
            event_type='BOOKING_CONFIRMED',
            actor=user.username,
            entity_type='Booking',
            entity_id=booking.booking_reference,
            details={
                'booking_id': booking.id,
                'showtime_id': showtime.id,
                'movie': showtime.movie.title,
                'theatre': showtime.screen.theatre.name,
                'seats': [s.seat_code for s in seats],
                'total_amount': float(total_amount),
                'payment_reference': simulated_pay_ref,
                'qr_token': qr_token
            }
        )

        return booking


def cancel_booking(
    booking_reference: str,
    requested_by: User,
    reason: str = "Customer requested cancellation"
) -> Booking:
    """
    Cancels a confirmed booking, calculates simulated refund, releases seats,
    and logs the audit trail.
    """
    with transaction.atomic():
        try:
            booking = (
                Booking.objects.select_for_update()
                .select_related('showtime', 'showtime__movie', 'user')
                .prefetch_related('seats', 'seats__seat')
                .get(booking_reference=booking_reference)
            )
        except Booking.DoesNotExist:
            raise ValidationError(f"Booking {booking_reference} not found.")

        # RBAC Check: Only owner or staff/admin can cancel
        if not (requested_by.is_cinema_admin or requested_by.is_gate_staff or booking.user_id == requested_by.id):
            raise ValidationError("You are not authorized to cancel this booking.")

        if booking.status == Booking.Status.CANCELLED:
            raise ValidationError("This booking is already cancelled.")

        if booking.is_validated:
            raise ValidationError("Cannot cancel a ticket that has already been validated and scanned at the gate.")

        # Refund policy logic
        now = timezone.now()
        hours_before_show = (booking.showtime.start_time - now).total_seconds() / 3600.0

        if hours_before_show < 0:
            raise ValidationError("Cannot cancel a booking for a show that has already started or ended.")
        elif hours_before_show >= 2.0:
            # Full ticket refund (retaining convenience fee)
            ticket_subtotal = booking.total_amount - booking.convenience_fee
            refund_amount = max(ticket_subtotal, Decimal('0.00'))
            refund_note = "Full ticket price refund (convenience fee non-refundable)"
        else:
            # 50% ticket refund if cancelled within 2 hours of show
            ticket_subtotal = booking.total_amount - booking.convenience_fee
            refund_amount = (ticket_subtotal * Decimal('0.5')).quantize(Decimal('0.01'))
            refund_note = "50% cancellation fee applied within 2 hours of showtime"

        booking.status = Booking.Status.CANCELLED
        booking.cancellation_reason = reason
        booking.refund_amount = refund_amount
        booking.refund_status = f"SIMULATED_REFUND_PROCESSED ({refund_note})"
        booking.cancelled_at = now
        booking.save()

        # Seats are automatically available for subsequent queries because active queries filter out CANCELLED bookings.

        # Log material cancellation audit to NoSQL
        seat_codes = [bs.seat.seat_code for bs in booking.seats.all()]
        log_audit_event(
            event_type='BOOKING_CANCELLED',
            actor=requested_by.username,
            entity_type='Booking',
            entity_id=booking.booking_reference,
            details={
                'movie': booking.showtime.movie.title,
                'seats_released': seat_codes,
                'refund_amount': float(refund_amount),
                'refund_status': booking.refund_status,
                'reason': reason
            }
        )

        return booking


def validate_ticket_entry(
    token_or_reference: str,
    staff_user: User,
    device_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Gate Scanner Service:
    Validates a customer's ticket reference or QR token for entry into the cinema hall.
    Strictly enforces:
    - First scan: APPROVED, marks validated_at & validated_by, logs to NoSQL.
    - Second scan: REJECTED with ALREADY_USED status, logging incident to NoSQL.
    - Cancelled ticket: REJECTED.
    """
    with transaction.atomic():
        token_or_reference = token_or_reference.strip()
        booking = (
            Booking.objects.select_for_update()
            .select_related('showtime', 'showtime__movie', 'showtime__screen', 'showtime__screen__theatre', 'user')
            .prefetch_related('seats', 'seats__seat')
            .filter(Q(qr_token=token_or_reference) | Q(booking_reference=token_or_reference))
            .first()
        )

        if not booking:
            log_ticket_scan(
                booking_reference=token_or_reference,
                qr_token=token_or_reference,
                status='INVALID_TOKEN',
                staff_username=staff_user.username if staff_user else 'unknown',
                message='Ticket reference / QR token not found in database',
                metadata=device_info
            )
            raise TicketValidationError("Invalid ticket. No booking found with this reference or QR token.")

        if booking.status == Booking.Status.CANCELLED:
            log_ticket_scan(
                booking_reference=booking.booking_reference,
                qr_token=booking.qr_token,
                status='REJECTED_CANCELLED',
                staff_username=staff_user.username if staff_user else 'unknown',
                message=f"Attempted entry with CANCELLED booking: {booking.cancellation_reason}",
                metadata=device_info
            )
            raise TicketValidationError(f"Entry Denied: Booking was CANCELLED on {booking.cancelled_at.strftime('%d %b %H:%M')}.")

        if booking.is_validated:
            scanned_time = booking.validated_at.strftime('%d %b %Y %H:%M:%S') if booking.validated_at else 'earlier'
            scanned_by = booking.validated_by.username if booking.validated_by else 'Gate Staff'
            msg = f"Ticket already validated and used for entry at {scanned_time} by {scanned_by}."
            log_ticket_scan(
                booking_reference=booking.booking_reference,
                qr_token=booking.qr_token,
                status='ALREADY_USED',
                staff_username=staff_user.username if staff_user else 'unknown',
                message=msg,
                metadata=device_info
            )
            raise TicketAlreadyUsedError(msg)

        # Mark ticket as validated
        now = timezone.now()
        booking.is_validated = True
        booking.validated_at = now
        booking.validated_by = staff_user
        booking.save(update_fields=['is_validated', 'validated_at', 'validated_by'])

        seat_codes = [s.seat.seat_code for s in booking.seats.all()]
        success_message = f"Valid Ticket! Customer: {booking.user.get_full_name() or booking.user.username} | Seats: {', '.join(seat_codes)}"

        log_ticket_scan(
            booking_reference=booking.booking_reference,
            qr_token=booking.qr_token,
            status='VALID_ENTRY',
            staff_username=staff_user.username if staff_user else 'unknown',
            message=success_message,
            metadata=device_info
        )

        return {
            'success': True,
            'status': 'VALID_ENTRY',
            'message': success_message,
            'booking_reference': booking.booking_reference,
            'customer_name': booking.user.get_full_name() or booking.user.username,
            'movie_title': booking.showtime.movie.title,
            'theatre_name': booking.showtime.screen.theatre.name,
            'screen_name': booking.showtime.screen.name,
            'show_time': booking.showtime.start_time.strftime('%d %b %Y, %I:%M %p'),
            'seats': seat_codes,
            'validated_at': now.isoformat()
        }


def get_show_seat_matrix(showtime_id: int, current_hold_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Builds the complete visual seat matrix for a showtime.
    Classifies each seat as:
    - 'AVAILABLE': Open for selection
    - 'HELD': Locked by another customer
    - 'MY_HOLD': Locked by the current user's session
    - 'BOOKED': Confirmed reservation
    """
    # Clean up expired holds first
    release_expired_holds(showtime_id)

    showtime = (
        Showtime.objects.select_related('movie', 'screen', 'screen__theatre')
        .get(id=showtime_id)
    )

    all_seats = list(
        Seat.objects.filter(screen=showtime.screen, is_active=True)
        .order_by('row_label', 'seat_number')
    )

    # Active holds
    active_holds = SeatHold.objects.filter(
        showtime=showtime,
        status=SeatHold.Status.ACTIVE
    )
    holds_by_seat = {}
    for h in active_holds:
        holds_by_seat[h.seat_id] = h

    # Confirmed booked seats
    confirmed_seat_ids = set(
        BookingSeat.objects.filter(
            showtime=showtime,
            booking__status=Booking.Status.CONFIRMED
        ).values_list('seat_id', flat=True)
    )

    rows_dict = {}
    categories_summary = {}

    for seat in all_seats:
        price = showtime.get_seat_price(seat.category)
        
        if seat.id in confirmed_seat_ids:
            state = 'BOOKED'
        elif seat.id in holds_by_seat:
            hold = holds_by_seat[seat.id]
            if current_hold_token and hold.hold_token == current_hold_token:
                state = 'MY_HOLD'
            else:
                state = 'HELD'
        else:
            state = 'AVAILABLE'

        row = seat.row_label
        if row not in rows_dict:
            rows_dict[row] = []

        seat_info = {
            'id': seat.id,
            'code': seat.seat_code,
            'row': seat.row_label,
            'number': seat.seat_number,
            'category': seat.category,
            'price': float(price),
            'status': state,
        }
        rows_dict[row].append(seat_info)

        # Category pricing summary
        if seat.category not in categories_summary:
            categories_summary[seat.category] = {
                'category': seat.category,
                'price': float(price),
                'total': 0,
                'available': 0
            }
        categories_summary[seat.category]['total'] += 1
        if state == 'AVAILABLE':
            categories_summary[seat.category]['available'] += 1

    total_seats = len(all_seats)
    booked_count = len(confirmed_seat_ids)
    held_count = len(holds_by_seat)
    available_count = max(0, total_seats - booked_count - held_count)
    occupancy_pct = round((booked_count / total_seats * 100), 1) if total_seats > 0 else 0

    return {
        'showtime': {
            'id': showtime.id,
            'movie_title': showtime.movie.title,
            'movie_poster': showtime.movie.poster_url,
            'language': showtime.language,
            'experience': showtime.experience,
            'theatre_name': showtime.screen.theatre.name,
            'theatre_city': showtime.screen.theatre.city,
            'screen_name': showtime.screen.name,
            'start_time': showtime.start_time.isoformat(),
            'start_time_formatted': showtime.start_time.strftime('%a, %d %b | %I:%M %p'),
        },
        'stats': {
            'total_seats': total_seats,
            'available_seats': available_count,
            'held_seats': held_count,
            'booked_seats': booked_count,
            'occupancy_percentage': occupancy_pct,
        },
        'categories': list(categories_summary.values()),
        'rows': [{'row_label': r, 'seats': s} for r, s in sorted(rows_dict.items())],
    }


def get_occupancy_report_data(theatre_id: Optional[int] = None, movie_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Computes occupancy and sales reconciliation metrics for administrative reporting.
    Guarantees that:
    - Confirmed bookings + active holds + available = total capacity.
    - Cancellations decrement confirmed bookings and track simulated refund amounts.
    - Gross revenue, refunds, and net revenue reconcile perfectly.
    """
    release_expired_holds()

    showtimes_qs = Showtime.objects.select_related('movie', 'screen', 'screen__theatre').all()
    if theatre_id:
        showtimes_qs = showtimes_qs.filter(screen__theatre_id=theatre_id)
    if movie_id:
        showtimes_qs = showtimes_qs.filter(movie_id=movie_id)

    show_reports = []
    total_capacity_sum = 0
    total_confirmed_seats_sum = 0
    total_active_holds_sum = 0
    total_cancelled_bookings_sum = 0
    total_gross_revenue_sum = Decimal('0.00')
    total_refunds_sum = Decimal('0.00')

    for show in showtimes_qs.order_by('-start_time'):
        capacity = show.screen.seats.filter(is_active=True).count()
        
        # Confirmed bookings
        confirmed_bookings = Booking.objects.filter(showtime=show, status=Booking.Status.CONFIRMED)
        confirmed_seats_count = BookingSeat.objects.filter(
            showtime=show,
            booking__status=Booking.Status.CONFIRMED
        ).count()
        gross_rev = confirmed_bookings.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')

        # Active holds
        active_holds_count = SeatHold.objects.filter(
            showtime=show,
            status=SeatHold.Status.ACTIVE
        ).count()

        # Cancelled bookings
        cancelled_bookings = Booking.objects.filter(showtime=show, status=Booking.Status.CANCELLED)
        cancelled_count = cancelled_bookings.count()
        refunds_issued = cancelled_bookings.aggregate(total=Sum('refund_amount'))['total'] or Decimal('0.00')

        available_seats = max(0, capacity - confirmed_seats_count - active_holds_count)
        occupancy_rate = round((confirmed_seats_count / capacity * 100), 1) if capacity > 0 else 0
        net_revenue = gross_rev - refunds_issued

        total_capacity_sum += capacity
        total_confirmed_seats_sum += confirmed_seats_count
        total_active_holds_sum += active_holds_count
        total_cancelled_bookings_sum += cancelled_count
        total_gross_revenue_sum += gross_rev
        total_refunds_sum += refunds_issued

        show_reports.append({
            'showtime_id': show.id,
            'movie_title': show.movie.title,
            'theatre_name': show.screen.theatre.name,
            'screen_name': show.screen.name,
            'start_time': show.start_time.strftime('%d %b %Y, %I:%M %p'),
            'total_capacity': capacity,
            'confirmed_seats': confirmed_seats_count,
            'active_holds': active_holds_count,
            'available_seats': available_seats,
            'cancelled_bookings': cancelled_count,
            'occupancy_percentage': occupancy_rate,
            'gross_revenue': float(gross_rev),
            'refunds_issued': float(refunds_issued),
            'net_revenue': float(net_revenue),
        })

    overall_occupancy = (
        round((total_confirmed_seats_sum / total_capacity_sum * 100), 1)
        if total_capacity_sum > 0 else 0
    )

    return {
        'summary': {
            'total_shows': len(show_reports),
            'total_capacity': total_capacity_sum,
            'total_confirmed_seats': total_confirmed_seats_sum,
            'total_active_holds': total_active_holds_sum,
            'total_cancelled_bookings': total_cancelled_bookings_sum,
            'overall_occupancy_percentage': overall_occupancy,
            'total_gross_revenue': float(total_gross_revenue_sum),
            'total_refunds': float(total_refunds_sum),
            'net_revenue': float(total_gross_revenue_sum - total_refunds_sum),
            'currency': 'INR'
        },
        'shows': show_reports
    }

