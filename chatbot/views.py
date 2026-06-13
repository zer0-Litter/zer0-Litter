import logging
import os

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from trash_loc.views import (
    trash_bin_map as _tl_trash_bin_map,
    trash_bin_list as _tl_trash_bin_list,
)
from .chatbot_core import chatbot_router
from . import services

logger = logging.getLogger(__name__)

# 업로드 파일 검증 정책 (이미지 전용)
ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB


def _validate_uploads(files):
    """업로드 파일 타입/용량 검증. 문제가 있으면 사용자용 에러 메시지를, 없으면 None을 반환."""
    for f in files:
        content_type = (getattr(f, "content_type", "") or "").lower()
        if content_type not in ALLOWED_UPLOAD_TYPES:
            return '이미지 파일(JPEG/PNG/GIF/WEBP)만 업로드할 수 있습니다.'
        if getattr(f, "size", 0) > MAX_UPLOAD_SIZE:
            return '파일 크기는 5MB를 초과할 수 없습니다.'
    return None


def _to_float(v):
    """잘못된 값이 와도 500이 나지 않도록 방어적으로 float 변환."""
    try:
        return float(v) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None


# --- 챗봇 API 엔드포인트 ---
@require_POST
def chatbot_api(request):
    """챗봇 대화를 처리한다. 영속화/민원 생성 로직은 services 계층에 위임하고
    여기서는 요청 파싱 → 라우팅 → 저장 호출 → 응답만 담당한다."""
    logger.debug("chatbot_api 호출됨")

    # 첫 요청 시 1회 ChromaDB 초기 로드
    services.ensure_chroma_loaded()

    is_authed = getattr(request.user, "is_authenticated", False)
    username = request.user.username if is_authed else "guest"
    user_id = request.user.id if is_authed else None
    user_input = (request.POST.get('message') or '').strip()
    scenario_id = request.POST.get('scenario_id') or 'default'
    reset_session = (request.POST.get('reset_session') or '').lower() == 'true'

    upload_files = request.FILES.getlist('file') or request.FILES.getlist('files')

    if not user_input and not upload_files and not reset_session:
        return JsonResponse({'response': '', 'session_id': request.POST.get('session_id') or ''})

    # 업로드 파일 검증을 DB 저장 이전에 수행하여 불완전 저장 방지
    if upload_files:
        upload_error = _validate_uploads(upload_files)
        if upload_error:
            return JsonResponse({'error': upload_error}, status=400)

    session_id = request.POST.get('session_id') or services.get_next_session_id()
    temp_com_location = (request.POST.get('com_location') or '').strip()
    lat = _to_float(request.POST.get('lat'))
    lon = _to_float(request.POST.get('lon'))
    logger.debug("username=%s, scenario_id=%s, session_id=%s", username, scenario_id, session_id)

    # 챗봇 라우터 호출
    try:
        result = chatbot_router(user_input, username, session_id, scenario_id,
                                temp_com_location, reset_session=reset_session)
        logger.debug("router 결과: %s", result)
    except Exception as e:
        logger.error("router 호출 실패: %s", e, exc_info=True)
        result = {'response': '챗봇 처리 중 오류가 발생했습니다.', 'session_id': session_id, 'is_final': False}

    # 메시지/파일 저장
    chat_doc = services.save_user_message(username, scenario_id, session_id, user_input, lat, lon)
    services.save_uploaded_files(chat_doc, upload_files)
    services.save_bot_message(username, scenario_id, session_id, result)

    # 최종 확정 시 민원 자동 생성
    try:
        error_msg = services.create_complaint_from_chat(
            username, session_id, temp_com_location, result, user_id=user_id)
    except Exception as e:
        logger.error("Complaints 및 임베딩 자동 생성 실패: %s", e, exc_info=True)
        return JsonResponse({
            'response': '민원 접수 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.',
            'session_id': session_id,
        })
    if error_msg:
        return JsonResponse({'response': error_msg, 'session_id': session_id})

    return JsonResponse({'response': result.get('response', ''), 'session_id': session_id})


# --- 기타 뷰 ---
@login_required
def chatbot_chat(request, scenario_id):
    """지정된 시나리오 ID의 챗봇 채팅 페이지를 렌더링합니다."""
    return render(request, 'chatbot/chatbot_chat.html', {'scenario_id': scenario_id})


@login_required
def chatbot_chat_default(request):
    """기본 챗봇 채팅 페이지를 렌더링합니다."""
    return render(request, 'chatbot/chatbot_chat_default.html', {
        'kakao_api_key': os.getenv('KAKAO_MAP_API_KEY'),
        'district_id': '11000',
    })


# trash_bin_map / trash_bin_list 의 실제 구현은 trash_loc.views 에 1곳으로 통합.
# 챗봇 라우트는 로그인 필요 정책만 덧씌워 그대로 위임한다(중복 제거).
@login_required
def trash_bin_map(request, district_id=None):
    return _tl_trash_bin_map(request, district_id)


@login_required
def trash_bin_list(request, district_id):
    return _tl_trash_bin_list(request, district_id)
