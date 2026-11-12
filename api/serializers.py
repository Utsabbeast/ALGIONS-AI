from rest_framework import serializers
from cinema.models import User, Genre, Theatre, Screen, Seat, Movie, Showtime
from bookings.models import Booking, BookingSeat, SeatHold


class GenreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genre
        fields = ['id', 'name', 'slug']


class TheatreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Theatre
        fields = ['id', 'name', 'city', 'address', 'facilities', 'is_active']


class ScreenSerializer(serializers.ModelSerializer):
    theatre_name = serializers.CharField(source='theatre.name', read_only=True)
    theatre_city = serializers.CharField(source='theatre.city', read_only=True)

    class Meta:
        model = Screen
        fields = ['id', 'theatre', 'theatre_name', 'theatre_city', 'name', 'screen_type', 'total_rows', 'total_columns']


class SeatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Seat
        fields = ['id', 'screen', 'row_label', 'seat_number', 'seat_code', 'category', 'is_active']


class MovieListSerializer(serializers.ModelSerializer):
    genres = GenreSerializer(many=True, read_only=True)
    duration_formatted = serializers.ReadOnlyField()

    class Meta:
        model = Movie
        fields = [
            'id', 'title', 'slug', 'description', 'duration_minutes', 'duration_formatted',
            'language', 'format_types', 'certification', 'genres', 'release_date',
            'poster_url', 'banner_url', 'trailer_url', 'rating_average', 'votes_count', 'is_active'
        ]


class ShowtimeSerializer(serializers.ModelSerializer):
    movie_title = serializers.CharField(source='movie.title', read_only=True)
    movie_poster = serializers.CharField(source='movie.poster_url', read_only=True)
    theatre_name = serializers.CharField(source='screen.theatre.name', read_only=True)
    theatre_city = serializers.CharField(source='screen.theatre.city', read_only=True)
    screen_name = serializers.CharField(source='screen.name', read_only=True)

    class Meta:
        model = Showtime
        fields = [
            'id', 'movie', 'movie_title', 'movie_poster', 'screen', 'theatre_name',
            'theatre_city', 'screen_name', 'start_time', 'end_time', 'experience',
            'language', 'price_silver', 'price_gold', 'price_platinum', 'price_vip', 'is_active'
        ]


class SeatHoldRequestSerializer(serializers.Serializer):
    showtime_id = serializers.IntegerField()
    seat_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    hold_token = serializers.CharField(required=False, allow_blank=True, default='')


class ReleaseHoldRequestSerializer(serializers.Serializer):
    hold_token = serializers.CharField()


class BookingConfirmRequestSerializer(serializers.Serializer):
    hold_token = serializers.CharField()
    payment_method = serializers.CharField(default='SIMULATED_UPI')


class BookingSeatSerializer(serializers.ModelSerializer):
    seat_code = serializers.CharField(source='seat.seat_code', read_only=True)
    row_label = serializers.CharField(source='seat.row_label', read_only=True)
    seat_number = serializers.IntegerField(source='seat.seat_number', read_only=True)

    class Meta:
        model = BookingSeat
        fields = ['id', 'seat', 'seat_code', 'row_label', 'seat_number', 'seat_price', 'seat_category']


class BookingDetailSerializer(serializers.ModelSerializer):
    seats = BookingSeatSerializer(many=True, read_only=True)
    movie_title = serializers.CharField(source='showtime.movie.title', read_only=True)
    movie_poster = serializers.CharField(source='showtime.movie.poster_url', read_only=True)
    theatre_name = serializers.CharField(source='showtime.screen.theatre.name', read_only=True)
    screen_name = serializers.CharField(source='showtime.screen.name', read_only=True)
    show_time = serializers.DateTimeField(source='showtime.start_time', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_reference', 'user', 'user_email', 'user_name', 'showtime',
            'movie_title', 'movie_poster', 'theatre_name', 'screen_name', 'show_time',
            'status', 'total_amount', 'convenience_fee', 'discount_amount', 'payment_method',
            'payment_reference', 'payment_status', 'qr_token', 'is_validated', 'validated_at',
            'cancellation_reason', 'refund_amount', 'refund_status', 'cancelled_at',
            'created_at', 'seats'
        ]


class TicketValidateRequestSerializer(serializers.Serializer):
    token_or_reference = serializers.CharField(
        help_text="QR token (e.g. TKT-...) or booking reference (e.g. BMS-...)"
    )
    device_id = serializers.CharField(required=False, default='gate-terminal-01')


class MovieReviewRequestSerializer(serializers.Serializer):
    rating = serializers.FloatField(min_value=1.0, max_value=10.0)
    comment = serializers.CharField(max_length=1000)
    tags = serializers.ListField(child=serializers.CharField(max_length=30), required=False, default=list)

