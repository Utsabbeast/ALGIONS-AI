from django.urls import path
from cinema import views

app_name = 'cinema'

urlpatterns = [
    path('', views.home_view, name='home'),
    path('movies/<slug:slug>/', views.movie_detail_view, name='movie-detail'),
    path('accounts/login/', views.login_view, name='login'),
    path('accounts/register/', views.register_view, name='register'),
    path('accounts/logout/', views.logout_view, name='logout'),
    path('accounts/demo-login/<str:role>/', views.demo_login_view, name='demo-login'),
]

