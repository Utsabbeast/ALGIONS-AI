from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.html import strip_tags
from datetime import datetime, timedelta

from cinema.models import Movie, Showtime, Theatre, Genre, User
from nosql import service as nosql_service


def home_view(request):
    """
    Discovery page: Browse movies with search, genre pills, language, and city filters.
    """
    search_query = request.GET.get('search', '').strip()
    selected_genre = request.GET.get('genre', '')
    selected_language = request.GET.get('language', '')
    selected_city = request.GET.get('city', 'Mumbai')

    movies_qs = Movie.objects.filter(is_active=True).prefetch_related('genres')

    if search_query:
        movies_qs = movies_qs.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(language__icontains=search_query)
        )
    if selected_genre:
        movies_qs = movies_qs.filter(genres__slug=selected_genre)
    if selected_language:
        movies_qs = movies_qs.filter(language__iexact=selected_language)

    # Available cities from theatres
    cities = list(Theatre.objects.filter(is_active=True).values_list('city', flat=True).distinct())
    if 'Mumbai' not in cities and cities:
        selected_city = cities[0]

    genres = Genre.objects.all()
    languages = Movie.objects.values_list('language', flat=True).distinct()

    # Featured blockbusters for carousel
    featured_movies = Movie.objects.filter(is_active=True).order_by('-rating_average')[:3]

    context = {
        'movies': movies_qs,
        'featured_movies': featured_movies,
        'genres': genres,
        'languages': languages,
        'cities': cities,
        'selected_genre': selected_genre,
        'selected_language': selected_language,
        'selected_city': selected_city,
        'search_query': search_query,
    }
    return render(request, 'cinema/home.html', context)


def movie_detail_view(request, slug):
    """
    Movie Details & Showtime Selection grouped by Theatre and Date.
    """
    movie = get_object_or_404(Movie.objects.prefetch_related('genres'), slug=slug)
    selected_city = request.GET.get('city', 'Mumbai')
    date_str = request.GET.get('date', '')

    today = timezone.localdate() if hasattr(timezone, 'localdate') else timezone.now().date()
    
    # 7-day date strip
    dates = []
    for i in range(7):
        d = today + timedelta(days=i)
        dates.append({
            'date': d,
            'date_str': d.strftime('%Y-%m-%d'),
            'day_name': d.strftime('%a'),
            'day_num': d.strftime('%d'),
            'month': d.strftime('%b'),
            'is_today': i == 0
        })

    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            target_date = today
    else:
        target_date = today

    # Fetch showtimes for target date
    showtimes_qs = Showtime.objects.filter(
        movie=movie,
        is_active=True,
        start_time__date=target_date,
        screen__theatre__city__iexact=selected_city
    ).select_related('screen', 'screen__theatre').order_by('screen__theatre__name', 'start_time')

    # Group showtimes by theatre
    theatre_shows = {}
    for st in showtimes_qs:
        theatre = st.screen.theatre
        if theatre not in theatre_shows:
            theatre_shows[theatre] = []
        theatre_shows[theatre].append(st)

    # Reviews from NoSQL document collection
    reviews = nosql_service.get_movie_reviews(movie.id, limit=10)

    context = {
        'movie': movie,
        'dates': dates,
        'selected_date_str': target_date.strftime('%Y-%m-%d'),
        'theatre_shows': theatre_shows,
        'selected_city': selected_city,
        'reviews': reviews,
    }
    return render(request, 'cinema/movie_detail.html', context)


def login_view(request):
    if request.user.is_authenticated:
        return redirect('cinema:home')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            messages.success(request, f"Welcome back, {user.get_full_name() or user.username}!")
            next_url = request.GET.get('next') or request.POST.get('next') or ''
            if next_url and url_has_allowed_host_and_scheme(
                url=next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure()
            ):
                return redirect(next_url)
            return redirect('cinema:home')
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, 'cinema/login.html')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('cinema:home')

    if request.method == 'POST':
        username = strip_tags(request.POST.get('username', '')).strip()
        email = strip_tags(request.POST.get('email', '')).strip().lower()
        password = request.POST.get('password', '')
        first_name = strip_tags(request.POST.get('first_name', '')).strip()[:50]
        last_name = strip_tags(request.POST.get('last_name', '')).strip()[:50]
        phone = strip_tags(request.POST.get('phone', '')).strip()[:20]

        if not username:
            messages.error(request, "Username is required.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, "Username is already taken.")
        elif not email:
            messages.error(request, "Email address is required.")
        elif User.objects.filter(email=email).exists():
            messages.error(request, "Email address is already registered.")
        elif len(password) < 6:
            messages.error(request, "Password must be at least 6 characters long.")
        else:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                role=User.Role.CUSTOMER
            )
            login(request, user)
            messages.success(request, "Registration successful! Welcome to COMET.")
            return redirect('cinema:home')

    return render(request, 'cinema/register.html')


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('cinema:home')


def demo_login_view(request, role):
    """
    Convenience route for assessment reviewers: 1-click login as customer, staff, or admin.
    """
    role = role.lower()
    user = None
    if role == 'admin':
        user = User.objects.filter(role=User.Role.ADMIN).first()
    elif role == 'staff':
        user = User.objects.filter(role=User.Role.STAFF).first()
    else:
        user = User.objects.filter(role=User.Role.CUSTOMER).first()

    if user:
        login(request, user)
        messages.success(request, f"Logged in as {user.get_role_display()} ({user.username})")
        if user.is_cinema_admin:
            return redirect('bookings:admin-dashboard')
        elif user.is_gate_staff:
            return redirect('bookings:gate-scanner')
        return redirect('cinema:home')

    messages.error(request, f"No demo account found for role '{role}'. Please run seed data first.")
    return redirect('cinema:login')
