from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Q
from decimal import Decimal
import json

from cinema.models import Showtime, Seat, Movie, Theatre, Screen
from bookings.models import Booking, SeatHold, BookingSeat
from bookings import services
from nosql import service as nosql_service


def seat_selection_view(request, showtime_id):
    """
    Interactive BookMyShow-style seat map with tiers (VIP, Platinum, Gold, Silver),
    real-time availability, hold timer, and price summary.
    """
    showtime = get_object_or_404(
        Showtime.objects.select_related('movie', 'screen', 'screen__theatre'),
        id=showtime_id,
        is_active=True
    )
    
    # Existing hold token in session or query param
    hold_token = request.session.get('current_hold_token')

    matrix_data = services.get_show_seat_matrix(
        showtime_id=showtime.id,
        current_hold_token=hold_token
    )

    context = {
        'showtime': showtime,
        'matrix_data': matrix_data,
        'rows': matrix_data['rows'],
        'categories': matrix_data['categories'],
        'stats': matrix_data['stats'],
        'hold_token': hold_token or '',
    }
    return render(request, 'bookings/seat_selection.html', context)


@login_required
def payment_checkout_view(request, hold_token):
    """
    Simulated checkout page with price breakdown, convenience fee, and payment gateway simulation.
    """
    # Flush expired holds first
    services.release_expired_holds()

    active_holds = list(
        SeatHold.objects.filter(hold_token=hold_token, status=SeatHold.Status.ACTIVE)
        .select_related('seat', 'showtime', 'showtime__movie', 'showtime__screen', 'showtime__screen__theatre')
    )

    if not active_holds:
        messages.error(request, "Your temporary seat reservation has expired. Please select your seats again.")
        return redirect('cinema:home')

    showtime = active_holds[0].showtime
    seats = [h.seat for h in active_holds]

    subtotal = sum(showtime.get_seat_price(s.category) for s in seats)
    convenience_fee = Decimal('20.00') * len(seats)
    grand_total = subtotal + convenience_fee

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method', 'SIMULATED_UPI')
        try:
            booking = services.confirm_booking(
                hold_token=hold_token,
                user=request.user,
                payment_method=payment_method
            )
            # Clear hold from session
            if 'current_hold_token' in request.session:
                del request.session['current_hold_token']

            messages.success(request, f"Booking confirmed! Booking Reference: {booking.booking_reference}")
            return redirect('bookings:booking-confirmation', reference=booking.booking_reference)
        except Exception as e:
            messages.error(request, f"Booking confirmation failed: {str(e)}")
            return redirect('bookings:seat-selection', showtime_id=showtime.id)

    # Check seconds remaining
    now = timezone.now()
    expires_at = active_holds[0].expires_at
    seconds_remaining = max(0, int((expires_at - now).total_seconds()))

    context = {
        'showtime': showtime,
        'seats': seats,
        'seat_codes': ", ".join(s.seat_code for s in seats),
        'subtotal': subtotal,
        'convenience_fee': convenience_fee,
        'grand_total': grand_total,
        'hold_token': hold_token,
        'seconds_remaining': seconds_remaining,
    }
    return render(request, 'bookings/checkout.html', context)


@login_required
def booking_confirmation_view(request, reference):
    """
    Display confirmed ticket with unique QR Code, seat details, and print capability.
    """
    booking = get_object_or_404(
        Booking.objects.select_related('showtime', 'showtime__movie', 'showtime__screen', 'showtime__screen__theatre', 'user')
        .prefetch_related('seats', 'seats__seat'),
        booking_reference=reference
    )

    if not (request.user.is_cinema_admin or request.user.is_gate_staff or booking.user_id == request.user.id):
        messages.error(request, "You are not authorized to view this ticket.")
        return redirect('cinema:home')

    qr_image_base64 = services.generate_qr_code_base64(booking.qr_token)

    context = {
        'booking': booking,
        'qr_image_base64': qr_image_base64,
    }
    return render(request, 'bookings/ticket_confirmation.html', context)


