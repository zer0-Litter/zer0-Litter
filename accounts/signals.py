"""교차 저장소 정합성: SQLite의 Users 삭제 시 MongoDB의 연관 데이터를 정리한다.

Users(관계형)와 민원/채팅(MongoDB)은 서로 다른 DB라 FK 연쇄삭제가 동작하지 않는다.
계정 탈퇴 시 Mongo 쪽 데이터가 고아(orphan)로 남는 문제를 신호로 보완한다.
"""
import logging

from django.contrib.auth import get_user_model
from django.db.models.signals import post_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)
User = get_user_model()


def purge_user_mongo_data(user_id, username):
    """탈퇴 사용자의 MongoDB 연관 데이터(민원·상태·재민원·채팅·파일)를 삭제한다."""
    from mongoengine.queryset.visitor import Q
    from common.models_mongo import (
        Complaints, ComplaintStatus, ReComplaints, ChatHistory, ChatFiles,
    )

    # 안정 식별자(user_id) 우선, 과거 데이터 호환을 위해 username 도 함께 매칭
    owner_q = Q(username=username)
    if user_id is not None:
        owner_q = owner_q | Q(user_id=user_id)

    complaints = Complaints.objects(owner_q)
    com_ids = [c.com_id for c in complaints.only('com_id')]

    summary = {}
    if com_ids:
        summary['complaint_status'] = ComplaintStatus.objects(com_id__in=com_ids).delete()
        summary['re_complaints'] = ReComplaints.objects(
            Q(origin_com_id__in=com_ids) | Q(new_com_id__in=com_ids)
        ).delete()
    summary['complaints'] = complaints.delete()

    # 채팅 기록/첨부파일
    chats = ChatHistory.objects(username=username)
    chat_pks = [c.id for c in chats.only('id')]
    if chat_pks:
        summary['chat_files'] = ChatFiles.objects(chat_id__in=chat_pks).delete()
    summary['chat_history'] = chats.delete()

    logger.info("탈퇴 사용자(%s) Mongo 데이터 정리: %s", username, summary)
    return summary


@receiver(post_delete, sender=User)
def on_user_deleted(sender, instance, **kwargs):
    try:
        purge_user_mongo_data(getattr(instance, 'id', None), instance.username)
    except Exception as e:
        logger.error("탈퇴 사용자 Mongo 정리 실패: %s", e, exc_info=True)
