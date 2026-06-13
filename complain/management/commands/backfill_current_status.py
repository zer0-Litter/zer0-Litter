"""
기존 Complaints 문서의 current_status(비정규화 필드)를 ComplaintStatus 최신 상태로 채운다.

current_status 도입 이전에 생성된 민원은 이 필드가 비어 있으므로,
배포 직후 1회 실행해야 목록/통계 필터가 정상 동작한다.

    python manage.py backfill_current_status
"""
from django.core.management.base import BaseCommand

from common.models_mongo import Complaints, ComplaintStatus


class Command(BaseCommand):
    help = "Complaints.current_status 를 ComplaintStatus 최신 상태로 백필한다."

    def handle(self, *args, **options):
        updated = 0
        total = 0
        for c in Complaints.objects.only("com_id", "current_status"):
            total += 1
            last = (
                ComplaintStatus.objects(com_id=c.com_id)
                .only("status_name", "updated_at", "status_id")
                .order_by("-updated_at", "-status_id")
                .first()
            )
            status = last.status_name if last else "처리중"
            if c.current_status != status:
                c.update(set__current_status=status)
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(f"current_status 백필 완료: 전체 {total}건 중 {updated}건 갱신")
        )
