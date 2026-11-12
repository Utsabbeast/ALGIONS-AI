from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from cinema.models import User, Genre, Theatre, Screen, Seat, Movie, Showtime


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'role', 'phone', 'is_staff']
    list_filter = ['role', 'is_staff', 'is_superuser']
    fieldsets = UserAdmin.fieldsets + (
        ('CinemaBox Role & Profile', {'fields': ('role', 'phone')}),
    )


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Theatre)
class TheatreAdmin(admin.ModelAdmin):
    list_display = ['name', 'city', 'is_active', 'created_at']
    list_filter = ['city', 'is_active']
    search_fields = ['name', 'address']


class SeatInline(admin.TabularInline):
    model = Seat
    extra = 0
    fields = ['seat_code', 'row_label', 'seat_number', 'category', 'is_active']
    readonly_fields = ['seat_code']


@admin.register(Screen)
class ScreenAdmin(admin.ModelAdmin):
    list_display = ['name', 'theatre', 'screen_type', 'total_rows', 'total_columns', 'total_seats']
    list_filter = ['theatre', 'screen_type']
    inlines = [SeatInline]


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['seat_code', 'screen', 'category', 'is_active']
    list_filter = ['screen__theatre', 'screen', 'category', 'is_active']
    search_fields = ['seat_code']


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['title', 'language', 'duration_minutes', 'certification', 'rating_average', 'release_date', 'is_active']
    list_filter = ['language', 'certification', 'is_active', 'genres']
    search_fields = ['title', 'description']
    prepopulated_fields = {'slug': ('title',)}


@admin.register(Showtime)
class ShowtimeAdmin(admin.ModelAdmin):
    list_display = ['movie', 'screen', 'start_time', 'experience', 'price_gold', 'is_active']
    list_filter = ['movie', 'screen__theatre', 'experience', 'start_time']
