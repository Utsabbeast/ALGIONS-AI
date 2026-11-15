#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

echo "--- Building CinemaBox for Render Deployment ---"

# Install production dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Collect static files with whitenoise compression
python manage.py collectstatic --no-input

# Apply database migrations
python manage.py migrate

# Seed baseline demo data (theatres, screens, movies, showtimes, users, NoSQL reviews)
python manage.py seed_data

echo "--- Build completed successfully! ---"

