from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        # 계정 삭제 시 MongoDB 연관 데이터 정리 신호 등록
        from . import signals  # noqa: F401
