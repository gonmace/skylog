import logging
from urllib.parse import parse_qs

from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

User = get_user_model()
log = logging.getLogger(__name__)


def get_user_from_ws_scope(scope):
    """
    Extrae y valida el JWT del query string (?token=...).
    Retorna (user, employee) o (AnonymousUser, None) si falla.
    """
    query_string = scope.get('query_string', b'').decode('utf-8')
    params = parse_qs(query_string)
    token_list = params.get('token', [])

    if not token_list:
        return AnonymousUser(), None, ''

    raw_token = token_list[0]
    version = params.get('version', [''])[0]
    try:
        validated = AccessToken(raw_token)
        user_id = validated['user_id']
        user = User.objects.select_related('employee').get(pk=user_id)
        employee = getattr(user, 'employee', None)
        return user, employee, version
    except (TokenError, InvalidToken, User.DoesNotExist) as e:
        log.warning('WS JWT auth failed: %s', e)
        return AnonymousUser(), None, ''
