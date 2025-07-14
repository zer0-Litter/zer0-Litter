import re
from rest_framework import serializers
from common.models import Users
from django.contrib.auth.hashers import make_password
from rest_framework.validators import UniqueValidator

class UserRegisterSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        validators=[UniqueValidator(queryset=Users.objects.all())]
    )
    password2 = serializers.CharField(write_only=True, required=True)  # 비밀번호 확인 필드 추가

    class Meta:
        model = Users
        fields = ['username', 'password','password2', 'name', 'birth', 'gender', 'address', 'phone_number']
        extra_kwargs = {
            'password': {'write_only': True},  # 비밀번호는 쓰기 전용
        }

    def validate(self, data):
        # 비밀번호 확인
        if data['password'] != data['password2']:
            raise serializers.ValidationError({"password": "비밀번호가 일치하지 않습니다."})

        # 비밀번호 규칙 검사 (영문 소문자, 숫자, 기호 포함 8자리 이상 16자리 이하)
        password = data['password']
        password_regex = r'^(?=.*[a-z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,16}$'

        if not re.match(password_regex,password):
            raise serializers.ValidationError({"password":"비밀번호는 영문 소문자, 숫자, 기호 조합으로 8자리 이상 16자 이하여야 합니다."})

        return data

    def create(self, validated_data):
        # 비밀번호 해시화
        validated_data['password'] = make_password(validated_data['password'])
        # 비밀번호 확인 필드인 password2는 삭제하고 저장
        validated_data.pop('password2', None) # password2는 db에 저장x
        return super().create(validated_data)  # users 모델에 저장을 위임
