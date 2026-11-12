import uuid
from decimal import Decimal
from datetime import timedelta, date, time, datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from cinema.models import User, Genre, Theatre, Screen, Seat, Movie, Showtime
from bookings.models import Booking, BookingSeat, SeatHold
from bookings import services
from nosql import service as nosql_service


class Command(BaseCommand):
    help = 'Seeds realistic cinema booking data (theatres, screens, movies, showtimes, seats, users, and NoSQL reviews)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting database seeding for CinemaBox..."))

        # 1. Create Core Users
        admin_user, _ = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@cinemabox.com',
                'first_name': 'Cinema',
                'last_name': 'Administrator',
                'role': User.Role.ADMIN,
                'is_staff': True,
                'is_superuser': True
            }
        )
        admin_user.set_password('admin123')
        admin_user.save()

        staff_user, _ = User.objects.get_or_create(
            username='staff1',
            defaults={
                'email': 'staff1@cinemabox.com',
                'first_name': 'Vikram',
                'last_name': 'Verma (Gate Staff)',
                'role': User.Role.STAFF,
                'is_staff': True,
            }
        )
        staff_user.set_password('staff123')
        staff_user.save()

        customer_user, _ = User.objects.get_or_create(
            username='customer1',
            defaults={
                'email': 'customer1@cinemabox.com',
                'first_name': 'Aarav',
                'last_name': 'Mehta',
                'role': User.Role.CUSTOMER,
            }
        )
        customer_user.set_password('customer123')
        customer_user.save()

        customer_user2, _ = User.objects.get_or_create(
            username='priya_sharma',
            defaults={
                'email': 'priya@cinemabox.com',
                'first_name': 'Priya',
                'last_name': 'Sharma',
                'role': User.Role.CUSTOMER,
            }
        )
        customer_user2.set_password('customer123')
        customer_user2.save()

        self.stdout.write(self.style.SUCCESS("✓ Seeded demo users (admin, staff1, customer1, priya_sharma)"))

        # 2. Genres
        genre_names = ['Action', 'Sci-Fi', 'Thriller', 'Drama', 'Adventure', 'Animation', 'Comedy']
        genres = {}
        for g_name in genre_names:
            g, _ = Genre.objects.get_or_create(name=g_name)
            genres[g_name] = g

        self.stdout.write(self.style.SUCCESS(f"✓ Seeded {len(genres)} genres"))

        # 3. Theatres & Screens
        theatres_data = [
            {
                'name': 'PVR ICON: Phoenix Palladium',
                'city': 'Mumbai',
                'address': '462, Senapati Bapat Marg, Lower Parel, Mumbai, Maharashtra 400013',
                'facilities': ['IMAX Laser', 'Dolby Atmos', 'Recliner Seats', 'Gourmet Food Court', 'Valet Parking'],
                'screens': [
                    {'name': 'Screen 1 - IMAX Laser', 'type': 'IMAX 3D', 'rows': 8, 'cols': 12},
                    {'name': 'Screen 2 - Dolby Atmos', 'type': 'DOLBY ATMOS', 'rows': 7, 'cols': 10},
                ]
            },
            {
                'name': 'INOX: Megaplex Inorbit Mall',
                'city': 'Mumbai',
                'address': 'Link Road, Malad West, Mumbai, Maharashtra 400064',
                'facilities': ['MX4D', 'Dolby 7.1', 'Executive Lounges', 'Cafe'],
                'screens': [
                    {'name': 'Audi 1 - Premium', 'type': 'STANDARD', 'rows': 7, 'cols': 10},
                    {'name': 'Audi 2 - MX4D', 'type': '4DX', 'rows': 6, 'cols': 8},
                ]
            },
            {
                'name': 'Cinepolis: DLF Avenue Saket',
                'city': 'Delhi-NCR',
                'address': 'A4, Press Enclave Marg, Saket District Centre, New Delhi 110017',
                'facilities': ['Macro XE', 'Dolby Atmos', 'VIP Recliners', 'Coffee Bar'],
                'screens': [
                    {'name': 'Screen 1 - Macro XE', 'type': 'MACRO XE', 'rows': 8, 'cols': 12},
                ]
            },
            {
                'name': 'PVR: The Forum Mall Koramangala',
                'city': 'Bengaluru',
                'address': 'Hosur Road, Chikku Lakshmaiah Layout, Koramangala, Bengaluru 560095',
                'facilities': ['IMAX', 'Gold Class Recliners', 'Parking'],
                'screens': [
                    {'name': 'Screen 1 - IMAX', 'type': 'IMAX', 'rows': 8, 'cols': 12},
                ]
            },
        ]

        all_screens = []
        for t_info in theatres_data:
            theatre, _ = Theatre.objects.get_or_create(
                name=t_info['name'],
                defaults={
                    'city': t_info['city'],
                    'address': t_info['address'],
                    'facilities': t_info['facilities']
                }
            )

            for s_info in t_info['screens']:
                screen, _ = Screen.objects.get_or_create(
                    theatre=theatre,
                    name=s_info['name'],
                    defaults={
                        'screen_type': s_info['type'],
                        'total_rows': s_info['rows'],
                        'total_columns': s_info['cols']
                    }
                )
                all_screens.append(screen)

                # Generate seats if not present
                if screen.seats.count() == 0:
                    row_letters = [chr(ord('A') + r) for r in range(s_info['rows'])]
                    seats_batch = []
                    for r_idx, r_letter in enumerate(row_letters):
                        for col in range(1, s_info['cols'] + 1):
                            # Assign tier based on row position
                            if r_idx < 2:
                                cat = Seat.Category.SILVER
                            elif r_idx < 5:
                                cat = Seat.Category.GOLD
                            elif r_idx < s_info['rows'] - 1:
                                cat = Seat.Category.PLATINUM
                            else:
                                cat = Seat.Category.VIP

                            seats_batch.append(
                                Seat(
                                    screen=screen,
                                    row_label=r_letter,
                                    seat_number=col,
                                    seat_code=f"{r_letter}{col}",
                                    category=cat
                                )
                            )
                    Seat.objects.bulk_create(seats_batch)

        self.stdout.write(self.style.SUCCESS(f"✓ Seeded theatres, screens, and seat layouts"))

        # 4. Movies
        movies_data = [
            {
                'title': 'Dune: Part Two',
                'description': 'Paul Atreides unites with Chani and the Fremen while seeking revenge against the conspirators who destroyed his family. Facing a choice between the love of his life and the fate of the universe, he endeavors to prevent a terrible future only he can foresee.',
                'duration': 166,
                'language': 'English',
                'formats': ['2D', '3D', 'IMAX 3D'],
                'cert': 'UA',
                'genres': ['Sci-Fi', 'Adventure', 'Action'],
                'release_date': date(2026, 3, 1),
                'poster_url': 'https://images.unsplash.com/photo-1534447677768-be436bb09401?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=Way9Dexny3w',
                'rating': Decimal('8.9'),
                'votes': 15200
            },
            {
                'title': 'Oppenheimer',
                'description': 'The story of American scientist J. Robert Oppenheimer and his role in the development of the atomic bomb during World War II, exploring the moral complexity and personal fallout.',
                'duration': 180,
                'language': 'English',
                'formats': ['2D', 'IMAX 70mm'],
                'cert': 'A',
                'genres': ['Drama', 'Thriller'],
                'release_date': date(2026, 7, 21),
                'poster_url': 'https://images.unsplash.com/photo-1478760329108-5c3ed9d495a0?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=uYPbbksJxIg',
                'rating': Decimal('9.1'),
                'votes': 22400
            },
            {
                'title': 'Interstellar: IMAX Special',
                'description': 'When Earth becomes uninhabitable in the future, a farmer and ex-NASA pilot, Joseph Cooper, is tasked to pilot a spacecraft, along with a team of researchers, to find a new planet for humans.',
                'duration': 169,
                'language': 'English',
                'formats': ['2D', 'IMAX'],
                'cert': 'UA',
                'genres': ['Sci-Fi', 'Adventure', 'Drama'],
                'release_date': date(2026, 1, 15),
                'poster_url': 'https://images.unsplash.com/photo-1506703719100-a0f3a48c0f86?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=zSWdZVtXT7E',
                'rating': Decimal('9.3'),
                'votes': 48000
            },
            {
                'title': 'Kalki 2898 AD',
                'description': 'A modern avatar of Vishnu, a Hindu god, who is believed to have descended to the earth to protect the world from evil forces in a dystopian futuristic world.',
                'duration': 181,
                'language': 'Hindi',
                'formats': ['2D', '3D', 'IMAX 3D'],
                'cert': 'UA',
                'genres': ['Action', 'Sci-Fi'],
                'release_date': date(2026, 6, 27),
                'poster_url': 'https://images.unsplash.com/photo-1579546929518-9e396f3cc809?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=kQDd1AhGIHk',
                'rating': Decimal('8.6'),
                'votes': 19500
            },
            {
                'title': 'Spider-Man: Beyond the Spider-Verse',
                'description': 'Miles Morales catapults across the Multiverse, encountering a team of Spider-People charged with protecting its very existence.',
                'duration': 140,
                'language': 'English',
                'formats': ['2D', '3D'],
                'cert': 'U',
                'genres': ['Animation', 'Action', 'Adventure'],
                'release_date': date(2026, 8, 10),
                'poster_url': 'https://images.unsplash.com/photo-1635805737707-575885ab0820?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=cqGjhVJWtEg',
                'rating': Decimal('8.8'),
                'votes': 11800
            },
            {
                'title': 'Fighter: Aerial Combat',
                'description': 'An aspiring young man and his fellow aviators face danger and high-stakes missions as they forge brotherhood and protect their homeland in supersonic fighter jets.',
                'duration': 166,
                'language': 'Hindi',
                'formats': ['2D', '3D', 'IMAX 3D'],
                'cert': 'UA',
                'genres': ['Action', 'Thriller'],
                'release_date': date(2026, 1, 25),
                'poster_url': 'https://images.unsplash.com/photo-1517976487502-5bfb40a3f81e?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=6amIq_mP4xM',
                'rating': Decimal('8.2'),
                'votes': 8400
            },
        ]

        created_movies = []
        for m_data in movies_data:
            movie, _ = Movie.objects.get_or_create(
                title=m_data['title'],
                defaults={
                    'description': m_data['description'],
                    'duration_minutes': m_data['duration'],
                    'language': m_data['language'],
                    'format_types': m_data['formats'],
                    'certification': m_data['cert'],
                    'release_date': m_data['release_date'],
                    'poster_url': m_data['poster_url'],
                    'trailer_url': m_data['trailer_url'],
                    'rating_average': m_data['rating'],
                    'votes_count': m_data['votes']
                }
            )
            # Add genres
            for g_name in m_data['genres']:
                if g_name in genres:
                    movie.genres.add(genres[g_name])
            created_movies.append(movie)

        self.stdout.write(self.style.SUCCESS(f"✓ Seeded {len(created_movies)} movies"))

        # 5. Showtimes (Today and next 5 days)
        now = timezone.now()
        base_date = now.date()
        show_times = [
            time(10, 30),
            time(14, 15),
            time(18, 45),
            time(22, 0)
        ]

        created_showtimes = []
        for day_offset in range(5):
            target_date = base_date + timedelta(days=day_offset)
            for screen in all_screens:
                for idx, movie in enumerate(created_movies[:4]):
                    st_time = show_times[(idx + day_offset) % len(show_times)]
                    start_dt = timezone.make_aware(datetime.combine(target_date, st_time))
                    end_dt = start_dt + timedelta(minutes=movie.duration_minutes + 25)

                    showtime, _ = Showtime.objects.get_or_create(
                        movie=movie,
                        screen=screen,
                        start_time=start_dt,
                        defaults={
                            'end_time': end_dt,
                            'experience': 'IMAX 3D' if 'IMAX' in screen.name else '2D',
                            'language': movie.language,
                            'price_silver': Decimal('160.00'),
                            'price_gold': Decimal('240.00'),
                            'price_platinum': Decimal('350.00'),
                            'price_vip': Decimal('480.00')
                        }
                    )
                    created_showtimes.append(showtime)

        self.stdout.write(self.style.SUCCESS(f"✓ Seeded {len(created_showtimes)} showtimes"))

        # 6. Pre-book some seats to create a realistic living seat map
        first_show = created_showtimes[0]
        seats_to_book = list(first_show.screen.seats.filter(row_label__in=['D', 'E'], seat_number__in=[4, 5, 6]))
        if seats_to_book and not Booking.objects.filter(showtime=first_show).exists():
            hold_res = services.hold_seats(
                showtime_id=first_show.id,
                seat_ids=[s.id for s in seats_to_book],
                user=customer_user,
                hold_minutes=15
            )
            booking = services.confirm_booking(
                hold_token=hold_res['hold_token'],
                user=customer_user,
                payment_method='SIMULATED_UPI'
            )
            self.stdout.write(self.style.SUCCESS(f"✓ Seeded demo confirmed booking: {booking.booking_reference}"))

        # 7. Seed NoSQL Collections (movie reviews and audit logs)
        nosql_service.add_movie_review(
            movie_id=created_movies[0].id,
            username='Aarav Mehta',
            rating=9.5,
            comment='Visually breathtaking in IMAX 3D! The score by Hans Zimmer vibrates through the seats. Must watch!',
            tags=['IMAX Experience', 'Masterpiece', 'Cinematography'],
            verified_booking=True
        )
        nosql_service.add_movie_review(
            movie_id=created_movies[0].id,
            username='Priya Sharma',
            rating=9.0,
            comment='Superb pacing and acting. Timothee and Zendaya had great chemistry.',
            tags=['Great Visuals', 'Paisa Vasool'],
            verified_booking=True
        )
        nosql_service.add_movie_review(
            movie_id=created_movies[1].id,
            username='Rohan Joshi',
            rating=10.0,
            comment='Christopher Nolan at his pinnacle. Cillian Murphy gave an Oscar-worthy performance.',
            tags=['Must Watch', 'Masterpiece'],
            verified_booking=False
        )

        self.stdout.write(self.style.SUCCESS("✓ Seeded NoSQL movie reviews into document collection"))
        self.stdout.write(self.style.SUCCESS("=== SEEDING COMPLETED SUCCESSFULLY! ==="))
