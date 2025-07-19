from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from common.models import Users

@admin.register(Users)
class CustomUserAdmin(UserAdmin):
    model = Users
    list_display = ('username', 'name', 'email', 'birth', 'gender', 'address', 'phone_number', 'user_reg_date', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (
        ("추가 정보", {'fields': ('name', 'birth', 'gender', 'address', 'phone_number', 'user_reg_date')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("추가 정보", {'fields': ('name', 'birth', 'gender', 'address', 'phone_number')}),
    )
