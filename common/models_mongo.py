from mongoengine import  FloatField, BooleanField, DecimalField, DictField, StringField
from mongoengine import Document, StringField, DateTimeField, DateField
from mongoengine import IntField, BinaryField, ReferenceField


class ComplaintStatus(Document):
    status_id = StringField(primary_key=True)  # AutoField → 직접 string으로 ID 관리
    status_name = StringField(max_length=50)
    updated_at = DateTimeField()

    meta = {'collection': 'complaint_status'}


class Complaints(Document):
    com_id = IntField(primary_key=True)  # 자동 증가 직접 관리 필요
    t_district_id = IntField(required=True)
    user_id = StringField(max_length=255, required=True)
    re_complain = StringField(max_length=255)
    status_id = IntField(required=True)
    com_trashcan = StringField(max_length=255)
    com_type = StringField(max_length=255, required=True)
    com_trash_type = StringField(max_length=255)
    com_pic1 = BinaryField()
    com_pic2 = BinaryField()
    com_location = StringField(max_length=255)
    com_title = StringField(max_length=255, required=True)
    com_contents = StringField(max_length=255)
    com_reg_date = DateTimeField()

    meta = {'collection': 'complaints'}


class ReComplaints(Document):
    re_com_id = StringField(primary_key=True)
    user_id = StringField(max_length=255)  # auth.User 대신 직접 저장
    com_id = ReferenceField(Complaints, required=True)
    re_complain = StringField(max_length=255)
    status_id = ReferenceField(ComplaintStatus, null=True)
    created_at = DateTimeField()

    meta = {'collection': 're_complaints'}


class ChatHistory(Document):
    message_id = StringField(primary_key=True)  # AutoField 대체
    user_id = StringField(max_length=100)
    scenario_id = StringField(max_length=255)
    session_id = StringField(max_length=255)
    role = StringField(max_length=50)
    content = StringField(max_length=10000)  # 텍스트 길이에 따라 max_length 설정
    latitude = FloatField()
    longitude = FloatField()
    is_final = BooleanField(default=False)
    metadata = DictField()
    created_at = DateTimeField()

    meta = {'collection': 'chat_history'}


class ChatFiles(Document):
    file_id = StringField(primary_key=True)
    message_id = ReferenceField(ChatHistory, required=True)
    file_name = StringField(max_length=255)
    file_path = StringField(max_length=255)
    file_type = StringField(max_length=50)
    uploaded_at = DateTimeField()

    meta = {'collection': 'chat_files'}