from rest_framework import permissions


class IsCinemaStaffOrAdmin(permissions.BasePermission):
    """
    Allows access only to authenticated users with STAFF or ADMIN roles.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            (request.user.is_gate_staff or request.user.is_cinema_admin or request.user.is_staff or request.user.is_superuser)
        )


class IsCinemaAdmin(permissions.BasePermission):
    """
    Allows access only to users with ADMIN role or Django superusers.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            (request.user.is_cinema_admin or request.user.is_superuser)
        )