@login_required
def my_bookings_view(request):
    """
    Customer booking history with status and simulated cancellation action.
    """
    bookings = (
        Booking.objects.filter(user=request.user)
        .select_related('showtime', 'showtime__movie', 'showtime__screen', 'showtime__screen__theatre')
        .prefetch_related('seats', 'seats__seat')
        .order_by('-created_at')
    )

    context = {
        'bookings': bookings,
    }
    return render(request, 'bookings/my_bookings.html', context)


@login_required
def cancel_booking_view(request, reference):
    """
    Processes customer cancellation, refunds, and restores seats back to inventory.
    """
    if request.method == 'POST':
        reason = request.POST.get('reason', 'Customer requested cancellation from portal')
        try:
            booking = services.cancel_booking(
                booking_reference=reference,
                requested_by=request.user,
                reason=reason
            )
            messages.success(
                request,
                f"Booking {booking.booking_reference} has been cancelled. Refund of ₹{booking.refund_amount} processed ({booking.refund_status})."
            )
        except Exception as e:
            messages.error(request, f"Cancellation failed: {str(e)}")

    return redirect('bookings:my-bookings')


@login_required
def gate_scanner_view(request):
    """
    Operational gate validator for staff to scan ticket QRs and references.
    """
    if not (request.user.is_gate_staff or request.user.is_cinema_admin):
        messages.error(request, "Access restricted to Cinema Staff and Administrators.")
        return redirect('cinema:home')

    validation_result = None

    if request.method == 'POST':
        token = request.POST.get('token', '').strip()
        device_id = request.POST.get('device_id', 'Staff-Gate-Terminal-1')
        try:
            device_info = {
                'device_id': device_id,
                'staff_username': request.user.username,
                'ip': request.META.get('REMOTE_ADDR', '127.0.0.1')
            }
            res = services.validate_ticket_entry(
                token_or_reference=token,
                staff_user=request.user,
                device_info=device_info
            )
            validation_result = res
            messages.success(request, f"ENTRY APPROVED: {res['message']}")
        except services.TicketAlreadyUsedError as e:
            validation_result = {'success': False, 'status': 'ALREADY_USED', 'error': str(e)}
            messages.warning(request, f"ENTRY REJECTED: {str(e)}")
        except services.TicketValidationError as e:
            validation_result = {'success': False, 'status': 'REJECTED', 'error': str(e)}
            messages.error(request, f"ENTRY DENIED: {str(e)}")
        except Exception as e:
            validation_result = {'success': False, 'status': 'ERROR', 'error': str(e)}
            messages.error(request, f"Error: {str(e)}")

    # Fetch recent scan audit logs from NoSQL
    scan_logs = nosql_service.get_ticket_scan_logs(limit=25)

    context = {
        'validation_result': validation_result,
        'scan_logs': scan_logs,
    }
    return render(request, 'bookings/gate_scanner.html', context)


@login_required
def admin_dashboard_view(request):
    """
    Cinema Administrator Dashboard:
    - Occupancy and sales reconciliation report.
    - NoSQL Database health and document stats.
    - Material business audit trail.
    """
    if not request.user.is_cinema_admin:
        messages.error(request, "Access restricted to Cinema Administrators.")
        return redirect('cinema:home')

    theatre_id = request.GET.get('theatre_id')
    movie_id = request.GET.get('movie_id')

    report_data = services.get_occupancy_report_data(
        theatre_id=int(theatre_id) if theatre_id else None,
        movie_id=int(movie_id) if movie_id else None
    )

    nosql_status = nosql_service.get_nosql_status()
    audit_events = nosql_service.get_audit_trail(limit=30)
    theatres = Theatre.objects.filter(is_active=True)
    movies = Movie.objects.filter(is_active=True)

    context = {
        'summary': report_data['summary'],
        'shows': report_data['shows'],
        'nosql_status': nosql_status,
        'audit_events': audit_events,
        'theatres': theatres,
        'movies': movies,
        'selected_theatre_id': int(theatre_id) if theatre_id else None,
        'selected_movie_id': int(movie_id) if movie_id else None,
    }
    return render(request, 'bookings/admin_dashboard.html', context)
