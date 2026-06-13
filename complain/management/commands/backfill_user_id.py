"""
기존 Complaints 문서의 user_id(안정 식별자)를 username 기준으로 백필한다.

user_id 도입 이전 데이터는 username 만 있으므로, 배포 직후 1회 실행해야
소유권 기반 조회(마이페이지/내 민원/재민원)가 정상 동작한다.
매칭되는 회원이 없는 데이터(크롤러='crawler', 게스트 등)는 user_id 없이 남는다.

    python manage.py backfill_user_id
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from common.models_mongo import Complaints


class Command(BaseCommand):
    help = "Complaints.user_id 를 username 기준으로 백필한다."

    def handle(self, *args, **options):
        User = get_user_model()
        name_to_id = {u.username: u.id for u in User.objects.all()}

        updated = 0
        unmatched = 0
        for c in Complaints.objects(user_id=None).only("com_id", "username", "user_id"):
            uid = name_to_id.get(c.username)
            if uid is not None:
                c.update(set__user_id=uid)
                updated += 1
            else:
                unmatched += 1

        self.stdout.write(self.style.SUCCESS(
            f"user_id 백필 완료: {updated}건 갱신, "
            f"{unmatched}건은 매칭 회원 없음(크롤러/게스트 → user_id 없음 유지)"
        ))
