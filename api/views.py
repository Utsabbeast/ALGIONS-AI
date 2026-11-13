from rest_framework import generics, status, views, permissions, serializers as drf_serializers
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample, inline_serializer

from cinema.models import Movie, Showtime, Theatre, Genre, Screen
from bookings.models import Booking
from bookings import services
from api.serializers import (
    MovieListSerializer, ShowtimeSerializer, TheatreSerializer,
    SeatHoldRequestSerializer, ReleaseHoldRequestSerializer,
    BookingConfirmRequestSerializer, BookingDetailSerializer,
    TicketValidateRequestSerializer, MovieReviewRequestSerializer
)
from api.permissions import IsCinemaStaffOrAdmin, IsCinemaAdmin
from nosql import service as nosql_service


class MovieListAPIView(generics.ListAPIView):
    """
    Search and filter movies currently showing.
    """
    serializer_class = MovieListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = Movie.objects.filter(is_active=True).prefetch_related('genres')
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(description__icontains=search))
        
        genre = self.request.query_params.get('genre')
        if genre:
            qs = qs.filter(genres__slug=genre)
        
        language = self.request.query_params.get('language')
        if language:
            qs = qs.filter(language__iexact=language)
            
        city = self.request.query_params.get('city')
        if city:
            qs = qs.filter(showtimes__screen__theatre__city__iexact=city, showtimes__start_time__gte=timezone.now()).distinct()
            
        return qs


class MovieDetailAPIView(generics.RetrieveAPIView):
    """
    Detailed information for a single movie, including dynamic customer reviews from NoSQL.
    """
    queryset = Movie.objects.filter(is_active=True).prefetch_related('genres')
    serializer_class = MovieListSerializer
    permission_classes = [permissions.AllowAny]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data
        reviews = nosql_service.get_movie_reviews(instance.id, limit=10)
        data['reviews'] = reviews
        return Response(data)


class TheatreListAPIView(generics.ListAPIView):
    serializer_class = TheatreSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = Theatre.objects.filter(is_active=True)
        city = self.request.query_params.get('city')
        if city:
            qs = qs.filter(city__iexact=city)
        return qs


class ShowtimeListAPIView(generics.ListAPIView):
    """
    List upcoming showtimes for a movie, optionally filtered by date and theatre city.
    """
    serializer_class = ShowtimeSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = Showtime.objects.filter(
            is_active=True,
            start_time__gte=timezone.now()
        ).select_related('movie', 'screen', 'screen__theatre')

        movie_id = self.request.query_params.get('movie_id')
        if movie_id:
            try:
                qs = qs.filter(movie_id=int(movie_id))
            except (ValueError, TypeError):
                pass

        city = self.request.query_params.get('city')
        if city:
            qs = qs.filter(screen__theatre__city__iexact=city)

        date_str = self.request.query_params.get('date')
        if date_str:
            try:
                date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
                qs = qs.filter(start_time__date=date)
            except ValueError:
                pass

        return qs.order_by('start_time')


