from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.text import slugify
from django.utils import timezone
from decimal import Decimal


class User(AbstractUser):
    """
    Custom user model with Role-Based Access Control (RBAC).
    Roles:
      - customer: Standard ticket buyers
      - staff: Theatre operational gatekeepers / ticket scanners
      - admin: Cinema managers / schedules & reporting controllers
    """
    class Role(models.TextChoices):
        CUSTOMER = 'customer', 'Customer'
        STAFF = 'staff', 'Theatre Staff (Gate Scanner)'
        ADMIN = 'admin', 'Cinema Admin / Manager'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
        help_text="Role determining user authorization privileges"
    )
    phone = models.CharField(max_length=20, blank=True, null=True)

    @property
    def is_cinema_admin(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_gate_staff(self) -> bool:
        return self.role in (self.Role.STAFF, self.Role.ADMIN) or self.is_staff or self.is_superuser

    @property
    def is_customer(self) -> bool:
        return self.role == self.Role.CUSTOMER

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class Genre(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=70, unique=True, blank=True)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Theatre(models.Model):
    name = models.CharField(max_length=150)
    city = models.CharField(max_length=100, db_index=True)
    address = models.TextField()
    facilities = models.JSONField(
        default=list,
        blank=True,
        help_text="List of amenities: ['Dolby Atmos', 'Recliners', '4K Laser Projection', 'Parking', 'Food Court']"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['city', 'name']

    def __str__(self):
        return f"{self.name} - {self.city}"


class Screen(models.Model):
    theatre = models.ForeignKey(Theatre, on_delete=models.CASCADE, related_name='screens')
    name = models.CharField(max_length=80, help_text="e.g. Screen 1 - IMAX, Audi 2 - Atmos")
    screen_type = models.CharField(max_length=40, default='STANDARD')
    total_rows = models.PositiveIntegerField(default=10)
    total_columns = models.PositiveIntegerField(default=12)

    class Meta:
        ordering = ['theatre', 'name']
        unique_together = ('theatre', 'name')

    @property
    def total_seats(self) -> int:
        return self.seats.filter(is_active=True).count()

    def __str__(self):
        return f"{self.theatre.name} | {self.name}"


class Seat(models.Model):
    class Category(models.TextChoices):
        SILVER = 'SILVER', 'Silver'
        GOLD = 'GOLD', 'Gold'
        PLATINUM = 'PLATINUM', 'Platinum'
        VIP = 'VIP', 'VIP Recliner'

    screen = models.ForeignKey(Screen, on_delete=models.CASCADE, related_name='seats')
    row_label = models.CharField(max_length=5, help_text="A, B, C... ")
    seat_number = models.PositiveIntegerField(help_text="1, 2, 3... ")
    seat_code = models.CharField(max_length=10, db_index=True, help_text="e.g. A1, B12")
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.GOLD)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['screen', 'row_label', 'seat_number']
        unique_together = ('screen', 'row_label', 'seat_number')
        indexes = [
            models.Index(fields=['screen', 'seat_code']),
        ]

    def save(self, *args, **kwargs):
        if not self.seat_code:
            self.seat_code = f"{self.row_label.upper()}{self.seat_number}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.screen.name} - {self.seat_code} ({self.category})"


class Movie(models.Model):
    title = models.CharField(max_length=200, db_index=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField()
    duration_minutes = models.PositiveIntegerField(help_text="Duration in minutes")
    language = models.CharField(max_length=60, default='English')
    format_types = models.JSONField(
        default=list,
        blank=True,
        help_text="e.g. ['2D', '3D', 'IMAX 3D', '4DX']"
    )
    certification = models.CharField(max_length=15, default='UA', help_text="U, UA, A, PG-13, R")
    genres = models.ManyToManyField(Genre, related_name='movies')
    release_date = models.DateField()
    poster_url = models.URLField(max_length=500, blank=True)
    banner_url = models.URLField(max_length=500, blank=True)
    trailer_url = models.URLField(max_length=500, blank=True)
    rating_average = models.DecimalField(max_digits=3, decimal_places=1, default=8.5)
    votes_count = models.PositiveIntegerField(default=1200)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-release_date', 'title']

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Movie.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def duration_formatted(self) -> str:
        hours = self.duration_minutes // 60
        mins = self.duration_minutes % 60
        return f"{hours}h {mins}m" if hours else f"{mins}m"

    def __str__(self):
        return f"{self.title} ({self.language})"


class Showtime(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='showtimes')
    screen = models.ForeignKey(Screen, on_delete=models.CASCADE, related_name='showtimes')
    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField()
    experience = models.CharField(max_length=30, default='2D', help_text="2D, 3D, IMAX 3D, etc.")
    language = models.CharField(max_length=50, default='English')
    
    # Tiered pricing
    price_silver = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('150.00'))
    price_gold = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('220.00'))
    price_platinum = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('320.00'))
    price_vip = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('450.00'))
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start_time']
        indexes = [
            models.Index(fields=['movie', 'start_time']),
            models.Index(fields=['screen', 'start_time']),
        ]

    def get_seat_price(self, category: str) -> Decimal:
        cat = category.upper()
        if cat == Seat.Category.SILVER:
            return self.price_silver
        elif cat == Seat.Category.GOLD:
            return self.price_gold
        elif cat == Seat.Category.PLATINUM:
            return self.price_platinum
        elif cat == Seat.Category.VIP:
            return self.price_vip
        return self.price_gold

    @property
    def is_past(self) -> bool:
        return self.start_time < timezone.now()

    def __str__(self):
        return f"{self.movie.title} @ {self.screen} on {self.start_time.strftime('%d %b %H:%M')}"
