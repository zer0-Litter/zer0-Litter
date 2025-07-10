from django.db import models

# Create your models here.
class Users(models.Model):
    user_id = models.CharField(max_length=100, primary_key=True)  # 아이디
    password = models.CharField(max_length=100)  # 비밀번호
    name = models.CharField(max_length=100)  # 이름
    birth = models.DateField()  # 나이 (생년월일)
    gender = models.CharField(max_length=20)  # 성별
    address = models.CharField(max_length=255)  # 주소
    phone_number = models.CharField(max_length=20)  # 휴대전화번호
    user_reg_date = models.DateTimeField(auto_now_add=True)  # 가입날짜, 기본적으로 현재 시간

    class Meta:
        db_table = 'accounts_user'