class ShowtimeSeatMatrixAPIView(views.APIView):
    """
    Retrieves the complete interactive seat layout for a showtime.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        responses={200: inline_serializer(
            name='SeatMatrixResponse',
            fields={
                'showtime': drf_serializers.DictField(),
                'stats': drf_serializers.DictField(),
                'categories': drf_serializers.ListField(),
                'rows': drf_serializers.ListField(),
            }
        )}
    )
    def get(self, request, showtime_id):
        hold_token = request.query_params.get('hold_token')
        try:
            matrix = services.get_show_seat_matrix(showtime_id=showtime_id, current_hold_token=hold_token)
            return Response(matrix, status=status.HTTP_200_OK)
        except Showtime.DoesNotExist:
            return Response({'error': 'Showtime not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class SeatHoldAPIView(views.APIView):
    """
    Locks one or more seats with a temporary hold token and expiry countdown timer.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=SeatHoldRequestSerializer,
        responses={201: inline_serializer(
            name='SeatHoldResponse',
            fields={
                'hold_token': drf_serializers.CharField(),
                'showtime_id': drf_serializers.IntegerField(),
                'expires_at': drf_serializers.DateTimeField(),
                'seats': drf_serializers.ListField(),
                'grand_total': drf_serializers.FloatField(),
            }
        )}
    )
    def post(self, request):
        serializer = SeatHoldRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            user = request.user if request.user.is_authenticated else None
            hold_result = services.hold_seats(
                showtime_id=data['showtime_id'],
                seat_ids=data['seat_ids'],
                user=user,
                existing_hold_token=data.get('hold_token')
            )
            return Response(hold_result, status=status.HTTP_201_CREATED)
        except services.SeatUnavailableError as e:
            return Response({'error': str(e), 'code': 'SEAT_UNAVAILABLE'}, status=status.HTTP_409_CONFLICT)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class SeatReleaseAPIView(views.APIView):
    """
    Explicitly releases temporary seat holds when a user deselects seats or abandons cart.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=ReleaseHoldRequestSerializer,
        responses={200: inline_serializer(
            name='SeatReleaseResponse',
            fields={'message': drf_serializers.CharField()}
        )}
    )
    def post(self, request):
        serializer = ReleaseHoldRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = services.release_hold(
            hold_token=serializer.validated_data['hold_token'],
            user=request.user if request.user.is_authenticated else None
        )
        return Response({'message': f'Released {count} held seat(s)'}, status=status.HTTP_200_OK)


class BookingConfirmAPIView(views.APIView):
    """
    Confirms an active reservation hold into a confirmed booking.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=BookingConfirmRequestSerializer,
        responses={201: BookingDetailSerializer}
    )
    def post(self, request):
        serializer = BookingConfirmRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            booking = services.confirm_booking(
                hold_token=data['hold_token'],
                user=request.user,
                payment_method=data.get('payment_method', 'SIMULATED_UPI')
            )
            qr_base64 = services.generate_qr_code_base64(booking.qr_token)

            detail_serializer = BookingDetailSerializer(booking)
            resp_data = detail_serializer.data
            resp_data['qr_image_base64'] = qr_base64

            return Response(resp_data, status=status.HTTP_201_CREATED)
        except services.HoldExpiredError as e:
            return Response({'error': str(e), 'code': 'HOLD_EXPIRED'}, status=status.HTTP_410_GONE)
        except services.SeatUnavailableError as e:
            return Response({'error': str(e), 'code': 'SEAT_CONFLICT'}, status=status.HTTP_409_CONFLICT)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class BookingDetailAPIView(views.APIView):
    """
    Retrieves full booking confirmation receipt, seats, and verifiable QR code.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: BookingDetailSerializer})
    def get(self, request, reference):
        booking = get_object_or_404(
            Booking.objects.select_related('showtime', 'showtime__movie', 'showtime__screen', 'showtime__screen__theatre', 'user')
            .prefetch_related('seats', 'seats__seat'),
            booking_reference=reference
        )

        if not (request.user.is_cinema_admin or request.user.is_gate_staff or booking.user_id == request.user.id):
            return Response({'error': 'Unauthorized to view this booking'}, status=status.HTTP_403_FORBIDDEN)

        serializer = BookingDetailSerializer(booking)
        data = serializer.data
        data['qr_image_base64'] = services.generate_qr_code_base64(booking.qr_token)
        return Response(data, status=status.HTTP_200_OK)


class BookingCancelAPIView(views.APIView):
    """
    Cancels a confirmed reservation, issues simulated refund, and releases seats back to inventory.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=inline_serializer(
            name='CancelRequest',
            fields={'reason': drf_serializers.CharField(required=False, default='Customer cancellation')}
        ),
        responses={200: BookingDetailSerializer}
    )
    def post(self, request, reference):
        reason = request.data.get('reason', 'Customer requested cancellation via portal')
        try:
            booking = services.cancel_booking(
                booking_reference=reference,
                requested_by=request.user,
                reason=reason
            )
            serializer = BookingDetailSerializer(booking)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class UserBookingsListAPIView(generics.ListAPIView):
    """
    Lists all bookings belonging to the currently authenticated user.
    """
    serializer_class = BookingDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Booking.objects.filter(user=self.request.user)
            .select_related('showtime', 'showtime__movie', 'showtime__screen', 'showtime__screen__theatre')
            .prefetch_related('seats', 'seats__seat')
            .order_by('-created_at')
        )


