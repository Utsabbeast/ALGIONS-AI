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
        self.stdout.write(self.style.NOTICE("Starting database seeding for COMET..."))

        # 1. Create Core Users
        admin_user, _ = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@comet.test',
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
                'email': 'staff1@comet.test',
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
                'email': 'customer1@comet.test',
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
                'email': 'priya@comet.test',
                'first_name': 'Priya',
                'last_name': 'Sharma',
                'role': User.Role.CUSTOMER,
            }
        )
        customer_user2.set_password('customer123')
        customer_user2.save()

        self.stdout.write(self.style.SUCCESS("✓ Seeded demo users (admin, staff1, customer1, priya_sharma)"))

        # 2. Genres
        genre_names = [
            'Action', 'Sci-Fi', 'Thriller', 'Drama', 'Adventure',
            'Animation', 'Comedy', 'Horror', 'Crime', 'Fantasy', 'Biography'
        ]
        genres = {}
        for g_name in genre_names:
            g, _ = Genre.objects.get_or_create(name=g_name)
            genres[g_name] = g

        self.stdout.write(self.style.SUCCESS(f"✓ Seeded {len(genres)} genres"))

        # 3. Theatres & Screens across Metropolitan Hubs
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
                'name': 'Cinepolis: Nexus Seawoods',
                'city': 'Mumbai',
                'address': 'Sector 40, Seawoods Railway Station, Navi Mumbai 400706',
                'facilities': ['VIP Lounge', 'Dolby Atmos', 'Laser Projection'],
                'screens': [
                    {'name': 'Audi 1 - Laser 4K', 'type': 'STANDARD', 'rows': 7, 'cols': 10},
                ]
            },
            {
                'name': 'Cinepolis: DLF Avenue Saket',
                'city': 'Delhi-NCR',
                'address': 'A4, Press Enclave Marg, Saket District Centre, New Delhi 110017',
                'facilities': ['Macro XE', 'Dolby Atmos', 'VIP Recliners', 'Coffee Bar'],
                'screens': [
                    {'name': 'Screen 1 - Macro XE', 'type': 'MACRO XE', 'rows': 8, 'cols': 12},
                    {'name': 'Screen 2 - Club Class', 'type': 'STANDARD', 'rows': 7, 'cols': 10},
                ]
            },
            {
                'name': 'PVR Director’s Cut: Ambience Mall',
                'city': 'Delhi-NCR',
                'address': 'Nelson Mandela Marg, Vasant Kunj II, New Delhi 110070',
                'facilities': ['Luxury Dining', 'Director Cut Recliners', 'Concierge Service'],
                'screens': [
                    {'name': 'Screen 1 - Director Cut', 'type': 'VIP', 'rows': 6, 'cols': 8},
                ]
            },
            {
                'name': 'PVR: The Forum Mall Koramangala',
                'city': 'Bengaluru',
                'address': 'Hosur Road, Chikku Lakshmaiah Layout, Koramangala, Bengaluru 560095',
                'facilities': ['IMAX', 'Gold Class Recliners', 'Parking'],
                'screens': [
                    {'name': 'Screen 1 - IMAX', 'type': 'IMAX', 'rows': 8, 'cols': 12},
                    {'name': 'Screen 2 - Atmos Lounge', 'type': 'DOLBY ATMOS', 'rows': 7, 'cols': 10},
                ]
            },
            {
                'name': 'INOX: Garuda Mall',
                'city': 'Bengaluru',
                'address': 'Magrath Road, Ashok Nagar, Bengaluru, Karnataka 560025',
                'facilities': ['Dolby Atmos', 'Recliner Luxury', 'Live Kitchen'],
                'screens': [
                    {'name': 'Audi 1 - Insignia', 'type': 'STANDARD', 'rows': 7, 'cols': 10},
                ]
            },
            {
                'name': 'Prasads Multiplex: Large Screen',
                'city': 'Hyderabad',
                'address': 'NTR Gardens, Necklace Road, Khairatabad, Hyderabad 500063',
                'facilities': ['IMAX Giant Screen', 'Dolby Atmos', 'VR Zone', 'Gourmet Food Court'],
                'screens': [
                    {'name': 'Screen 1 - Large Screen', 'type': 'IMAX 3D', 'rows': 8, 'cols': 12},
                    {'name': 'Audi 2 - Atmos Gold', 'type': 'DOLBY ATMOS', 'rows': 7, 'cols': 10},
                ]
            },
            {
                'name': 'AMB Cinemas: Superplex Gachibowli',
                'city': 'Hyderabad',
                'address': 'Sarath City Capital Mall, Gachibowli - Miyapur Rd, Hyderabad 500084',
                'facilities': ['Laser 4K', 'M-Lounge Recliners', 'VIP Dining', 'Valet Parking'],
                'screens': [
                    {'name': 'Screen 1 - Laser 4K', 'type': 'STANDARD', 'rows': 7, 'cols': 10},
                ]
            },
            {
                'name': 'PVR INOX: Sathyam Cinemas',
                'city': 'Chennai',
                'address': '8, Thiruvika Road, Royapettah, Chennai, Tamil Nadu 600014',
                'facilities': ['RDX 4K', 'Dolby Atmos', 'Sathyam Popcorn Bar', 'Elite Recliners'],
                'screens': [
                    {'name': 'Main Audi - Sathyam 4K', 'type': 'DOLBY ATMOS', 'rows': 8, 'cols': 12},
                    {'name': 'Audi 2 - Santham', 'type': 'STANDARD', 'rows': 7, 'cols': 10},
                ]
            },
            {
                'name': 'SPI Cinemas: Palazzo (Nexus Vijaya)',
                'city': 'Chennai',
                'address': '183, Arcot Road, Vadapalani, Chennai, Tamil Nadu 600026',
                'facilities': ['IMAX Experience', 'Italian Cafe', 'Royal Lounges'],
                'screens': [
                    {'name': 'Palazzo - IMAX', 'type': 'IMAX 3D', 'rows': 8, 'cols': 12},
                ]
            },
            {
                'name': 'PVR INOX: South City Mall',
                'city': 'Kolkata',
                'address': '375, Prince Anwar Shah Rd, South City Complex, Kolkata, West Bengal 700068',
                'facilities': ['IMAX Laser', 'Dolby Atmos', 'Sub-Zero Cafe', 'Valet Parking'],
                'screens': [
                    {'name': 'Screen 1 - IMAX Laser', 'type': 'IMAX', 'rows': 8, 'cols': 12},
                    {'name': 'Screen 2 - Insignia', 'type': 'STANDARD', 'rows': 7, 'cols': 10},
                ]
            },
            {
                'name': 'Cinepolis: Acropolis Mall',
                'city': 'Kolkata',
                'address': '1858, Rajdanga Main Road, Kasba, Kolkata, West Bengal 700107',
                'facilities': ['VIP Recliners', 'Dolby 7.1', 'Coffee House'],
                'screens': [
                    {'name': 'Audi 1 - Club Class', 'type': 'STANDARD', 'rows': 7, 'cols': 10},
                ]
            },
            {
                'name': 'PVR: Phoenix Marketcity Viman Nagar',
                'city': 'Pune',
                'address': 'S.No. 207, Viman Nagar Road, Pune, Maharashtra 411014',
                'facilities': ['IMAX 3D', 'Dolby Atmos 4K', 'Gold Class Recliners'],
                'screens': [
                    {'name': 'Screen 1 - IMAX 3D', 'type': 'IMAX 3D', 'rows': 8, 'cols': 12},
                    {'name': 'Screen 2 - Atmos Prime', 'type': 'DOLBY ATMOS', 'rows': 7, 'cols': 10},
                ]
            },
            {
                'name': 'Cinepolis: Westend Mall Aundh',
                'city': 'Pune',
                'address': 'Near Parihar Chowk, Aundh, Pune, Maharashtra 411007',
                'facilities': ['Laser 4K Projection', 'Coffee Bar', 'Luxury Lounges'],
                'screens': [
                    {'name': 'Audi 1 - VIP Laser', 'type': 'VIP', 'rows': 6, 'cols': 8},
                ]
            },
            {
                'name': 'PVR: Acropolis Mall Thaltej',
                'city': 'Ahmedabad',
                'address': 'Drive In Road, Thaltej, Ahmedabad, Gujarat 380054',
                'facilities': ['4DX Motion Seats', 'Dolby Atmos', 'Cafe Gourmet'],
                'screens': [
                    {'name': 'Screen 1 - 4DX', 'type': '4DX', 'rows': 6, 'cols': 8},
                    {'name': 'Screen 2 - Atmos Laser', 'type': 'DOLBY ATMOS', 'rows': 7, 'cols': 10},
                ]
            },
            {
                'name': 'Cinepolis: Ahmedabad One Mall',
                'city': 'Ahmedabad',
                'address': 'Vastrapur Lake, Vastrapur, Ahmedabad, Gujarat 380015',
                'facilities': ['Macro XE Giant Screen', 'Dolby Atmos', 'VIP Recliners'],
                'screens': [
                    {'name': 'Screen 1 - Macro XE', 'type': 'MACRO XE', 'rows': 8, 'cols': 12},
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

        self.stdout.write(self.style.SUCCESS(f"✓ Seeded {len(theatres_data)} theatres and {len(all_screens)} screens"))

        # 4. Comprehensive Movie Catalog (20 Blockbusters across Hollywood, Bollywood & Indian Cinema)
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
                'title': 'Deadpool & Wolverine',
                'description': 'A listless Wade Wilson toils away in civilian life with his days as the morally flexible mercenary behind him. When his home world faces an existential threat, Wade must reluctantly suit-up with an even more reluctant Wolverine.',
                'duration': 128,
                'language': 'English',
                'formats': ['2D', '3D', 'IMAX 3D', '4DX'],
                'cert': 'A',
                'genres': ['Action', 'Comedy', 'Sci-Fi'],
                'release_date': date(2026, 7, 26),
                'poster_url': 'https://images.unsplash.com/photo-1563089145-599997674d42?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=73_1biulkYk',
                'rating': Decimal('8.7'),
                'votes': 34200
            },
            {
                'title': 'The Batman: Part II',
                'description': 'The Dark Knight ventures deeper into Gotham City criminal underworld as corruption and subterranean syndicates emerge from the flooded district to challenge Bruce Wayne order.',
                'duration': 165,
                'language': 'English',
                'formats': ['2D', 'IMAX', 'Dolby Atmos'],
                'cert': 'UA',
                'genres': ['Action', 'Crime', 'Drama', 'Thriller'],
                'release_date': date(2026, 10, 2),
                'poster_url': 'https://images.unsplash.com/photo-1509198397868-475647b2a1e5?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=mqqft2x_Aa4',
                'rating': Decimal('9.0'),
                'votes': 28500
            },
            {
                'title': 'Gladiator II',
                'description': 'Years after witnessing the death of Maximus, Lucius must enter the Colosseum after his home is conquered by tyrannical emperors who rule Rome with an iron fist.',
                'duration': 148,
                'language': 'English',
                'formats': ['2D', 'IMAX 3D', 'Dolby Atmos'],
                'cert': 'A',
                'genres': ['Action', 'Adventure', 'Drama'],
                'release_date': date(2026, 11, 15),
                'poster_url': 'https://images.unsplash.com/photo-1533929736458-ca588d08c8be?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=4rgYUipGJNo',
                'rating': Decimal('8.5'),
                'votes': 16900
            },
            {
                'title': 'Stree 2: Sarkate Ka Aatank',
                'description': 'The town of Chanderi is being haunted again by a headless entity named Sarkata who is abducting progressive women. Vicky and his friends re-team with the mysterious woman to protect their town.',
                'duration': 149,
                'language': 'Hindi',
                'formats': ['2D', 'Dolby Atmos'],
                'cert': 'UA',
                'genres': ['Comedy', 'Horror'],
                'release_date': date(2026, 8, 15),
                'poster_url': 'https://images.unsplash.com/photo-1509248961158-e54f6934749c?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=KVnheQj6qtg',
                'rating': Decimal('8.6'),
                'votes': 31000
            },
            {
                'title': 'Pushpa 2: The Rule',
                'description': 'Pushpa Raj ascends the syndicate throne of red sandalwood smuggling, sparking all-out war with Bhanwar Singh Shekhawat and rival cartels in an explosive high-stakes confrontation.',
                'duration': 175,
                'language': 'Telugu',
                'formats': ['2D', '3D', 'IMAX'],
                'cert': 'UA',
                'genres': ['Action', 'Crime', 'Drama'],
                'release_date': date(2026, 12, 6),
                'poster_url': 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=1kVK0MZlbI4',
                'rating': Decimal('8.9'),
                'votes': 42000
            },
            {
                'title': 'Kalki 2898 AD',
                'description': 'A modern avatar of Vishnu descends to earth to protect humanity from evil forces in a dystopian post-apocalyptic future ruled by the Supreme Yaskin in the Complex.',
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
                'title': 'Avatar: The Way of Water (Special Re-Release)',
                'description': 'Jake Sully and Neytiri navigate the oceanic regions of Pandora as the RDA returns to exploit the planet, teaming with the aquatic Metkayina clan.',
                'duration': 192,
                'language': 'English',
                'formats': ['3D', 'IMAX 3D', '4DX'],
                'cert': 'UA',
                'genres': ['Sci-Fi', 'Adventure', 'Action'],
                'release_date': date(2026, 4, 12),
                'poster_url': 'https://images.unsplash.com/photo-1518709779341-56cf4535e983?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=d9MyW72ELq0',
                'rating': Decimal('8.8'),
                'votes': 39000
            },
            {
                'title': 'Spider-Man: Beyond the Spider-Verse',
                'description': 'Miles Morales catapults across the Multiverse, encountering a coalition of Spider-Heroes defending the canon of existence from reality-shattering anomalies.',
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
                'title': 'Interstellar: IMAX Special',
                'description': 'When Earth becomes uninhabitable, ex-NASA pilot Joseph Cooper pilots an endurance spacecraft through a Saturn wormhole to find a habitable colony for humanity.',
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
                'title': 'Jawan: Director’s Cut',
                'description': 'A high-octane action thriller detailing the emotional odyssey of a vigilante commando executing daring public takeovers to force systemic political accountability.',
                'duration': 171,
                'language': 'Hindi',
                'formats': ['2D', 'IMAX', 'Dolby Atmos'],
                'cert': 'UA',
                'genres': ['Action', 'Thriller', 'Drama'],
                'release_date': date(2026, 5, 20),
                'poster_url': 'https://images.unsplash.com/photo-1536440136628-849c177e76a1?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=MWOlnZSnXpc',
                'rating': Decimal('8.4'),
                'votes': 27800
            },
            {
                'title': 'Inside Out 2',
                'description': 'Teenager Riley faces turbulent emotional headquarters alterations as Anxiety, Envy, Ennui, and Embarrassment clash with Joy and Sadness.',
                'duration': 96,
                'language': 'English',
                'formats': ['2D', '3D'],
                'cert': 'U',
                'genres': ['Animation', 'Comedy', 'Adventure'],
                'release_date': date(2026, 6, 14),
                'poster_url': 'https://images.unsplash.com/photo-1514306191717-452ec28c7814?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=LEjhY15eCx0',
                'rating': Decimal('8.7'),
                'votes': 21500
            },
            {
                'title': 'Godzilla x Kong: The New Empire',
                'description': 'Two colossal ancient titans clash before joining forces to combat a tyrannical Hollow Earth ape despot commanding a frost titan that threatens the surface realm.',
                'duration': 115,
                'language': 'English',
                'formats': ['2D', '3D', 'IMAX 3D', '4DX'],
                'cert': 'UA',
                'genres': ['Action', 'Sci-Fi', 'Adventure'],
                'release_date': date(2026, 3, 29),
                'poster_url': 'https://images.unsplash.com/photo-1568605117036-5fe5e7bab0b7?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=lV1OOlGwExg',
                'rating': Decimal('8.1'),
                'votes': 14700
            },
            {
                'title': 'Suzume',
                'description': 'High school girl Suzume teams up with a mysterious guardian to travel across Japan and latch shut supernatural doorway portals unleashing earthquake disasters.',
                'duration': 122,
                'language': 'Japanese',
                'formats': ['2D', 'IMAX'],
                'cert': 'U',
                'genres': ['Animation', 'Fantasy', 'Adventure'],
                'release_date': date(2026, 4, 21),
                'poster_url': 'https://images.unsplash.com/photo-1578632767115-351597cf2477?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=5p_hO6v_N18',
                'rating': Decimal('8.8'),
                'votes': 18200
            },
            {
                'title': 'Inception: 15th Anniversary Special',
                'description': 'Dom Cobb specializes in subconscious heist extraction. He is offered an impossible redemption assignment: plant an original idea into a corporate heir mind.',
                'duration': 148,
                'language': 'English',
                'formats': ['2D', 'IMAX 70mm', 'Dolby Atmos'],
                'cert': 'UA',
                'genres': ['Sci-Fi', 'Action', 'Thriller'],
                'release_date': date(2026, 7, 16),
                'poster_url': 'https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=YoHD9XEInc0',
                'rating': Decimal('9.2'),
                'votes': 52000
            },
            {
                'title': 'Animal: Park Edition',
                'description': 'Ranvijay Singh deep-seated paternal adoration spirals into visceral and unchecked brutality as criminal forces attempt to assassinate his business tycoon father.',
                'duration': 201,
                'language': 'Hindi',
                'formats': ['2D', 'Dolby Atmos'],
                'cert': 'A',
                'genres': ['Action', 'Crime', 'Drama'],
                'release_date': date(2026, 2, 14),
                'poster_url': 'https://images.unsplash.com/photo-1508739773434-c26b3d09e071?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=Dydmpfo68DA',
                'rating': Decimal('8.0'),
                'votes': 25100
            },
            {
                'title': 'Fighter: Aerial Combat',
                'description': 'Top Air Force aviators unite as the Air Dragons quick-response squadron, navigating aerial dogfights and intense camaraderie defending international airspace.',
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
            {
                'title': 'Chandu Champion',
                'description': 'The incredible true biographical journey of Murlikant Petkar, an Olympic boxer and soldier who overcame severe battle wounds to become India first Paralympic gold medalist.',
                'duration': 143,
                'language': 'Hindi',
                'formats': ['2D'],
                'cert': 'U',
                'genres': ['Biography', 'Drama', 'Action'],
                'release_date': date(2026, 6, 14),
                'poster_url': 'https://images.unsplash.com/photo-1517838277536-f5f99be501cd?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=kYJ6gVbX680',
                'rating': Decimal('8.5'),
                'votes': 17300
            },
            {
                'title': 'Furiosa: A Mad Max Saga',
                'description': 'Young Furiosa is snatched from the Green Place of Many Mothers and falls into the hands of a great Biker Horde led by the Warlord Dementus through the Wasteland.',
                'duration': 148,
                'language': 'English',
                'formats': ['2D', 'IMAX 3D', 'Dolby Atmos'],
                'cert': 'A',
                'genres': ['Action', 'Adventure', 'Sci-Fi'],
                'release_date': date(2026, 5, 24),
                'poster_url': 'https://images.unsplash.com/photo-1509316975850-ff9c5deb0cd9?auto=format&fit=crop&w=800&q=80',
                'trailer_url': 'https://www.youtube.com/watch?v=XJMuhwVlca4',
                'rating': Decimal('8.6'),
                'votes': 23400
            },
        ]

        created_movies = []
        for m_data in movies_data:
            movie, created = Movie.objects.get_or_create(
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
                    'votes_count': m_data['votes'],
                    'is_active': True
                }
            )
            if not created:
                # Update attributes to ensure up-to-date posters and descriptions
                movie.description = m_data['description']
                movie.duration_minutes = m_data['duration']
                movie.language = m_data['language']
                movie.format_types = m_data['formats']
                movie.certification = m_data['cert']
                movie.poster_url = m_data['poster_url']
                movie.trailer_url = m_data['trailer_url']
                movie.rating_average = m_data['rating']
                movie.votes_count = m_data['votes']
                movie.is_active = True
                movie.save()

            # Add genres
            for g_name in m_data['genres']:
                if g_name in genres:
                    movie.genres.add(genres[g_name])
            created_movies.append(movie)

        self.stdout.write(self.style.SUCCESS(f"✓ Seeded and updated {len(created_movies)} movies"))

        # 5. Showtimes (Today and next 7 days across all theatres and screens)
        now = timezone.now()
        base_date = now.date()
        show_times = [
            time(9, 45),
            time(13, 15),
            time(16, 45),
            time(20, 15),
            time(23, 30)
        ]

        created_showtimes = []
        num_movies = len(created_movies)

        for day_offset in range(7):
            target_date = base_date + timedelta(days=day_offset)
            for s_idx, screen in enumerate(all_screens):
                # Cycle distinct movies across each screen and day
                screen_offset = (s_idx * 3 + day_offset * 2) % num_movies
                movies_for_screen = [
                    created_movies[(screen_offset + m_idx) % num_movies]
                    for m_idx in range(len(show_times))
                ]

                for t_idx, movie in enumerate(movies_for_screen):
                    st_time = show_times[t_idx]
                    start_dt = timezone.make_aware(datetime.combine(target_date, st_time))
                    end_dt = start_dt + timedelta(minutes=movie.duration_minutes + 25)

                    exp = '2D'
                    if 'IMAX' in screen.name:
                        exp = 'IMAX 3D'
                    elif '4D' in screen.name or 'MX4D' in screen.name:
                        exp = '4DX'
                    elif 'Dolby' in screen.name or 'Macro' in screen.name:
                        exp = 'Dolby Atmos'

                    showtime, created = Showtime.objects.get_or_create(
                        movie=movie,
                        screen=screen,
                        start_time=start_dt,
                        defaults={
                            'end_time': end_dt,
                            'experience': exp,
                            'language': movie.language,
                            'price_silver': Decimal('160.00'),
                            'price_gold': Decimal('240.00'),
                            'price_platinum': Decimal('350.00'),
                            'price_vip': Decimal('480.00')
                        }
                    )
                    created_showtimes.append(showtime)

        self.stdout.write(self.style.SUCCESS(f"✓ Seeded {len(created_showtimes)} showtimes across 7-day schedule"))

        # 6. Pre-book sample seats for live demonstration
        upcoming_shows = [s for s in created_showtimes if s.start_time > now]
        if upcoming_shows:
            first_show = upcoming_shows[0]
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

        # 7. Seed NoSQL Collections (movie reviews into document collection)
        reviews_data = [
            (created_movies[0].id, 'Aarav Mehta', 9.5, 'Visually breathtaking in IMAX 3D! The score by Hans Zimmer vibrates through the seats. Must watch!', ['IMAX Experience', 'Masterpiece', 'Cinematography'], True),
            (created_movies[0].id, 'Priya Sharma', 9.0, 'Superb pacing and acting. Timothee and Zendaya had great chemistry.', ['Great Visuals', 'Paisa Vasool'], True),
            (created_movies[1].id, 'Rohan Joshi', 10.0, 'Christopher Nolan at his pinnacle. Cillian Murphy gave an Oscar-worthy performance.', ['Must Watch', 'Masterpiece'], False),
            (created_movies[2].id, 'Karan Singhania', 9.2, 'Hugh Jackman and Ryan Reynolds chemistry is out of this world. Nostalgia overload and insane cameos!', ['Blockbuster', 'Hilarious', 'Action Packed'], True),
            (created_movies[3].id, 'Ananya Sen', 9.1, 'Matt Reeves created a gritty, atmospheric masterpiece. Pattinson is the definitive detective Batman.', ['Dark & Gritty', 'Cinematography'], False),
            (created_movies[5].id, 'Sneha Patel', 8.8, 'Sarkata gave real chills! Shraddha Kapoor and Rajkummar Rao comedic timing is unmatched.', ['Horror Comedy', 'Family Entertainer'], True),
            (created_movies[6].id, 'Vikram Reddy', 9.4, 'Allu Arjun rules the big screen! High-voltage background score and unstoppable elevation scenes.', ['Mass Elevation', 'Allu Arjun', 'Wild Action'], True),
            (created_movies[12].id, 'Meera Nair', 9.0, 'Anxiety as a character was portrayed so accurately. Left the theatre with happy tears!', ['Emotional', 'Heartwarming', 'Animation Peak'], True),
        ]

        for m_id, u_name, r_val, c_text, t_list, v_b in reviews_data:
            nosql_service.add_movie_review(
                movie_id=m_id,
                username=u_name,
                rating=r_val,
                comment=c_text,
                tags=t_list,
                verified_booking=v_b
            )

        self.stdout.write(self.style.SUCCESS(f"✓ Seeded {len(reviews_data)} NoSQL reviews into document store"))
        self.stdout.write(self.style.SUCCESS("=== SEEDING COMPLETED SUCCESSFULLY! ==="))
