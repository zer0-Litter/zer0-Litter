from django.db import models
from datetime import datetime
from django.conf import settings

<<<<<<< Updated upstream
=======

class Complaints(models.Model):
    com_id = models.AutoField(primary_key=True)
    t_district_id = models.IntegerField()
    user_id = models.CharField(max_length=255)
    re_complain = models.CharField(max_length=255, null=True, blank=True)
    status_id = models.IntegerField()
    com_trashcan = models.CharField(max_length=255, null=True, blank=True)
    com_type = models.CharField(max_length=255)
    com_trash_type = models.CharField(max_length=255, null=True, blank=True)
    com_pic1 = models.BinaryField(null=True, blank=True)
    com_pic2 = models.BinaryField(null=True, blank=True)
    com_location = models.CharField(max_length=255, null=True, blank=True)
    com_title = models.CharField(max_length=255)
    com_contents = models.CharField(max_length=255, null=True, blank=True)
    com_reg_date = models.DateTimeField()

    def __str__(self):
        return f"{self.com_title} ({self.user_id})"



class ReComplaints(models.Model):
    re_com_id = models.AutoField(primary_key=True)
    user_id = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    com_id = models.ForeignKey('Complaints', on_delete=models.CASCADE)
    re_complain = models.CharField(max_length=255)
    status_id = models.ForeignKey('ComplaintStatus',on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ReComplaint {self.re_com_id} by {self.user_id}"


class ComplaintStatus(models.Model):
    status_id = models.AutoField(primary_key=True)
    status_name = models.CharField(max_length=50)  # "처리중", "처리완료"
    updated_at = models.DateTimeField(auto_now_add=True)  # 상태가 지정된 시간

    def __str__(self):
        return f"{self.status_name} ({self.updated_at.strftime('%Y-%m-%d %H:%M')})"


class ChatHistory(models.Model):
    message_id = models.AutoField(primary_key=True)
    user_id = models.CharField(max_length=100)
    scenario_id = models.CharField(max_length=255)
    session_id = models.CharField(max_length=255)
    role = models.CharField(max_length=50)
    content = models.TextField()
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    is_final = models.BooleanField(default=False)
    metadata = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ChatbotHistory {self.session_id} - {self.user_id}"



class ChatFiles(models.Model):
    file_id = models.AutoField(primary_key=True)
    message_id = models.ForeignKey(ChatHistory, on_delete=models.CASCADE)
    file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.file_name

>>>>>>> Stashed changes
from django.contrib.auth.models import AbstractUser

# Create your models here.


class Users(AbstractUser):
    # username = 아이디 (기본 제공)
    # password = 비밀번호 (기본 제공)
    name = models.CharField(max_length=100)  # 사용자 이름 (실명)
    birth = models.DateField()
    gender = models.CharField(max_length=20)
    address = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    user_reg_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'users'


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

