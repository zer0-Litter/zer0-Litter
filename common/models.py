from django.db import models
from django.contrib.auth.models import AbstractUser

# Create your models here.

class Users(AbstractUser):
    # username = 아이디 (기본 제공)
    # password = 비밀번호 (기본 제공)
    name = models.CharField(max_length=100)  # 사용자 이름 (실명)
    birth = models.DateField()  # 슈퍼 유저 필요하면 임시로 null, blank 허용으로 변경해야함 null=True, blank=True (슈퍼유저 생성 후 다시 변경할 것)
    gender = models.CharField(max_length=20)
    address = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    user_reg_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'users'

# --- 슈퍼유저 생성 완료 후에는 아래처럼 birth 필드에서 null=True, blank=True 옵션 제거 후
# python manage.py makemigrations
# python manage.py migrate
# 명령어를 실행하여 필드를 다시 필수값으로 변경해주세요 ---
# birth = models.DateField()



from django.db import models

class TrashLoc(models.Model):
    t_district_id = models.CharField(max_length=100, primary_key=True)
    t_district = models.CharField(max_length=255, null=True, blank=True)
    t_road_addr = models.CharField(max_length=255, null=True, blank=True)
    t_street_addr = models.CharField(max_length=255, null=True, blank=True)
    t_detailed_addr = models.CharField(max_length=255, null=True, blank=True)
    t_lat = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    t_lon = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    t_loc = models.CharField(max_length=50, null=True, blank=True)
    t_shape = models.CharField(max_length=50, null=True, blank=True)
    t_trash_type = models.CharField(max_length=50, null=True, blank=True)
    t_dept = models.CharField(max_length=50, null=True, blank=True)
    t_contact = models.CharField(max_length=50, null=True, blank=True)
    t_date = models.DateField(null=True, blank=True)
    t_update_year = models.IntegerField(null=True, blank=True)
    t_addr = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'trash_loc'

