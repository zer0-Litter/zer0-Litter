from mongoengine import FloatField, BooleanField, DictField, StringField
from mongoengine import Document, DateTimeField
from mongoengine import IntField, BinaryField, ReferenceField



class Counter(Document):
    name = StringField(required=True, unique=True)  # 예: 'complaint'
    seq = IntField(default=0)

    meta = {'collection': 'counters'}

class ComplaintStatus(Document):
    status_id = IntField(unique=True, required=True)  # AutoField → 직접 string으로 ID 관리
    com_id = IntField(required=True)
    status_name = StringField(max_length=50)
    updated_at = DateTimeField()
    changed_by = StringField(max_length=150)  # 변경자(username)

    meta = {'collection': 'complaint_status'}


class Complaints(Document):
    com_id = IntField(required=True, unique=True, db_field='com_id')  # 자동 증가 직접 관리 필요
    t_district_id = IntField()
    # SQLite Users.pk 를 가리키는 안정 식별자(소유권 판정의 기준).
    # username 은 표시/검색/크롤러용으로 유지하되, 소유권은 user_id 로 본다.
    # 크롤러/게스트 등 실제 회원이 없는 경우 None.
    user_id = IntField(null=True)
    username = StringField(max_length=255, required=True)
    re_complain = StringField(max_length=255)
    com_trashcan = StringField(max_length=255)
    com_type = StringField(max_length=255, required=True)
    com_trash_type = StringField(max_length=255)
    com_pic1 = BinaryField()
    com_pic2 = BinaryField()
    com_location = StringField(max_length=255)
    lat = FloatField(null=True)
    lon = FloatField(null=True)
    com_contents = StringField(max_length=5000)
    com_reg_date = DateTimeField()
    # 최신 처리 상태를 비정규화로 저장(목록/통계의 N+1 조회 제거용).
    # 정본 이력은 ComplaintStatus 컬렉션에 그대로 남고, 이 필드는 '최신값' 캐시.
    current_status = StringField(max_length=50, default='처리중')

    meta = {'collection': 'complaints',
            'indexes': ['user_id', 'username', 'current_status', '-com_reg_date']}


class ReComplaints(Document):
    re_request_id = StringField(primary_key=True) # 고유값
    username = StringField(max_length=255)  # auth.User 대신 직접 저장
    origin_com_id = IntField(required=True) # 원본 민원 com_id
    new_com_id = IntField(required=True) # 이번에 생성된 재민원 com_id
    re_complain = StringField(max_length=1, default='Y') # y 고정
    status_id = ReferenceField(ComplaintStatus, null=True) # 이번 재민원의 상태 id
    created_at = DateTimeField()

    meta = {'collection': 're_complaints'}


class ChatHistory(Document):
    chat_id = StringField(unique=True, required=True, db_field='chat_id')  # AutoField 대체
    username = StringField(max_length=100)
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
    file_id = StringField(unique=True, required=True, sparse=True, db_field='file_id')
    chat_id = ReferenceField(ChatHistory, required=True)
    file_name = StringField(max_length=255)
    file_data = BinaryField()
    file_type = StringField(max_length=50)
    uploaded_at = DateTimeField()

    meta = {'collection': 'chat_files'}