class TicketValidateAPIView(views.APIView):
    """
    Gate Scanner Validation Endpoint (Staff & Admin only).
    """
    permission_classes = [IsCinemaStaffOrAdmin]

    @extend_schema(
        request=TicketValidateRequestSerializer,
        responses={200: inline_serializer(
            name='TicketValidationSuccessResponse',
            fields={
                'success': drf_serializers.BooleanField(),
                'status': drf_serializers.CharField(),
                'message': drf_serializers.CharField(),
                'booking_reference': drf_serializers.CharField(),
                'customer_name': drf_serializers.CharField(),
                'movie_title': drf_serializers.CharField(),
                'seats': drf_serializers.ListField(),
            }
        )}
    )
    def post(self, request):
        serializer = TicketValidateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            device_info = {
                'device_id': data.get('device_id', 'gate-terminal-01'),
                'operator_ip': request.META.get('REMOTE_ADDR', '127.0.0.1')
            }
            res = services.validate_ticket_entry(
                token_or_reference=data['token_or_reference'],
                staff_user=request.user,
                device_info=device_info
            )
            return Response(res, status=status.HTTP_200_OK)
        except services.TicketAlreadyUsedError as e:
            return Response({'success': False, 'status': 'ALREADY_USED', 'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except services.TicketValidationError as e:
            return Response({'success': False, 'status': 'REJECTED', 'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class OccupancyReportAPIView(views.APIView):
    """
    Admin Occupancy & Sales Report Endpoint (Admin only).
    """
    permission_classes = [IsCinemaAdmin]

    @extend_schema(
        responses={200: inline_serializer(
            name='OccupancyReportResponse',
            fields={
                'summary': drf_serializers.DictField(),
                'shows': drf_serializers.ListField(),
            }
        )}
    )
    def get(self, request):
        theatre_id = request.query_params.get('theatre_id')
        movie_id = request.query_params.get('movie_id')

        parsed_theatre_id = None
        if theatre_id:
            try:
                parsed_theatre_id = int(theatre_id)
            except (ValueError, TypeError):
                parsed_theatre_id = None

        parsed_movie_id = None
        if movie_id:
            try:
                parsed_movie_id = int(movie_id)
            except (ValueError, TypeError):
                parsed_movie_id = None

        data = services.get_occupancy_report_data(
            theatre_id=parsed_theatre_id,
            movie_id=parsed_movie_id
        )
        return Response(data, status=status.HTTP_200_OK)


class NoSQLStatusAPIView(views.APIView):
    """
    Diagnostic info about the active NoSQL database and document collections.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        responses={200: inline_serializer(
            name='NoSQLStatusResponse',
            fields={
                'engine': drf_serializers.CharField(),
                'is_mongodb_connected': drf_serializers.BooleanField(),
                'database_name': drf_serializers.CharField(),
                'collections': drf_serializers.DictField(),
            }
        )}
    )
    def get(self, request):
        info = nosql_service.get_nosql_status()
        return Response(info, status=status.HTTP_200_OK)


class NoSQLAuditTrailAPIView(views.APIView):
    """
    Retrieves the immutable audit trail from NoSQL (Admin/Staff only).
    """
    permission_classes = [IsCinemaStaffOrAdmin]

    @extend_schema(
        responses={200: inline_serializer(
            name='NoSQLAuditResponse',
            fields={
                'count': drf_serializers.IntegerField(),
                'events': drf_serializers.ListField(),
            }
        )}
    )
    def get(self, request):
        raw_limit = request.query_params.get('limit', 50)
        try:
            limit = min(max(1, int(raw_limit)), 100)
        except (ValueError, TypeError):
            limit = 50
        trail = nosql_service.get_audit_trail(limit=limit)
        return Response({'count': len(trail), 'events': trail}, status=status.HTTP_200_OK)


class NoSQLTicketScansAPIView(views.APIView):
    """
    Retrieves gate scanner security logs from NoSQL (Admin/Staff only).
    """
    permission_classes = [IsCinemaStaffOrAdmin]

    @extend_schema(
        responses={200: inline_serializer(
            name='NoSQLTicketScansResponse',
            fields={
                'count': drf_serializers.IntegerField(),
                'scans': drf_serializers.ListField(),
            }
        )}
    )
    def get(self, request):
        raw_limit = request.query_params.get('limit', 50)
        try:
            limit = min(max(1, int(raw_limit)), 100)
        except (ValueError, TypeError):
            limit = 50
        scans = nosql_service.get_ticket_scan_logs(limit=limit)
        return Response({'count': len(scans), 'scans': scans}, status=status.HTTP_200_OK)


class MovieReviewCreateAPIView(views.APIView):
    """
    Posts a customer review directly to the NoSQL movie_reviews document collection.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=MovieReviewRequestSerializer,
        responses={201: inline_serializer(
            name='MovieReviewResponse',
            fields={
                'movie_id': drf_serializers.IntegerField(),
                'username': drf_serializers.CharField(),
                'rating': drf_serializers.FloatField(),
                'comment': drf_serializers.CharField(),
                'tags': drf_serializers.ListField(),
            }
        )}
    )
    def post(self, request, movie_id):
        movie = get_object_or_404(Movie, id=movie_id)
        serializer = MovieReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        has_booking = Booking.objects.filter(
            user=request.user,
            showtime__movie=movie,
            status=Booking.Status.CONFIRMED
        ).exists()

        review_doc = nosql_service.add_movie_review(
            movie_id=movie.id,
            username=request.user.get_full_name() or request.user.username,
            rating=data['rating'],
            comment=data['comment'],
            tags=data.get('tags', []),
            verified_booking=has_booking
        )
        return Response(review_doc, status=status.HTTP_201_CREATED)
